"""
Docker and ECR-related API routes for pushing Docker images to ECR.
Supports tar file uploads from user's local machine.
"""

import os
import subprocess
import tempfile
import base64

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form

router = APIRouter(prefix="/api", tags=["docker"])


def _get_session_credentials_from_api_server(session_id):
    """Import and call session credentials function from api_server to avoid circular imports."""
    from api_server import _get_session_credentials
    return _get_session_credentials(session_id)


def _session_from_credentials_from_api_server(credentials, region):
    """Import and call session creation function from api_server to avoid circular imports."""
    from api_server import _session_from_credentials
    return _session_from_credentials(credentials, region)


def check_docker_availability():
    """Check if Docker is installed and available."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            docker_version = result.stdout.strip()
            # Also check if Docker daemon is running
            try:
                daemon_result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=5
                )
                return {
                    "available": True,
                    "version": docker_version,
                    "daemon_running": daemon_result.returncode == 0,
                    "message": "Docker is available and daemon is running" if daemon_result.returncode == 0 else "Docker is installed but daemon is not running"
                }
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return {
                    "available": True,
                    "version": docker_version,
                    "daemon_running": False,
                    "message": "Docker is installed but daemon is not running"
                }
        else:
            return {
                "available": False,
                "version": None,
                "daemon_running": False,
                "message": "Docker command failed"
            }
    except FileNotFoundError:
        return {
            "available": False,
            "version": None,
            "daemon_running": False,
            "message": "Docker is not installed"
        }
    except Exception as e:
        return {
            "available": False,
            "version": None,
            "daemon_running": False,
            "message": f"Error checking Docker: {str(e)}"
        }


@router.get("/docker/check")
def docker_check():
    """Check if Docker is installed and available."""
    return check_docker_availability()


@router.post("/ecr/push-image")
async def push_image_to_ecr(
    request: Request,
    repository: str = Form(...),
    image_tag: str = Form(default="latest"),
    region: str = Form(default="us-east-1"),
    tar_file: UploadFile = File(..., description="Docker image tar file (from 'docker save', e.g., 'docker save myimage:latest -o myimage.tar')")
):
    """
    Push Docker image to ECR repository from uploaded tar file.
    
    The user must:
    1. Build their Docker image locally: docker build -t myimage:latest .
    2. Export to tar file: docker save myimage:latest -o myimage.tar
    3. Upload the tar file through this endpoint
    
    The backend will load the image, tag it, and push it to ECR.
    """
    # Check for session-based auth
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = _get_session_credentials_from_api_server(session_id)
        # Use region from form, fallback to session region
        region = region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_api_server(creds, region)
        account_id = creds.get('account_id', '')
    except HTTPException as e:
        raise
    
    # Check if Docker is available
    docker_check_result = check_docker_availability()
    if not docker_check_result["available"]:
        raise HTTPException(
            status_code=503,
            detail=f"Docker is not available: {docker_check_result['message']}"
        )
    if not docker_check_result["daemon_running"]:
        raise HTTPException(
            status_code=503,
            detail="Docker daemon is not running. Please start Docker and try again."
        )
    
    ecr = session.client("ecr", region_name=region)
    ecr_registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    full_image_name = f"{ecr_registry}/{repository}:{image_tag}"
    
    temp_tar_path = None
    loaded_image_name = None
    
    try:
        # Step 1: Ensure repository exists
        try:
            ecr.describe_repositories(repositoryNames=[repository])
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                # Create repository if it doesn't exist
                try:
                    ecr.create_repository(
                        repositoryName=repository,
                        imageScanningConfiguration={'scanOnPush': True},
                        imageTagMutability='MUTABLE'
                    )
                except ClientError as create_err:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create repository: {create_err}"
                    )
            else:
                raise
        
        # Step 2: Get ECR login token
        try:
            response = ecr.get_authorization_token()
            token = response['authorizationData'][0]['authorizationToken']
            username, password = base64.b64decode(token).decode('utf-8').split(':')
        except ClientError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get ECR authorization token: {e}"
            )
        
        # Step 3: Login to ECR
        try:
            login_cmd = [
                "docker", "login",
                "--username", username,
                "--password-stdin",
                ecr_registry
            ]
            login_process = subprocess.Popen(
                login_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = login_process.communicate(input=password, timeout=30)
            if login_process.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to login to ECR: {stderr}"
                )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=500,
                detail="Docker login timed out"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to login to ECR: {str(e)}"
            )
        
        # Step 4: Load image from uploaded tar file
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
            temp_tar_path = temp_file.name
            # Read and write the uploaded file
            content = await tar_file.read()
            temp_file.write(content)
        
        # Load the image from tar file
        load_cmd = ["docker", "load", "-i", temp_tar_path]
        load_result = subprocess.run(
            load_cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes for large images
        )
        
        if load_result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load image from tar file: {load_result.stderr}"
            )
        
        # Extract image name from docker load output
        # Output format: "Loaded image: myimage:latest" or "Loaded image: myimage:latest\nLoaded image: myimage:tag2"
        loaded_image_name = None
        output_lines_load = load_result.stdout.strip().split('\n')
        if output_lines_load:
            # Get the last loaded image (usually the main one)
            last_line = output_lines_load[-1]
            if 'Loaded image:' in last_line:
                loaded_image_name = last_line.split('Loaded image:')[1].strip()
            else:
                # Fallback: try to extract from first line
                if 'Loaded image:' in output_lines_load[0]:
                    loaded_image_name = output_lines_load[0].split('Loaded image:')[1].strip()
        
        if not loaded_image_name:
            raise HTTPException(
                status_code=500,
                detail="Failed to extract image name from docker load output. Please ensure the tar file contains a valid Docker image."
            )
        
        # Use the loaded image name for tagging
        source_image_name = loaded_image_name
        
        # Step 5: Tag the image
        tag_cmd = ["docker", "tag", source_image_name, full_image_name]
        tag_result = subprocess.run(
            tag_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        if tag_result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to tag image '{source_image_name}'. Make sure the image exists. Error: {tag_result.stderr}"
            )
        
        # Step 6: Push image to ECR
        push_cmd = ["docker", "push", full_image_name]
        push_process = subprocess.Popen(
            push_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Stream output
        output_lines = []
        for line in push_process.stdout:
            output_lines.append(line.strip())
        
        push_process.wait(timeout=600)  # 10 minute timeout
        
        if push_process.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to push image to ECR. Output: {''.join(output_lines[-10:])}"
            )
        
        return {
            "status": "ok",
            "message": f"Successfully pushed {full_image_name} to ECR",
            "imageUri": full_image_name,
            "sourceImage": source_image_name,
            "output": "\n".join(output_lines)
        }
        
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail="Docker operation timed out"
        )
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS ECR error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to push image to ECR: {str(e)}"
        )
    finally:
        # Clean up temporary tar file
        if temp_tar_path and os.path.exists(temp_tar_path):
            try:
                os.unlink(temp_tar_path)
            except Exception:
                pass  # Don't fail if cleanup fails


@router.delete("/ecr/repositories/{repository}")
async def clear_repository(
    request: Request,
    repository: str,
    region: str = "us-east-1"
):
    """
    Delete all images from an ECR repository.
    This will delete all image tags but keep the repository itself.
    """
    # Check for session-based auth
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = _get_session_credentials_from_api_server(session_id)
        # Use region from query parameter if provided, fallback to session region
        query_region = request.query_params.get("region")
        if query_region:
            region = query_region
        else:
            region = region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_api_server(creds, region)
    except HTTPException as e:
        raise
    
    ecr = session.client("ecr", region_name=region)
    
    try:
        total_deleted = 0
        max_attempts = 5  # Maximum number of deletion attempts
        
        for attempt in range(max_attempts):
            # List all remaining images in the repository (including untagged)
            all_image_ids = []
            paginator = ecr.get_paginator('list_images')
            for page in paginator.paginate(repositoryName=repository):
                all_image_ids.extend(page.get('imageIds', []))
            
            if not all_image_ids:
                # All images deleted successfully
                break
            
            # Try to delete all remaining images
            delete_response = ecr.batch_delete_image(
                repositoryName=repository,
                imageIds=all_image_ids
            )
            
            deleted_this_round = len(delete_response.get('imageIds', []))
            total_deleted += deleted_this_round
            failures = delete_response.get('failures', [])
            
            # If no failures, we're done
            if not failures:
                break
            
            # Check if all failures are due to manifest lists
            # If so, we'll retry (manifest lists can be deleted after their referenced images)
            manifest_list_only = all(
                f.get('failureCode') == 'ImageReferencedByManifestList' 
                for f in failures
            )
            
            if not manifest_list_only:
                # There are other types of failures, report them
                failure_messages = [f.get('failureCode', 'Unknown') for f in failures]
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to delete {len(failures)} image(s). Errors: {', '.join(set(failure_messages))}"
                )
            
            # All failures are manifest list related - wait a moment and retry
            # This allows ECR to clean up references
            if attempt < max_attempts - 1:
                import time
                time.sleep(1)  # Brief pause before retry
        
        # Final check: if there are still images, they might be stuck manifest lists
        # List one more time to see if anything remains
        final_check = []
        paginator = ecr.get_paginator('list_images')
        for page in paginator.paginate(repositoryName=repository):
            final_check.extend(page.get('imageIds', []))
        
        if final_check:
            # Try one more time with just digests (no tags)
            digest_only = [{'imageDigest': img.get('imageDigest')} for img in final_check if img.get('imageDigest')]
            if digest_only:
                final_response = ecr.batch_delete_image(
                    repositoryName=repository,
                    imageIds=digest_only
                )
                total_deleted += len(final_response.get('imageIds', []))
        
        return {
            "status": "ok",
            "message": f"Successfully deleted {total_deleted} image(s) from repository '{repository}'",
            "deletedCount": total_deleted
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        
        if error_code == 'RepositoryNotFoundException':
            raise HTTPException(
                status_code=404,
                detail=f"Repository '{repository}' not found"
            )
        
        raise HTTPException(
            status_code=500,
            detail=f"AWS ECR error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear repository: {str(e)}"
        )

