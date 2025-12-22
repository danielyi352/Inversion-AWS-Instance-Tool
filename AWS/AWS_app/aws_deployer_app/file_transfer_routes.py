"""
File transfer routes for uploading and downloading files to/from EC2 instances and containers.
Uses S3 + SSM for secure file transfers without SSH.
"""

import os
import time
import hashlib
import shlex
import tempfile
import uuid
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["file-transfer"])


def _get_session_credentials_from_auth(session_id):
    """Import and call session credentials function from auth_routes."""
    from auth_routes import get_session_credentials
    return get_session_credentials(session_id)


def _session_from_credentials_from_auth(credentials, region):
    """Import and call session creation function from auth_routes."""
    from auth_routes import session_from_credentials
    return session_from_credentials(credentials, region)


def _session_from_api_server(profile, region):
    """Import and call session creation function from api_server to avoid circular imports."""
    from api_server import _session
    return _session(profile, region)


class UploadRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    local_path: str
    destination_path: str
    container_name: Optional[str] = Field(None, description="Container name if uploading to container")


class DownloadRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    remote_path: str
    local_path: str
    container_name: Optional[str] = Field(None, description="Container name if downloading from container. If not provided, will auto-detect based on instance tags.")
    repository: Optional[str] = Field(None, description="Repository name for auto-detecting container name")
    account_id: Optional[str] = Field(None, description="Account ID for auto-detecting container name")


class ListFilesRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    path: str = Field(default="/", description="Directory path to list")
    container_name: Optional[str] = Field(None, description="Container name if listing files in container. If not provided, will auto-detect based on instance tags.")
    repository: Optional[str] = Field(None, description="Repository name for auto-detecting container name")
    account_id: Optional[str] = Field(None, description="Account ID for auto-detecting container name")


class ContainerLogsRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    container_name: Optional[str] = Field(None, description="Container name. If not provided, will auto-detect based on instance tags.")
    repository: Optional[str] = Field(None, description="Repository name for auto-detecting container name")
    account_id: Optional[str] = Field(None, description="Account ID for auto-detecting container name")
    tail: int = Field(default=100, description="Number of lines to retrieve from the end of logs")
    follow: bool = Field(default=False, description="Follow log output (for streaming, not implemented yet)")


class ExecuteCommandRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    command: str = Field(..., description="Command to execute")
    container_name: Optional[str] = Field(None, description="Container name if executing command in container. If not provided, executes on host.")
    repository: Optional[str] = Field(None, description="Repository name for auto-detecting container name")
    account_id: Optional[str] = Field(None, description="Account ID for auto-detecting container name")
    execute_on_host: bool = Field(default=False, description="Force execution on host instead of container, even if container exists")


def _get_container_name_from_instance(ec2_client, instance_id: str, account_id: str, repository: Optional[str] = None) -> Optional[str]:
    """Auto-detect container name from instance tags or repository."""
    try:
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        if not response.get('Reservations'):
            return None
        
        instance = response['Reservations'][0]['Instances'][0]
        tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
        
        # Try to get repository from tags
        repo = repository or tags.get('Project')
        if repo and account_id:
            return f"{account_id}-{repo}-container"
        
        return None
    except Exception:
        return None


@router.post("/upload")
def upload(request: Request, body: UploadRequest):
    """Upload file to EC2 instance using S3 + SSM (no SSH required)."""
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = _get_session_credentials_from_auth(session_id)
        session = _session_from_credentials_from_auth(creds, body.region)
        account_id = creds.get('account_id', '')
    elif body.profile:
        # Legacy: use profile-based auth
        session = _session_from_api_server(body.profile, body.region)
        # Get account ID from STS
        sts = session.client('sts')
        account_id = sts.get_caller_identity()['Account']
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    
    s3_client = session.client('s3', region_name=body.region)
    ssm_client = session.client('ssm', region_name=body.region)
    
    # Generate unique S3 key for this transfer
    file_hash = hashlib.md5(f"{body.instance_id}{body.local_path}{time.time()}".encode()).hexdigest()[:8]
    bucket_name = f"inversion-deployer-temp-{account_id}"
    s3_key = f"uploads/{body.instance_id}/{file_hash}/{os.path.basename(body.local_path)}"
    
    try:
        # Step 1: Create S3 bucket if it doesn't exist
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404' or error_code == '403':
                # Bucket doesn't exist, create it
                try:
                    s3_client.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': body.region} if body.region != 'us-east-1' else {}
                    )
                    # Add lifecycle policy to auto-delete after 24 hours
                    s3_client.put_bucket_lifecycle_configuration(
                        Bucket=bucket_name,
                        LifecycleConfiguration={
                            'Rules': [{
                                'Id': 'DeleteOldUploads',
                                'Status': 'Enabled',
                                'Expiration': {'Days': 1}
                            }]
                        }
                    )
                except ClientError as create_err:
                    if create_err.response.get('Error', {}).get('Code') != 'BucketAlreadyOwnedByYou':
                        raise
        
        # Step 2: Upload file to S3
        local_path = os.path.expanduser(body.local_path)
        if not os.path.exists(local_path):
            raise HTTPException(status_code=404, detail=f"Local file not found: {local_path}")
        
        s3_client.upload_file(local_path, bucket_name, s3_key)
        
        # Step 3: Generate presigned URL for download (valid for 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
        
        # Step 4: Use SSM to download from presigned URL to instance (no AWS CLI needed)
        # Escape the presigned URL for shell safety
        presigned_url_escaped = shlex.quote(presigned_url)
        
        if body.container_name:
            # Upload to container: copy to instance first, then into container
            instance_path = f"/tmp/{os.path.basename(body.local_path)}"
            # Use curl to download from presigned URL
            download_cmd = f"curl -f -o {shlex.quote(instance_path)} {presigned_url_escaped}"
            copy_to_container_cmd = f"docker cp {shlex.quote(instance_path)} {shlex.quote(body.container_name)}:{shlex.quote(body.destination_path)} && rm -f {shlex.quote(instance_path)}"
            command = f"{download_cmd} && {copy_to_container_cmd}"
        else:
            # Upload to instance filesystem
            command = f"curl -f -o {shlex.quote(body.destination_path)} {presigned_url_escaped}"
        
        response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Step 5: Wait for command to complete
        for _ in range(30):  # Wait up to 5 minutes
            time.sleep(10)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=body.instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                break
        
        if result['Status'] != 'Success':
            error_output = result.get('StandardErrorContent', 'Unknown error')
            raise HTTPException(
                status_code=500,
                detail=f"SSM command failed: {error_output}"
            )
        
        # Step 6: Clean up S3 file
        try:
            s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
        except Exception:
            pass  # Don't fail if cleanup fails
        
        return {
            "status": "ok",
            "message": f"Uploaded {local_path} to {body.destination_path}",
            "method": "S3 + SSM"
        }
    except HTTPException:
        raise
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/download")
def download(request: Request, background_tasks: BackgroundTasks, body: DownloadRequest):
    """Download file from EC2 instance or Docker container using S3 + SSM (no SSH required).
    
    If container_name is not provided, will attempt to auto-detect the container name
    based on the instance tags or provided repository/account_id.
    """
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = _get_session_credentials_from_auth(session_id)
        session = _session_from_credentials_from_auth(creds, body.region)
        account_id = creds.get('account_id', '') or body.account_id or ''
    elif body.profile:
        # Legacy: use profile-based auth
        session = _session_from_api_server(body.profile, body.region)
        # Get account ID from STS
        sts = session.client('sts')
        account_id = sts.get_caller_identity()['Account']
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    
    s3_client = session.client('s3', region_name=body.region)
    ssm_client = session.client('ssm', region_name=body.region)
    ec2_client = session.client('ec2', region_name=body.region)
    
    # Auto-detect container name if not provided
    container_name = body.container_name
    if not container_name and account_id:
        container_name = _get_container_name_from_instance(
            ec2_client, body.instance_id, account_id, body.repository
        )
        if container_name:
            print(f"[DEBUG] Auto-detected container name: {container_name}")
    
    # Generate unique S3 key for this transfer
    job_id = str(uuid.uuid4())[:8]
    bucket_name = f"inversion-deployer-temp-{account_id}"
    filename = os.path.basename(body.remote_path)
    s3_key = f"downloads/{job_id}/{filename}"
    
    try:
        # Step 1: Ensure S3 bucket exists
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404' or error_code == '403':
                try:
                    s3_client.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': body.region} if body.region != 'us-east-1' else {}
                    )
                except ClientError as create_err:
                    if create_err.response.get('Error', {}).get('Code') != 'BucketAlreadyOwnedByYou':
                        raise
        
        # Step 2: Use SSM to copy file from container to host, then upload to S3
        # Use a known directory on the host for temporary storage
        host_temp_dir = "/tmp/inversion-downloads"
        host_file_path = f"{host_temp_dir}/{filename}"
        
        if container_name:
            # Step 2a: Locate the container (docker ps to verify it exists)
            # Step 2b: Copy file from container to host
            # Step 2c: Upload to S3 using aws s3 cp
            # Step 2d: Clean up temp file
            command = f"""mkdir -p {shlex.quote(host_temp_dir)} && \
CONTAINER_ID=$(docker ps -a --filter 'name=^{shlex.quote(container_name)}$' --format '{{{{.ID}}}}') && \
if [ -z "$CONTAINER_ID" ]; then \
  echo "ERROR: Container '{container_name}' not found" && exit 1; \
fi && \
docker cp {shlex.quote(container_name)}:{shlex.quote(body.remote_path)} {shlex.quote(host_file_path)} && \
aws s3 cp {shlex.quote(host_file_path)} s3://{bucket_name}/{s3_key} --region {body.region} && \
rm -f {shlex.quote(host_file_path)} && \
echo "SUCCESS: File uploaded to S3"
"""
        else:
            # Download from instance filesystem directly to S3
            command = f"aws s3 cp {shlex.quote(body.remote_path)} s3://{bucket_name}/{s3_key} --region {body.region}"
        
        response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Step 3: Wait for command to complete
        for _ in range(30):  # Wait up to 5 minutes
            time.sleep(10)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=body.instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                break
        
        output = result.get('StandardOutputContent', '')
        error_output = result.get('StandardErrorContent', '')
        
        if result['Status'] != 'Success':
            # Check for specific error messages
            if 'Container' in error_output and 'not found' in error_output:
                raise HTTPException(
                    status_code=404,
                    detail=f"Container '{container_name}' not found. It may have been removed or never existed."
                )
            raise HTTPException(
                status_code=500,
                detail=f"SSM command failed: {error_output or 'Unknown error'}"
            )
        
        # Verify file was uploaded to S3
        if 'SUCCESS' not in output and container_name:
            # Check if file exists in S3
            try:
                s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            except ClientError:
                raise HTTPException(
                    status_code=500,
                    detail=f"File was not uploaded to S3. SSM output: {output}, Error: {error_output}"
                )
        
        # Step 4: Download from S3 to temporary file
        # Create a temporary file to store the downloaded content
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(body.remote_path)[1])
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            s3_client.download_file(bucket_name, s3_key, temp_path)
            
            # Step 6: Clean up S3 file
            try:
                s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
            except Exception:
                pass  # Don't fail if cleanup fails
            
            # Return file as download response
            filename = os.path.basename(body.remote_path)
            # Schedule cleanup of temp file after response is sent
            background_tasks.add_task(os.unlink, temp_path)
            return FileResponse(
                temp_path,
                media_type='application/octet-stream',
                filename=filename
            )
        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise
    except HTTPException:
        raise
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.post("/list-files")
def list_files(request: Request, body: ListFilesRequest):
    """List files and directories in a container or instance filesystem using SSM.
    
    Returns a list of files and directories with their types and sizes.
    """
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = _get_session_credentials_from_auth(session_id)
        session = _session_from_credentials_from_auth(creds, body.region)
        account_id = creds.get('account_id', '') or body.account_id or ''
    elif body.profile:
        # Legacy: use profile-based auth
        session = _session_from_api_server(body.profile, body.region)
        # Get account ID from STS
        sts = session.client('sts')
        account_id = sts.get_caller_identity()['Account']
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    
    ssm_client = session.client('ssm', region_name=body.region)
    ec2_client = session.client('ec2', region_name=body.region)
    
    # Auto-detect container name if not provided
    container_name = body.container_name
    if not container_name and account_id:
        container_name = _get_container_name_from_instance(
            ec2_client, body.instance_id, account_id, body.repository
        )
        if container_name:
            print(f"[DEBUG] Auto-detected container name: {container_name}")
    
    # Normalize path (ensure it starts with /)
    path = body.path if body.path.startswith('/') else f"/{body.path}"
    
    try:
        if container_name:
            # List files in container - works even if container is stopped
            # First, check if container exists and get its status
            # If container is stopped and we're accessing /workspace, map to host volume
            # Otherwise, try docker exec if running, or return error if stopped
            command = f"""CONTAINER_ID=$(docker ps -a --filter 'name=^{shlex.quote(container_name)}$' --format '{{{{.ID}}}}') && \
if [ -z "$CONTAINER_ID" ]; then \
  echo "ERROR: Container '{container_name}' not found" && exit 1; \
fi && \
CONTAINER_STATE=$(docker inspect --format='{{{{{{.State.Status}}}}}}' {shlex.quote(container_name)} 2>/dev/null || echo "unknown") && \
if [ "$CONTAINER_STATE" = "running" ]; then \
  # Container is running, use docker exec
  docker exec {shlex.quote(container_name)} ls -la {shlex.quote(path)} 2>/dev/null || echo 'Directory not found or empty'; \
elif echo {shlex.quote(path)} | grep -q "^/workspace"; then \
  # Container is stopped but we're accessing /workspace - map to host volume
  HOST_PATH=$(echo {shlex.quote(path)} | sed 's|^/workspace|/home/ec2-user/simulations|') && \
  ls -la "$HOST_PATH" 2>/dev/null || echo 'Directory not found or empty'; \
else \
  # Container is stopped and path is not /workspace - try docker cp as fallback
  TEMP_DIR="/tmp/inversion-list-$$" && \
  mkdir -p "$TEMP_DIR" && \
  if docker cp {shlex.quote(container_name)}:{shlex.quote(path)} "$TEMP_DIR/listing" 2>/dev/null; then \
    if [ -d "$TEMP_DIR/listing" ]; then \
      ls -la "$TEMP_DIR/listing"; \
    else \
      ls -la "$TEMP_DIR" | grep listing; \
    fi && \
    rm -rf "$TEMP_DIR"; \
  else \
    echo "ERROR: Container is stopped and cannot access {shlex.quote(path)}. Container state: $CONTAINER_STATE" && \
    rm -rf "$TEMP_DIR" && exit 1; \
  fi; \
fi
"""
        else:
            # List files on instance filesystem
            command = f"ls -la {shlex.quote(path)} 2>/dev/null || echo 'Directory not found or empty'"
        
        response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        for _ in range(30):  # Wait up to 5 minutes
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=body.instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                break
        
        output = result.get('StandardOutputContent', '')
        error_output = result.get('StandardErrorContent', '')
        
        # Check for container-specific errors
        if container_name:
            if 'Container' in error_output and 'not found' in error_output:
                raise HTTPException(
                    status_code=404,
                    detail=f"Container '{container_name}' not found. It may have been removed."
                )
            if 'Container is stopped' in output or 'Container is stopped' in error_output:
                raise HTTPException(
                    status_code=400,
                    detail=f"Container '{container_name}' is stopped and cannot access this path. Try accessing files from /workspace (mapped to host volume) or start the container."
                )
        
        if result['Status'] != 'Success':
            # Check if output contains an error message
            if 'ERROR:' in output:
                error_msg = output.split('ERROR:')[-1].strip()
                raise HTTPException(
                    status_code=500,
                    detail=f"SSM command failed: {error_msg or error_output or 'Unknown error'}"
                )
            raise HTTPException(
                status_code=500,
                detail=f"SSM command failed: {error_output or 'Unknown error'}"
            )
        
        # Parse ls -la output
        files = []
        lines = output.strip().split('\n')
        
        # Skip the first line (total) and parse each file entry
        for line in lines[1:]:
            if not line.strip():
                continue
            
            # Parse: permissions links owner group size date time name
            # Example: drwxr-xr-x 2 root root 4096 Dec 13 10:00 workspace
            parts = line.split()
            if len(parts) >= 9:
                permissions = parts[0]
                # size is typically at index 4
                size = parts[4] if parts[4].isdigit() else '0'
                # name is everything after index 8 (to handle spaces in filenames)
                name = ' '.join(parts[8:])
                
                # Skip . and ..
                if name in ['.', '..']:
                    continue
                
                is_directory = permissions.startswith('d')
                files.append({
                    "name": name,
                    "path": f"{path.rstrip('/')}/{name}" if path != '/' else f"/{name}",
                    "isDirectory": is_directory,
                    "size": int(size) if size.isdigit() else 0,
                    "permissions": permissions
                })
        
        return {
            "status": "ok",
            "path": path,
            "containerName": container_name,
            "files": files
        }
    except HTTPException:
        raise
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List files failed: {str(e)}")


@router.post("/container-logs")
def container_logs(request: Request, body: ContainerLogsRequest):
    """Get logs from a Docker container using SSM.
    
    Returns container logs. Works even if container is stopped (shows logs up to when it stopped).
    """
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = _get_session_credentials_from_auth(session_id)
        session = _session_from_credentials_from_auth(creds, body.region)
        account_id = creds.get('account_id', '') or body.account_id or ''
    elif body.profile:
        # Legacy: use profile-based auth
        session = _session_from_api_server(body.profile, body.region)
        # Get account ID from STS
        sts = session.client('sts')
        account_id = sts.get_caller_identity()['Account']
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    
    ssm_client = session.client('ssm', region_name=body.region)
    ec2_client = session.client('ec2', region_name=body.region)
    
    # Auto-detect container name if not provided
    container_name = body.container_name
    if not container_name and account_id:
        container_name = _get_container_name_from_instance(
            ec2_client, body.instance_id, account_id, body.repository
        )
        if container_name:
            print(f"[DEBUG] Auto-detected container name for logs: {container_name}")
    
    if not container_name:
        raise HTTPException(
            status_code=400,
            detail="Could not determine container name. Please provide container_name or ensure repository/account_id are set."
        )
    
    try:
        # Use docker logs to get container logs
        # docker logs works even if container is stopped (shows logs up to when it stopped)
        command = f"docker logs --tail {body.tail} {shlex.quote(container_name)} 2>&1 || echo 'Container not found or has no logs'"
        
        response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        for _ in range(30):  # Wait up to 60 seconds
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=body.instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                break
        
        output = result.get('StandardOutputContent', '')
        error_output = result.get('StandardErrorContent', '')
        
        # Check for container not found
        if 'Container not found' in output or 'No such container' in error_output:
            raise HTTPException(
                status_code=404,
                detail=f"Container '{container_name}' not found. It may have been removed."
            )
        
        if result['Status'] != 'Success' and 'Container not found' not in output:
            raise HTTPException(
                status_code=500,
                detail=f"SSM command failed: {error_output or 'Unknown error'}"
            )
        
        # Get container status
        status_command = f"docker ps -a --filter 'name=^{shlex.quote(container_name)}$' --format '{{{{.Status}}}}'"
        status_response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [status_command]}
        )
        status_command_id = status_response['Command']['CommandId']
        
        # Wait briefly for status
        time.sleep(2)
        status_result = ssm_client.get_command_invocation(
            CommandId=status_command_id,
            InstanceId=body.instance_id
        )
        container_status = status_result.get('StandardOutputContent', '').strip()
        is_running = 'Up' in container_status or container_status.startswith('Up')
        
        return {
            "status": "ok",
            "containerName": container_name,
            "logs": output,
            "isRunning": is_running,
            "containerStatus": container_status,
            "lineCount": len(output.split('\n')) if output else 0
        }
    except HTTPException:
        raise
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get container logs failed: {str(e)}")


@router.post("/container-logs/download")
def download_container_logs(request: Request, background_tasks: BackgroundTasks, body: ContainerLogsRequest):
    """Download container logs as a text file.
    
    Gets all logs (or tail) and returns as a downloadable file.
    """
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = _get_session_credentials_from_auth(session_id)
        session = _session_from_credentials_from_auth(creds, body.region)
        account_id = creds.get('account_id', '') or body.account_id or ''
    elif body.profile:
        # Legacy: use profile-based auth
        session = _session_from_api_server(body.profile, body.region)
        # Get account ID from STS
        sts = session.client('sts')
        account_id = sts.get_caller_identity()['Account']
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    
    ssm_client = session.client('ssm', region_name=body.region)
    ec2_client = session.client('ec2', region_name=body.region)
    
    # Auto-detect container name if not provided
    container_name = body.container_name
    if not container_name and account_id:
        container_name = _get_container_name_from_instance(
            ec2_client, body.instance_id, account_id, body.repository
        )
        if container_name:
            print(f"[DEBUG] Auto-detected container name for log download: {container_name}")
    
    if not container_name:
        raise HTTPException(
            status_code=400,
            detail="Could not determine container name. Please provide container_name or ensure repository/account_id are set."
        )
    
    try:
        # Get all logs (or tail if specified)
        # Use a large tail value to get most logs, or all if tail is very large
        tail_value = body.tail if body.tail < 10000 else 10000  # Cap at 10k lines for performance
        command = f"docker logs --tail {tail_value} {shlex.quote(container_name)} 2>&1 || echo 'Container not found or has no logs'"
        
        response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        for _ in range(30):  # Wait up to 60 seconds
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=body.instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                break
        
        output = result.get('StandardOutputContent', '')
        error_output = result.get('StandardErrorContent', '')
        
        # Check for container not found
        if 'Container not found' in output or 'No such container' in error_output:
            raise HTTPException(
                status_code=404,
                detail=f"Container '{container_name}' not found. It may have been removed."
            )
        
        if result['Status'] != 'Success' and 'Container not found' not in output:
            raise HTTPException(
                status_code=500,
                detail=f"SSM command failed: {error_output or 'Unknown error'}"
            )
        
        # Create temporary file with logs
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log', encoding='utf-8')
        temp_path = temp_file.name
        temp_file.write(output)
        temp_file.close()
        
        # Return file as download response
        filename = f"{container_name}_logs_{int(time.time())}.log"
        # Schedule cleanup of temp file after response is sent
        background_tasks.add_task(os.unlink, temp_path)
        return FileResponse(
            temp_path,
            media_type='text/plain',
            filename=filename
        )
    except HTTPException:
        raise
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download container logs failed: {str(e)}")


@router.post("/execute-command")
def execute_command(request: Request, body: ExecuteCommandRequest):
    """
    Execute a command on an EC2 instance or inside a container via SSM.
    Can execute commands on the host or inside a Docker container.
    """
    # Check for session-based auth
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = _get_session_credentials_from_auth(session_id)
        region = body.region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_auth(creds, region)
        account_id = creds.get('account_id', '')
    except HTTPException as e:
        raise
    
    ssm_client = session.client("ssm", region_name=region)
    
    # Auto-detect container name if not provided (unless forcing host execution)
    container_name = body.container_name
    if not container_name and not body.execute_on_host:
        ec2_client = session.client("ec2", region_name=region)
        container_name = _get_container_name_from_instance(
            ec2_client, body.instance_id, account_id, body.repository
        )
    
    try:
        # Build command - execute on host if explicitly requested or no container
        if body.execute_on_host or not container_name:
            # Execute command on host
            command = body.command
        else:
            # Execute command inside Docker container
            command = f"docker exec {shlex.quote(container_name)} sh -c {shlex.quote(body.command)}"
        
        response = ssm_client.send_command(
            InstanceIds=[body.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete (up to 60 seconds)
        for _ in range(30):
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=body.instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                break
        
        output = result.get('StandardOutputContent', '')
        error_output = result.get('StandardErrorContent', '')
        
        return {
            "status": "ok",
            "command": body.command,
            "container_name": container_name,
            "exit_code": 0 if result['Status'] == 'Success' else 1,
            "stdout": output,
            "stderr": error_output,
            "combined": output + (f"\n{error_output}" if error_output else "")
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execute command failed: {str(e)}")

