#!/usr/bin/env python3
"""
Migration script to add UserAutoscrapingConfig table
Run this after updating the database models.
"""

import sys
import os
sys.path.append('backend')

from database import engine, Base, SessionLocal
from sqlalchemy import text

def run_migration():
    """Add the user_autoscraping_configs table"""
    print("🔄 Running migration: Add UserAutoscrapingConfig table...")

    try:
        # Create all tables (this will only create new ones)
        Base.metadata.create_all(bind=engine)
        print("✅ Successfully created user_autoscraping_configs table")

        # Verify the table was created
        db = SessionLocal()
        try:
            result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='user_autoscraping_configs';"))
            table_exists = result.fetchone()

            if table_exists:
                print("✅ Migration completed successfully")
                print("📋 New table: user_autoscraping_configs")
                print("🔗 Each user now has their own autoscraping configuration")
            else:
                print("⚠️  Warning: Table may not have been created properly")

        finally:
            db.close()

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    run_migration()