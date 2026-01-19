"""
Helper functions for organization management and authorization.
"""

from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException

from database import connect_to_mongodb
from models import (
    OrganizationMember, OrganizationRole, Organization, AWSConnection, AWSConnectionStatus,
    dict_to_organization_member, dict_to_organization, dict_to_aws_connection
)


async def verify_org_membership(user_id: str, org_id: str) -> OrganizationMember:
    """
    Verify user is a member of the organization.
    
    Args:
        user_id: User ID to check
        org_id: Organization ID to check membership in
        
    Returns:
        OrganizationMember: The membership record
        
    Raises:
        HTTPException: If user is not a member
    """
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    membership_doc = await members_collection.find_one({
        "user_id": user_id,
        "org_id": org_id
    })
    
    if not membership_doc:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this organization"
        )
    
    return dict_to_organization_member(membership_doc)


async def verify_org_permission(
    user_id: str, 
    org_id: str, 
    allowed_roles: List[OrganizationRole]
) -> OrganizationMember:
    """
    Verify user has required role in organization.
    
    Args:
        user_id: User ID to check
        org_id: Organization ID to check permission in
        allowed_roles: List of roles that are allowed
        
    Returns:
        OrganizationMember: The membership record
        
    Raises:
        HTTPException: If user doesn't have required permission
    """
    membership = await verify_org_membership(user_id, org_id)
    
    if membership.role not in allowed_roles:
        role_names = [r.value for r in allowed_roles]
        raise HTTPException(
            status_code=403,
            detail=f"Requires one of these roles: {role_names}. Your role: {membership.role.value}"
        )
    
    return membership


async def get_user_orgs(user_id: str) -> List[str]:
    """
    Get list of org_ids the user belongs to.
    
    Args:
        user_id: User ID
        
    Returns:
        List of organization IDs
    """
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    memberships = await members_collection.find({"user_id": user_id}).to_list(length=100)
    return [m["org_id"] for m in memberships]


async def get_org_aws_connections(org_id: str, status: Optional[AWSConnectionStatus] = None) -> List[AWSConnection]:
    """
    Get all AWS connections for an organization.
    
    Args:
        org_id: Organization ID
        status: Optional status filter (default: None = all statuses)
        
    Returns:
        List of AWSConnection objects
    """
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    
    query = {"org_id": org_id}
    if status:
        query["status"] = status.value
    
    connections = await connections_collection.find(query).to_list(length=100)
    
    return [dict_to_aws_connection(c) for c in connections]


async def get_organization(org_id: str) -> Organization:
    """
    Get organization by ID.
    
    Args:
        org_id: Organization ID
        
    Returns:
        Organization object
        
    Raises:
        HTTPException: If organization not found
    """
    db = await connect_to_mongodb()
    orgs_collection = db.organizations
    
    org_doc = await orgs_collection.find_one({"org_id": org_id})
    
    if not org_doc:
        raise HTTPException(
            status_code=404,
            detail="Organization not found"
        )
    
    return dict_to_organization(org_doc)


async def get_org_members(org_id: str) -> List[OrganizationMember]:
    """
    Get all members of an organization.
    
    Args:
        org_id: Organization ID
        
    Returns:
        List of OrganizationMember objects
    """
    db = await connect_to_mongodb()
    members_collection = db.organization_members
    
    memberships = await members_collection.find({"org_id": org_id}).to_list(length=1000)
    
    return [dict_to_organization_member(m) for m in memberships]


async def is_org_owner(user_id: str, org_id: str) -> bool:
    """
    Check if user is the owner of an organization.
    
    Args:
        user_id: User ID to check
        org_id: Organization ID
        
    Returns:
        True if user is owner, False otherwise
    """
    try:
        membership = await verify_org_membership(user_id, org_id)
        return membership.role == OrganizationRole.OWNER
    except HTTPException:
        return False


async def can_manage_aws_connections(user_id: str, org_id: str) -> bool:
    """
    Check if user can manage AWS connections for an organization.
    Requires ADMIN or OWNER role.
    
    Args:
        user_id: User ID to check
        org_id: Organization ID
        
    Returns:
        True if user can manage connections, False otherwise
    """
    try:
        membership = await verify_org_membership(user_id, org_id)
        return membership.role in [OrganizationRole.ADMIN, OrganizationRole.OWNER]
    except HTTPException:
        return False


async def can_invite_users(user_id: str, org_id: str) -> bool:
    """
    Check if user can invite other users to the organization.
    Requires ADMIN or OWNER role.
    
    Args:
        user_id: User ID to check
        org_id: Organization ID
        
    Returns:
        True if user can invite, False otherwise
    """
    try:
        membership = await verify_org_membership(user_id, org_id)
        return membership.role in [OrganizationRole.ADMIN, OrganizationRole.OWNER]
    except HTTPException:
        return False
