"""
Database models for MongoDB collections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema
from bson import ObjectId


class PyObjectId(ObjectId):
    """Custom ObjectId type for Pydantic v2 models."""
    
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: Any
    ) -> core_schema.CoreSchema:
        def validate_from_str(value: str) -> ObjectId:
            if ObjectId.is_valid(value):
                return ObjectId(value)
            raise ValueError("Invalid ObjectId string")
        
        return core_schema.no_info_after_validator_function(
            validate_from_str,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x)
            )
        )
    
    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string"}


class AWSConnectionStatus(str, Enum):
    """Status states for AWS connections."""
    PENDING_CLAIM = "pending_claim"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED_PENDING = "expired_pending"


# ============================================================================
# User Model
# ============================================================================

class User(BaseModel):
    """
    User model for authentication and authorization.
    
    Users can authenticate via:
    - Email magic link
    - OAuth (Google, etc.)
    """
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_id: str = Field(..., description="Unique user identifier (UUID)")
    email: EmailStr = Field(..., description="User email address")
    name: Optional[str] = Field(None, description="User's display name")
    
    # Authentication
    auth_provider: str = Field(..., description="Auth provider: 'email', 'google', etc.")
    auth_provider_id: Optional[str] = Field(None, description="Provider-specific user ID")
    
    # Organization/Team support (for future)
    org_id: Optional[str] = Field(None, description="Organization ID (if part of an org)")
    
    # AWS Account Association
    aws_account_id: Optional[str] = Field(None, description="Associated AWS Account ID (12 digits)")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: Optional[datetime] = Field(None, description="Last login timestamp")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "email": "user@example.com",
                "name": "John Doe",
                "auth_provider": "google",
                "auth_provider_id": "google_123456789",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        }


# ============================================================================
# AWS Connection Model
# ============================================================================

class AWSConnection(BaseModel):
    """
    AWS account connection model.
    
    Represents a connection between a user and an AWS account.
    Uses a "claiming" flow to verify ownership before activation.
    """
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_id: str = Field(..., description="User who owns this connection")
    org_id: Optional[str] = Field(None, description="Organization ID (if connection is org-level)")
    
    # AWS Account Information
    aws_account_id: str = Field(..., description="AWS Account ID (12 digits)")
    role_arn: Optional[str] = Field(None, description="IAM Role ARN to assume")
    region: str = Field(default="us-east-1", description="Default AWS region")
    
    # Claiming/Verification
    status: AWSConnectionStatus = Field(
        default=AWSConnectionStatus.PENDING_CLAIM,
        description="Connection status"
    )
    external_id: str = Field(..., description="External ID for AssumeRole (rotated on each claim)")
    
    # CloudFormation stack info
    stack_name: Optional[str] = Field(None, description="CloudFormation stack name")
    stack_region: Optional[str] = Field(None, description="Region where stack was created")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_at: Optional[datetime] = Field(None, description="When connection was successfully claimed")
    last_used_at: Optional[datetime] = Field(None, description="Last time this connection was used for deployment")
    
    # Metadata
    notes: Optional[str] = Field(None, description="User-provided notes about this connection")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "aws_account_id": "123456789012",
                "role_arn": "arn:aws:iam::123456789012:role/InversionDeployerRole",
                "status": "active",
                "external_id": "550e8400-e29b-41d4-a716-446655440001",
                "region": "us-east-1",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "claimed_at": "2024-01-01T00:05:00Z"
            }
        }


# ============================================================================
# Helper Functions for Database Operations
# ============================================================================

def user_to_dict(user: User) -> dict:
    """Convert User model to dictionary for MongoDB insertion."""
    user_dict = user.model_dump(by_alias=True, exclude={"id"})
    if user.id:
        user_dict["_id"] = user.id
    return user_dict


def aws_connection_to_dict(connection: AWSConnection) -> dict:
    """Convert AWSConnection model to dictionary for MongoDB insertion."""
    conn_dict = connection.model_dump(by_alias=True, exclude={"id"})
    if connection.id:
        conn_dict["_id"] = connection.id
    return conn_dict


def dict_to_user(data: dict) -> User:
    """Convert MongoDB document to User model."""
    # Create a copy to avoid modifying the original
    user_data = data.copy()
    
    # Convert ObjectId to string for the id field
    if "_id" in user_data:
        user_data["id"] = str(user_data["_id"])
        # Remove _id since we're using id with alias
        del user_data["_id"]
    
    return User(**user_data)


def dict_to_aws_connection(data: dict) -> AWSConnection:
    """Convert MongoDB document to AWSConnection model."""
    # Create a copy to avoid modifying the original
    conn_data = data.copy()
    
    # Convert ObjectId to string for the id field
    if "_id" in conn_data:
        conn_data["id"] = str(conn_data["_id"])
        # Remove _id since we're using id with alias
        del conn_data["_id"]
    
    return AWSConnection(**conn_data)
