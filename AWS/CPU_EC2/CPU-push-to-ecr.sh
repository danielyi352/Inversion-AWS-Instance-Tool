#!/usr/bin/env bash
#
# Push CPU Docker Image to Amazon ECR
# This script builds and pushes the CPU Docker image to Amazon ECR.
# It handles AWS SSO authentication and ensures all prerequisites are met.
#
# Usage:
#   ./push-to-ecr.sh

set -euo pipefail

# Configuration
readonly AWS_REGION="us-east-2"
readonly AWS_ACCOUNT_ID="095232028760"
readonly ECR_REPOSITORY="cpu"
readonly IMAGE_TAG="latest"
readonly ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
readonly ECR_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
readonly FULL_IMAGE_NAME="${ECR_URI}"

# SSO Configuration
readonly AWS_PROFILE="Daniel-Inversion"  # Your SSO profile name
readonly SSO_SESSION="Daniel-Inversion"     # Your SSO session name

# Functions
log() {
  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") - $1"
}

error_exit() {
  echo "[ERROR] $1" >&2
  exit 1
}

check_sso_login() {
  log "Checking AWS SSO login status..."
  
  # Check if we can get caller identity with the SSO profile
  if ! aws sts get-caller-identity --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
    log "SSO session expired or not logged in. Attempting to log in..."
    
    # Attempt SSO login
    if ! aws sso login --profile "${AWS_PROFILE}"; then
      error_exit "Failed to log in to AWS SSO. Please check your configuration."
    fi
    
    # Verify login was successful
    if ! aws sts get-caller-identity --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
      error_exit "SSO login appeared successful but credentials are still not working."
    fi
  fi
  
  log "SSO authentication verified"
}

get_sso_credentials() {
  log "Extracting SSO credentials for ECR..."
  
  # Get temporary credentials from SSO
  local creds
  creds=$(aws configure export-credentials --profile "${AWS_PROFILE}" --format env)
  if [[ $? -ne 0 ]] || [[ -z "${creds}" ]]; then
    error_exit "Failed to export SSO credentials"
  fi
  
  # Parse credentials
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
    error_exit "AWS CLI is not installed. Please install it from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  fi

  # Check SSO login instead of basic credentials
  check_sso_login
  get_sso_credentials
  
  log "AWS CLI and SSO check passed"
}

check_docker() {
  log "Checking Docker prerequisites..."
  
  if ! command -v docker &> /dev/null; then
    error_exit "Docker is not installed. Please install it from https://docs.docker.com/get-docker/"
  fi
  
  if ! docker info &> /dev/null; then
    error_exit "Docker daemon is not running. Please start Docker and try again."
  fi
  
  log "Docker check passed"
}

create_ecr_repository() {
  log "Checking if ECR repository exists: ${ECR_REPOSITORY}"
  
  if ! aws ecr describe-repositories --profile "${AWS_PROFILE}" --region "${AWS_REGION}" --repository-names "${ECR_REPOSITORY}" &> /dev/null; then
    log "Creating ECR repository: ${ECR_REPOSITORY}"
    
    aws ecr create-repository \
      --profile "${AWS_PROFILE}" \
      --region "${AWS_REGION}" \
      --repository-name "${ECR_REPOSITORY}" \
      --image-scanning-configuration scanOnPush=true \
      --image-tag-mutability MUTABLE
    
    log "ECR repository created successfully"
  else
    log "ECR repository already exists"
  fi
}

authenticate_ecr() {
  log "Authenticating Docker with ECR..."
  
  # Get ECR login token and authenticate Docker
  aws ecr get-login-password --profile "${AWS_PROFILE}" --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${ECR_REGISTRY}"
  
  if [[ $? -ne 0 ]]; then
    error_exit "Failed to authenticate with ECR"
  fi
  
  log "Docker authenticated with ECR successfully"
}

build_and_push_image() {
  log "Building and pushing Docker image..."
  
  # Build the image
  log "Building Docker image: ${FULL_IMAGE_NAME}"
  docker build --platform linux/amd64 -f CPU.dockerfile -t "${FULL_IMAGE_NAME}" .
  
  if [[ $? -ne 0 ]]; then
    error_exit "Failed to build Docker image"
  fi
  
  # Push the image
  log "Pushing Docker image to ECR..."
  docker push "${FULL_IMAGE_NAME}"
  
  if [[ $? -ne 0 ]]; then
    error_exit "Failed to push Docker image to ECR"
  fi
  
  log "Docker image built and pushed successfully"
}

main() {
  log "Starting CPU Docker Image Push to ECR..."
  check_aws_cli
  check_docker
  create_ecr_repository
  authenticate_ecr
  build_and_push_image
  log "CPU Docker Image Push to ECR completed successfully."
  log "Image is now available at: ${FULL_IMAGE_NAME}"
}

main "$@"
