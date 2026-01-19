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


class OrganizationRole(str, Enum):
    """Roles within an organization."""
    OWNER = "owner"      # Can manage org, invite users, delete org
    ADMIN = "admin"      # Can manage AWS connections, invite users
    MEMBER = "member"    # Can use AWS connections


class InvitationStatus(str, Enum):
    """Status of organization invitations."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


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
    
    # Organization/Team support
    # Note: Users can belong to multiple orgs, this is just for UI convenience (primary org)
    org_id: Optional[str] = Field(None, description="Primary organization ID (for UI convenience)")
    
    # AWS Account Association (DEPRECATED - use Organization AWS connections instead)
    # Keeping for backward compatibility during migration
    aws_account_id: Optional[str] = Field(None, description="[DEPRECATED] Associated AWS Account ID (12 digits)")
    
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
    AWS account connection model - now organization-based.
    
    Represents a connection between an organization and an AWS account.
    All members of the organization can use this connection.
    Uses a "claiming" flow to verify ownership before activation.
    """
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    org_id: str = Field(..., description="Organization that owns this connection")
    created_by: str = Field(..., description="User ID who created this connection")
    
    # Legacy field for backward compatibility during migration
    user_id: Optional[str] = Field(None, description="[DEPRECATED] User who owns this connection - use org_id instead")
    
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
                "org_id": "550e8400-e29b-41d4-a716-446655440000",
                "created_by": "550e8400-e29b-41d4-a716-446655440001",
                "aws_account_id": "123456789012",
                "role_arn": "arn:aws:iam::123456789012:role/InversionDeployerRole",
                "status": "active",
                "external_id": "550e8400-e29b-41d4-a716-446655440002",
                "region": "us-east-1",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "claimed_at": "2024-01-01T00:05:00Z"
            }
        }


# ============================================================================
# Organization Model
# ============================================================================

class Organization(BaseModel):
    """Organization model for multi-user AWS account sharing."""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    org_id: str = Field(..., description="Unique organization identifier (UUID)")
    name: str = Field(..., description="Organization name")
    slug: Optional[str] = Field(None, description="URL-friendly organization slug")
    
    # Owner information
    owner_id: str = Field(..., description="User ID of the organization owner")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Metadata
    description: Optional[str] = Field(None, description="Organization description")
    
    # AWS Account
    default_aws_account_id: Optional[str] = Field(
        None, 
        description="Default AWS Account ID for this organization. Used when members connect via AWS."
    )
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}
        json_schema_extra = {
            "example": {
                "org_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Acme Corp",
                "slug": "acme-corp",
                "owner_id": "550e8400-e29b-41d4-a716-446655440001",
                "description": "Main organization for Acme Corp",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        }


# ============================================================================
# Organization Member Model
# ============================================================================

class OrganizationMember(BaseModel):
    """Represents a user's membership in an organization."""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    org_id: str = Field(..., description="Organization ID")
    user_id: str = Field(..., description="User ID")
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER, description="User's role in org")
    
    # Timestamps
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    invited_by: Optional[str] = Field(None, description="User ID who invited this member")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}
        json_schema_extra = {
            "example": {
                "org_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "550e8400-e29b-41d4-a716-446655440001",
                "role": "member",
                "joined_at": "2024-01-01T00:00:00Z",
                "invited_by": "550e8400-e29b-41d4-a716-446655440002"
            }
        }


# ============================================================================
# Organization Invitation Model
# ============================================================================

class OrganizationInvitation(BaseModel):
    """Invitation for a user to join an organization."""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    org_id: str = Field(..., description="Organization ID")
    email: EmailStr = Field(..., description="Email of invited user")
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER, description="Role to assign")
    token: str = Field(..., description="Unique invitation token (UUID)")
    invited_by: str = Field(..., description="User ID who sent invitation")
    
    status: InvitationStatus = Field(default=InvitationStatus.PENDING)
    expires_at: datetime = Field(..., description="Invitation expiration")
    accepted_at: Optional[datetime] = Field(None)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}
        json_schema_extra = {
            "example": {
                "org_id": "550e8400-e29b-41d4-a716-446655440000",
                "email": "user@example.com",
                "role": "member",
                "token": "550e8400-e29b-41d4-a716-446655440003",
                "invited_by": "550e8400-e29b-41d4-a716-446655440001",
                "status": "pending",
                "expires_at": "2024-01-08T00:00:00Z",
                "created_at": "2024-01-01T00:00:00Z"
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


def organization_to_dict(org: Organization) -> dict:
    """Convert Organization model to dictionary for MongoDB insertion."""
    org_dict = org.model_dump(by_alias=True, exclude={"id"})
    if org.id:
        org_dict["_id"] = org.id
    return org_dict


def dict_to_organization(data: dict) -> Organization:
    """Convert MongoDB document to Organization model."""
    org_data = data.copy()
    if "_id" in org_data:
        org_data["id"] = str(org_data["_id"])
        del org_data["_id"]
    return Organization(**org_data)


def organization_member_to_dict(member: OrganizationMember) -> dict:
    """Convert OrganizationMember model to dictionary for MongoDB insertion."""
    member_dict = member.model_dump(by_alias=True, exclude={"id"})
    if member.id:
        member_dict["_id"] = member.id
    return member_dict


def dict_to_organization_member(data: dict) -> OrganizationMember:
    """Convert MongoDB document to OrganizationMember model."""
    member_data = data.copy()
    if "_id" in member_data:
        member_data["id"] = str(member_data["_id"])
        del member_data["_id"]
    return OrganizationMember(**member_data)


def organization_invitation_to_dict(invitation: OrganizationInvitation) -> dict:
    """Convert OrganizationInvitation model to dictionary for MongoDB insertion."""
    inv_dict = invitation.model_dump(by_alias=True, exclude={"id"})
    if invitation.id:
        inv_dict["_id"] = invitation.id
    return inv_dict


def dict_to_organization_invitation(data: dict) -> OrganizationInvitation:
    """Convert MongoDB document to OrganizationInvitation model."""
    inv_data = data.copy()
    if "_id" in inv_data:
        inv_data["id"] = str(inv_data["_id"])
        del inv_data["_id"]
    return OrganizationInvitation(**inv_data)
