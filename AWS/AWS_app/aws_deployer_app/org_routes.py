"""
Organization management routes for multi-user AWS account sharing.
"""

from __future__ import annotations

import os
import uuid
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, EmailStr

from database import connect_to_mongodb
from models import (
    Organization, OrganizationMember, OrganizationInvitation,
    OrganizationRole, InvitationStatus,
    organization_to_dict, dict_to_organization,
    organization_member_to_dict, dict_to_organization_member,
    organization_invitation_to_dict, dict_to_organization_invitation
)
from org_helpers import (
    verify_org_membership, verify_org_permission, get_user_orgs,
    get_organization, get_org_members, can_invite_users, get_org_aws_connections
)
from models import AWSConnectionStatus
from auth_routes import get_current_user

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


# ============================================================================
# Request Models
# ============================================================================

class CreateOrgRequest(BaseModel):
    name: str = Field(..., description="Organization name", min_length=1, max_length=100)
    slug: Optional[str] = Field(None, description="URL-friendly slug (auto-generated if not provided)", max_length=50)
    description: Optional[str] = Field(None, description="Organization description", max_length=500)


class InviteUserRequest(BaseModel):
    email: EmailStr = Field(..., description="Email of user to invite")
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER, description="Role to assign")


class UpdateMemberRoleRequest(BaseModel):
    user_id: str = Field(..., description="User ID to update")
    role: OrganizationRole = Field(..., description="New role")


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = Field(None, description="Organization name", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="Organization description", max_length=500)
    default_aws_account_id: Optional[str] = Field(
        None, 
        description="Default AWS Account ID (12 digits). Set this to use a dedicated AWS account for the organization."
    )


# ============================================================================
# Organization Management Routes
# ============================================================================

@router.post("/create")
async def create_organization(body: CreateOrgRequest, request: Request):
    """
    Create a new organization.
    
    The creator becomes the owner of the organization.
    Users can only create one organization.
    """
    # Get current user
    current_user = await get_current_user(request)
    
    # Check if user already owns an organization
    db = await connect_to_mongodb()
    orgs_collection = db.organizations
    
    existing_owned_org = await orgs_collection.find_one({"owner_id": current_user.user_id})
    if existing_owned_org:
        raise HTTPException(
            status_code=400,
            detail="You already own an organization. Each user can only create one organization."
        )
    
    # Generate slug from name if not provided
    slug = body.slug
    if not slug:
        # Convert name to slug: lowercase, replace spaces with hyphens, remove special chars
        slug = re.sub(r'[^a-z0-9-]', '', body.name.lower().replace(' ', '-'))
        # Ensure it's not empty
        if not slug:
            slug = f"org-{uuid.uuid4().hex[:8]}"
    
    # Check if slug is already taken
    existing_org = await orgs_collection.find_one({"slug": slug})
    if existing_org:
        # Append random suffix if slug exists
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    
    # Create organization
    org = Organization(
        org_id=str(uuid.uuid4()),
        name=body.name,
        slug=slug,
        owner_id=current_user.user_id,
        description=body.description,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    # Save to database
    org_dict = organization_to_dict(org)
    await orgs_collection.insert_one(org_dict)
    
    # Add owner as member with OWNER role
    member = OrganizationMember(
        org_id=org.org_id,
        user_id=current_user.user_id,
        role=OrganizationRole.OWNER,
        joined_at=datetime.now(timezone.utc)
    )
    members_collection = db.organization_members
    member_dict = organization_member_to_dict(member)
    await members_collection.insert_one(member_dict)
    
    return {
        "status": "ok",
        "organization": org.model_dump(),
        "message": "Organization created successfully"
    }


@router.get("")
async def list_user_organizations(request: Request):
    """
    List all organizations the current user belongs to.
    """
    current_user = await get_current_user(request)
    
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    orgs_collection = db.organizations
    
    # Find all org memberships
    memberships = await members_collection.find({"user_id": current_user.user_id}).to_list(length=100)
    
    # Get org details
    orgs = []
    for membership in memberships:
        org_doc = await orgs_collection.find_one({"org_id": membership["org_id"]})
        if org_doc:
            org = dict_to_organization(org_doc)
            orgs.append({
                **org.model_dump(),
                "role": membership["role"]
            })
    
    return {"status": "ok", "organizations": orgs}


# ============================================================================
# Invitation Management Routes
# ============================================================================
# NOTE: These routes must come BEFORE /{org_id} routes to avoid route conflicts
# FastAPI matches routes in order, so specific routes must come before parameterized ones

@router.get("/invitations")
async def list_user_invitations(request: Request):
    """
    List pending invitations for the current user (by email).
    """
    current_user = await get_current_user(request)
    
    db = await connect_to_mongodb()
    invitations_collection = db.organization_invitations
    
    # Find pending invitations for this user's email
    # Note: We query by status first, then filter by email and expires_at in Python
    # to handle potential case sensitivity and datetime string vs datetime object issues
    now = datetime.now(timezone.utc)
    user_email = current_user.email.strip().lower()
    
    # Query all pending invitations, then filter by email in Python (case-insensitive)
    all_invitations = await invitations_collection.find({
        "status": InvitationStatus.PENDING.value
    }).to_list(length=100)
    
    # Filter by email (case-insensitive)
    matching_invitations = []
    for inv_doc in all_invitations:
        inv_email = inv_doc.get("email", "").strip().lower()
        if inv_email == user_email:
            matching_invitations.append(inv_doc)
    
    # Filter by expiration date (handle both datetime objects and strings)
    valid_invitations = []
    for inv_doc in matching_invitations:
        expires_at = inv_doc.get("expires_at")
        if expires_at:
            # Handle datetime object
            if isinstance(expires_at, datetime):
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at > now:
                    valid_invitations.append(inv_doc)
            # Handle string (ISO format)
            elif isinstance(expires_at, str):
                try:
                    expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                    if expires_dt > now:
                        valid_invitations.append(inv_doc)
                except (ValueError, AttributeError):
                    # Skip invalid date formats
                    continue
    
    # Get organization details for each invitation
    orgs_collection = db.organizations
    invitation_details = []
    
    for inv_doc in valid_invitations:
        try:
            inv = dict_to_organization_invitation(inv_doc)
            org_doc = await orgs_collection.find_one({"org_id": inv.org_id})
            if org_doc:
                org = dict_to_organization(org_doc)
                invitation_details.append({
                    **inv.model_dump(),
                    "organization_name": org.name
                })
            else:
                # Organization not found - still include invitation but without org name
                invitation_details.append({
                    **inv.model_dump(),
                    "organization_name": None
                })
        except Exception as e:
            # Skip invalid invitations
            import logging
            logging.error(f"Error processing invitation {inv_doc.get('_id')}: {e}")
            continue
    
    return {"status": "ok", "invitations": invitation_details}


@router.post("/invitations/{token}/accept")
async def accept_invitation(token: str, request: Request):
    """
    Accept an organization invitation.
    """
    current_user = await get_current_user(request)
    
    db = await connect_to_mongodb()
    invitations_collection = db.organization_invitations
    members_collection = db.organization_members
    
    # Find invitation
    invitation_doc = await invitations_collection.find_one({
        "token": token,
        "status": InvitationStatus.PENDING.value
    })
    
    if not invitation_doc:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    
    invitation = dict_to_organization_invitation(invitation_doc)
    
    # Verify email matches
    if invitation.email != current_user.email:
        raise HTTPException(
            status_code=403,
            detail="Invitation email does not match your account"
        )
    
    # Check expiration - ensure expires_at is timezone-aware
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if expires_at < datetime.now(timezone.utc):
        await invitations_collection.update_one(
            {"_id": invitation_doc["_id"]},
            {"$set": {"status": InvitationStatus.EXPIRED.value}}
        )
        raise HTTPException(status_code=400, detail="Invitation has expired")
    
    # Check if already a member
    existing_member = await members_collection.find_one({
        "org_id": invitation.org_id,
        "user_id": current_user.user_id
    })
    
    if existing_member:
        # Mark invitation as accepted anyway
        await invitations_collection.update_one(
            {"_id": invitation_doc["_id"]},
            {"$set": {
                "status": InvitationStatus.ACCEPTED.value,
                "accepted_at": datetime.now(timezone.utc)
            }}
        )
        raise HTTPException(status_code=400, detail="You are already a member of this organization")
    
    # Add user as member
    member = OrganizationMember(
        org_id=invitation.org_id,
        user_id=current_user.user_id,
        role=invitation.role,
        joined_at=datetime.now(timezone.utc),
        invited_by=invitation.invited_by
    )
    
    member_dict = organization_member_to_dict(member)
    await members_collection.insert_one(member_dict)
    
    # Mark invitation as accepted
    await invitations_collection.update_one(
        {"_id": invitation_doc["_id"]},
        {"$set": {
            "status": InvitationStatus.ACCEPTED.value,
            "accepted_at": datetime.now(timezone.utc)
        }}
    )
    
    return {
        "status": "ok",
        "message": "Successfully joined organization"
    }


@router.post("/invitations/{token}/reject")
async def reject_invitation(token: str, request: Request):
    """
    Reject an organization invitation.
    """
    current_user = await get_current_user(request)
    
    db = await connect_to_mongodb()
    invitations_collection = db.organization_invitations
    
    # Find invitation
    invitation_doc = await invitations_collection.find_one({
        "token": token,
        "status": InvitationStatus.PENDING.value
    })
    
    if not invitation_doc:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    invitation = dict_to_organization_invitation(invitation_doc)
    
    # Verify email matches
    if invitation.email != current_user.email:
        raise HTTPException(
            status_code=403,
            detail="Invitation email does not match your account"
        )
    
    # Mark as rejected
    await invitations_collection.update_one(
        {"_id": invitation_doc["_id"]},
        {"$set": {"status": InvitationStatus.REJECTED.value}}
    )
    
    return {"status": "ok", "message": "Invitation rejected"}


@router.get("/{org_id}")
async def get_org_details(org_id: str, request: Request):
    """
    Get details of a specific organization.
    User must be a member of the organization.
    """
    current_user = await get_current_user(request)
    
    # Verify membership
    await verify_org_membership(current_user.user_id, org_id)
    
    # Get organization
    org = await get_organization(org_id)
    
    # Get member count
    members = await get_org_members(org_id)
    
    # Get AWS connections count
    connections = await get_org_aws_connections(org_id, AWSConnectionStatus.ACTIVE)
    
    return {
        "status": "ok",
        "organization": org.model_dump(),
        "member_count": len(members),
        "aws_connection_count": len(connections)
    }


@router.put("/{org_id}")
async def update_organization(org_id: str, body: UpdateOrgRequest, request: Request):
    """
    Update organization details.
    Requires ADMIN or OWNER role.
    """
    current_user = await get_current_user(request)
    
    # Verify permission
    await verify_org_permission(current_user.user_id, org_id, [OrganizationRole.ADMIN, OrganizationRole.OWNER])
    
    db = await connect_to_mongodb()
    orgs_collection = db.organizations
    
    # Build update dict
    update_data = {"updated_at": datetime.now(timezone.utc)}
    if body.name is not None:
        update_data["name"] = body.name
    if body.description is not None:
        update_data["description"] = body.description
    if body.default_aws_account_id is not None:
        # Validate AWS account ID format (12 digits)
        if body.default_aws_account_id and (not body.default_aws_account_id.isdigit() or len(body.default_aws_account_id) != 12):
            raise HTTPException(
                status_code=400,
                detail="Invalid AWS Account ID. Account ID must be 12 digits."
            )
        update_data["default_aws_account_id"] = body.default_aws_account_id.strip() if body.default_aws_account_id else None
    
    await orgs_collection.update_one(
        {"org_id": org_id},
        {"$set": update_data}
    )
    
    # Get updated org
    org = await get_organization(org_id)
    
    return {
        "status": "ok",
        "organization": org.model_dump(),
        "message": "Organization updated successfully"
    }


# ============================================================================
# Member Management Routes
# ============================================================================

@router.get("/{org_id}/members")
async def list_org_members(org_id: str, request: Request):
    """
    List all members of an organization.
    User must be a member of the organization.
    """
    current_user = await get_current_user(request)
    
    # Verify membership
    await verify_org_membership(current_user.user_id, org_id)
    
    # Get members
    members = await get_org_members(org_id)
    
    # Get user details for each member
    db = await connect_to_mongodb()
    users_collection = db.users
    from models import dict_to_user
    
    member_details = []
    for member in members:
        user_doc = await users_collection.find_one({"user_id": member.user_id})
        if user_doc:
            user = dict_to_user(user_doc)
            member_details.append({
                "user_id": member.user_id,
                "email": user.email,
                "name": user.name,
                "role": member.role.value,
                "joined_at": member.joined_at.isoformat()
            })
    
    return {"status": "ok", "members": member_details}


@router.put("/{org_id}/members/{user_id}/role")
async def update_member_role(org_id: str, user_id: str, body: UpdateMemberRoleRequest, request: Request):
    """
    Update a member's role in the organization.
    Requires ADMIN or OWNER role.
    Cannot change owner role or remove last owner.
    """
    current_user = await get_current_user(request)
    
    # Verify permission
    await verify_org_permission(current_user.user_id, org_id, [OrganizationRole.ADMIN, OrganizationRole.OWNER])
    
    # Get organization to check owner
    org = await get_organization(org_id)
    
    # Prevent changing owner's role
    if user_id == org.owner_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot change the organization owner's role"
        )
    
    # Check if this is the last owner (besides the actual owner)
    if body.role != OrganizationRole.OWNER:
        members = await get_org_members(org_id)
        owner_count = sum(1 for m in members if m.role == OrganizationRole.OWNER and m.user_id != org.owner_id)
        if owner_count == 0:
            # Check if the user being updated is an owner
            target_member = await verify_org_membership(user_id, org_id)
            if target_member.role == OrganizationRole.OWNER:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last owner role. At least one owner (besides the organization creator) is required."
                )
    
    # Update member role
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    await members_collection.update_one(
        {"org_id": org_id, "user_id": user_id},
        {"$set": {"role": body.role.value}}
    )
    
    return {
        "status": "ok",
        "message": f"Member role updated to {body.role.value}"
    }


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(org_id: str, user_id: str, request: Request):
    """
    Remove a member from the organization.
    Requires ADMIN or OWNER role.
    Cannot remove owner.
    """
    current_user = await get_current_user(request)
    
    # Verify permission
    await verify_org_permission(current_user.user_id, org_id, [OrganizationRole.ADMIN, OrganizationRole.OWNER])
    
    # Get organization to check owner
    org = await get_organization(org_id)
    
    # Prevent removing owner
    if user_id == org.owner_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the organization owner"
        )
    
    # Remove member
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    result = await members_collection.delete_one({"org_id": org_id, "user_id": user_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return {"status": "ok", "message": "Member removed successfully"}


@router.delete("/{org_id}")
async def delete_organization(org_id: str, request: Request):
    """
    Delete an organization and all associated data.
    Only the organization owner can delete the organization.
    This will:
    - Remove all members from the organization
    - Delete all pending invitations
    - Delete all AWS connections associated with the organization
    - Delete the organization itself
    """
    current_user = await get_current_user(request)
    
    # Get organization to verify ownership
    org = await get_organization(org_id)
    
    # Only owner can delete
    if current_user.user_id != org.owner_id:
        raise HTTPException(
            status_code=403,
            detail="Only the organization owner can delete the organization"
        )
    
    db = await connect_to_mongodb()
    
    # Delete all organization members
    members_collection = db.organization_members
    await members_collection.delete_many({"org_id": org_id})
    
    # Delete all organization invitations
    invitations_collection = db.organization_invitations
    await invitations_collection.delete_many({"org_id": org_id})
    
    # Delete all AWS connections for this organization
    connections_collection = db.aws_connections
    await connections_collection.delete_many({"org_id": org_id})
    
    # Delete the organization itself
    orgs_collection = db.organizations
    result = await orgs_collection.delete_one({"org_id": org_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    return {
        "status": "ok",
        "message": "Organization deleted successfully. All members have been removed."
    }


@router.post("/{org_id}/leave")
async def leave_organization(org_id: str, request: Request):
    """
    Leave an organization.
    Users can leave organizations they are members of, but owners cannot leave.
    """
    current_user = await get_current_user(request)
    
    # Verify membership
    membership = await verify_org_membership(current_user.user_id, org_id)
    
    # Get organization to check owner
    org = await get_organization(org_id)
    
    # Prevent owner from leaving
    if current_user.user_id == org.owner_id:
        raise HTTPException(
            status_code=400,
            detail="Organization owners cannot leave their organization. Transfer ownership or delete the organization instead."
        )
    
    # Remove member
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    result = await members_collection.delete_one({"org_id": org_id, "user_id": current_user.user_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return {"status": "ok", "message": "Successfully left the organization"}


@router.post("/{org_id}/invite")
async def invite_user(org_id: str, body: InviteUserRequest, request: Request):
    """
    Invite a user to join an organization.
    Requires ADMIN or OWNER role.
    """
    current_user = await get_current_user(request)
    
    # Verify permission
    await verify_org_permission(current_user.user_id, org_id, [OrganizationRole.ADMIN, OrganizationRole.OWNER])
    
    # Check if user is already a member
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    existing_member = await members_collection.find_one({
        "org_id": org_id,
        "user_id": {"$exists": False}  # We'll check by email via user lookup
    })
    
    # Check if user exists and is already a member
    users_collection = db.users
    user_doc = await users_collection.find_one({"email": body.email})
    if user_doc:
        from models import dict_to_user
        user = dict_to_user(user_doc)
        existing_member = await members_collection.find_one({
            "org_id": org_id,
            "user_id": user.user_id
        })
        if existing_member:
            raise HTTPException(
                status_code=400,
                detail="User is already a member of this organization"
            )
    
    # Check for existing pending invitation
    invitations_collection = db.organization_invitations
    existing_invitation = await invitations_collection.find_one({
        "org_id": org_id,
        "email": body.email,
        "status": InvitationStatus.PENDING.value
    })
    
    if existing_invitation:
        inv = dict_to_organization_invitation(existing_invitation)
        # Ensure expires_at is timezone-aware (MongoDB might return naive datetime)
        expires_at = inv.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        
        if expires_at > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400,
                detail="An invitation is already pending for this email"
            )
    
    # Create invitation
    invitation = OrganizationInvitation(
        org_id=org_id,
        email=body.email,
        role=body.role,
        token=str(uuid.uuid4()),
        invited_by=current_user.user_id,
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=datetime.now(timezone.utc)
    )
    
    # Save invitation
    inv_dict = organization_invitation_to_dict(invitation)
    await invitations_collection.insert_one(inv_dict)
    
    # TODO: Send email invitation
    
    return {
        "status": "ok",
        "invitation": invitation.model_dump(),
        "message": "Invitation sent successfully"
    }
