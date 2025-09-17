#!/usr/bin/env python3
"""
Reset password for a user
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

def reset_password(email, new_password):
    """Reset password for a user"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User with email {email} not found")
            return False

        print(f"Found user: {user.username} (ID: {user.id})")

        # Update password
        user.hashed_password = get_password_hash(new_password)
        db.commit()

        print(f"✅ Password updated for user: {user.username} ({user.email})")
        print(f"🔑 New password: {new_password}")
        return True

    except Exception as e:
        print(f"❌ Error updating password: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python reset_user_password.py <email> <new_password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    reset_password(email, password)