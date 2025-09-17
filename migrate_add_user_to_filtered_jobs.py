#!/usr/bin/env python3
"""
Migration script to add user_id column to filtered_job_views table
This makes filtered jobs user-specific instead of global
"""

import sys
import os
sys.path.append('backend')

from database import engine, SessionLocal
from sqlalchemy import text

def run_migration():
    """Add user_id column to filtered_job_views table"""
    print("🔄 Running migration: Add user_id to filtered_job_views...")

    db = SessionLocal()
    try:
        # Check if user_id column already exists
        result = db.execute(text("PRAGMA table_info(filtered_job_views);"))
        columns = [row[1] for row in result.fetchall()]

        if 'user_id' in columns:
            print("✅ user_id column already exists")
            return

        # Add user_id column
        print("➕ Adding user_id column...")
        db.execute(text("ALTER TABLE filtered_job_views ADD COLUMN user_id TEXT;"))

        # Create index for user_id
        print("📊 Creating index for user_id...")
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_filtered_jobs_user_id ON filtered_job_views(user_id);"))

        # Check if we have any existing filtered jobs that need user assignment
        result = db.execute(text("SELECT COUNT(*) FROM filtered_job_views WHERE user_id IS NULL;"))
        orphaned_count = result.fetchone()[0]

        if orphaned_count > 0:
            print(f"⚠️  Warning: Found {orphaned_count} existing filtered jobs without user assignment")
            print("💡 These jobs will not be visible to any user until re-scraped")

            # Option: Delete orphaned jobs or assign to a default user
            response = input("Delete orphaned jobs? (y/N): ").lower().strip()
            if response == 'y':
                db.execute(text("DELETE FROM filtered_job_views WHERE user_id IS NULL;"))
                print(f"🗑️  Deleted {orphaned_count} orphaned filtered jobs")

        db.commit()
        print("✅ Migration completed successfully")
        print("🔒 Filtered jobs are now user-specific")

    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()