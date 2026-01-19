"""
MongoDB database connection and configuration.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import logging

logger = logging.getLogger(__name__)

# Global database connection
_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


def get_mongodb_uri() -> str:
    """
    Get MongoDB connection URI from environment variable.
    
    Returns:
        str: MongoDB connection URI
        
    Raises:
        ValueError: If MONGODB_URI is not set
    """
    mongodb_uri = os.environ.get("MONGODB_URI")
    if not mongodb_uri:
        raise ValueError(
            "MONGODB_URI environment variable is required. "
            "Set it to your MongoDB connection string, e.g., "
            "mongodb://username:password@host:port/database"
        )
    return mongodb_uri


def get_database_name() -> str:
    """
    Get database name from environment or extract from URI.
    
    Returns:
        str: Database name
    """
    # Allow override via environment variable
    db_name = os.environ.get("MONGODB_DATABASE")
    if db_name:
        return db_name
    
    # Try to extract from URI
    uri = os.environ.get("MONGODB_URI", "")
    if uri:
        # Extract database name from URI (format: mongodb://.../database?options)
        try:
            parsed = urlparse(uri)
            if parsed.path and len(parsed.path) > 1:
                # Remove leading slash
                return parsed.path[1:].split('?')[0]
        except Exception:
            pass
    
    # Default fallback
    return "inversion_deployer"


async def connect_to_mongodb() -> AsyncIOMotorDatabase:
    """
    Connect to MongoDB and return database instance.
    
    This function is idempotent - calling it multiple times will reuse
    the existing connection if it's still valid.
    
    Returns:
        AsyncIOMotorDatabase: Database instance
        
    Raises:
        ConnectionFailure: If unable to connect to MongoDB
    """
    global _client, _database
    
    # If already connected, verify connection and return
    if _client is not None:
        try:
            # Ping the database to verify connection is still alive
            await _client.admin.command('ping')
            return _database
        except (ConnectionFailure, ServerSelectionTimeoutError):
            # Connection is dead, reset and reconnect
            logger.warning("MongoDB connection lost, reconnecting...")
            _client = None
            _database = None
    
    # Get connection URI
    uri = get_mongodb_uri()
    database_name = get_database_name()
    
    try:
        # Create new client
        _client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=5000,  # 5 second timeout
            connectTimeoutMS=10000,  # 10 second connection timeout
        )
        
        # Test connection
        await _client.admin.command('ping')
        
        # Get database (use name from URI or override)
        _database = _client[database_name]
        
        logger.info(f"Connected to MongoDB database: {database_name}")
        
        # Create indexes on startup
        await create_indexes(_database)
        
        return _database
        
    except ConnectionFailure as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        _client = None
        _database = None
        raise
    except ServerSelectionTimeoutError as e:
        logger.error(f"MongoDB server selection timeout: {e}")
        _client = None
        _database = None
        raise
    except Exception as e:
        logger.error(f"Unexpected error connecting to MongoDB: {e}")
        _client = None
        _database = None
        raise


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create database indexes for efficient queries.
    
    Args:
        db: Database instance
    """
    try:
        # Users collection indexes
        users_collection = db.users
        await users_collection.create_index("email", unique=True)
        await users_collection.create_index("user_id", unique=True)
        # Keep aws_account_id index for backward compatibility during migration
        await users_collection.create_index("aws_account_id")
        
        # Organizations collection indexes
        orgs_collection = db.organizations
        await orgs_collection.create_index("org_id", unique=True)
        await orgs_collection.create_index("owner_id")
        # Sparse index for optional slug field
        await orgs_collection.create_index("slug", unique=True, sparse=True)
        
        # Organization members collection indexes
        org_members_collection = db.organization_members
        # Unique compound index: one user can only have one role per org
        await org_members_collection.create_index([("org_id", 1), ("user_id", 1)], unique=True)
        await org_members_collection.create_index("user_id")  # Find all orgs for a user
        await org_members_collection.create_index("org_id")   # Find all members of an org
        await org_members_collection.create_index("role")
        
        # Organization invitations collection indexes
        org_invitations_collection = db.organization_invitations
        await org_invitations_collection.create_index("token", unique=True)
        await org_invitations_collection.create_index([("org_id", 1), ("email", 1)])
        await org_invitations_collection.create_index("status")
        await org_invitations_collection.create_index("expires_at")
        
        # AWS connections collection indexes - UPDATED for org-based model
        aws_connections_collection = db.aws_connections
        # Keep user_id index for backward compatibility during migration
        await aws_connections_collection.create_index("user_id")
        # New org-based indexes
        await aws_connections_collection.create_index("org_id")  # Find connections for an org
        await aws_connections_collection.create_index("created_by")  # Find connections created by a user
        # Not unique - multiple orgs can have same AWS account
        await aws_connections_collection.create_index("aws_account_id")
        # Unique: one connection per org per account
        await aws_connections_collection.create_index([("org_id", 1), ("aws_account_id", 1)], unique=True)
        await aws_connections_collection.create_index("status")
        await aws_connections_collection.create_index("external_id")
        
        logger.info("MongoDB indexes created successfully")
        
    except Exception as e:
        logger.warning(f"Failed to create some indexes (may already exist): {e}")


async def close_mongodb_connection() -> None:
    """
    Close MongoDB connection.
    
    Should be called on application shutdown.
    """
    global _client, _database
    
    if _client is not None:
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed")


def get_database() -> Optional[AsyncIOMotorDatabase]:
    """
    Get the current database instance.
    
    Note: This returns the database instance without checking if it's connected.
    Use connect_to_mongodb() to ensure a connection exists.
    
    Returns:
        Optional[AsyncIOMotorDatabase]: Database instance or None if not connected
    """
    return _database
