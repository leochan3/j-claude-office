"""
Database Migration: Fix Multi-User Deduplication Issue

This migration removes the global unique constraint on job_hash and adds a composite
unique constraint on (job_hash, scraping_run_id) to allow different users to scrape
the same jobs while preventing duplicates within the same scraping run.

Run this migration after updating the database.py schema.
"""

import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_database_url():
    """Get database URL from environment variables."""
    # Try PostgreSQL first (production)
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")
    
    # Fallback to SQLite (development)
    return "sqlite:///./jobsearch.db"

def run_migration():
    """Run the deduplication fix migration."""
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    print(f"🔄 Running deduplication fix migration on: {database_url}")
    
    try:
        with engine.connect() as conn:
            # Check if we're using PostgreSQL or SQLite
            is_postgres = "postgresql" in database_url
            
            if is_postgres:
                print("📊 Detected PostgreSQL database")
                migrate_postgres(conn)
            else:
                print("📊 Detected SQLite database")
                migrate_sqlite(conn)
                
        print("✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

def migrate_postgres(conn):
    """Migrate PostgreSQL database."""
    try:
        # Check if the old unique constraint exists
        inspector = inspect(conn)
        constraints = inspector.get_unique_constraints('scraped_jobs')
        
        # Find the job_hash unique constraint
        job_hash_constraint = None
        for constraint in constraints:
            if 'job_hash' in constraint['column_names']:
                job_hash_constraint = constraint
                break
        
        if job_hash_constraint:
            print(f"🔍 Found existing job_hash unique constraint: {job_hash_constraint['name']}")
            
            # Drop the old unique constraint
            drop_constraint_sql = f"ALTER TABLE scraped_jobs DROP CONSTRAINT IF EXISTS {job_hash_constraint['name']}"
            conn.execute(text(drop_constraint_sql))
            conn.commit()
            print("✅ Dropped old job_hash unique constraint")
        else:
            print("ℹ️  No existing job_hash unique constraint found")
        
        # Add the new composite unique constraint
        add_constraint_sql = """
        ALTER TABLE scraped_jobs 
        ADD CONSTRAINT idx_job_hash_run_unique 
        UNIQUE (job_hash, scraping_run_id)
        """
        
        try:
            conn.execute(text(add_constraint_sql))
            conn.commit()
            print("✅ Added new composite unique constraint (job_hash, scraping_run_id)")
        except OperationalError as e:
            if "already exists" in str(e).lower():
                print("ℹ️  Composite unique constraint already exists")
            else:
                raise e
                
    except Exception as e:
        print(f"❌ PostgreSQL migration error: {e}")
        raise e

def migrate_sqlite(conn):
    """Migrate SQLite database."""
    try:
        # SQLite doesn't support dropping constraints directly
        # We need to recreate the table with the new schema
        
        print("🔄 SQLite migration requires table recreation...")
        
        # Check if the new constraint already exists
        inspector = inspect(conn)
        constraints = inspector.get_unique_constraints('scraped_jobs')
        
        has_composite_constraint = any(
            'job_hash' in constraint['column_names'] and 'scraping_run_id' in constraint['column_names']
            for constraint in constraints
        )
        
        if has_composite_constraint:
            print("ℹ️  Composite unique constraint already exists")
            return
        
        # Get the current table structure
        result = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='scraped_jobs'"))
        table_sql = result.fetchone()
        
        if not table_sql:
            print("❌ scraped_jobs table not found")
            return
        
        print("⚠️  SQLite migration requires manual intervention:")
        print("   1. Backup your database")
        print("   2. Delete the scraped_jobs table")
        print("   3. Restart the application to recreate with new schema")
        print("   4. Re-scrape jobs as needed")
        
        # For now, just warn the user
        print("ℹ️  Skipping SQLite migration - manual steps required")
        
    except Exception as e:
        print(f"❌ SQLite migration error: {e}")
        raise e

if __name__ == "__main__":
    run_migration()
