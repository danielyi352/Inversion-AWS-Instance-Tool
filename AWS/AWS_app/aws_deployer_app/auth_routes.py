"""
Authentication routes for user login (Google OAuth) and AWS IAM role assumption via CloudFormation.
"""

from __future__ import annotations

import os
import uuid
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Database imports
from database import connect_to_mongodb
from models import User, AWSConnection, AWSConnectionStatus, user_to_dict, dict_to_user, aws_connection_to_dict

# Load .env file if it exists (for development)
try:
    from dotenv import load_dotenv
    # Try multiple possible .env locations
    possible_env_paths = [
        Path(__file__).parent / '.env',  # aws_deployer_app/.env
        Path(__file__).parent.parent / '.env',  # AWS_app/.env
    ]
    for env_path in possible_env_paths:
        if env_path.exists():
            load_dotenv(env_path, override=True)
            break
except ImportError:
    pass  # python-dotenv not installed, skip
except Exception as e:
    print(f"Warning: Failed to load .env file: {e}")

router = APIRouter(prefix="/api", tags=["auth"])

# In-memory session storage
# AWS sessions: for AWS role assumption credentials
aws_sessions: Dict[str, Dict[str, Any]] = {}
# User sessions: for authenticated users
user_sessions: Dict[str, Dict[str, Any]] = {}


def _get_caller_identity(access_key: str, secret_key: str, region: str = "us-east-1") -> Optional[str]:
    """
    Get the AWS identity ARN that the backend is currently using.
    
    Returns:
        str: The ARN of the caller identity (user or role), or None if unable to determine
    """
    try:
        sts = boto3.client(
            'sts',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        response = sts.get_caller_identity()
        return response.get('Arn')
    except Exception as e:
        print(f"Warning: Failed to get caller identity: {e}")
        return None


def _get_your_aws_credentials():
    """
    Get your AWS account credentials for assuming roles.
    
    Tries multiple secure methods in order:
    1. Environment variables (YOUR_AWS_ACCESS_KEY_ID, YOUR_AWS_SECRET_ACCESS_KEY)
    2. AWS Secrets Manager (if SECRET_NAME env var is set)
    3. AWS Systems Manager Parameter Store (if PARAMETER_NAME env var is set)
    4. .env file (for development, requires python-dotenv)
    
    Returns:
        Tuple[str, str]: (access_key_id, secret_access_key)
    
    Raises:
        HTTPException: If credentials cannot be found
    """
    access_key = None
    secret_key = None
    
    # Method 1: Environment variables (highest priority)
    access_key = os.environ.get("YOUR_AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("YOUR_AWS_SECRET_ACCESS_KEY")
    
    if access_key and secret_key:
        return access_key, secret_key
    
    # Method 2: AWS Secrets Manager
    secret_name = os.environ.get("AWS_SECRET_NAME")
    if secret_name:
        try:
            secrets_client = boto3.client('secretsmanager')
            response = secrets_client.get_secret_value(SecretId=secret_name)
            secret_data = json.loads(response['SecretString'])
            access_key = secret_data.get('YOUR_AWS_ACCESS_KEY_ID') or secret_data.get('access_key_id')
            secret_key = secret_data.get('YOUR_AWS_SECRET_ACCESS_KEY') or secret_data.get('secret_access_key')
            if access_key and secret_key:
                return access_key, secret_key
        except Exception as e:
            # Log but continue to next method
            print(f"Warning: Failed to get credentials from Secrets Manager: {e}")
    
    # Method 3: AWS Systems Manager Parameter Store
    param_name = os.environ.get("AWS_PARAMETER_NAME")
    if param_name:
        try:
            ssm_client = boto3.client('ssm')
            response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
            param_data = json.loads(response['Parameter']['Value'])
            access_key = param_data.get('YOUR_AWS_ACCESS_KEY_ID') or param_data.get('access_key_id')
            secret_key = param_data.get('YOUR_AWS_SECRET_ACCESS_KEY') or param_data.get('secret_access_key')
            if access_key and secret_key:
                return access_key, secret_key
        except Exception as e:
            # Log but continue to next method
            print(f"Warning: Failed to get credentials from Parameter Store: {e}")
    
    # Method 4: .env file (for development)
    try:
        from dotenv import load_dotenv
        # Load .env file if it exists
        env_path = Path(__file__).parent.parent / '.env'
        if env_path.exists():
            load_dotenv(env_path)
            access_key = os.environ.get("YOUR_AWS_ACCESS_KEY_ID")
            secret_key = os.environ.get("YOUR_AWS_SECRET_ACCESS_KEY")
            if access_key and secret_key:
                return access_key, secret_key
    except ImportError:
        # python-dotenv not installed, skip
        pass
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}")
    
    # If we get here, no credentials were found
    raise HTTPException(
        status_code=500,
        detail=(
            "Server configuration error: AWS credentials not configured.\n"
            "Please set credentials using one of these methods:\n"
            "1. Environment variables: YOUR_AWS_ACCESS_KEY_ID and YOUR_AWS_SECRET_ACCESS_KEY\n"
            "2. AWS Secrets Manager: Set AWS_SECRET_NAME environment variable\n"
            "3. AWS Parameter Store: Set AWS_PARAMETER_NAME environment variable\n"
            "4. .env file: Create .env file in project root (requires python-dotenv)"
        )
    )


def get_session_credentials(session_id: Optional[str]) -> Dict[str, Any]:
    """Get AWS credentials from session, raise error if invalid/expired."""
    if not session_id:
        raise HTTPException(status_code=401, detail="No session ID provided")
    
    session = aws_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    expiration = datetime.fromisoformat(session['expiration'])
    # Use timezone-aware datetime for comparison (AWS returns UTC timestamps)
    now = datetime.now(timezone.utc)
    # Ensure expiration is timezone-aware (if it's not already)
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    
    if expiration < now:
        # Clean up expired session
        aws_sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    
    return session


def get_user_session(session_id: Optional[str]) -> Dict[str, Any]:
    """Get user session, raise error if invalid/expired."""
    if not session_id:
        raise HTTPException(status_code=401, detail="No session ID provided")
    
    session = user_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    expiration = datetime.fromisoformat(session['expires_at'])
    now = datetime.now(timezone.utc)
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    
    if expiration < now:
        user_sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    
    return session


async def get_current_user(request: Request) -> User:
    """Get current authenticated user from request headers."""
    session_id = request.headers.get("X-User-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login first.")
    
    user_session = get_user_session(session_id)
    user_id = user_session.get('user_id')
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Fetch user from database
    db = await connect_to_mongodb()
    users_collection = db.users
    user_doc = await users_collection.find_one({"user_id": user_id})
    
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    
    return dict_to_user(user_doc)


def session_from_credentials(credentials: Dict[str, Any], region: str):
    """Create boto3 session from stored credentials."""
    return boto3.Session(
        aws_access_key_id=credentials['access_key_id'],
        aws_secret_access_key=credentials['secret_access_key'],
        aws_session_token=credentials['session_token'],
        region_name=region
    )


# Pydantic models
class CloudFormationLoginRequest(BaseModel):
    account_id: str = Field(..., description="AWS Account ID")
    region: str = Field(default="us-east-1", description="AWS Region")
    org_id: str = Field(..., description="Organization ID to connect this AWS account to")


class AssumeRoleRequest(BaseModel):
    role_arn: str = Field(..., description="IAM Role ARN created by CloudFormation")
    account_id: str = Field(..., description="AWS Account ID")
    region: str = Field(default="us-east-1")
    external_id: Optional[str] = Field(None, description="External ID for security (optional)")
    org_id: str = Field(..., description="Organization ID to connect this AWS account to")


class CloudFormationVerifyRequest(BaseModel):
    account_id: str = Field(..., description="AWS Account ID")
    region: str = Field(default="us-east-1", description="AWS Region")
    org_id: str = Field(..., description="Organization ID to connect this AWS account to")


class LoginRequest(BaseModel):
    profile: str = Field(default="default")
    region: str = Field(default="us-east-1")


@router.post("/auth/cloudformation/login")
def cloudformation_login(body: CloudFormationLoginRequest):
    """
    Initiate CloudFormation-based login flow.
    Returns a CloudFormation console URL that opens directly to stack creation page
    with S3 template URL and parameters pre-filled.
    """
    import urllib.parse
    
    account_id = body.account_id.strip()
    region = body.region
    
    # Validate account ID format (12 digits)
    if not account_id.isdigit() or len(account_id) != 12:
        raise HTTPException(
            status_code=400,
            detail="Invalid AWS Account ID. Account ID must be 12 digits."
        )
    
    # Generate CloudFormation stack name
    stack_name = f"inversion-deployer-role-{account_id}"
    
    # Get the S3 template URL from environment or use default
    # This should point to your CloudFormation template hosted in S3
    template_s3_url = os.environ.get(
        'CLOUDFORMATION_TEMPLATE_S3_URL',
        'https://inversion-cloudformation-template.s3.amazonaws.com/templates/cloudformation_template.yaml'
    )
    
    # Load .env file if it exists (for development)
    try:
        from dotenv import load_dotenv
        # Try multiple possible .env locations
        possible_env_paths = [
            Path(__file__).parent / '.env',  # aws_deployer_app/.env
            Path(__file__).parent.parent / '.env',  # AWS_app/.env
        ]
        for env_path in possible_env_paths:
            if env_path.exists():
                load_dotenv(env_path, override=True)
                break
    except ImportError:
        pass  # python-dotenv not installed, skip
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}")
    
    # Get the Trust ARN from environment (the ARN that will assume the role)
    # This is passed as a parameter to the CloudFormation template
    trust_arn = os.environ.get('TRUST_ARN', '').strip()
    
    # Fallback: construct from account ID if TRUST_ARN not set (for backward compatibility)
    if not trust_arn:
        service_account_id = os.environ.get('YOUR_AWS_ACCOUNT_ID', '').strip()
        if service_account_id:
            trust_arn = f"arn:aws:iam::{service_account_id}:root"
    
    # Get External ID if configured (optional parameter)
    external_id = os.environ.get('EXTERNAL_ID', '').strip()
    
    # Build CloudFormation quick create URL that allows one-click deployment
    # Format: https://console.aws.amazon.com/cloudformation/home?region=REGION#/stacks/quickcreate?templateURL=URL&stackName=NAME&param_ParamName=Value
    # This URL will:
    # 1. Open the "Quick create stack" page
    # 2. Pre-fill template URL, stack name, and all parameters
    # 3. User just needs to click "Create stack" button
    
    url_params = [
        f"templateURL={urllib.parse.quote(template_s3_url, safe=':/')}",
        f"stackName={urllib.parse.quote(stack_name)}"
    ]
    
    # Add TrustARN parameter (required by the template)
    # CloudFormation expects param_<ParameterName>=<value> format
    if trust_arn:
        url_params.append(f"param_TrustARN={urllib.parse.quote(trust_arn)}")
    
    # Add ExternalId parameter if configured (optional)
    if external_id:
        url_params.append(f"param_ExternalId={urllib.parse.quote(external_id)}")
    
    # Construct the quick create URL
    # Region is a query param before #, everything else (templateURL, stackName, param_*) are in hash fragment
    cloudformation_console_url = (
        f"https://console.aws.amazon.com/cloudformation/home"
        f"?region={urllib.parse.quote(region)}"
        f"#/stacks/quickcreate"
        f"?{'&'.join(url_params)}"
    )
    
    # Expected role ARN format (from the template, role name is "InversionDeployerRole")
    role_arn_format = f"arn:aws:iam::{account_id}:role/InversionDeployerRole"
    
    return {
        "status": "ok",
        "account_id": account_id,
        "region": region,
        "stack_name": stack_name,
        "cloudformation_console_url": cloudformation_console_url,
        "template_s3_url": template_s3_url,
        "role_arn_format": role_arn_format,
        "instructions": (
            f"1. Click 'Open AWS Console' - the CloudFormation quick create page will open\n"
            f"2. All values are pre-filled (template URL, stack name, and parameters)\n"
            + (f"3. Trust ARN is pre-filled: {trust_arn}\n" if trust_arn else "3. Enter your Trust ARN (the ARN that will assume this role)\n")
            + (f"4. External ID is pre-filled: {external_id}\n" if external_id else "4. External ID is optional (leave empty if not needed)\n")
            + f"5. Click 'Create stack' button\n"
            + f"6. Wait for stack creation to complete\n"
            + f"7. Return here and click 'Verify Connection' to automatically connect\n\n"
            + f"Expected Role ARN format: {role_arn_format}"
        )
    }


@router.post("/auth/cloudformation/verify")
async def cloudformation_verify(body: CloudFormationVerifyRequest, request: Request):
    """
    Automatically verify and connect to the customer's AWS account after stack creation.
    Computes the role ARN and attempts to assume it with retries.
    Stores the AWS account connection in the database linked to an organization.
    """
    import time
    
    account_id = body.account_id.strip()
    region = body.region
    org_id = body.org_id
    
    # Check if organization has a default AWS account ID set
    from org_helpers import get_organization
    org = await get_organization(org_id)
    if org.default_aws_account_id:
        # Use organization's default AWS account ID instead of the provided one
        account_id = org.default_aws_account_id.strip()
    
    # Validate account ID format (12 digits)
    if not account_id.isdigit() or len(account_id) != 12:
        raise HTTPException(
            status_code=400,
            detail="Invalid AWS Account ID. Account ID must be 12 digits."
        )
    
    # Get current user from request
    try:
        current_user = await get_current_user(request)
        user_id = current_user.user_id
    except HTTPException:
        raise HTTPException(
            status_code=401,
            detail="You must be logged in to connect an AWS account. Please login first."
        )
    
    # Verify user is a member of the organization
    from org_helpers import verify_org_membership, can_manage_aws_connections
    membership = await verify_org_membership(user_id, org_id)
    
    # Check if user can manage AWS connections (ADMIN or OWNER)
    if not await can_manage_aws_connections(user_id, org_id):
        raise HTTPException(
            status_code=403,
            detail="You must be an ADMIN or OWNER to connect AWS accounts to this organization"
        )
    
    # Check if this org already has this AWS account
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    org_has_account = await connections_collection.find_one({
        "org_id": org_id,
        "aws_account_id": account_id
    })
    
    # Compute role ARN (role name is fixed: InversionDeployerRole)
    role_arn = f"arn:aws:iam::{account_id}:role/InversionDeployerRole"
    
    # Get External ID from environment (same one passed to CloudFormation)
    external_id = os.environ.get('EXTERNAL_ID', '').strip()
    
    # Get your AWS credentials (for assuming the role)
    your_access_key, your_secret_key = _get_your_aws_credentials()
    
    # Create IAM client to check if role exists first
    # Note: We can't check roles in other accounts directly, but we can try to assume and see what error we get
    iam_client = boto3.client(
        'iam',
        aws_access_key_id=your_access_key,
        aws_secret_access_key=your_secret_key,
        region_name=region
    )
    
    # Create STS client with your credentials
    sts = boto3.client(
        'sts',
        aws_access_key_id=your_access_key,
        aws_secret_access_key=your_secret_key,
        region_name=region
    )
    
    # Retry AssumeRole with exponential backoff
    # CloudFormation can take 30-60 seconds to create the role
    max_attempts = 24  # 24 attempts * 5 seconds = 2 minutes max
    retry_delay = 5  # Start with 5 seconds
    
    # Track if we've seen AccessDenied - if we get it on first attempt, role probably doesn't exist
    first_attempt = True
    
    for attempt in range(max_attempts):
        try:
            # Prepare assume role parameters
            assume_role_params = {
                'RoleArn': role_arn,
                'RoleSessionName': f"inversion-verify-{uuid.uuid4().hex[:8]}",
                'DurationSeconds': 3600,  # 1 hour
            }
            
            # Add ExternalId if configured
            if external_id:
                assume_role_params['ExternalId'] = external_id
            
            # Attempt to assume the role
            response = sts.assume_role(**assume_role_params)
            
            # Success! Get credentials from assumed role
            credentials = response['Credentials']
            
            # Now check if we need to update the CloudFormation stack automatically
            # This allows the role to update itself when new permissions are added
            stack_name = f"inversion-deployer-role-{account_id}"
            template_s3_url = os.environ.get(
                'CLOUDFORMATION_TEMPLATE_S3_URL',
                'https://inversion-cloudformation-template.s3.amazonaws.com/templates/cloudformation_template.yaml'
            )
            
            # Create CloudFormation client with assumed role credentials
            cf_client = boto3.client(
                'cloudformation',
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'],
                region_name=region
            )
            
            # Check if stack exists and needs updating
            print(f"[VERIFY] Checking if CloudFormation stack needs updating...")
            try:
                # Get stack details
                stack_response = cf_client.describe_stacks(StackName=stack_name)
                stack = stack_response['Stacks'][0]
                stack_status = stack['StackStatus']
                print(f"[VERIFY] Stack found. Current status: {stack_status}")
                
                # Get current template URL from the stack
                current_template_url = None
                try:
                    template_response = cf_client.get_template(StackName=stack_name)
                    current_template_url = template_response.get('TemplateURL') or template_response.get('StacksReceivedTemplateUrl')
                    print(f"[VERIFY] Current template URL: {current_template_url}")
                except Exception as e:
                    print(f"[VERIFY] Could not get current template URL: {str(e)}")
                
                # Check if we need to update (if template URL is different or stack is in a state that allows updates)
                can_update = stack_status not in ['UPDATE_ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_FAILED']
                print(f"[VERIFY] Can update: {can_update} (stack status: {stack_status})")
                
                # Handle stuck stack states
                if stack_status == 'UPDATE_ROLLBACK_FAILED':
                    print(f"⚠️  Stack is in UPDATE_ROLLBACK_FAILED state - attempting to automatically continue rollback...")
                    try:
                        # Automatically continue the rollback
                        cf_client.continue_update_rollback(StackName=stack_name)
                        print(f"✅ Rollback continuation initiated. Waiting for completion...")
                        
                        # Wait for rollback to complete
                        max_wait = 300  # 5 minutes
                        elapsed = 0
                        rollback_complete = False
                        while elapsed < max_wait:
                            time.sleep(5)
                            elapsed += 5
                            stack_response = cf_client.describe_stacks(StackName=stack_name)
                            new_status = stack_response['Stacks'][0]['StackStatus']
                            if new_status in ['UPDATE_ROLLBACK_COMPLETE', 'UPDATE_COMPLETE', 'CREATE_COMPLETE']:
                                print(f"✅ Rollback completed. New status: {new_status}")
                                rollback_complete = True
                                can_update = True  # Now we can update
                                stack_status = new_status  # Update for later checks
                                break
                            if elapsed % 30 == 0:
                                print(f"   Waiting for rollback... Status: {new_status} ({elapsed}s)")
                        
                        if not rollback_complete:
                            print(f"⚠️  Rollback did not complete in time. Will still attempt update if possible.")
                            # Check current status one more time
                            stack_response = cf_client.describe_stacks(StackName=stack_name)
                            final_status = stack_response['Stacks'][0]['StackStatus']
                            if final_status in ['UPDATE_ROLLBACK_COMPLETE', 'UPDATE_COMPLETE', 'CREATE_COMPLETE']:
                                can_update = True
                                stack_status = final_status
                    except ClientError as rollback_error:
                        error_code = rollback_error.response.get('Error', {}).get('Code', 'Unknown')
                        error_msg = rollback_error.response.get('Error', {}).get('Message', str(rollback_error))
                        print(f"❌ Could not automatically continue rollback: {error_code}")
                        print(f"   Error: {error_msg}")
                        print(f"   User will need to manually continue rollback in AWS Console.")
                        print(f"   Stack: {stack_name}")
                elif stack_status == 'UPDATE_ROLLBACK_COMPLETE':
                    print(f"⚠️  Stack is in UPDATE_ROLLBACK_COMPLETE state.")
                    print(f"   Previous update was rolled back. Will attempt update again...")
                    can_update = True  # Allow update from ROLLBACK_COMPLETE state
                
                # Always try to update if we can (the template might have new permissions)
                # CloudFormation will detect if there are actual changes
                if can_update and stack_status not in ['UPDATE_IN_PROGRESS', 'CREATE_IN_PROGRESS']:
                    print(f"[VERIFY] Proceeding with stack update...")
                    try:
                        # Get parameters from existing stack
                        existing_params = {param['ParameterKey']: param['ParameterValue'] for param in stack.get('Parameters', [])}
                        
                        # Get Trust ARN and External ID from environment
                        trust_arn = os.environ.get('TRUST_ARN', '').strip()
                        if not trust_arn:
                            service_account_id = os.environ.get('YOUR_AWS_ACCOUNT_ID', '').strip()
                            if service_account_id:
                                trust_arn = f"arn:aws:iam::{service_account_id}:root"
                        
                        external_id = os.environ.get('EXTERNAL_ID', '').strip()
                        
                        # Build update parameters
                        update_params = [
                            {'ParameterKey': 'TrustARN', 'ParameterValue': trust_arn}
                        ]
                        if external_id:
                            update_params.append({'ParameterKey': 'ExternalId', 'ParameterValue': external_id})
                        else:
                            # If external_id was removed, use existing value or empty
                            existing_external_id = existing_params.get('ExternalId', '')
                            update_params.append({'ParameterKey': 'ExternalId', 'ParameterValue': existing_external_id})
                        
                        # Update the stack with new template
                        print(f"Attempting to automatically update CloudFormation stack {stack_name} with latest template...")
                        cf_client.update_stack(
                            StackName=stack_name,
                            TemplateURL=template_s3_url,
                            Parameters=update_params,
                            Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']  # Required for IAM roles with specific names
                        )
                        
                        # Wait for update to complete (with timeout)
                        print(f"Stack update initiated, waiting for completion...")
                        max_wait_time = 300  # 5 minutes max wait
                        wait_interval = 5
                        elapsed = 0
                        
                        while elapsed < max_wait_time:
                            time.sleep(wait_interval)
                            elapsed += wait_interval
                            
                            stack_response = cf_client.describe_stacks(StackName=stack_name)
                            stack = stack_response['Stacks'][0]
                            stack_status = stack['StackStatus']
                            
                            if stack_status in ['UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_FAILED']:
                                break
                            
                            if elapsed % 30 == 0:  # Log every 30 seconds
                                print(f"Stack update in progress... Status: {stack_status} ({elapsed}s)")
                        
                        # Get detailed error information if update failed
                        if stack_status == 'UPDATE_COMPLETE':
                            print(f"✅ Stack updated successfully!")
                        elif stack_status == 'UPDATE_ROLLBACK_COMPLETE':
                            print(f"⚠️  Stack update rolled back (likely no changes detected)")
                        elif stack_status == 'UPDATE_ROLLBACK_FAILED':
                            # Get stack events to find the error
                            try:
                                events_response = cf_client.describe_stack_events(StackName=stack_name, MaxResults=10)
                                error_events = [
                                    e for e in events_response.get('StackEvents', [])
                                    if e.get('ResourceStatus', '').endswith('FAILED')
                                ]
                                if error_events:
                                    latest_error = error_events[0]
                                    error_reason = latest_error.get('ResourceStatusReason', 'Unknown error')
                                    print(f"❌ Stack update failed and rollback also failed!")
                                    print(f"   Error reason: {error_reason}")
                                    print(f"   Failed resource: {latest_error.get('LogicalResourceId', 'Unknown')}")
                                else:
                                    print(f"❌ Stack update failed with status: {stack_status}")
                                    print(f"   Stack status reason: {stack.get('StackStatusReason', 'No reason provided')}")
                            except Exception as e:
                                print(f"❌ Stack update failed with status: {stack_status}")
                                print(f"   Could not fetch error details: {str(e)}")
                        else:
                            print(f"⚠️  Stack update completed with status: {stack_status}")
                            if 'StackStatusReason' in stack:
                                print(f"   Reason: {stack['StackStatusReason']}")
                    
                    except ClientError as update_error:
                        error_code = update_error.response.get('Error', {}).get('Code', 'Unknown')
                        error_msg = update_error.response.get('Error', {}).get('Message', str(update_error))
                        # If no updates are needed, CloudFormation returns ValidationError
                        if error_code == 'ValidationError' and 'No updates' in str(update_error):
                            print(f"⚠️  Stack update skipped: CloudFormation detected no changes. This usually means:")
                            print(f"   1. The template in S3 hasn't been updated yet, OR")
                            print(f"   2. CloudFormation didn't detect the changes (template URL might be cached)")
                            print(f"   Template URL used: {template_s3_url}")
                            print(f"   Action: Upload the updated template to S3, then verify connection again.")
                        else:
                            print(f"⚠️  Could not automatically update stack: {error_code}")
                            print(f"   Error message: {error_msg}")
                            print(f"   Template URL used: {template_s3_url}")
                            print(f"   User may need to update manually via AWS Console.")
                            # Continue anyway - the role should still work with current permissions
                    except Exception as update_error:
                        print(f"⚠️  Error during automatic stack update: {str(update_error)}. Continuing...")
                        # Continue anyway - the role should still work with current permissions
            
            except ClientError as stack_error:
                error_code = stack_error.response.get('Error', {}).get('Code', 'Unknown')
                error_msg = stack_error.response.get('Error', {}).get('Message', str(stack_error))
                if error_code == 'ValidationError' and 'does not exist' in str(stack_error):
                    # Stack doesn't exist yet - this is expected for new connections
                    print(f"[VERIFY] Stack does not exist yet (new connection). Skipping update check.")
                else:
                    print(f"⚠️  Could not check/update CloudFormation stack: {error_code}")
                    print(f"   Error message: {error_msg}")
                    print(f"   Continuing anyway...")
            except Exception as stack_error:
                print(f"⚠️  Error checking CloudFormation stack: {str(stack_error)}")
                print(f"   Continuing anyway...")
            
            # Store credentials in AWS session (after potential stack update)
            session_id = str(uuid.uuid4())
            aws_sessions[session_id] = {
                'access_key_id': credentials['AccessKeyId'],
                'secret_access_key': credentials['SecretAccessKey'],
                'session_token': credentials['SessionToken'],
                'expiration': credentials['Expiration'].isoformat(),
                'region': region,
                'role_arn': role_arn,
                'account_id': account_id,
                'org_id': org_id,  # Include org_id in session
            }
            
            # Generate a new external ID for this connection
            new_external_id = str(uuid.uuid4())
            
            # Store or update AWS connection in database (org-based)
            connection_data = {
                'org_id': org_id,
                'created_by': user_id,
                'aws_account_id': account_id,
                'role_arn': role_arn,
                'region': region,
                'status': AWSConnectionStatus.ACTIVE.value,
                'external_id': new_external_id,
                'claimed_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc),
                'last_used_at': datetime.now(timezone.utc),
            }
            
            # Check if connection already exists for this org
            existing_org_connection = await connections_collection.find_one({
                "org_id": org_id,
                "aws_account_id": account_id
            })
            
            if existing_org_connection:
                # Update existing connection
                await connections_collection.update_one(
                    {"_id": existing_org_connection["_id"]},
                    {"$set": connection_data}
                )
            else:
                # Create new connection
                connection_data['created_at'] = datetime.now(timezone.utc)
                connection = AWSConnection(**connection_data)
                conn_dict = aws_connection_to_dict(connection)
                await connections_collection.insert_one(conn_dict)
            
            return {
                "status": "ok",
                "session_id": session_id,
                "expires_at": credentials['Expiration'].isoformat(),
                "account_id": account_id,
                "role_arn": role_arn,
                "message": f"Successfully connected to account {account_id}",
                "attempt": attempt + 1
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            # Handle different error cases
            if error_code == 'NoSuchEntity':
                # Role doesn't exist yet - stack might still be creating
                if attempt < max_attempts - 1:
                    # Wait and retry
                    time.sleep(retry_delay)
                    continue
                else:
                    # Max retries reached
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Role 'InversionDeployerRole' not found in account {account_id}.\n\n"
                            f"The CloudFormation stack hasn't been created yet.\n\n"
                            f"To fix this:\n"
                            f"1. Click 'Open AWS Console' button in the login dialog\n"
                            f"2. In the AWS CloudFormation console, verify the TrustARN parameter is set to: arn:aws:iam::851725483944:user/my-tool-backend\n"
                            f"3. Click 'Create stack' and wait for it to complete (usually 1-2 minutes)\n"
                            f"4. Return here and click 'Verify Connection' again"
                        )
                    )
            
            elif error_code == 'AccessDenied':
                # AccessDenied can mean:
                # 1. Role doesn't exist (AWS sometimes returns this instead of NoSuchEntity)
                # 2. Trust policy doesn't match
                # 3. External ID mismatch
                
                # If this is the first attempt and we get AccessDenied immediately,
                # it's likely the role doesn't exist
                if first_attempt:
                    # Try to get more info - check if we can describe the role
                    # (This won't work for cross-account, but we can try)
                    try:
                        # This will fail for cross-account, but gives us a chance to catch NoSuchEntity
                        iam_client.get_role(RoleName='InversionDeployerRole')
                    except ClientError as iam_error:
                        iam_error_code = iam_error.response.get('Error', {}).get('Code', 'Unknown')
                        if iam_error_code == 'NoSuchEntity':
                            raise HTTPException(
                                status_code=404,
                                detail=(
                                    f"Role 'InversionDeployerRole' not found in account {account_id}.\n\n"
                                    f"The CloudFormation stack hasn't been created yet.\n\n"
                                    f"To fix this:\n"
                                    f"1. Click 'Open AWS Console' button in the login dialog\n"
                                    f"2. In the AWS CloudFormation console, verify the TrustARN parameter is set to: arn:aws:iam::851725483944:user/my-tool-backend\n"
                                    f"3. Click 'Create stack' and wait for it to complete (usually 1-2 minutes)\n"
                                    f"4. Return here and click 'Verify Connection' again"
                                )
                            )
                
                # If we get here, the role probably exists but trust policy is wrong
                # Trust relationship issue - provide actionable error
                trust_arn = os.environ.get('TRUST_ARN', '').strip()
                if not trust_arn:
                    service_account_id = os.environ.get('YOUR_AWS_ACCOUNT_ID', '').strip()
                    trust_arn = f"arn:aws:iam::{service_account_id}:root" if service_account_id else "your backend account"
                
                # Get the actual ARN being used by the backend
                actual_arn = _get_caller_identity(your_access_key, your_secret_key, region)
                
                error_detail = (
                    f"Access denied when trying to assume role '{role_arn}'.\n\n"
                    f"This usually means:\n"
                    f"1. The CloudFormation stack hasn't been created yet (most likely)\n"
                    f"   → Go to AWS CloudFormation Console in account {account_id} and create the stack first\n\n"
                    f"2. OR the Trust ARN in the CloudFormation stack doesn't match:\n"
                    f"   - Expected: {trust_arn}\n"
                    f"   - Actual (backend using): {actual_arn or 'Unable to determine'}\n\n"
                    f"3. OR External ID mismatch (expected: '{external_id}' if configured)\n\n"
                    f"To fix:\n"
                    f"1. Make sure you've created the CloudFormation stack in account {account_id}\n"
                    f"2. Verify the TrustARN parameter in the stack is: {actual_arn or trust_arn}\n"
                    f"3. Wait for stack creation to complete, then try again"
                )
                raise HTTPException(status_code=403, detail=error_detail)
            
            elif error_code in ['InvalidClientTokenId', 'SignatureDoesNotMatch']:
                raise HTTPException(
                    status_code=500,
                    detail="Backend AWS credentials are invalid. Please contact support."
                )
            
            else:
                # Other error - return as-is
                raise HTTPException(
                    status_code=401,
                    detail=f"Failed to assume role: {error_code} - {error_msg}"
                )
            
            first_attempt = False
        
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
    # Should never reach here, but just in case
    raise HTTPException(
        status_code=500,
        detail="Failed to connect after maximum retries"
    )


@router.post("/auth/assume-role")
async def assume_role_login(body: AssumeRoleRequest, request: Request):
    """Complete login by assuming the IAM role created by CloudFormation."""
    try:
        # Get current user from request
        try:
            current_user = await get_current_user(request)
            user_id = current_user.user_id
        except HTTPException:
            raise HTTPException(
                status_code=401,
                detail="You must be logged in to connect an AWS account. Please login first."
            )
        
        # Extract account ID from role ARN or use provided one
        account_id = body.account_id or body.role_arn.split(':')[4]
        org_id = body.org_id
        
        # Check if organization has a default AWS account ID set
        from org_helpers import get_organization
        org = await get_organization(org_id)
        if org.default_aws_account_id:
            # Use organization's default AWS account ID instead of the provided one
            account_id = org.default_aws_account_id.strip()
            # Update role ARN to match the organization's AWS account
            body.role_arn = f"arn:aws:iam::{account_id}:role/InversionDeployerRole"
        
        # Verify user is a member of the organization
        from org_helpers import verify_org_membership, can_manage_aws_connections
        membership = await verify_org_membership(user_id, org_id)
        
        # Check if user can manage AWS connections (ADMIN or OWNER)
        if not await can_manage_aws_connections(user_id, org_id):
            raise HTTPException(
                status_code=403,
                detail="You must be an ADMIN or OWNER to connect AWS accounts to this organization"
            )
        
        # Check if this org already has this AWS account
        db = await connect_to_mongodb()
        connections_collection = db.aws_connections
        
        # Get your AWS credentials (for assuming the role)
        your_access_key, your_secret_key = _get_your_aws_credentials()
        
        # Create STS client with your credentials
        sts = boto3.client(
            'sts',
            aws_access_key_id=your_access_key,
            aws_secret_access_key=your_secret_key,
            region_name=body.region
        )
        
        # Prepare assume role parameters
        assume_role_params = {
            'RoleArn': body.role_arn,
            'RoleSessionName': f"inversion-deployer-session-{uuid.uuid4().hex[:8]}",
            'DurationSeconds': 3600,  # 1 hour
        }
        
        # Add ExternalId if provided (recommended for security)
        if body.external_id:
            assume_role_params['ExternalId'] = body.external_id
        
        # Assume the role
        response = sts.assume_role(**assume_role_params)
        
        credentials = response['Credentials']
        
        # Store in AWS session
        session_id = str(uuid.uuid4())
        aws_sessions[session_id] = {
            'access_key_id': credentials['AccessKeyId'],
            'secret_access_key': credentials['SecretAccessKey'],
            'session_token': credentials['SessionToken'],
            'expiration': credentials['Expiration'].isoformat(),
            'region': body.region,
            'role_arn': body.role_arn,
            'account_id': account_id,
            'org_id': org_id,  # Include org_id in session
        }
        
        # Generate a new external ID for this connection
        new_external_id = str(uuid.uuid4())
        
        # Store or update AWS connection in database (org-based)
        connection_data = {
            'org_id': org_id,
            'created_by': user_id,
            'aws_account_id': account_id,
            'role_arn': body.role_arn,
            'region': body.region,
            'status': AWSConnectionStatus.ACTIVE.value,
            'external_id': new_external_id,
            'claimed_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'last_used_at': datetime.now(timezone.utc),
        }
        
        # Check if connection already exists for this org
        existing_org_connection = await connections_collection.find_one({
            "org_id": org_id,
            "aws_account_id": account_id
        })
        
        if existing_org_connection:
            # Update existing connection
            await connections_collection.update_one(
                {"_id": existing_org_connection["_id"]},
                {"$set": connection_data}
            )
        else:
            # Create new connection
            connection_data['created_at'] = datetime.now(timezone.utc)
            connection = AWSConnection(**connection_data)
            conn_dict = aws_connection_to_dict(connection)
            await connections_collection.insert_one(conn_dict)
        
        return {
            "status": "ok",
            "session_id": session_id,
            "expires_at": credentials['Expiration'].isoformat(),
            "account_id": account_id,
            "message": f"Successfully assumed role in account {account_id}"
        }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        
        if error_code == 'AccessDenied':
            # Get the expected TrustARN
            trust_arn = os.environ.get('TRUST_ARN', '').strip()
            if not trust_arn:
                service_account_id = os.environ.get('YOUR_AWS_ACCOUNT_ID', '').strip()
                trust_arn = f"arn:aws:iam::{service_account_id}:root" if service_account_id else "your backend account"
            
            # Get the actual ARN being used by the backend
            actual_arn = _get_caller_identity(your_access_key, your_secret_key, body.region)
            
            error_detail = (
                f"Access denied. This usually means:\n"
                f"1. The Trust ARN in the CloudFormation stack doesn't match the backend's identity\n"
                f"   - Expected (from TRUST_ARN env var or CloudFormation): {trust_arn}\n"
                f"   - Actual (backend is using): {actual_arn or 'Unable to determine'}\n"
                f"2. External ID mismatch (if configured)\n"
                f"3. The role trust policy is incorrect\n\n"
                f"To fix this:\n"
                f"- If running locally: Set TRUST_ARN environment variable to match your IAM user/role ARN\n"
                f"- If running on a hosted server: Update the CloudFormation stack's TrustARN parameter to: {actual_arn or 'your backend IAM role/user ARN'}\n"
                f"- Or update your backend's AWS credentials to match the TrustARN in the CloudFormation stack"
            )
            raise HTTPException(status_code=403, detail=error_detail)
        
        raise HTTPException(
            status_code=401,
            detail=f"Failed to assume role: {error_code} - {error_msg}. Please verify the role ARN and trust relationship."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/sso/login")
def sso_login(body: LoginRequest):
    """Trigger AWS SSO login for the given profile/region (legacy)."""
    import subprocess
    try:
        output = subprocess.check_output(
            ["aws", "sso", "login", "--profile", body.profile, "--region", body.region],
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "ok", "message": output}
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.output) from exc
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="AWS CLI not found. Please install AWS CLI.")


# ============================================================================
# Google OAuth Authentication Routes
# ============================================================================

class GoogleTokenRequest(BaseModel):
    token: str = Field(..., description="Google ID token from client-side OAuth")


@router.post("/auth/google/login")
async def google_login(body: GoogleTokenRequest):
    """
    Authenticate user with Google OAuth token.
    
    The frontend should get the Google ID token from Google Sign-In,
    then send it to this endpoint for verification.
    """
    try:
        # Get Google OAuth client ID from environment
        google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
        if not google_client_id:
            raise HTTPException(
                status_code=500,
                detail="Google OAuth not configured. Please set GOOGLE_CLIENT_ID environment variable."
            )
        
        # Verify the Google ID token
        try:
            token_request = google_requests.Request()
            idinfo = id_token.verify_oauth2_token(
                body.token,
                token_request,
                google_client_id
            )
        except ValueError as e:
            raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
        
        # Extract user information from token
        google_user_id = idinfo.get('sub')
        email = idinfo.get('email')
        name = idinfo.get('name')
        picture = idinfo.get('picture')
        
        if not email:
            raise HTTPException(status_code=400, detail="Email not provided in Google token")
        
        # Connect to database
        db = await connect_to_mongodb()
        users_collection = db.users
        
        # Check if user exists
        user_doc = await users_collection.find_one({"email": email})
        
        if user_doc:
            # User exists - update last login
            user = dict_to_user(user_doc)
            user.last_login_at = datetime.now(timezone.utc)
            user.updated_at = datetime.now(timezone.utc)
            # Update name/picture if changed
            if name:
                user.name = name
            
            await users_collection.update_one(
                {"user_id": user.user_id},
                {
                    "$set": {
                        "last_login_at": user.last_login_at,
                        "updated_at": user.updated_at,
                        "name": user.name
                    }
                }
            )
        else:
            # New user - create account
            user = User(
                user_id=str(uuid.uuid4()),
                email=email,
                name=name,
                auth_provider="google",
                auth_provider_id=google_user_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                last_login_at=datetime.now(timezone.utc)
            )
            
            user_dict = user_to_dict(user)
            await users_collection.insert_one(user_dict)
        
        # Create user session
        session_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)  # 7 day session
        
        user_sessions[session_id] = {
            'user_id': user.user_id,
            'email': user.email,
            'expires_at': expires_at.isoformat(),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        return {
            "status": "ok",
            "session_id": session_id,
            "user": {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name
            },
            "expires_at": expires_at.isoformat(),
            "message": "Successfully authenticated with Google"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")


@router.get("/auth/me")
async def get_current_user_info(request: Request):
    """Get current authenticated user information."""
    try:
        user = await get_current_user(request)
        return {
            "user_id": user.user_id,
            "email": user.email,
            "name": user.name,
            "auth_provider": user.auth_provider,
            "aws_account_id": user.aws_account_id,  # Include AWS account ID for auto-fill
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user info: {str(e)}")


@router.post("/auth/logout")
async def logout(request: Request):
    """Logout current user by invalidating session."""
    session_id = request.headers.get("X-User-Session-ID")
    if session_id and session_id in user_sessions:
        user_sessions.pop(session_id, None)
    return {"status": "ok", "message": "Logged out successfully"}


@router.get("/auth/check-aws-account/{account_id}")
async def check_aws_account(request: Request, account_id: str, org_id: Optional[str] = Query(None)):
    """
    Check if an AWS account ID is already connected to an organization.
    Returns information about which organizations have it connected (if any).
    """
    try:
        current_user = await get_current_user(request)
        user_id = current_user.user_id
    except HTTPException:
        raise HTTPException(
            status_code=401,
            detail="You must be logged in to check AWS account associations."
        )
    
    # Validate account ID format
    if not account_id.isdigit() or len(account_id) != 12:
        raise HTTPException(
            status_code=400,
            detail="Invalid AWS Account ID. Account ID must be 12 digits."
        )
    
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    
    # Check which organizations have this AWS account connected
    connections = await connections_collection.find({
        "aws_account_id": account_id
    }).to_list(length=100)
    
    if connections:
        org_ids = [conn.get("org_id") for conn in connections if conn.get("org_id")]
        
        # If org_id provided, check if this org already has it
        if org_id:
            if org_id in org_ids:
                return {
                    "account_id": account_id,
                    "is_associated": True,
                    "associated_with_current_org": True,
                    "message": "This AWS account is already connected to this organization."
                }
            else:
                return {
                    "account_id": account_id,
                    "is_associated": True,
                    "associated_with_current_org": False,
                    "associated_with_other_orgs": True,
                    "org_count": len(org_ids),
                    "message": f"This AWS account is connected to {len(org_ids)} other organization(s)."
                }
        else:
            return {
                "account_id": account_id,
                "is_associated": True,
                "org_count": len(org_ids),
                "message": f"This AWS account is connected to {len(org_ids)} organization(s)."
            }
    else:
        return {
            "account_id": account_id,
            "is_associated": False,
            "message": "This AWS account is not connected to any organization"
        }

