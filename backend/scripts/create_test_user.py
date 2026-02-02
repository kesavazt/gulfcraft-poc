#!/usr/bin/env python
"""
Create a test admin user for the Gulf Craft Costing Agent.
Run this script to create a default admin user for testing.
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import SessionLocal, User
from core.api import hash_password

def create_test_user(username="admin", password="admin123", role="admin"):
    """Create a test user."""
    db = SessionLocal()
    try:
        # Check if user exists
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"✗ User '{username}' already exists")
            return False

        # Create user
        user = User(
            username=username,
            hashed_password=hash_password(password),
            role=role
        )
        db.add(user)
        db.commit()
        print(f"✓ Created user: {username} / {password} (role: {role})")
        print(f"  You can now login with these credentials")
        return True

    except Exception as e:
        print(f"✗ Error creating user: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("Creating test admin user...")
    create_test_user()
