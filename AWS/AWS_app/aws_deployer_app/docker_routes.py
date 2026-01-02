"""
Docker and ECR-related API routes.
Uses AWS CodeBuild to build and push Docker images to ECR.
No Docker required on backend - CodeBuild handles everything.
"""

import os
import json
import time
import uuid
import zipfile
import tempfile
import logging
import yaml
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["docker"])


def _get_session_credentials_from_auth(session_id):
    """Import and call session credentials function from auth_routes."""
    from auth_routes import get_session_credentials
    return get_session_credentials(session_id)


def _session_from_credentials_from_auth(credentials, region):
    """Import and call session creation function from auth_routes."""
    from auth_routes import session_from_credentials
    return session_from_credentials(credentials, region)


@router.get("/docker/check")
def docker_check():
    """
    Informational endpoint - Docker should be installed on the user's local machine.
    This endpoint always returns available=True since Docker operations are done client-side.
    """
    return {
        "available": True,
        "version": None,
        "daemon_running": True,
        "message": "Docker should be installed on your local machine. Push images using the provided commands."
    }


@router.post("/ecr/build-image")
async def build_image_with_codebuild(
    request: Request,
    repository: str = Form(...),
    image_tag: str = Form(default="latest"),
    region: str = Form(default="us-east-1"),
    dockerfile_path: str = Form(default="Dockerfile"),
    source_code: UploadFile = File(..., description="Source code zip file or Docker image tar file")
):
    """
    Build and push Docker image to ECR using AWS CodeBuild.
    Supports both:
    - Source code zip file: CodeBuild will build from Dockerfile
    - Docker image tar file: CodeBuild will load and push the image
    """
    # Check for session-based auth
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = _get_session_credentials_from_auth(session_id)
        region = region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_auth(creds, region)
        account_id = creds.get('account_id', '')
    except HTTPException as e:
        raise
    
    ecr = session.client("ecr", region_name=region)
    s3 = session.client("s3", region_name=region)
    codebuild = session.client("codebuild", region_name=region)
    iam = session.client("iam", region_name=region)
    
    ecr_registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    full_image_uri = f"{ecr_registry}/{repository}:{image_tag}"
    
    # Detect file type from filename
    filename = source_code.filename or "source.zip"
    is_tar_file = filename.endswith('.tar') or filename.endswith('.tar.gz')
    file_extension = '.tar' if is_tar_file else '.zip'
    
    # Generate unique build ID
    build_id = str(uuid.uuid4())[:8]
    s3_bucket = f"inversion-codebuild-{account_id}"
    s3_key = f"source/{build_id}/source{file_extension}"
    
    temp_file_path = None
    
    try:
        # Step 1: Ensure ECR repository exists
        try:
            ecr.describe_repositories(repositoryNames=[repository])
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                ecr.create_repository(
                    repositoryName=repository,
                    imageScanningConfiguration={'scanOnPush': True},
                    imageTagMutability='MUTABLE'
                )
            else:
                raise
        
        # Step 2: Ensure S3 bucket exists for source code
        try:
            s3.head_bucket(Bucket=s3_bucket)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['404', '403']:
                try:
                    s3.create_bucket(
                        Bucket=s3_bucket,
                        CreateBucketConfiguration={'LocationConstraint': region} if region != 'us-east-1' else {}
                    )
                except ClientError as create_err:
                    if create_err.response.get('Error', {}).get('Code') != 'BucketAlreadyOwnedByYou':
                        raise
        
        # Step 3: Save uploaded file, create buildspec.yml, package into zip, and upload to S3
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file_path = temp_file.name
            content = await source_code.read()
            temp_file.write(content)
        
        # Create buildspec.yml content using yaml.dump for proper escaping
        if is_tar_file:
            # For tar files: load and push
            buildspec_dict = {
                'version': '0.2',
                'phases': {
                    'pre_build': {
                        'commands': [
                            'echo Logging in to Amazon ECR...',
                            f'aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com',
                            f'export REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/{repository}',
                            f'export IMAGE_TAG={image_tag}',
                            'echo Listing files in working directory...',
                            'ls -la',
                            'echo Finding tar file...',
                            "TAR_FILE=$(find . -maxdepth 2 '(' -name '*.tar' -o -name '*.tar.gz' ')' | head -n 1)",
                            'echo Found tar file: $TAR_FILE',
                            'test -n "$TAR_FILE"',
                            'echo Loading Docker image from tar file...',
                            'docker load -i "$TAR_FILE"'
                        ]
                    },
                    'build': {
                        'commands': [
                            'echo Extracting image name from loaded image...',
                            "LOADED_IMAGE=$(docker images --format '{{.Repository}}:{{.Tag}}' | head -n 1)",
                            'echo Loaded image: $LOADED_IMAGE',
                            'echo Tagging image for ECR...',
                            'docker tag "$LOADED_IMAGE" "$REPOSITORY_URI:$IMAGE_TAG"'
                        ]
                    },
                    'post_build': {
                        'commands': [
                            'echo Pushing the Docker image to ECR...',
                            'docker push "$REPOSITORY_URI:$IMAGE_TAG"',
                            'echo Image pushed successfully: $REPOSITORY_URI:$IMAGE_TAG'
                        ]
                    }
                }
            }
        else:
            # For source code: build from Dockerfile
            buildspec_dict = {
                'version': '0.2',
                'phases': {
                    'pre_build': {
                        'commands': [
                            'echo Logging in to Amazon ECR...',
                            f'aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com',
                            f'export REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/{repository}',
                            f'export IMAGE_TAG={image_tag}',
                            'echo Listing files in working directory...',
                            'ls -la',
                            'echo Finding zip file...',
                            "ZIP_FILE=$(find . -name '*.zip' | head -n 1)",
                            'echo Found zip file: $ZIP_FILE',
                            'echo Extracting source code...',
                            'unzip -q "$ZIP_FILE"'
                        ]
                    },
                    'build': {
                        'commands': [
                            'echo Build started on $(date)',
                            'echo Building the Docker image...',
                            f'docker build -f {dockerfile_path} -t "$REPOSITORY_URI:$IMAGE_TAG" .'
                        ]
                    },
                    'post_build': {
                        'commands': [
                            'echo Build completed on $(date)',
                            'echo Pushing the Docker image...',
                            'docker push "$REPOSITORY_URI:$IMAGE_TAG"',
                            'echo Image pushed: $REPOSITORY_URI:$IMAGE_TAG'
                        ]
                    }
                }
            }
        
        # Generate YAML content with proper formatting
        buildspec_content = yaml.dump(buildspec_dict, default_flow_style=False, sort_keys=False)
        
        # Create a zip file containing both the user's file and buildspec.yml
        zip_s3_key = f"source/{build_id}/source.zip"
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as zip_file:
            zip_path = zip_file.name
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add the user's file (tar or zip) to the zip
                zipf.write(temp_file_path, os.path.basename(temp_file_path))
                # Add buildspec.yml to the zip
                zipf.writestr('buildspec.yml', buildspec_content)
        
        # Upload the zip to S3
        s3.upload_file(zip_path, s3_bucket, zip_s3_key)
        
        # Update s3_key to point to the zip file
        s3_key = zip_s3_key
        
        # Clean up zip file
        try:
            os.unlink(zip_path)
        except Exception:
            pass
        
        # Step 4: Ensure CodeBuild service role exists
        role_name = f"InversionCodeBuildRole-{account_id}"
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        
        # Trust policy for CodeBuild
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "codebuild.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        # Policy for ECR, S3, and CloudWatch Logs access
        policy_doc = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectVersion",
                        "s3:PutObject"
                    ],
                    "Resource": f"arn:aws:s3:::{s3_bucket}/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:ListBucket",
                        "s3:GetBucketLocation"
                    ],
                    "Resource": f"arn:aws:s3:::{s3_bucket}"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:GetAuthorizationToken"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:PutImage",
                        "ecr:InitiateLayerUpload",
                        "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload"
                    ],
                    "Resource": f"arn:aws:ecr:{region}:{account_id}:repository/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": f"arn:aws:logs:{region}:{account_id}:log-group:/aws/codebuild/*"
                }
            ]
        }
        
        try:
            existing_role = iam.get_role(RoleName=role_name)
            # Role exists - verify and update trust policy if needed
            existing_trust_policy = existing_role['Role']['AssumeRolePolicyDocument']
            # Compare trust policies (need to parse JSON string if it's a string)
            if isinstance(existing_trust_policy, str):
                existing_trust_policy = json.loads(existing_trust_policy)
            
            # Check if trust policy matches what we need
            expected_service = trust_policy['Statement'][0]['Principal']['Service']
            existing_service = existing_trust_policy.get('Statement', [{}])[0].get('Principal', {}).get('Service', '')
            
            if existing_service != expected_service:
                # Update trust policy
                print(f"[DEBUG] Updating trust policy for role {role_name} to allow {expected_service}")
                iam.update_assume_role_policy(
                    RoleName=role_name,
                    PolicyDocument=json.dumps(trust_policy)
                )
                # Wait for policy to propagate
                time.sleep(2)
            
            # Always update the inline policy to ensure it has correct permissions
            try:
                iam.put_role_policy(
                    RoleName=role_name,
                    PolicyName="CodeBuildPolicy",
                    PolicyDocument=json.dumps(policy_doc)
                )
                time.sleep(1)  # Wait for policy to propagate
            except ClientError as policy_error:
                print(f"[WARNING] Failed to update role policy: {policy_error}")
                
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                # Create service role for CodeBuild
                print(f"[DEBUG] Creating CodeBuild service role: {role_name}")
                iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="Service role for Inversion CodeBuild projects"
                )
                
                # Wait a moment for role to be available
                time.sleep(2)
                
                iam.put_role_policy(
                    RoleName=role_name,
                    PolicyName="CodeBuildPolicy",
                    PolicyDocument=json.dumps(policy_doc)
                )
                
                # Wait for policy to propagate
                time.sleep(1)
            else:
                raise
        
        # Step 5: Create or get CodeBuild project
        project_name = f"inversion-build-{repository.replace('_', '-')}"
        
        # S3 location for CodeBuild (without s3:// prefix)
        s3_location = f"{s3_bucket}/{s3_key}"
        
        try:
            codebuild.create_project(
                name=project_name,
                description=f"Build Docker image for {repository}",
                source={
                    'type': 'S3',
                    'location': s3_location,
                },
                artifacts={
                    'type': 'NO_ARTIFACTS'
                },
                environment={
                    'type': 'LINUX_CONTAINER',
                    'image': 'aws/codebuild/standard:7.0',
                    'computeType': 'BUILD_GENERAL1_SMALL',
                    'privilegedMode': True,
                    'environmentVariables': [
                        {'name': 'AWS_DEFAULT_REGION', 'value': region},
                        {'name': 'AWS_ACCOUNT_ID', 'value': account_id},
                        {'name': 'IMAGE_REPO_NAME', 'value': repository},
                        {'name': 'IMAGE_TAG', 'value': image_tag},
                        {'name': 'IMAGE_URI', 'value': full_image_uri},
                    ]
                },
                serviceRole=role_arn,
            )
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                raise
            # Project exists, update it
            codebuild.update_project(
                name=project_name,
                description=f"Build Docker image for {repository}",
                source={
                    'type': 'S3',
                    'location': s3_location,
                },
                artifacts={
                    'type': 'NO_ARTIFACTS'
                },
                environment={
                    'type': 'LINUX_CONTAINER',
                    'image': 'aws/codebuild/standard:7.0',
                    'computeType': 'BUILD_GENERAL1_SMALL',
                    'privilegedMode': True,
                    'environmentVariables': [
                        {'name': 'AWS_DEFAULT_REGION', 'value': region},
                        {'name': 'AWS_ACCOUNT_ID', 'value': account_id},
                        {'name': 'IMAGE_REPO_NAME', 'value': repository},
                        {'name': 'IMAGE_TAG', 'value': image_tag},
                        {'name': 'IMAGE_URI', 'value': full_image_uri},
                    ]
                },
                serviceRole=role_arn,
            )
        
        # Step 6: Start the build
        build_response = codebuild.start_build(
            projectName=project_name,
            sourceLocationOverride=s3_location,
        )
        
        build_id_arn = build_response['build']['id']
        
        return {
            "status": "ok",
            "message": "Build started successfully",
            "build_id": build_id_arn,
            "project_name": project_name,
            "image_uri": full_image_uri,
            "repository": repository,
            "tag": image_tag,
            "region": region
        }
        
    except HTTPException:
        raise
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        # Log full error for debugging
        logger.error(f"CodeBuild ClientError: {error_code} - {error_msg}")
        logger.error(f"Full error response: {json.dumps(e.response, default=str)}")
        
        # Provide more helpful error messages
        if error_code == 'AccessDeniedException':
            detail_msg = f"Access denied: {error_msg}. Please ensure the IAM role has CodeBuild permissions."
        elif error_code == 'InvalidInputException':
            detail_msg = f"Invalid input: {error_msg}. Check your parameters."
        else:
            detail_msg = f"AWS error ({error_code}): {error_msg}"
        
        raise HTTPException(
            status_code=500,
            detail=detail_msg
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Unexpected error starting build: {str(e)}")
        logger.error(f"Traceback: {error_trace}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start build: {str(e)}"
        )
    finally:
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass


@router.get("/ecr/build-status/{build_id}")
def get_build_status(
    request: Request,
    build_id: str,
    region: str = "us-east-1"
):
    """Get the status of a CodeBuild build."""
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = _get_session_credentials_from_auth(session_id)
        region = region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_auth(creds, region)
    except HTTPException as e:
        raise
    
    codebuild = session.client("codebuild", region_name=region)
    
    try:
        builds = codebuild.batch_get_builds(ids=[build_id])
        if not builds['builds']:
            raise HTTPException(status_code=404, detail="Build not found")
        
        build = builds['builds'][0]
        
        # Extract error information if build failed
        error_info = None
        error_message = None
        if build.get('buildStatus') == 'FAILED':
            # Get phase information for errors
            phases = build.get('phases', [])
            failed_phases = [p for p in phases if p.get('phaseStatus') == 'FAILED']
            
            # Also check for any phase with errors, even if status isn't explicitly FAILED
            all_phases_with_context = [p for p in phases if p.get('phaseContext')]
            
            if failed_phases:
                failed_phase = failed_phases[0]
                error_info = {
                    "failed_phase": failed_phase.get('phaseType', 'UNKNOWN'),
                    "phase_context": failed_phase.get('phaseContext', []),
                }
                # Try to extract error message from phase context
                phase_context = failed_phase.get('phaseContext', [])
                if phase_context:
                    # Look for error messages in context
                    for ctx in phase_context:
                        if isinstance(ctx, str):
                            if 'error' in ctx.lower() or 'failed' in ctx.lower() or 'exit status' in ctx.lower():
                                error_message = ctx
                                break
                    if not error_message and len(phase_context) > 0:
                        error_message = str(phase_context[-1])  # Use last context item
            
            # If no error message found, try to get from build status reason
            if not error_message:
                status_reason = build.get('buildStatusReason', '')
                if status_reason:
                    error_message = status_reason
        
        # Extract image_uri from environment variables (which is a list, not a dict)
        env_vars = build.get("environment", {}).get("environmentVariables", []) or []
        env_map = {v.get("name"): v.get("value") for v in env_vars if isinstance(v, dict)}
        image_uri = env_map.get("IMAGE_URI") or env_map.get("REPOSITORY_URI")
        
        return {
            "status": "ok",
            "build_id": build['id'],
            "build_status": build['buildStatus'],
            "build_phase": build.get('currentPhase', 'UNKNOWN'),
            "build_complete": build['buildComplete'],
            "start_time": build.get('startTime').isoformat() if build.get('startTime') else None,
            "end_time": build.get('endTime').isoformat() if build.get('endTime') else None,
            "logs": {
                "group_name": build.get('logs', {}).get('groupName'),
                "stream_name": build.get('logs', {}).get('streamName'),
                "deep_link": build.get('logs', {}).get('deepLink'),
            },
            "image_uri": image_uri,
            "error_info": error_info,
            "error_message": error_message,
            "build_number": build.get('buildNumber'),
        }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS CodeBuild error ({error_code}): {error_msg}"
        )


@router.get("/ecr/build-logs/{build_id}")
def get_build_logs(
    request: Request,
    build_id: str,
    region: str = "us-east-1",
    limit: int = 1000
):
    """Get CloudWatch logs for a CodeBuild build."""
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = _get_session_credentials_from_auth(session_id)
        region = region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_auth(creds, region)
    except HTTPException as e:
        raise
    
    codebuild = session.client("codebuild", region_name=region)
    logs_client = session.client("logs", region_name=region)
    
    try:
        # Get build info to find log group/stream
        builds = codebuild.batch_get_builds(ids=[build_id])
        if not builds['builds']:
            raise HTTPException(status_code=404, detail="Build not found")
        
        build = builds['builds'][0]
        logs_info = build.get('logs', {})
        log_group = logs_info.get('groupName')
        log_stream = logs_info.get('streamName')
        
        if not log_group or not log_stream:
            return {
                "status": "ok",
                "logs": "",
                "message": "No logs available for this build"
            }
        
        # Fetch logs from CloudWatch
        try:
            response = logs_client.get_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                limit=limit,
                startFromHead=False  # Get most recent logs first
            )
            
            # Combine all log events
            log_lines = []
            for event in response.get('events', []):
                timestamp = event.get('timestamp', 0)
                message = event.get('message', '')
                # Convert timestamp to readable format
                from datetime import datetime
                dt = datetime.fromtimestamp(timestamp / 1000)
                log_lines.append(f"[{dt.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
            
            # Reverse to show oldest first
            log_lines.reverse()
            logs_content = '\n'.join(log_lines)
            
            return {
                "status": "ok",
                "logs": logs_content,
                "log_group": log_group,
                "log_stream": log_stream,
                "event_count": len(log_lines)
            }
        except ClientError as log_error:
            error_code = log_error.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'ResourceNotFoundException':
                return {
                    "status": "ok",
                    "logs": "",
                    "message": "Log stream not found. Logs may not be available yet or may have been deleted."
                }
            raise
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"AWS error ({error_code}): {error_msg}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get build logs: {str(e)}"
        )


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
        creds = _get_session_credentials_from_auth(session_id)
        # Use region from query parameter if provided, fallback to session region
        query_region = request.query_params.get("region")
        if query_region:
            region = query_region
        else:
            region = region or creds.get('region', 'us-east-1')
        session = _session_from_credentials_from_auth(creds, region)
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

