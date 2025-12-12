#!/usr/bin/env bash
#
# Deploy container to EC2 instance.
# All key parameters are passed as environment variables.


set -euo pipefail

# ---------------------------------------------------------------------------
# Constants / Defaults (override via environment variables)
# ---------------------------------------------------------------------------

AWS_REGION="${AWS_REGION:-us-west-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-095232028760}"
ECR_REPOSITORY="${ECR_REPOSITORY:-cpu}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
AWS_PROFILE="${AWS_PROFILE:-default}"
SSO_SESSION="${SSO_SESSION:-}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.micro}"
KEY_PAIR_NAME="${KEY_PAIR_NAME:-cpu-key}"
SECURITY_GROUP_NAME="${SECURITY_GROUP_NAME:-default}"
VOLUME_SIZE="${VOLUME_SIZE:-30}"

# Derived vars
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
FULL_IMAGE_NAME="${ECR_URI}"
CONTAINER_NAME="${AWS_PROFILE}-${ECR_REPOSITORY}-container"
SIMULATION_DIR="/home/ec2-user/simulations"

# Optional override for the local private key path. When unset we fall back to
# ~/.ssh/<KEY_PAIR_NAME>.pem and, if that does not exist, to whatever identities
# the user's ssh-agent / ~/.ssh/config provides.
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
KEY_PAIR_FILE_DEFAULT="${HOME}/.ssh/${KEY_PAIR_NAME}.pem"
declare -a SSH_KEY_ARGS=()
declare -a SSH_COMMON_OPTS=(
  -o StrictHostKeyChecking=no
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=6
)
SSH_SELECTED_KEY=""
SSH_RETRY_ATTEMPTS="${SSH_RETRY_ATTEMPTS:-5}"
SSH_RETRY_DELAY="${SSH_RETRY_DELAY:-8}"

# Detect whether this deployment targets GPU or CPU based on ECR name (case-insensitive)
# Lower-case repo name in a portable way (macOS ships bash 3.2 w/o ${var,,})
ECR_REPO_LC=$(printf '%s' "${ECR_REPOSITORY}" | tr '[:upper:]' '[:lower:]')
if [[ "${ECR_REPO_LC}" == *cpu* ]]; then
  TARGET_GPU=0
else
  TARGET_GPU=1
fi

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------
log() {
  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") - $1"
}

error_exit() {
  echo "[ERROR] $1" >&2
  exit 1
}

resolve_ssh_identity() {
  local candidate=""
  if [[ -n "${SSH_KEY_PATH}" ]]; then
    candidate="${SSH_KEY_PATH}"
    if [[ ! -f "${candidate}" ]]; then
      error_exit "SSH key specified via SSH_KEY_PATH not found: ${candidate}"
    fi
  elif [[ -f "${KEY_PAIR_FILE_DEFAULT}" ]]; then
    candidate="${KEY_PAIR_FILE_DEFAULT}"
  fi

  if [[ -n "${candidate}" ]]; then
    chmod 600 "${candidate}"
    SSH_SELECTED_KEY="${candidate}"
    SSH_KEY_ARGS=(-i "${candidate}")
    log "Using SSH identity ${candidate}"
  else
    SSH_SELECTED_KEY=""
    SSH_KEY_ARGS=()
    log "Local key ${KEY_PAIR_FILE_DEFAULT} not found. Set SSH_KEY_PATH to your .pem or ensure the key for '${KEY_PAIR_NAME}' is available via ssh-agent / ~/.ssh/config."
  fi
}

run_with_retries() {
  local desc="$1"
  shift
  local attempt=1
  local max="${SSH_RETRY_ATTEMPTS}"
  while true; do
    if "$@"; then
      return 0
    fi
    if (( attempt >= max )); then
      error_exit "${desc} failed after ${max} attempts"
    fi
    log "${desc} failed (attempt ${attempt}/${max}). Retrying in ${SSH_RETRY_DELAY}s..."
    attempt=$((attempt + 1))
    sleep "${SSH_RETRY_DELAY}"
  done
}

check_sso_login() {
  log "Checking AWS SSO login status..."
  if ! aws sts get-caller-identity --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
    log "SSO session expired or not logged in. Attempting to log in..."
    if ! aws sso login --profile "${AWS_PROFILE}"; then
      error_exit "Failed to log in to AWS SSO. Please check your configuration."
    fi
    if ! aws sts get-caller-identity --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
      error_exit "SSO login appeared successful but credentials are still not working."
    fi
  fi
  log "SSO authentication verified"
}

get_sso_credentials() {
  log "Extracting SSO credentials for EC2 instance..."
  local creds
  creds=$(aws configure export-credentials --profile "${AWS_PROFILE}" --format env)
  if [[ $? -ne 0 ]] || [[ -z "${creds}" ]]; then
    error_exit "Failed to export SSO credentials"
  fi
  export AWS_ACCESS_KEY_ID=$(echo "${creds}" | grep AWS_ACCESS_KEY_ID | cut -d'=' -f2)
  export AWS_SECRET_ACCESS_KEY=$(echo "${creds}" | grep AWS_SECRET_ACCESS_KEY | cut -d'=' -f2)
  export AWS_SESSION_TOKEN=$(echo "${creds}" | grep AWS_SESSION_TOKEN | cut -d'=' -f2)
  if [[ -z "${AWS_ACCESS_KEY_ID}" ]] || [[ -z "${AWS_SECRET_ACCESS_KEY}" ]] || [[ -z "${AWS_SESSION_TOKEN}" ]]; then
    error_exit "Failed to parse SSO credentials"
  fi
  log "SSO credentials extracted successfully"
}

check_aws_cli() {
  log "Checking AWS CLI prerequisites..."
  if ! command -v aws &> /dev/null; then
    error_exit "AWS CLI is not installed."
  fi
  
  # Check if we have credentials from environment variables (assumed role)
  if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]] && [[ -n "${AWS_SECRET_ACCESS_KEY:-}" ]] && [[ -n "${AWS_SESSION_TOKEN:-}" ]]; then
    log "Using provided AWS credentials (assumed role)"
    # Verify credentials work
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
      error_exit "Provided AWS credentials are invalid or expired"
    fi
    log "AWS credentials verified"
  else
    # Fall back to SSO login (legacy)
    check_sso_login
    get_sso_credentials
  fi
  log "AWS CLI check passed"
}

check_key_pair() {
  log "Checking if EC2 key pair exists: ${KEY_PAIR_NAME}"
  if ! aws ec2 describe-key-pairs --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --key-names "${KEY_PAIR_NAME}" &> /dev/null; then
    log "Key pair ${KEY_PAIR_NAME} does not exist. Creating it..."
    mkdir -p ~/.ssh
    aws ec2 create-key-pair \
      --profile "${AWS_PROFILE}" \
      --region "${AWS_REGION}" \
      --key-name "${KEY_PAIR_NAME}" \
      --query 'KeyMaterial' \
      --output text > ~/.ssh/${KEY_PAIR_NAME}.pem
    chmod 600 ~/.ssh/${KEY_PAIR_NAME}.pem
    log "Key pair created and saved to ~/.ssh/${KEY_PAIR_NAME}.pem"
  else
    log "Key pair ${KEY_PAIR_NAME} already exists"
  fi
}

# ----------------------------------------------------------------------------
# AMI resolution helpers
# ----------------------------------------------------------------------------
get_latest_gpu_ami() {
  log "Finding latest Amazon Linux Deep Learning Base OSS Nvidia Driver GPU AMI (x86_64)..."
  local ami_id
  ami_id=$(aws ec2 describe-images \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --owners amazon \
    --filters \
      "Name=name,Values=Deep Learning Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023)*" \
      "Name=state,Values=available" \
      "Name=architecture,Values=x86_64" \
    --query 'Images|sort_by(@, &CreationDate)[-1].ImageId' \
    --output text)
  if [[ "${ami_id}" = "None" ]] || [[ -z "${ami_id}" ]]; then
    error_exit "Could not find GPU AMI"
  fi
  AMI_ID="${ami_id}"
  log "Using GPU AMI: ${AMI_ID}"
}

get_latest_cpu_ami() {
  log "Finding latest Amazon Linux 2023 AMI (x86_64)..."
  local ami_id
  ami_id=$(aws ssm get-parameters \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --names "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64" \
    --query 'Parameters[0].Value' \
    --output text)
  if [[ -z "${ami_id}" ]] || [[ "${ami_id}" = "None" ]]; then
    error_exit "Could not retrieve Amazon Linux 2023 AMI via SSM"
  fi
  AMI_ID="${ami_id}"
  log "Using CPU AMI: ${AMI_ID}"
}

select_ami() {
  if [[ ${TARGET_GPU} -eq 1 ]]; then
    get_latest_gpu_ami
  else
    get_latest_cpu_ami
  fi

  # Determine the AMI's root device name (e.g. /dev/xvda)
  ROOT_DEVICE_NAME=$(aws ec2 describe-images \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --image-ids "${AMI_ID}" \
    --query 'Images[0].RootDeviceName' \
    --output text)
  log "Root device name for AMI ${AMI_ID}: ${ROOT_DEVICE_NAME}"
}

create_security_group() {
  log "Ensuring security group: ${SECURITY_GROUP_NAME} (allows SSH)"
  local sg_id
  if sg_id=$(aws ec2 describe-security-groups --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --group-names "${SECURITY_GROUP_NAME}" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null); then
    log "Security group ${SECURITY_GROUP_NAME} already exists (${sg_id})"
  else
    sg_id=$(aws ec2 create-security-group \
      --profile "${AWS_PROFILE}" \
      --region "${AWS_REGION}" \
      --group-name "${SECURITY_GROUP_NAME}" \
      --description "Security group for ${ECR_REPOSITORY} Docker container" \
      --query 'GroupId' \
      --output text)
    log "Created security group: ${sg_id}"
  fi

  # Check if port 22 is open. If not, add rule.
  local ssh_rule
  ssh_rule=$(aws ec2 describe-security-groups --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --group-ids "${sg_id}" \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`22` && IpProtocol==`tcp`].IpRanges[?CidrIp==`0.0.0.0/0`]' --output text)
  if [[ -z "${ssh_rule}" ]]; then
    log "Authorizing SSH ingress (tcp/22 0.0.0.0/0) on ${SECURITY_GROUP_NAME} (ignoring duplicates)"
    if ! aws ec2 authorize-security-group-ingress \
        --profile "${AWS_PROFILE}" \
        --region "${AWS_REGION}" \
        --group-id "${sg_id}" \
        --protocol tcp --port 22 --cidr 0.0.0.0/0 2>&1 | grep -q "InvalidPermission.Duplicate"; then
      # Command succeeded or failed with a different error; set -e will catch unexpected failures.
      true
    fi
  fi
}

wait_for_ssh() {
  log "Waiting for SSH connectivity on ${PUBLIC_DNS}..."
  local retry=0 max_retries=30
  local dest="ec2-user@${PUBLIC_DNS}"
  while [[ ${retry} -lt ${max_retries} ]]; do
    if ssh "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" "${dest}" "echo ok" >/dev/null 2>&1; then
      log "SSH connection established"
      return 0
    fi
    retry=$((retry+1))
    sleep 10
  done
  error_exit "SSH connection failed after $((max_retries*10)) seconds"
}

launch_instance() {
  log "Launching EC2 instance..."
  local instance_id
  instance_id=$(aws ec2 run-instances \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --image-id "${AMI_ID}" \
    --instance-type "${INSTANCE_TYPE}" \
    --key-name "${KEY_PAIR_NAME}" \
    --security-groups "${SECURITY_GROUP_NAME}" \
    --block-device-mappings "[{\"DeviceName\":\"${ROOT_DEVICE_NAME}\",\"Ebs\":{\"VolumeSize\":${VOLUME_SIZE},\"VolumeType\":\"gp3\"}}]" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${CONTAINER_NAME}},{Key=Project,Value=${ECR_REPOSITORY}}]" \
    --query 'Instances[0].InstanceId' \
    --output text)
  if [[ -z "${instance_id}" ]]; then
    error_exit "Failed to launch EC2 instance"
  fi
  log "Instance launched: ${instance_id}"
  INSTANCE_ID="${instance_id}"
  log "Waiting for instance to be running..."
  aws ec2 wait instance-running --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --instance-ids "${INSTANCE_ID}"
  local public_dns
  public_dns=$(aws ec2 describe-instances \
    --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --instance-ids "${INSTANCE_ID}" \
    --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
  PUBLIC_DNS="${public_dns}"
  log "Instance is running. Public DNS: ${PUBLIC_DNS}"
  wait_for_ssh
}

install_docker_on_instance() {
  log "Installing Docker and prerequisites on EC2 instance (Amazon Linux 2023)..."
  
  # Create a setup script tailored for Amazon Linux 2023
  cat > /tmp/setup-docker.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

sudo yum update -y

# Install Docker (Amazon Linux 2023 ships docker with extras)
sudo amazon-linux-extras install docker -y || sudo yum install -y docker

# Enable & start Docker
sudo systemctl enable docker
sudo systemctl start docker

# Add ec2-user to docker group
sudo usermod -aG docker ec2-user

# Install unzip only. Curl-minimal is preinstalled on AL2023; installing full
# curl conflicts. Gnupg not required.
sudo yum install -y unzip || sudo dnf install -y unzip

# Install AWS CLI v2 if not already present
if ! command -v aws &> /dev/null; then
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  unzip awscliv2.zip
  sudo ./aws/install
fi

# Create simulation directory
mkdir -p /home/ec2-user/simulations

echo "Docker and AWS CLI installation completed"
EOF

  # Copy and execute the setup script on the instance
  run_with_retries "Upload setup-docker.sh" \
    scp "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" /tmp/setup-docker.sh "ec2-user@${PUBLIC_DNS}:/tmp/"

  run_with_retries "Execute setup-docker.sh" \
    ssh "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" "ec2-user@${PUBLIC_DNS}" "chmod +x /tmp/setup-docker.sh && /tmp/setup-docker.sh"

  log "Docker installation completed"
}


configure_aws_on_instance() {
  log "Configuring AWS credentials on instance using SSO credentials..."
  
  # Create AWS credentials file remotely
  cat > /tmp/aws-config.sh << EOF
#!/usr/bin/env bash
set -euo pipefail

mkdir -p ~/.aws

cat > ~/.aws/credentials << 'CREDS'
[default]
aws_access_key_id = ${AWS_ACCESS_KEY_ID}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}
aws_session_token = ${AWS_SESSION_TOKEN}
CREDS

cat > ~/.aws/config << 'CONFIG'
[default]
region = ${AWS_REGION}
output = json
CONFIG

chmod 600 ~/.aws/credentials ~/.aws/config

echo "AWS credentials configured"
EOF

  run_with_retries "Upload aws-config.sh" \
    scp "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" /tmp/aws-config.sh "ec2-user@${PUBLIC_DNS}:/tmp/"

  run_with_retries "Execute aws-config.sh" \
    ssh "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" "ec2-user@${PUBLIC_DNS}" "chmod +x /tmp/aws-config.sh && /tmp/aws-config.sh"

  log "AWS SSO credentials configured on instance"
}


pull_and_run_container() {
  log "Pulling ${ECR_REPOSITORY} container from ECR and starting it..."
  
  # Determine GPU flag locally so we can safely expand in heredoc
  local GPU_FLAG=""
  if [[ ${TARGET_GPU} -eq 1 ]]; then
    GPU_FLAG="--gpus all"
  fi

  cat > /tmp/run-container.sh << EOF
#!/usr/bin/env bash
set -euo pipefail

aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}

docker pull ${FULL_IMAGE_NAME}

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}\$"; then
  docker rm -f ${CONTAINER_NAME}
fi

docker run -dit \
  --name ${CONTAINER_NAME} \
  --restart unless-stopped \
  --shm-size=4g \
  -v ${SIMULATION_DIR}:/workspace \
  ${GPU_FLAG} \
  --tmpfs /app/tmp:rw,size=2g \
  ${FULL_IMAGE_NAME}


echo "Container started"
EOF

  run_with_retries "Upload run-container.sh" \
    scp "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" /tmp/run-container.sh "ec2-user@${PUBLIC_DNS}:/tmp/"

  run_with_retries "Execute run-container.sh" \
    ssh "${SSH_KEY_ARGS[@]}" "${SSH_COMMON_OPTS[@]}" "ec2-user@${PUBLIC_DNS}" "chmod +x /tmp/run-container.sh && /tmp/run-container.sh"

  log "Container deployment completed"
}

open_ssh_terminal() {
  log "Opening new macOS Terminal window connected via SSH..."
  local ssh_cmd
  if [[ -n "${SSH_SELECTED_KEY}" ]]; then
    ssh_cmd=$(printf "ssh -i '%s' -t ec2-user@%s" "${SSH_SELECTED_KEY}" "${PUBLIC_DNS}")
  else
    ssh_cmd=$(printf "ssh -t ec2-user@%s" "${PUBLIC_DNS}")
  fi
  osascript <<EOF
try
  tell application "Terminal"
    do script "${ssh_cmd}"
    activate
  end tell
end try
EOF
}

cleanup_on_exit() {
  if [[ ! -z "${INSTANCE_ID:-}" ]]; then
    log "Terminating instance ${INSTANCE_ID} (cleanup)..."
    aws ec2 terminate-instances --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --instance-ids "${INSTANCE_ID}" || true
    log "Instance termination initiated"
  fi
}

main() {
  # Cleanup only on interruption (Ctrl-C / SIGINT) or external termination. On
  # normal completion we leave the instance running for user control.
  trap cleanup_on_exit SIGINT SIGTERM
  check_aws_cli
  check_key_pair
  resolve_ssh_identity
  select_ami
  create_security_group
  launch_instance
  install_docker_on_instance
  configure_aws_on_instance
  pull_and_run_container
  log "Deployment completed successfully!"
  log "Instance ID: ${INSTANCE_ID}"
  log "Public DNS: ${PUBLIC_DNS}"
  if [[ -n "${SSH_SELECTED_KEY}" ]]; then
    log "SSH: ssh -i '${SSH_SELECTED_KEY}' ec2-user@${PUBLIC_DNS}"
  else
    log "SSH: ssh ec2-user@${PUBLIC_DNS}"
  fi
  # Optionally open a new Terminal window for the user
  # open_ssh_terminal
}

main "$@"