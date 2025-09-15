#!/usr/bin/env python3
"""
Database Migration Script for FilteredJobView Table

This script creates the new FilteredJobView table for the filtered jobs UI feature.
Run this script after updating the codebase to add the filtered jobs functionality.
"""

import sys
import os

# Add the backend directory to the path
sys.path.append('backend')

from database import create_tables, engine
from sqlalchemy import text
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def migrate_database():
    """Create the FilteredJobView table and related indexes."""
    try:
        logger.info("🚀 Starting database migration for FilteredJobView...")

        # Check if table already exists
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='filtered_job_views';
            """))

            if result.fetchone():
                logger.info("✅ FilteredJobView table already exists")
                return True

        # Create all tables (this will create the new FilteredJobView table)
        logger.info("📝 Creating FilteredJobView table...")
        create_tables()

        # Verify the table was created
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='filtered_job_views';
            """))

            if result.fetchone():
                logger.info("✅ FilteredJobView table created successfully")

                # Check the structure
                result = conn.execute(text("PRAGMA table_info(filtered_job_views);"))
                columns = result.fetchall()
                logger.info(f"📋 Table structure: {len(columns)} columns created")
                for col in columns:
                    logger.info(f"   - {col[1]} ({col[2]})")

                return True
            else:
                logger.error("❌ Failed to create FilteredJobView table")
                return False

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        return False

def verify_migration():
    """Verify that the migration was successful."""
    try:
        logger.info("🔍 Verifying migration...")

        with engine.connect() as conn:
            # Check table exists
            result = conn.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='filtered_job_views';
            """))

            if not result.fetchone():
                logger.error("❌ FilteredJobView table not found")
                return False

            # Check indexes exist
            result = conn.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='index' AND tbl_name='filtered_job_views';
            """))

            indexes = result.fetchall()
            logger.info(f"📊 Found {len(indexes)} indexes on filtered_job_views table")
            for idx in indexes:
                logger.info(f"   - {idx[0]}")

            # Test basic operations
            conn.execute(text("SELECT COUNT(*) FROM filtered_job_views;"))
            logger.info("✅ Table is accessible and functional")

            return True

    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        return False

def main():
    """Main migration function."""
    logger.info("🎯 FilteredJobView Migration Script")
    logger.info("=" * 50)

    # Step 1: Run migration
    if not migrate_database():
        logger.error("💥 Migration failed!")
        sys.exit(1)

    # Step 2: Verify migration
    if not verify_migration():
        logger.error("💥 Migration verification failed!")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("🎉 Migration completed successfully!")
    logger.info("")
    logger.info("📱 You can now access the new Filtered Jobs UI at:")
    logger.info("   http://localhost:8000/filteredjobs")
    logger.info("")
    logger.info("🔧 API endpoints available:")
    logger.info("   GET /api/filtered-jobs - Search filtered jobs")
    logger.info("   GET /api/filtered-jobs/dates - Get available dates")
    logger.info("")
    logger.info("💡 Next steps:")
    logger.info("   1. Run your next autoscraping to populate the table")
    logger.info("   2. View filtered jobs in the new UI")
    logger.info("   3. Use date range and filters to explore job data")

if __name__ == "__main__":
    main()