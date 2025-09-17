#!/usr/bin/env python3
"""Create a specific user for testing"""

import sys
sys.path.append('backend')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import User
from backend.auth import get_password_hash

DATABASE_URL = "sqlite:///jobsearch.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_user(email, password):
    db = SessionLocal()
    try:
        # Check if user exists
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"✅ User {email} already exists")
            return existing

        # Create new user
        user = User(
            username=email,
            email=email,
            hashed_password=get_password_hash(password),
            full_name=f"Test User {email}",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"✅ Created user: {email}")
        print(f"🔑 Password: {password}")
        print(f"👤 User ID: {user.id}")
        return user

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return None
    finally:
        db.close()

if __name__ == "__main__":
    create_user("gongjv1@gmail.com", "testpass123")
    create_user("gongjv2@gmail.com", "testpass123")