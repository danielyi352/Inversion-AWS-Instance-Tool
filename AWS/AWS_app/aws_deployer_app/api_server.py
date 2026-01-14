"""
FastAPI bridge that exposes the existing deployer engine over HTTP so the new
web UI can call into the same AWS workflows (SSO/login, metadata fetch, deploy,
terminate, connect).
"""

from __future__ import annotations

import os
import subprocess
import sys
import shlex
import time
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Generator

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import paramiko

# Import routers
from docker_routes import router as docker_router
from file_transfer_routes import router as file_transfer_router
from auth_routes import router as auth_router, get_session_credentials, session_from_credentials

# ------------------------------------------------------------------------------
# FastAPI setup
# ------------------------------------------------------------------------------

app = FastAPI(title="Inversion Deployer API", version="1.0.0")

# Allow local dev server (Vite) to talk to the API.
# Explicitly allow localhost and 127.0.0.1 for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"  # Allow all for production flexibility
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(docker_router)
app.include_router(file_transfer_router)
try:
    from terminal_routes import router as terminal_router
    app.include_router(terminal_router)
except ImportError:
    print("Warning: terminal_routes not available (websockets dependency may be missing)")


# ------------------------------------------------------------------------------
# Root and Health Check Endpoints
# ------------------------------------------------------------------------------

@app.get("/")
def root():
    """Root endpoint - returns API information."""
    return {
        "name": "Inversion Deployer API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "api": "/api"
        }
    }

@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ------------------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------------------




class DeployRequestModel(BaseModel):
    profile: Optional[str] = Field(None, description="AWS profile (deprecated - not used, session-based auth is used instead)")
    region: str
    account_id: str
    repository: str
    instance_type: str
    key_pair: Optional[str] = Field(None, description="EC2 key pair name (deprecated - not used, SSM is used instead)")
    security_group: Optional[str] = Field(None, description="Security group name (optional - defaults to 'inversion-deployer-default')")
    volume_size: int = Field(default=30, ge=1, le=2048)
    volume_type: Optional[str] = Field(default='gp3', description="EBS volume type (gp3, gp2, io1, io2, st1, sc1)")
    availability_zone: Optional[str] = Field(None, description="Availability zone (optional - uses default if not specified)")
    subnet_id: Optional[str] = Field(None, description="Subnet ID (optional - uses default VPC if not specified)")
    user_data: Optional[str] = Field(None, description="User data script (optional - base64 encoded bash script)")
    ami_id: Optional[str] = Field(None, description="Custom AMI ID (optional - uses auto-detection if not specified)")
    ami_type: Optional[str] = Field(None, description="AMI type: 'auto', 'al2023', 'deep-learning-gpu', 'ubuntu-22', 'custom'")


class TerminateRequest(BaseModel):
    profile: str
    region: str
    instance_id: str


class ConnectRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    ssh_user: str = Field(default="ubuntu")
    key_path: Optional[str] = None
    launch_terminal: bool = Field(default=True)






# ------------------------------------------------------------------------------
# Session Management (imported from auth_routes)
# ------------------------------------------------------------------------------
# Session management functions are imported from auth_routes module


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
AwsMilestones = (
    ("checking aws cli prerequisites", 5),
    ("key pair", 10),
    ("finding latest", 15),
    ("creating security group", 20),
    ("launching ec2", 30),
    ("waiting for instance state", 40),
    ("waiting for aws status checks", 50),
    ("ssh connection established", 55),
    ("installing docker", 60),
    ("docker installation completed", 70),
    ("configuring aws credentials", 75),
    ("aws sso credentials configured", 80),
    ("pulling", 85),
    ("container deployment completed", 95),
    ("deployment completed successfully", 100),
)


def _session(profile: str, region: str):
    """Legacy session creation using profile (for backward compatibility)."""
    try:
        return boto3.Session(profile_name=profile, region_name=region)
    except (BotoCoreError, NoCredentialsError) as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run(cmd: List[str], env: Optional[Dict[str, str]] = None) -> str:
    try:
        return subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT, env=env
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=exc.output) from exc


# ------------------------------------------------------------------------------
# New boto3-based deployment functions (no AWS CLI required)
# ------------------------------------------------------------------------------

def _log_message(message: str) -> str:
    """Format log message with timestamp."""
    return f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} - {message}"


def _ensure_iam_role(iam_client, role_name: str, account_id: str, log_callback=None) -> str:
    """Ensure IAM role exists with SSM and S3 permissions. Returns role ARN."""
    if log_callback:
        log_callback(_log_message(f"Checking IAM role: {role_name}"))
    
    # Trust policy for EC2
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "ec2.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    try:
        # Check if role exists
        role = iam_client.get_role(RoleName=role_name)
        role_arn = role['Role']['Arn']
        
        # Verify role has correct trust policy
        existing_trust_policy = role['Role']['AssumeRolePolicyDocument']
        if isinstance(existing_trust_policy, str):
            existing_trust_policy = json.loads(existing_trust_policy)
        
        expected_service = trust_policy['Statement'][0]['Principal']['Service']
        existing_service = existing_trust_policy.get('Statement', [{}])[0].get('Principal', {}).get('Service', '')
        
        if existing_service != expected_service:
            # Update trust policy
            if log_callback:
                log_callback(_log_message(f"Updating trust policy for role {role_name} to allow {expected_service}"))
            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy)
            )
            time.sleep(2)  # Wait for policy to propagate
        
        # Verify instance profile exists and is correctly configured
        try:
            profile = iam_client.get_instance_profile(InstanceProfileName=role_name)
            # Check if role is attached to instance profile
            roles = [r['RoleName'] for r in profile['InstanceProfile'].get('Roles', [])]
            if role_name not in roles:
                # Role not attached - attach it
                if log_callback:
                    log_callback(_log_message(f"Attaching role {role_name} to instance profile"))
                try:
                    iam_client.add_role_to_instance_profile(
                        InstanceProfileName=role_name,
                        RoleName=role_name
                    )
                    # Wait for attachment to propagate
                    time.sleep(2)
                except ClientError as add_err:
                    if add_err.response['Error']['Code'] not in ['LimitExceeded', 'EntityAlreadyExists']:
                        raise
            else:
                if log_callback:
                    log_callback(_log_message(f"IAM role {role_name} and instance profile already exist and are correctly configured"))
        except ClientError:
            # Role exists but instance profile doesn't - create it
            if log_callback:
                log_callback(_log_message(f"Creating instance profile for existing role: {role_name}"))
            try:
                iam_client.create_instance_profile(InstanceProfileName=role_name)
            except ClientError as profile_err:
                if profile_err.response['Error']['Code'] != 'EntityAlreadyExists':
                    raise
            
            # Attach role to instance profile
            try:
                profile = iam_client.get_instance_profile(InstanceProfileName=role_name)
                roles = [r['RoleName'] for r in profile['InstanceProfile'].get('Roles', [])]
                if role_name not in roles:
                    iam_client.add_role_to_instance_profile(
                        InstanceProfileName=role_name,
                        RoleName=role_name
                    )
            except ClientError as add_err:
                if add_err.response['Error']['Code'] not in ['LimitExceeded', 'EntityAlreadyExists']:
                    raise
            
            # Wait for instance profile to be ready
            for attempt in range(10):
                try:
                    profile = iam_client.get_instance_profile(InstanceProfileName=role_name)
                    if profile['InstanceProfile'].get('Roles'):
                        break
                except ClientError:
                    pass
                time.sleep(1)
        
        return role_arn
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            # Role doesn't exist, create it
            if log_callback:
                log_callback(_log_message(f"Creating IAM role: {role_name}"))
            
            # Create role
            role = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="IAM role for Inversion Deployer EC2 instances with SSM and S3 access"
            )
            role_arn = role['Role']['Arn']
            
            # Attach AWS managed policies for SSM
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
            )
            
            # Create and attach S3 policy
            s3_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:PutObject",
                            "s3:GetObject",
                            "s3:DeleteObject"
                        ],
                        "Resource": f"arn:aws:s3:::inversion-deployer-temp-{account_id}/*"
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:ListBucket",
                            "s3:GetBucketLocation"
                        ],
                        "Resource": f"arn:aws:s3:::inversion-deployer-temp-{account_id}"
                    }
                ]
            }
            
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{role_name}-S3Policy",
                PolicyDocument=json.dumps(s3_policy)
            )
            
            # Create instance profile and attach role
            profile_created = False
            try:
                iam_client.create_instance_profile(InstanceProfileName=role_name)
                profile_created = True
            except ClientError as profile_err:
                if profile_err.response['Error']['Code'] != 'EntityAlreadyExists':
                    raise
            
            # Check if role is already attached to instance profile
            try:
                profile = iam_client.get_instance_profile(InstanceProfileName=role_name)
                roles = [r['RoleName'] for r in profile['InstanceProfile']['Roles']]
                if role_name not in roles:
                    iam_client.add_role_to_instance_profile(
                        InstanceProfileName=role_name,
                        RoleName=role_name
                    )
            except ClientError as add_err:
                if add_err.response['Error']['Code'] not in ['LimitExceeded', 'EntityAlreadyExists']:
                    raise
            
            if log_callback:
                log_callback(_log_message(f"IAM role {role_name} created with SSM and S3 permissions"))
            
            # Wait for instance profile to be available (IAM can take a few seconds to propagate)
            if profile_created:
                if log_callback:
                    log_callback(_log_message("Waiting for instance profile to be available..."))
                for attempt in range(10):  # Wait up to 10 seconds
                    try:
                        profile = iam_client.get_instance_profile(InstanceProfileName=role_name)
                        if profile['InstanceProfile']['Roles']:
                            if log_callback:
                                log_callback(_log_message("Instance profile is ready"))
                            break
                    except ClientError:
                        pass
                    time.sleep(1)
            
            return role_arn
        else:
            raise HTTPException(status_code=500, detail=f"Failed to check IAM role: {e}")


# Key pair functions removed - all access is via SSM using IAM instance profiles


def _get_latest_ami(ec2_client, ssm_client, repository: str, region: str, log_callback=None,
                   ami_id: Optional[str] = None, ami_type: Optional[str] = None) -> tuple:
    """Get latest AMI ID and root device name. Returns (ami_id, root_device_name).
    
    Args:
        ami_id: Custom AMI ID to use (if provided, this takes precedence)
        ami_type: AMI type selection ('auto', 'al2023', 'deep-learning-gpu', 'ubuntu-22', 'custom')
    """
    # If custom AMI ID is provided, use it directly
    if ami_id:
        if log_callback:
            log_callback(_log_message(f"Using custom AMI: {ami_id}"))
        try:
            response = ec2_client.describe_images(ImageIds=[ami_id])
            root_device_name = response['Images'][0]['RootDeviceName']
            if log_callback:
                log_callback(_log_message(f"AMI root device: {root_device_name}"))
            return ami_id, root_device_name
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"Invalid custom AMI ID {ami_id}: {e}")
    
    # Determine AMI type based on selection or auto-detect
    if ami_type == 'al2023':
        target_gpu = 0
    elif ami_type == 'deep-learning-gpu':
        target_gpu = 1
    elif ami_type == 'ubuntu-22':
        # Ubuntu 22.04 LTS
        if log_callback:
            log_callback(_log_message("Finding latest Ubuntu Server 22.04 LTS AMI (x86_64)..."))
        try:
            response = ec2_client.describe_images(
                Owners=['099720109477'],  # Canonical
                Filters=[
                    {'Name': 'name', 'Values': ['ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*']},
                    {'Name': 'state', 'Values': ['available']},
                    {'Name': 'architecture', 'Values': ['x86_64']}
                ]
            )
            images = sorted(response['Images'], key=lambda x: x['CreationDate'], reverse=True)
            if not images:
                raise HTTPException(status_code=500, detail="Could not find Ubuntu 22.04 AMI")
            ami_id = images[0]['ImageId']
            root_device_name = images[0]['RootDeviceName']
            if log_callback:
                log_callback(_log_message(f"Using AMI: {ami_id} (root device: {root_device_name})"))
            return ami_id, root_device_name
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"Failed to find Ubuntu AMI: {e}")
    elif ami_type == 'auto' or ami_type is None:
        # Auto-detect: Detect GPU vs CPU based on repository name
        repo_lower = repository.lower()
        target_gpu = 0 if 'cpu' in repo_lower else 1
    else:
        # Default to CPU if unknown type
        target_gpu = 0
    
    if target_gpu == 1:
        # GPU AMI
        if log_callback:
            log_callback(_log_message("Finding latest Amazon Linux Deep Learning Base OSS Nvidia Driver GPU AMI (x86_64)..."))
        try:
            response = ec2_client.describe_images(
                Owners=['amazon'],
                Filters=[
                    {'Name': 'name', 'Values': ['Deep Learning Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023)*']},
                    {'Name': 'state', 'Values': ['available']},
                    {'Name': 'architecture', 'Values': ['x86_64']}
                ]
            )
            images = sorted(response['Images'], key=lambda x: x['CreationDate'], reverse=True)
            if not images:
                raise HTTPException(status_code=500, detail="Could not find GPU AMI")
            ami_id = images[0]['ImageId']
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"Failed to find GPU AMI: {e}")
    else:
        # CPU AMI
        if log_callback:
            log_callback(_log_message("Finding latest Amazon Linux 2023 AMI (x86_64)..."))
        try:
            response = ssm_client.get_parameters(
                Names=['/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64']
            )
            if not response['Parameters']:
                raise HTTPException(status_code=500, detail="Could not retrieve Amazon Linux 2023 AMI via SSM")
            ami_id = response['Parameters'][0]['Value']
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"Failed to get CPU AMI: {e}")
    
    # Get root device name
    try:
        response = ec2_client.describe_images(ImageIds=[ami_id])
        root_device_name = response['Images'][0]['RootDeviceName']
        if log_callback:
            log_callback(_log_message(f"Using AMI: {ami_id} (root device: {root_device_name})"))
        return ami_id, root_device_name
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to get AMI details: {e}")


def _ensure_security_group(ec2_client, security_group_name: str, repository: str, region: str, log_callback=None) -> str:
    """Ensure security group exists. Returns security group ID.
    
    Note: No inbound rules are added - SSM uses outbound HTTPS connections only.
    """
    try:
        # Check if security group exists
        response = ec2_client.describe_security_groups(GroupNames=[security_group_name])
        sg_id = response['SecurityGroups'][0]['GroupId']
        if log_callback:
            log_callback(_log_message(f"Security group {security_group_name} already exists ({sg_id})"))
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            # Create security group
            try:
                response = ec2_client.create_security_group(
                    GroupName=security_group_name,
                    Description=f"Security group for {repository} Docker container (SSM-only, no inbound rules needed)"
                )
                sg_id = response['GroupId']
                if log_callback:
                    log_callback(_log_message(f"Created security group: {sg_id} (SSM-only, no SSH rules)"))
            except ClientError as create_err:
                raise HTTPException(status_code=500, detail=f"Failed to create security group: {create_err}")
        else:
            raise
    
    # No SSH rules needed - SSM uses outbound HTTPS (port 443) which is allowed by default
    return sg_id


def _requires_cluster_placement_group(instance_type: str) -> bool:
    """Check if instance type requires a cluster placement group.
    
    HPC instances (hpc6a, hpc6id, hpc7a, hpc7g, etc.) require cluster placement groups
    for their high-performance networking capabilities.
    
    Args:
        instance_type: EC2 instance type (e.g., 'hpc7a.96xlarge', 'g5.xlarge')
    
    Returns:
        True if instance type requires cluster placement group, False otherwise
    """
    instance_lower = instance_type.lower()
    # HPC instance families require cluster placement groups
    hpc_families = ['hpc6a', 'hpc6id', 'hpc7a', 'hpc7g']
    return any(hpc_family in instance_lower for hpc_family in hpc_families)


def _get_hpc7a_supported_regions() -> Dict[str, str]:
    """Get mapping of HPC7a supported regions.
    
    Returns:
        Dictionary mapping region codes to region names
    """
    return {
        'us-east-2': 'US East (Ohio)',
        'eu-west-1': 'Europe (Ireland)',
        'eu-west-3': 'Europe (Paris)',
        'eu-north-1': 'Europe (Stockholm)',
        'us-gov-west-1': 'AWS GovCloud (US-West)'
    }


def _validate_instance_type_region(ec2_client, instance_type: str, region: str, 
                                   log_callback=None) -> None:
    """Validate that the instance type is available in the specified region.
    
    For HPC7a instances, provides specific error message with supported regions.
    
    Args:
        ec2_client: Boto3 EC2 client
        instance_type: EC2 instance type (e.g., 'hpc7a.96xlarge')
        region: AWS region code (e.g., 'us-east-2')
        log_callback: Optional callback function for logging
    
    Raises:
        HTTPException: If instance type is not available in the region
    """
    instance_lower = instance_type.lower()
    
    # Check if this is an HPC7a instance
    if 'hpc7a' in instance_lower:
        supported_regions = _get_hpc7a_supported_regions()
        
        if region not in supported_regions:
            # Region doesn't support HPC7a - provide helpful error
            region_list = ', '.join([f"{code} ({name})" for code, name in supported_regions.items()])
            error_msg = (
                f"HPC7a instances are not available in region '{region}'. "
                f"HPC7a instances are only available in the following regions: {region_list}. "
                f"Please use one of these regions to launch HPC7a instances."
            )
            if log_callback:
                log_callback(_log_message(f"ERROR: {error_msg}"))
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Region is supported, but verify instance type is actually available
        try:
            # Check if instance type is available in any AZ in this region
            response = ec2_client.describe_instance_type_offerings(
                LocationType='availability-zone',
                Filters=[
                    {'Name': 'instance-type', 'Values': [instance_type]}
                ]
            )
            
            if not response.get('InstanceTypeOfferings'):
                # Instance type not available in any AZ
                region_list = ', '.join([f"{code} ({name})" for code, name in supported_regions.items()])
                error_msg = (
                    f"Instance type '{instance_type}' is not available in region '{region}' "
                    f"(even though it's a supported HPC7a region). "
                    f"HPC7a instances are available in: {region_list}. "
                    f"This may be due to capacity constraints or the instance type not being available "
                    f"in any availability zones in this region."
                )
                if log_callback:
                    log_callback(_log_message(f"ERROR: {error_msg}"))
                raise HTTPException(status_code=400, detail=error_msg)
            
            if log_callback:
                available_azs = [offering['Location'] for offering in response['InstanceTypeOfferings']]
                log_callback(_log_message(
                    f"Instance type {instance_type} is available in region {region} "
                    f"(AZs: {', '.join(available_azs)})"
                ))
        except ClientError as e:
            # If describe_instance_type_offerings fails, log but don't fail
            # (might be a permissions issue, let the actual launch fail with a clearer error)
            if log_callback:
                log_callback(_log_message(
                    f"Warning: Could not verify instance type availability: {e}"
                ))


def _ensure_placement_group(ec2_client, account_id: str, region: str, 
                            availability_zone: Optional[str] = None, 
                            log_callback=None) -> Optional[str]:
    """Ensure cluster placement group exists. Returns placement group name if created/exists.
    
    Args:
        ec2_client: Boto3 EC2 client
        account_id: AWS account ID
        region: AWS region
        availability_zone: Availability zone (optional, will use default if not specified)
        log_callback: Optional callback function for logging
    
    Returns:
        Placement group name if placement group is needed, None otherwise
    """
    placement_group_name = f"inversion-deployer-hpc-placement-group-{account_id}"
    
    try:
        # Check if placement group already exists
        response = ec2_client.describe_placement_groups(GroupNames=[placement_group_name])
        if response['PlacementGroups']:
            if log_callback:
                log_callback(_log_message(f"Placement group {placement_group_name} already exists"))
            return placement_group_name
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidPlacementGroup.Unknown':
            # Placement group doesn't exist, create it
            if log_callback:
                log_callback(_log_message(f"Creating cluster placement group: {placement_group_name}"))
            try:
                ec2_client.create_placement_group(
                    GroupName=placement_group_name,
                    Strategy='cluster',
                    TagSpecifications=[{
                        'ResourceType': 'placement-group',
                        'Tags': [
                            {'Key': 'Name', 'Value': placement_group_name},
                            {'Key': 'Purpose', 'Value': 'HPC-instance-cluster-networking'}
                        ]
                    }]
                )
                if log_callback:
                    log_callback(_log_message(f"Created cluster placement group: {placement_group_name}"))
                # Wait a moment for placement group to be available
                time.sleep(1)
                return placement_group_name
            except ClientError as create_err:
                error_code = create_err.response.get('Error', {}).get('Code', '')
                if error_code == 'InvalidPlacementGroup.Duplicate':
                    # Placement group was created between check and create
                    if log_callback:
                        log_callback(_log_message(f"Placement group {placement_group_name} already exists"))
                    return placement_group_name
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create placement group: {create_err}"
                    )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to check placement group: {e}"
            )
    
    return placement_group_name


def _launch_ec2_instance(ec2_client, iam_client, ami_id: str, instance_type: str,
                        security_group_name: str, root_device_name: str, volume_size: int,
                        repository: str, account_id: str, region: str, log_callback=None,
                        volume_type: Optional[str] = 'gp3', availability_zone: Optional[str] = None,
                        subnet_id: Optional[str] = None, user_data: Optional[str] = None) -> tuple:
    """Launch EC2 instance and wait for it to be running. Returns (instance_id, public_dns).
    
    Note: Key pairs are not used - all access is via SSM.
    """
    if log_callback:
        log_callback(_log_message("Launching EC2 instance..."))
    
    container_name = f"{account_id}-{repository}-container"
    
    # Ensure IAM role exists for SSM and S3 access
    role_name = f"inversion-deployer-instance-role-{account_id}"
    _ensure_iam_role(iam_client, role_name, account_id, log_callback)
    
    # Get instance profile ARN (more reliable than name)
    try:
        profile = iam_client.get_instance_profile(InstanceProfileName=role_name)
        instance_profile_arn = profile['InstanceProfile']['Arn']
    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get instance profile: {e}. Please ensure the instance profile exists."
        )
    
    # Validate instance type is available in the region (especially for HPC instances)
    _validate_instance_type_region(ec2_client, instance_type, region, log_callback)
    
    # Build run_instances parameters
    # Note: No KeyName - all access is via SSM using the IAM instance profile
    run_params = {
        'ImageId': ami_id,
        'InstanceType': instance_type,
        'IamInstanceProfile': {'Arn': instance_profile_arn},
        'BlockDeviceMappings': [{
            'DeviceName': root_device_name,
            'Ebs': {
                'VolumeSize': volume_size,
                'VolumeType': volume_type or 'gp3'
            }
        }],
        'TagSpecifications': [{
            'ResourceType': 'instance',
            'Tags': [
                {'Key': 'Name', 'Value': container_name},
                {'Key': 'Project', 'Value': repository}
            ]
        }],
        'MinCount': 1,
        'MaxCount': 1
    }
    
    # Check if instance type requires cluster placement group (HPC instances)
    requires_placement_group = _requires_cluster_placement_group(instance_type)
    placement_group_name = None
    
    if requires_placement_group:
        placement_group_name = _ensure_placement_group(ec2_client, account_id, region, availability_zone, log_callback)
        if log_callback:
            log_callback(_log_message(f"HPC instance type {instance_type} requires cluster placement group"))
    
    # Handle security groups and networking
    if subnet_id:
        # When SubnetId is specified, must use SecurityGroupIds (not SecurityGroups names)
        # Get security group ID from name
        try:
            sg_response = ec2_client.describe_security_groups(
                GroupNames=[security_group_name]
            )
            if not sg_response['SecurityGroups']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Security group '{security_group_name}' not found"
                )
            security_group_id = sg_response['SecurityGroups'][0]['GroupId']
            run_params['SecurityGroupIds'] = [security_group_id]
        except ClientError as e:
            # If describe_security_groups fails, try by ID
            try:
                sg_response = ec2_client.describe_security_groups(
                    GroupIds=[security_group_name]
                )
                security_group_id = sg_response['SecurityGroups'][0]['GroupId']
                run_params['SecurityGroupIds'] = [security_group_id]
            except ClientError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get security group: {e}"
                )
        run_params['SubnetId'] = subnet_id
        
        # Handle placement group - if required, get subnet's AZ
        if requires_placement_group and placement_group_name:
            # Get subnet's AZ for placement group
            try:
                subnet_response = ec2_client.describe_subnets(SubnetIds=[subnet_id])
                subnet_az = subnet_response['Subnets'][0]['AvailabilityZone']
                run_params['Placement'] = {
                    'GroupName': placement_group_name,
                    'AvailabilityZone': subnet_az
                }
            except ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get subnet availability zone: {e}"
                )
        # Note: If not using placement group, subnet determines AZ automatically
    else:
        # No subnet specified, use SecurityGroups (names) and optional Placement
        run_params['SecurityGroups'] = [security_group_name]
        
        # Handle placement group
        if requires_placement_group and placement_group_name:
            # Use provided AZ or let AWS choose default
            placement_config = {'GroupName': placement_group_name}
            if availability_zone:
                placement_config['AvailabilityZone'] = availability_zone
            run_params['Placement'] = placement_config
        elif availability_zone:
            # Not using placement group, just specify AZ
            run_params['Placement'] = {'AvailabilityZone': availability_zone}
    
    if user_data:
        # User data should be base64 encoded
        try:
            # Try to decode to see if it's already base64
            base64.b64decode(user_data, validate=True)
            # If successful, it's already base64
            run_params['UserData'] = user_data
        except Exception:
            # Not base64, encode it
            run_params['UserData'] = base64.b64encode(user_data.encode('utf-8')).decode('utf-8')
    
    try:
        response = ec2_client.run_instances(**run_params)
        
        instance_id = response['Instances'][0]['InstanceId']
        if log_callback:
            log_callback(_log_message(f"Instance launched: {instance_id}"))
        
        # Wait for instance to be running
        if log_callback:
            log_callback(_log_message("Waiting for instance to be running..."))
        waiter = ec2_client.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id], WaiterConfig={'Delay': 5, 'MaxAttempts': 60})
        
        # Get public DNS
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        public_dns = response['Reservations'][0]['Instances'][0].get('PublicDnsName', '')
        
        if not public_dns:
            # Instance might not have public DNS yet, wait a bit more
            time.sleep(10)
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            public_dns = response['Reservations'][0]['Instances'][0].get('PublicDnsName', '')
        
        if log_callback:
            log_callback(_log_message(f"Instance is running. Public DNS: {public_dns}"))
        
        return instance_id, public_dns
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch instance: {e}")


def _wait_for_ssm(ssm_client, instance_id: str, log_callback=None, max_retries: int = 30) -> None:
    """Wait for SSM to be available on the instance."""
    if log_callback:
        log_callback(_log_message(f"Waiting for SSM agent to be ready on {instance_id}..."))
    
    for attempt in range(max_retries):
        try:
            if log_callback and attempt > 0 and attempt % 3 == 0:  # Log every 3rd attempt
                log_callback(_log_message(f"SSM connection attempt {attempt + 1}/{max_retries}..."))
            
            # Try to send a simple command via SSM
            response = ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={'commands': ['echo ok']}
            )
            command_id = response['Command']['CommandId']
            
            # Wait a moment and check if command succeeded
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            
            if result['Status'] == 'Success':
                if log_callback:
                    log_callback(_log_message("SSM connection established"))
                return
            elif result['Status'] == 'Failed':
                # SSM is responding but command failed - that's okay, SSM is ready
                if log_callback:
                    log_callback(_log_message("SSM connection established"))
                return
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['InvalidInstanceId', 'InstanceNotInPreregisteredState']:
                # Instance not ready for SSM yet
                if log_callback and attempt % 3 == 0:
                    log_callback(_log_message(f"SSM not ready yet (attempt {attempt + 1}/{max_retries})..."))
            else:
                if log_callback and attempt % 3 == 0:
                    log_callback(_log_message(f"SSM connection attempt {attempt + 1} failed: {error_code}"))
        except Exception as e:
            if log_callback and attempt % 3 == 0:
                log_callback(_log_message(f"SSM connection attempt {attempt + 1} failed: {type(e).__name__}"))
        
        if attempt < max_retries - 1:
            time.sleep(10)
    
    # If we get here, all retries failed
    raise HTTPException(
        status_code=500,
        detail=f"SSM connection failed after {max_retries * 10} seconds. Instance may still be initializing. Ensure the instance has an IAM role with SSM permissions."
    )


def _run_ssm_command(ssm_client, instance_id: str, command: str, log_callback=None, timeout: int = 300) -> tuple:
    """Run a command on instance via SSM. Returns (success: bool, output: str, error: str)."""
    try:
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        for _ in range(timeout // 10):  # Check every 10 seconds
            time.sleep(10)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                output = result.get('StandardOutputContent', '')
                error = result.get('StandardErrorContent', '')
                return (status == 'Success', output, error)
        
        return (False, '', 'Command timed out')
    except Exception as e:
        if log_callback:
            log_callback(_log_message(f"SSM command failed: {str(e)}"))
        return (False, '', str(e))


def _install_docker_on_instance(ssm_client, instance_id: str, log_callback=None):
    """Install Docker and prerequisites on EC2 instance via SSM."""
    if log_callback:
        log_callback(_log_message("Installing Docker and prerequisites on EC2 instance (Amazon Linux 2023)..."))
    
    setup_command = """sudo yum update -y && \
sudo amazon-linux-extras install docker -y || sudo yum install -y docker && \
sudo systemctl enable docker && \
sudo systemctl start docker && \
sudo usermod -aG docker ec2-user && \
sudo yum install -y unzip || sudo dnf install -y unzip && \
if ! command -v aws &> /dev/null; then \
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
  unzip awscliv2.zip && \
  sudo ./aws/install; \
fi && \
sudo systemctl enable amazon-ssm-agent || true && \
sudo systemctl start amazon-ssm-agent || true && \
mkdir -p /home/ec2-user/simulations && \
echo "Docker and AWS CLI installation completed"
"""
    
    success, output, error = _run_ssm_command(ssm_client, instance_id, setup_command, log_callback, timeout=600)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Docker installation failed: {error or output}")
    
    if log_callback:
        log_callback(_log_message("Docker installation completed"))


def _configure_aws_on_instance(ssm_client, instance_id: str, access_key: str, secret_key: str,
                               session_token: str, region: str, log_callback=None):
    """Configure AWS credentials on EC2 instance via SSM."""
    if log_callback:
        log_callback(_log_message("Configuring AWS credentials on instance..."))
    
    # Escape special characters for shell
    import shlex
    access_key_escaped = shlex.quote(access_key)
    secret_key_escaped = shlex.quote(secret_key)
    session_token_escaped = shlex.quote(session_token)
    
    config_command = f"""mkdir -p ~/.aws && \
cat > ~/.aws/credentials << 'CREDS'
[default]
aws_access_key_id = {access_key_escaped}
aws_secret_access_key = {secret_key_escaped}
aws_session_token = {session_token_escaped}
CREDS
cat > ~/.aws/config << 'CONFIG'
[default]
region = {region}
output = json
CONFIG
chmod 600 ~/.aws/credentials ~/.aws/config && \
echo "AWS credentials configured"
"""
    
    success, output, error = _run_ssm_command(ssm_client, instance_id, config_command, log_callback)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"AWS configuration failed: {error or output}")
    
    if log_callback:
        log_callback(_log_message("AWS credentials configured on instance"))


def _pull_and_run_container(ssm_client, instance_id: str, ecr_registry: str, repository: str,
                           image_tag: str, account_id: str, region: str, instance_type: str = None, log_callback=None):
    """Pull Docker image from ECR and run container via SSM."""
    if log_callback:
        log_callback(_log_message(f"Pulling {repository} container from ECR and starting it..."))
    
    # Detect GPU vs CPU - only use GPU if:
    # 1. Repository name doesn't contain 'cpu'
    # 2. Instance type is a GPU instance (contains 'g' or 'p' for GPU instance families)
    repo_lower = repository.lower()
    instance_lower = (instance_type or "").lower()
    
    # GPU instance families: g3, g4dn, g5, p2, p4, p5, inf1, inf2, trn1
    # Note: P3 instances are being retired by AWS - use P4 or G5 instead
    is_gpu_instance = any(gpu_family in instance_lower for gpu_family in ['g3', 'g4', 'g5', 'p2', 'p4', 'p5', 'inf1', 'inf2', 'trn1'])
    is_cpu_repo = 'cpu' in repo_lower
    
    # Only use GPU flag if it's a GPU instance AND not a CPU repository
    gpu_flag = "--gpus all" if (is_gpu_instance and not is_cpu_repo) else ""
    
    container_name = f"{account_id}-{repository}-container"
    full_image_name = f"{ecr_registry}/{repository}:{image_tag}"
    simulation_dir = "/home/ec2-user/simulations"
    
    run_command = f"""aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {ecr_registry} && \
docker pull {full_image_name} && \
if docker ps -a --format '{{{{.Names}}}}' | grep -q "^{container_name}$"; then docker rm -f {container_name}; fi && \
docker run -dit --name {container_name} --restart unless-stopped --shm-size=4g -v {simulation_dir}:/workspace {gpu_flag} --tmpfs /app/tmp:rw,size=2g {full_image_name} && \
echo "Container started"
"""
    
    success, output, error = _run_ssm_command(ssm_client, instance_id, run_command, log_callback, timeout=600)
    
    if not success:
        error_msg = error or output
        # Check for common errors and provide helpful messages
        if "manifest unknown" in error_msg or "Requested image not found" in error_msg:
            raise HTTPException(
                status_code=404,
                detail=f"Docker image not found in ECR. The repository '{repository}' appears to be empty. Please push an image to ECR using the Docker Image Upload section in the UI, or manually:\n\n"
                       f"1. Build your Docker image: docker build -t {repository} .\n"
                       f"2. Export to tar: docker save {repository}:latest -o {repository}.tar\n"
                       f"3. Upload the tar file through the UI's Docker Image Upload section\n\n"
                       f"Original error: {error_msg}"
            )
        raise HTTPException(status_code=500, detail=f"Container deployment failed: {error_msg}")
    
    if log_callback:
        log_callback(_log_message("Container deployment completed"))


def _deploy_with_boto3(req: DeployRequestModel, session_creds: Optional[Dict[str, Any]] = None,
                       log_callback=None) -> Dict[str, Any]:
    """Deploy using boto3 (no AWS CLI required)."""
    # Create boto3 session
    if session_creds:
        session = boto3.Session(
            aws_access_key_id=session_creds['access_key_id'],
            aws_secret_access_key=session_creds['secret_access_key'],
            aws_session_token=session_creds['session_token'],
            region_name=req.region
        )
    else:
        session = _session(req.profile, req.region)
    
    ec2_client = session.client('ec2')
    ssm_client = session.client('ssm')
    ecr_client = session.client('ecr')
    iam_client = session.client('iam')
    
    logs: List[str] = []
    
    def log(msg: str):
        formatted = _log_message(msg)
        logs.append(formatted)
        if log_callback:
            log_callback(formatted)
    
    try:
        # Step 1: Get AMI
        log("Checking AWS prerequisites...")
        ami_id, root_device_name = _get_latest_ami(
            ec2_client, ssm_client, req.repository, req.region, log,
            ami_id=req.ami_id, ami_type=req.ami_type
        )
        
        # Step 2: Ensure security group (use default name if not provided)
        security_group_name = req.security_group or f"inversion-deployer-default-{req.account_id}"
        _ensure_security_group(ec2_client, security_group_name, req.repository, req.region, log)
        
        # Step 3: Launch instance (no key pair needed - using SSM for all access)
        instance_id, public_dns = _launch_ec2_instance(
            ec2_client, iam_client, ami_id, req.instance_type, security_group_name,
            root_device_name, req.volume_size, req.repository, req.account_id, req.region, log,
            volume_type=req.volume_type, availability_zone=req.availability_zone,
            subnet_id=req.subnet_id, user_data=req.user_data
        )
        
        # Step 4: Wait for SSM to be ready
        _wait_for_ssm(ssm_client, instance_id, log)
        
        # Step 5: Install Docker
        _install_docker_on_instance(ssm_client, instance_id, log)
        
        # Step 6: Configure AWS credentials on instance (if using session credentials)
        if session_creds:
            _configure_aws_on_instance(
                ssm_client, instance_id, session_creds['access_key_id'], session_creds['secret_access_key'],
                session_creds['session_token'], req.region, log
            )
        
        # Step 7: Pull and run container
        ecr_registry = f"{req.account_id}.dkr.ecr.{req.region}.amazonaws.com"
        _pull_and_run_container(ssm_client, instance_id, ecr_registry, req.repository, "latest", req.account_id, req.region, req.instance_type, log)
        
        log("Deployment completed successfully!")

        return {
        "instance": {
            "id": instance_id,
            "publicDns": public_dns,
            "instanceType": req.instance_type,
        },
        "logs": logs,
    }
    except HTTPException:
        raise
    except Exception as e:
        log(f"[ERROR] Deployment failed: {e}")
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")


def _sse(event: str, data: Any) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _describe_instance_dns(profile: str, region: str, instance_id: str) -> str:
    """Legacy: Get instance DNS using profile."""
    session = _session(profile, region)
    return _describe_instance_dns_with_session(session, region, instance_id)


def _describe_instance_dns_with_session(session: boto3.Session, region: str, instance_id: str) -> str:
    """Get instance DNS using a boto3 session."""
    ec2 = session.client("ec2")
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            dns = inst.get("PublicDnsName", "")
            if dns:
                return dns
    raise HTTPException(status_code=404, detail="Instance public DNS not found")


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------


# Authentication routes moved to auth_routes.py


@app.get("/api/metadata")
def metadata(request: Request, profile: Optional[str] = None, region: str = "us-east-1"):
    """Fetch repositories and security groups."""
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        try:
            # Use assumed role credentials
            creds = get_session_credentials(session_id)
            # Use region from query parameter if explicitly provided, otherwise use session region
            query_region = request.query_params.get("region")
            if query_region:
                region = query_region
            else:
                # No region in query params, use session's region
                region = creds.get('region', region)
            session = session_from_credentials(creds, region)
        except HTTPException as e:
            # Re-raise HTTP exceptions (401, etc.) as-is
            raise
    elif profile:
        # Legacy: use profile-based auth
        session = _session(profile, region)
    else:
        # No session and no profile - return 401 (not 400) for consistency
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    ecr = session.client("ecr", region_name=region)
    ec2 = session.client("ec2", region_name=region)

    try:
        # List ECR repositories with explicit region and pagination
        repos = []
        try:
            # First, try to get account ID to verify we're using the right credentials
            sts = session.client("sts", region_name=region)
            caller_identity = sts.get_caller_identity()
            account_id_from_creds = caller_identity.get('Account', 'Unknown')
            print(f"[DEBUG] Using credentials for account: {account_id_from_creds}")
            
            # Now list repositories with pagination
            paginator = ecr.get_paginator('describe_repositories')
            for page in paginator.paginate():
                page_repos = page.get("repositories", [])
                repos.extend([r["repositoryName"] for r in page_repos])
                if page_repos:
                    print(f"[DEBUG] Found {len(page_repos)} repositories in this page")
            
            print(f"[DEBUG] ECR describe_repositories successful - Total found: {len(repos)} repositories")
            if repos:
                print(f"[DEBUG] Repository names: {repos}")
            else:
                print(f"[DEBUG] No repositories found in region {region} for account {account_id_from_creds}")
        except ClientError as ecr_exc:
            error_code = ecr_exc.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = ecr_exc.response.get('Error', {}).get('Message', str(ecr_exc))
            print(f"[ERROR] ECR API error: {error_code} - {error_msg}")
            # If it's a permission error, log it but continue with empty list
            if error_code in ['AccessDenied', 'UnauthorizedOperation']:
                print(f"[WARNING] ECR permission denied. IAM role needs 'ecr:DescribeRepositories' permission.")
                repos = []
            else:
                raise
        
        # List security groups
        security_groups = []
        try:
            security_groups = [
            s["GroupName"]
            for s in ec2.describe_security_groups().get("SecurityGroups", [])
        ]
        except ClientError as sg_exc:
            error_code = sg_exc.response.get('Error', {}).get('Code', 'Unknown')
            print(f"[WARNING] EC2 describe_security_groups error: {error_code}")
            security_groups = []
        
        # Log for debugging
        print(f"[DEBUG] Metadata fetch - Region: {region}, Repos: {len(repos)}, SecurityGroups: {len(security_groups)}")
        if repos:
            print(f"[DEBUG] Repository names: {repos}")
        
    except ClientError as exc:
        error_code = exc.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = exc.response.get('Error', {}).get('Message', str(exc))
        print(f"[ERROR] AWS API error: {error_code} - {error_msg}")
        raise HTTPException(
            status_code=500, 
            detail=f"AWS API error ({error_code}): {error_msg}. Check IAM role permissions."
        ) from exc
    except (BotoCoreError, Exception) as exc:  # pragma: no cover
        print(f"[ERROR] Unexpected error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "repositories": repos,
        "securityGroups": security_groups,
    }


@app.get("/api/repositories/{repository}/status")
def repository_status(
    request: Request,
    repository: str,
    region: str = "us-east-1"
):
    """Check if repository exists and has images."""
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    try:
        creds = get_session_credentials(session_id)
        # Use region from query parameter if explicitly provided, otherwise use session region
        query_region = request.query_params.get("region")
        if query_region:
            region = query_region
        else:
            region = creds.get('region', region)
        session = session_from_credentials(creds, region)
        account_id = creds.get('account_id', '')
    except HTTPException as e:
        raise
    
    ecr = session.client("ecr", region_name=region)
    
    # Debug logging
    print(f"[DEBUG] Checking repository '{repository}' in region '{region}' for account '{account_id}'")
    
    try:
        # Check if repository exists
        try:
            repo_info = ecr.describe_repositories(repositoryNames=[repository])
            repo_uri = repo_info['repositories'][0]['repositoryUri']
            print(f"[DEBUG] Repository '{repository}' found in region '{region}': {repo_uri}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error'].get('Message', '')
            print(f"[DEBUG] Repository '{repository}' not found in region '{region}': {error_code} - {error_msg}")
            
            # Try to list all repositories in this region to help debug
            try:
                all_repos = ecr.describe_repositories()
                repo_names = [r['repositoryName'] for r in all_repos.get('repositories', [])]
                print(f"[DEBUG] Available repositories in region '{region}': {repo_names}")
                if repo_names:
                    return {
                        "exists": False,
                        "hasImages": False,
                        "imageCount": 0,
                        "images": [],
                        "message": f"Repository '{repository}' not found in region '{region}'. Available repositories: {', '.join(repo_names)}"
                    }
            except Exception as list_err:
                print(f"[DEBUG] Could not list repositories for debugging: {list_err}")
            
            if error_code == 'RepositoryNotFoundException':
                return {
                    "exists": False,
                    "hasImages": False,
                    "imageCount": 0,
                    "images": [],
                    "message": f"Repository '{repository}' not found in region '{region}'. Please check that the repository exists in this region."
                }
            raise
        
        # List images in repository
        try:
            images_response = ecr.list_images(repositoryName=repository)
            all_images = images_response.get('imageIds', [])
            
            # Filter to only show tagged images (exclude untagged layers/manifests)
            tagged_images = [img for img in all_images if img.get('imageTag')]
            
            # Get image details (tags, pushed date, etc.)
            if tagged_images:
                image_details = []
                for image_id in tagged_images:
                    detail = {
                        "imageDigest": image_id.get('imageDigest', ''),
                        "imageTag": image_id.get('imageTag'),
                    }
                    image_details.append(detail)
                
                return {
                    "exists": True,
                    "hasImages": True,
                    "imageCount": len(tagged_images),  # Count only tagged images
                    "images": image_details,
                    "repositoryUri": repo_uri,
                    "message": f"Repository has {len(tagged_images)} tagged image(s)"
                }
            else:
                return {
                    "exists": True,
                    "hasImages": False,
                    "imageCount": 0,
                    "images": [],
                    "repositoryUri": repo_uri,
                    "message": "Repository exists but has no tagged images"
                }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'RepositoryNotFoundException':
                return {
                    "exists": False,
                    "hasImages": False,
                    "imageCount": 0,
                    "images": [],
                    "message": f"Repository '{repository}' not found"
                }
            raise
            
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check repository status: {error_code} - {error_msg}"
        )


@app.get("/api/instances")
def instances(request: Request, profile: Optional[str] = None, region: str = "us-east-1"):
    """List running EC2 instances."""
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = get_session_credentials(session_id)
        # Use region from query parameter if explicitly provided, otherwise use session region
        query_region = request.query_params.get("region")
        if query_region:
            region = query_region
        else:
            # No region in query params, use session's region
            region = creds.get('region', region)
        session = session_from_credentials(creds, region)
    elif profile:
        # Legacy: use profile-based auth
        session = _session(profile, region)
    else:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    ec2 = session.client("ec2", region_name=region)
    try:
        resp = ec2.describe_instances(
            Filters=[
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                }
            ]
        )
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    results = []
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            name_tag = next(
                (
                    tag.get("Value")
                    for tag in inst.get("Tags", [])
                    if tag.get("Key") == "Name"
                ),
                "",
            )
            results.append(
                {
                    "id": inst.get("InstanceId"),
                    "name": name_tag or inst.get("InstanceId"),
                    "status": inst.get("State", {}).get("Name", "unknown"),
                    "publicDns": inst.get("PublicDnsName", ""),
                    "instanceType": inst.get("InstanceType", ""),
                    "launchTime": (
                        inst.get("LaunchTime").isoformat()
                        if inst.get("LaunchTime")
                        else ""
                    ),
                }
            )

    return {"instances": results}


@app.post("/api/deploy")
def deploy(request: Request, body: DeployRequestModel):
    """Run the existing deploy-ec2.sh script with the provided parameters."""
    # Check for session-based auth
    session_id = request.headers.get("X-Session-ID")
    session_creds = None
    
    if session_id:
        session_creds = get_session_credentials(session_id)
        # Override account_id from session if available
        if 'account_id' in session_creds:
            body.account_id = session_creds['account_id']
    
    # Use new boto3-based deployment (no AWS CLI required)
    payload = _deploy_with_boto3(body, session_creds)
    return {"status": "ok", **payload}


@app.get("/api/deploy/stream")
def deploy_stream(
    request: Request,
    profile: Optional[str] = None,
    region: str = "us-east-1",
    account_id: Optional[str] = None,
    repository: str = "",
    instance_type: str = "",
    key_pair: str = "",
    security_group: str = "",  # Deprecated - not used, will use default
    volume_size: int = 30,
    volume_type: str = "gp3",
    availability_zone: Optional[str] = None,
    subnet_id: Optional[str] = None,
    user_data: Optional[str] = None,
    ami_id: Optional[str] = None,
    ami_type: Optional[str] = None,
    session_id: Optional[str] = None,  # Query parameter for EventSource
):
    """Stream deploy logs as server-sent events while running deploy-ec2.sh."""
    
    # Check for session-based auth (from header or query param)
    if not session_id:
        session_id = request.headers.get("X-Session-ID")
    session_creds = None
    
    if session_id:
        session_creds = get_session_credentials(session_id)
        # Use account_id and region from session
        if not account_id and 'account_id' in session_creds:
            account_id = session_creds['account_id']
        if not region:
            region = session_creds['region']
    elif not session_id:
        raise HTTPException(status_code=400, detail="Session ID is required. Please login first.")

    req = DeployRequestModel(
        profile=None,  # Not used - session-based auth only
        region=region,
        account_id=account_id or "",
        repository=repository,
        instance_type=instance_type,
        key_pair=None,  # Not used - SSM is used instead
        security_group=None,  # Will use default name automatically
        volume_size=volume_size,
        volume_type=volume_type,
        availability_zone=availability_zone,
        subnet_id=subnet_id,
        user_data=user_data,
        ami_id=ami_id,
        ami_type=ami_type,
    )

    def event_stream():
        import queue
        logs_queue = queue.Queue()
        instance_id = None
        public_dns = None
        deployment_done = False
        deployment_error = None
        
        def log_callback(message: str):
            """Collect logs and extract instance info."""
            nonlocal instance_id, public_dns
            logs_queue.put(("log", message))
            # Extract instance info from log messages
            if "Instance launched:" in message:
                parts = message.split()
                if len(parts) > 0:
                    instance_id = parts[-1]
            elif "Public DNS:" in message:
                parts = message.split()
                if len(parts) > 0:
                    public_dns = parts[-1]
        
        # Start deployment in a thread so we can yield logs in real-time
        import threading
        def run_deployment():
            nonlocal deployment_done, deployment_error, instance_id, public_dns
            try:
                result = _deploy_with_boto3(req, session_creds, log_callback=log_callback)
                instance_id = result["instance"]["id"]
                public_dns = result["instance"]["publicDns"]
                instance_type = result["instance"]["instanceType"]
                # Frontend expects "complete" event with instance object
                logs_queue.put(("complete", {
                    "instance": {
                        "id": instance_id,
                        "publicDns": public_dns,
                        "instanceType": instance_type
                    }
                }))
            except HTTPException as e:
                deployment_error = e
                logs_queue.put(("error", str(e.detail)))
            except Exception as e:
                deployment_error = e
                logs_queue.put(("error", f"Deployment failed: {str(e)}"))
            finally:
                deployment_done = True
                logs_queue.put(None)  # Sentinel to signal completion
        
        # Start deployment thread
        deploy_thread = threading.Thread(target=run_deployment, daemon=True)
        deploy_thread.start()
        
        # Yield logs as they come in
        try:
            while True:
                try:
                    item = logs_queue.get(timeout=1)
                    if item is None:  # Sentinel
                        # Wait a moment to ensure all messages are processed
                        time.sleep(0.5)
                        break
                    
                    event_type, data = item
                    
                    if event_type == "log":
                        yield _sse("log", data)
                        # Check for progress milestones
                        lower = data.lower()
                        for text, pct in AwsMilestones:
                            if text in lower:
                                yield _sse("progress", pct)
                                break
                    elif event_type == "complete":
                        yield _sse("complete", data)
                        # Wait a moment to ensure the complete event is sent before closing
                        time.sleep(0.5)
                        break
                    elif event_type == "success":
                        # Legacy support - convert to complete
                        yield _sse("complete", data)
                        time.sleep(0.5)
                        break
                    elif event_type == "error":
                        yield _sse("error", data)
                        break
                except queue.Empty:
                    # Check if deployment thread is still alive
                    if not deploy_thread.is_alive() and deployment_done:
                        # If thread is done but we didn't get a success/error event, something went wrong
                        # Wait a bit more to see if we get a final message
                        try:
                            item = logs_queue.get(timeout=0.5)
                            if item and item[0] == "complete":
                                yield _sse("complete", item[1])
                            elif item and item[0] == "success":
                                # Legacy support
                                yield _sse("complete", item[1])
                            elif item and item[0] == "error":
                                yield _sse("error", item[1])
                        except queue.Empty:
                            # No more messages, deployment might have completed silently
                            if instance_id:
                                # Try to send complete with whatever instance info we have
                                yield _sse("complete", {
                                    "instance": {
                                        "id": instance_id,
                                        "publicDns": public_dns or "",
                                        "instanceType": req.instance_type
                                    }
                                })
                        break
                    continue
        except GeneratorExit:
            # Client disconnected, cleanup if needed
            pass
        except Exception as e:
            # Log any unexpected errors but don't fail silently
            import traceback
            print(f"Error in event stream: {e}\n{traceback.format_exc()}")
            yield _sse("error", f"Stream error: {str(e)}")
        finally:
            # Cleanup: try to terminate instance if deployment failed and instance was created
            if deployment_error and instance_id:
                try:
                    if session_creds:
                        session = boto3.Session(
                            aws_access_key_id=session_creds['access_key_id'],
                            aws_secret_access_key=session_creds['secret_access_key'],
                            aws_session_token=session_creds['session_token'],
                            region_name=req.region
                        )
                    else:
                        session = _session(req.profile, req.region)
                    ec2_client = session.client('ec2')
                    ec2_client.terminate_instances(InstanceIds=[instance_id])
                except Exception:
                    pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/terminate")
def terminate(request: Request, body: TerminateRequest):
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = get_session_credentials(session_id)
        session = session_from_credentials(creds, body.region)
    elif body.profile:
        # Legacy: use profile-based auth
        session = _session(body.profile, body.region)
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    
    ec2 = session.client("ec2")
    try:
        ec2.terminate_instances(InstanceIds=[body.instance_id])
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/connect")
def connect(request: Request, body: ConnectRequest):
    # Check for session-based auth first
    session_id = request.headers.get("X-Session-ID")
    
    if session_id:
        # Use assumed role credentials
        creds = get_session_credentials(session_id)
        session = session_from_credentials(creds, body.region)
        public_dns = _describe_instance_dns_with_session(session, body.region, body.instance_id)
    elif body.profile:
        # Legacy: use profile-based auth
        public_dns = _describe_instance_dns(body.profile, body.region, body.instance_id)
    else:
        raise HTTPException(status_code=400, detail="Either session_id or profile must be provided")
    key_path = os.path.expanduser(body.key_path or f"~/.ssh/{body.instance_id}.pem")
    ssh_cmd = f"ssh -i {shlex.quote(key_path)} {body.ssh_user}@{public_dns}"

    launched = False
    launch_error = None
    if body.launch_terminal and sys.platform == "darwin":
        # Escape double quotes for AppleScript while keeping the raw command (no shell wrapping)
        escaped_cmd = ssh_cmd.replace('"', '\\"')
        osa = f'tell application "Terminal" to do script "{escaped_cmd}"'
        try:
            subprocess.check_call(["osascript", "-e", osa])
            launched = True
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            launch_error = exc.output or str(exc)

    return {
        "status": "ok",
        "sshCommand": ssh_cmd,
        "publicDns": public_dns,
        "launched": launched,
        "launchError": launch_error,
    }


# ------------------------------------------------------------------------------
# Static file serving for frontend (SPA support)
# ------------------------------------------------------------------------------

# Try to mount static files if the frontend build directory exists
# This allows the backend to serve the frontend in production
frontend_build_paths = [
    os.path.join(os.path.dirname(__file__), "..", "aws-deployer-hub-main", "dist"),
    os.path.join(os.path.dirname(__file__), "..", "..", "aws-deployer-hub-main", "dist"),
    os.path.join(os.path.dirname(__file__), "dist"),
]

frontend_dist_path = None
for path in frontend_build_paths:
    abs_path = os.path.abspath(path)
    if os.path.exists(abs_path) and os.path.isdir(abs_path):
        frontend_dist_path = abs_path
        break

if frontend_dist_path:
    # Mount static files (JS, CSS, images, etc.) - must be mounted before catch-all route
    assets_dir = os.path.join(frontend_dist_path, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    
    # Serve index.html for all non-API routes (SPA catch-all)
    # This must be the last route to catch all unmatched paths
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str, request: Request):
        """Serve index.html for all non-API routes to support client-side routing."""
        # Don't serve index.html for API routes or special endpoints
        # full_path doesn't include leading slash, so "api/metadata" not "/api/metadata"
        if (full_path.startswith("api/") or 
            full_path.startswith("auth/") or 
            full_path.startswith("docs") or 
            full_path.startswith("openapi.json") or 
            full_path == "health" or
            full_path.startswith("assets/")):
            raise HTTPException(status_code=404, detail="Not found")
        
        # Serve index.html for all other routes (including root "/" which gives empty string)
        index_path = os.path.join(frontend_dist_path, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        else:
            raise HTTPException(status_code=404, detail="Frontend not found. Please build the frontend first.")
else:
    # Frontend build not found - add a catch-all that returns a helpful message
    # This must be the last route to catch all unmatched paths
    @app.get("/{full_path:path}")
    def serve_spa_fallback(full_path: str, request: Request):
        """Fallback for when frontend build is not available."""
        # Don't interfere with API routes
        if (full_path.startswith("api/") or 
            full_path.startswith("auth/") or 
            full_path.startswith("docs") or 
            full_path.startswith("openapi.json") or 
            full_path == "health"):
            raise HTTPException(status_code=404, detail="Not found")
        
        # Return a helpful message
        return {
            "message": "Frontend build not found",
            "detail": "The frontend static files are not available. In production, ensure the frontend is built and the dist directory is accessible.",
            "paths_checked": frontend_build_paths
        }

