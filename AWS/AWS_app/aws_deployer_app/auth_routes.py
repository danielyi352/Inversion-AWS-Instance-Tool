"""
Authentication routes for AWS IAM role assumption via CloudFormation.
Users provide their AWS Account ID, get redirected to CloudFormation console,
and then provide the created IAM Role ARN to complete authentication.
"""

from __future__ import annotations

import os
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["auth"])

# In-memory session storage (use Redis/database in production)
sessions: Dict[str, Dict[str, Any]] = {}


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
    """Get credentials from session, raise error if invalid/expired."""
    if not session_id:
        raise HTTPException(status_code=401, detail="No session ID provided")
    
    session = sessions.get(session_id)
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
        sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    
    return session


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


class AssumeRoleRequest(BaseModel):
    role_arn: str = Field(..., description="IAM Role ARN created by CloudFormation")
    account_id: str = Field(..., description="AWS Account ID")
    region: str = Field(default="us-east-1")
    external_id: Optional[str] = Field(None, description="External ID for security (optional)")


class CloudFormationVerifyRequest(BaseModel):
    account_id: str = Field(..., description="AWS Account ID")
    region: str = Field(default="us-east-1", description="AWS Region")


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
def cloudformation_verify(body: CloudFormationVerifyRequest):
    """
    Automatically verify and connect to the customer's AWS account after stack creation.
    Computes the role ARN and attempts to assume it with retries.
    """
    import time
    
    account_id = body.account_id.strip()
    region = body.region
    
    # Validate account ID format (12 digits)
    if not account_id.isdigit() or len(account_id) != 12:
        raise HTTPException(
            status_code=400,
            detail="Invalid AWS Account ID. Account ID must be 12 digits."
        )
    
    # Compute role ARN (role name is fixed: InversionDeployerRole)
    role_arn = f"arn:aws:iam::{account_id}:role/InversionDeployerRole"
    
    # Get External ID from environment (same one passed to CloudFormation)
    external_id = os.environ.get('EXTERNAL_ID', '').strip()
    
    # Get your AWS credentials (for assuming the role)
    your_access_key, your_secret_key = _get_your_aws_credentials()
    
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
            
            # Success! Store credentials in session
            credentials = response['Credentials']
            session_id = str(uuid.uuid4())
            sessions[session_id] = {
                'access_key_id': credentials['AccessKeyId'],
                'secret_access_key': credentials['SecretAccessKey'],
                'session_token': credentials['SessionToken'],
                'expiration': credentials['Expiration'].isoformat(),
                'region': region,
                'role_arn': role_arn,
                'account_id': account_id,
            }
            
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
                            f"Role not found after {max_attempts} attempts. "
                            f"The CloudFormation stack may still be creating. "
                            f"Please wait a few more minutes and try again, or verify the stack completed successfully."
                        )
                    )
            
            elif error_code == 'AccessDenied':
                # Trust relationship issue - provide actionable error
                trust_arn = os.environ.get('TRUST_ARN', '').strip()
                if not trust_arn:
                    service_account_id = os.environ.get('YOUR_AWS_ACCOUNT_ID', '').strip()
                    trust_arn = f"arn:aws:iam::{service_account_id}:root" if service_account_id else "your backend account"
                
                error_detail = (
                    f"Access denied. This usually means:\n"
                    f"1. The Trust ARN in the CloudFormation stack doesn't match: {trust_arn}\n"
                    f"2. External ID mismatch (expected: '{external_id}' if configured)\n"
                    f"3. The role trust policy is incorrect\n\n"
                    f"Please verify the CloudFormation stack was created with the correct TrustARN parameter."
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
def assume_role_login(body: AssumeRoleRequest):
    """Complete login by assuming the IAM role created by CloudFormation."""
    try:
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
        
        # Extract account ID from the assumed role ARN or use provided one
        account_id = body.account_id or body.role_arn.split(':')[4]
        
        # Store in session
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            'access_key_id': credentials['AccessKeyId'],
            'secret_access_key': credentials['SecretAccessKey'],
            'session_token': credentials['SessionToken'],
            'expiration': credentials['Expiration'].isoformat(),
            'region': body.region,
            'role_arn': body.role_arn,
            'account_id': account_id,
        }
        
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

