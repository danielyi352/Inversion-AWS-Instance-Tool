"""
Test script to verify MongoDB connection is working.
Run this to check if your MONGODB_URI is configured correctly.
"""

import asyncio
import sys
import os
from pathlib import Path
from database import connect_to_mongodb, close_mongodb_connection, get_mongodb_uri, get_database_name
from models import User, AWSConnection, AWSConnectionStatus
import uuid
from datetime import datetime, timezone

# Try to load .env file if it exists
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
            print(f"Loaded .env file from: {env_path}")
            break
except ImportError:
    pass  # python-dotenv not installed, skip


async def test_connection():
    """Test MongoDB connection and basic operations."""
    print("=" * 60)
    print("MongoDB Connection Test")
    print("=" * 60)
    
    # Check if URI is set
    try:
        uri = get_mongodb_uri()
        # Mask password in output
        if "@" in uri:
            parts = uri.split("@")
            if len(parts) == 2:
                user_pass = parts[0].split("//")[1] if "//" in parts[0] else parts[0]
                if ":" in user_pass:
                    user = user_pass.split(":")[0]
                    masked_uri = uri.replace(user_pass, f"{user}:***")
                else:
                    masked_uri = uri
            else:
                masked_uri = uri
        else:
            masked_uri = uri
        print(f"[OK] MONGODB_URI is set: {masked_uri}")
    except ValueError as e:
        print(f"[ERROR] {e}")
        print("\nPlease set the MONGODB_URI environment variable.")
        return False
    
    db_name = get_database_name()
    print(f"[OK] Database name: {db_name}")
    print()
    
    # Test connection
    try:
        print("Connecting to MongoDB...")
        db = await connect_to_mongodb()
        print("[OK] Successfully connected to MongoDB!")
        print()
    except Exception as e:
        print(f"[ERROR] Failed to connect: {e}")
        print("\nPlease check:")
        print("  1. MONGODB_URI is correct")
        print("  2. MongoDB server is running and accessible")
        print("  3. Network/firewall allows connection")
        print("  4. Credentials are correct (if using authentication)")
        return False
    
    # Test basic operations
    try:
        print("Testing basic operations...")
        
        # Test 1: Ping
        print("  1. Testing ping...", end=" ")
        await db.client.admin.command('ping')
        print("[OK]")
        
        # Test 2: List collections
        print("  2. Listing collections...", end=" ")
        collections = await db.list_collection_names()
        print(f"[OK] Found {len(collections)} collection(s): {', '.join(collections) if collections else 'none'}")
        
        # Test 3: Insert test user
        print("  3. Testing user insert...", end=" ")
        users_collection = db.users
        test_user = User(
            user_id=str(uuid.uuid4()),
            email=f"test_{uuid.uuid4().hex[:8]}@test.com",
            name="Test User",
            auth_provider="test",
            auth_provider_id="test_123"
        )
        from models import user_to_dict
        user_dict = user_to_dict(test_user)
        result = await users_collection.insert_one(user_dict)
        print(f"[OK] Inserted user with ID: {result.inserted_id}")
        
        # Test 4: Read test user
        print("  4. Testing user read...", end=" ")
        found_user = await users_collection.find_one({"_id": result.inserted_id})
        if found_user:
            print(f"[OK] Found user: {found_user.get('email')}")
        else:
            print("[ERROR] User not found")
            return False
        
        # Test 5: Insert test AWS connection
        print("  5. Testing AWS connection insert...", end=" ")
        connections_collection = db.aws_connections
        test_connection = AWSConnection(
            user_id=test_user.user_id,
            aws_account_id="123456789012",
            external_id=str(uuid.uuid4()),
            status=AWSConnectionStatus.PENDING_CLAIM,
            region="us-east-1"
        )
        from models import aws_connection_to_dict
        conn_dict = aws_connection_to_dict(test_connection)
        conn_result = await connections_collection.insert_one(conn_dict)
        print(f"[OK] Inserted connection with ID: {conn_result.inserted_id}")
        
        # Test 6: Read test connection
        print("  6. Testing connection read...", end=" ")
        found_conn = await connections_collection.find_one({"_id": conn_result.inserted_id})
        if found_conn:
            print(f"[OK] Found connection: {found_conn.get('aws_account_id')} (status: {found_conn.get('status')})")
        else:
            print("[ERROR] Connection not found")
            return False
        
        # Test 7: Query with index
        print("  7. Testing indexed query...", end=" ")
        user_by_email = await users_collection.find_one({"email": test_user.email})
        if user_by_email:
            print(f"[OK] Found user by email index")
        else:
            print("[ERROR] User not found by email")
            return False
        
        # Cleanup test data
        print("  8. Cleaning up test data...", end=" ")
        await users_collection.delete_one({"_id": result.inserted_id})
        await connections_collection.delete_one({"_id": conn_result.inserted_id})
        print("[OK]")
        
        print()
        print("=" * 60)
        print("[OK] All tests passed! MongoDB is working correctly.")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Error during operations: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Close connection
        await close_mongodb_connection()
        print("\nConnection closed.")


async def main():
    """Main entry point."""
    success = await test_connection()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
