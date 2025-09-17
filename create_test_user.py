#!/usr/bin/env python3
"""
Create a fresh test user for testing the workflow
"""

import sys
import os
sys.path.append('backend')

# Set up direct database connection to match backend
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import User, Base
from backend.auth import get_password_hash

# Use the same database path as backend
DATABASE_URL = "sqlite:///jobsearch.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_test_user(username, email, password):
    """Create a test user"""
    db = SessionLocal()
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            print(f"✅ User {email} already exists")
            return existing_user

        # Create new user
        hashed_password = get_password_hash(password)
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            full_name=f"Test User {username}",
            is_active=True
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"✅ Created new user: {user.username} ({user.email})")
        print(f"🔑 Password: {password}")
        print(f"👤 User ID: {user.id}")
        return user

    except Exception as e:
        print(f"❌ Error creating user: {e}")
        db.rollback()
        return None
    finally:
        db.close()

if __name__ == "__main__":
    # Create a test user
    create_test_user("testuser", "test@example.com", "testpass123")