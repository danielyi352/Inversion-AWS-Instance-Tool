"""
Example usage of MongoDB database connection and models.

This file demonstrates how to use the database connection and models.
You can use this as a reference when implementing the claiming flow.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from database import connect_to_mongodb, close_mongodb_connection, get_database
from models import User, AWSConnection, AWSConnectionStatus, user_to_dict, aws_connection_to_dict, dict_to_user, dict_to_aws_connection
import uuid


async def example_create_user():
    """Example: Create a new user."""
    db = await connect_to_mongodb()
    users_collection = db.users
    
    # Create user
    user = User(
        user_id=str(uuid.uuid4()),
        email="user@example.com",
        name="John Doe",
        auth_provider="google",
        auth_provider_id="google_123456789"
    )
    
    # Insert into database
    user_dict = user_to_dict(user)
    result = await users_collection.insert_one(user_dict)
    print(f"Created user with ID: {result.inserted_id}")
    
    return user


async def example_find_user_by_email(email: str):
    """Example: Find a user by email."""
    db = await connect_to_mongodb()
    users_collection = db.users
    
    user_doc = await users_collection.find_one({"email": email})
    if user_doc:
        user = dict_to_user(user_doc)
        return user
    return None


async def example_create_aws_connection(user_id: str, aws_account_id: str, external_id: str):
    """Example: Create a new AWS connection in pending_claim status."""
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    
    connection = AWSConnection(
        user_id=user_id,
        aws_account_id=aws_account_id,
        external_id=external_id,
        status=AWSConnectionStatus.PENDING_CLAIM,
        region="us-east-1"
    )
    
    conn_dict = aws_connection_to_dict(connection)
    result = await connections_collection.insert_one(conn_dict)
    print(f"Created AWS connection with ID: {result.inserted_id}")
    
    return connection


async def example_activate_connection(user_id: str, aws_account_id: str, role_arn: str):
    """Example: Activate an AWS connection after successful claim."""
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    
    # Find the connection
    connection_doc = await connections_collection.find_one({
        "user_id": user_id,
        "aws_account_id": aws_account_id
    })
    
    if not connection_doc:
        raise ValueError("Connection not found")
    
    # Update to active status
    update_result = await connections_collection.update_one(
        {"_id": connection_doc["_id"]},
        {
            "$set": {
                "status": AWSConnectionStatus.ACTIVE.value,
                "role_arn": role_arn,
                "claimed_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
        }
    )
    
    print(f"Updated connection: {update_result.modified_count} document(s) modified")
    
    # Fetch updated document
    updated_doc = await connections_collection.find_one({"_id": connection_doc["_id"]})
    return dict_to_aws_connection(updated_doc)


async def example_list_user_connections(user_id: str):
    """Example: List all AWS connections for a user."""
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    
    cursor = connections_collection.find({"user_id": user_id})
    connections = []
    
    async for doc in cursor:
        connections.append(dict_to_aws_connection(doc))
    
    return connections


async def example_find_active_connection(user_id: str, aws_account_id: str):
    """Example: Find an active connection for a user and AWS account."""
    db = await connect_to_mongodb()
    connections_collection = db.aws_connections
    
    connection_doc = await connections_collection.find_one({
        "user_id": user_id,
        "aws_account_id": aws_account_id,
        "status": AWSConnectionStatus.ACTIVE.value
    })
    
    if connection_doc:
        return dict_to_aws_connection(connection_doc)
    return None


async def main():
    """Run example operations."""
    try:
        # Connect to database
        await connect_to_mongodb()
        
        # Example: Create a user
        user = await example_create_user()
        print(f"\nCreated user: {user.email} (ID: {user.user_id})")
        
        # Example: Find user by email
        found_user = await example_find_user_by_email("user@example.com")
        if found_user:
            print(f"\nFound user: {found_user.name}")
        
        # Example: Create AWS connection
        external_id = str(uuid.uuid4())
        connection = await example_create_aws_connection(
            user_id=user.user_id,
            aws_account_id="123456789012",
            external_id=external_id
        )
        print(f"\nCreated connection: {connection.aws_account_id} (Status: {connection.status})")
        
        # Example: Activate connection
        role_arn = "arn:aws:iam::123456789012:role/InversionDeployerRole"
        activated = await example_activate_connection(
            user_id=user.user_id,
            aws_account_id="123456789012",
            role_arn=role_arn
        )
        print(f"\nActivated connection: {activated.status} (Role: {activated.role_arn})")
        
        # Example: List user connections
        connections = await example_list_user_connections(user.user_id)
        print(f"\nUser has {len(connections)} connection(s)")
        
        # Example: Find active connection
        active_conn = await example_find_active_connection(
            user_id=user.user_id,
            aws_account_id="123456789012"
        )
        if active_conn:
            print(f"\nActive connection found: {active_conn.external_id}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Close connection
        await close_mongodb_connection()


if __name__ == "__main__":
    # Run the examples
    asyncio.run(main())
