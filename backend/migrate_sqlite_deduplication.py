"""
SQLite Migration: Fix Multi-User Deduplication Issue

This migration recreates the scraped_jobs table with the new schema that allows
different users to scrape the same jobs while preventing duplicates within the same run.
"""

import os
import sqlite3
from datetime import datetime
import shutil

def backup_database():
    """Create a backup of the current database."""
    db_path = "jobsearch.db"
    if os.path.exists(db_path):
        backup_path = f"jobsearch_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(db_path, backup_path)
        print(f"✅ Database backed up to: {backup_path}")
        return backup_path
    return None

def migrate_sqlite():
    """Migrate SQLite database by recreating the scraped_jobs table."""
    db_path = "jobsearch.db"
    
    if not os.path.exists(db_path):
        print("❌ Database file not found")
        return False
    
    # Create backup
    backup_path = backup_database()
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("🔄 Recreating scraped_jobs table with new schema...")
        
        # Get all data from the current table
        cursor.execute("SELECT * FROM scraped_jobs")
        rows = cursor.fetchall()
        
        # Get column names
        cursor.execute("PRAGMA table_info(scraped_jobs)")
        columns_info = cursor.fetchall()
        column_names = [col[1] for col in columns_info]
        
        print(f"📊 Found {len(rows)} existing jobs to migrate")
        
        # Drop the old table
        cursor.execute("DROP TABLE IF EXISTS scraped_jobs")
        
        # Create the new table with updated schema
        create_table_sql = """
        CREATE TABLE scraped_jobs (
            id TEXT PRIMARY KEY,
            job_url TEXT,
            job_hash TEXT NOT NULL,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            site TEXT NOT NULL,
            description TEXT,
            job_type TEXT,
            is_remote BOOLEAN,
            min_amount REAL,
            max_amount REAL,
            salary_interval TEXT,
            currency TEXT,
            date_posted TIMESTAMP,
            date_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            min_experience_years INTEGER,
            max_experience_years INTEGER,
            target_company_id TEXT,
            scraping_run_id TEXT,
            FOREIGN KEY (target_company_id) REFERENCES target_companies (id),
            FOREIGN KEY (scraping_run_id) REFERENCES scraping_runs (id)
        )
        """
        
        cursor.execute(create_table_sql)
        
        # Create indexes
        cursor.execute("CREATE INDEX ix_scraped_jobs_job_url ON scraped_jobs (job_url)")
        cursor.execute("CREATE INDEX ix_scraped_jobs_job_hash ON scraped_jobs (job_hash)")
        cursor.execute("CREATE INDEX ix_scraped_jobs_title ON scraped_jobs (title)")
        cursor.execute("CREATE INDEX ix_scraped_jobs_company ON scraped_jobs (company)")
        cursor.execute("CREATE INDEX ix_scraped_jobs_location ON scraped_jobs (location)")
        cursor.execute("CREATE INDEX idx_job_search ON scraped_jobs (title, company, location)")
        cursor.execute("CREATE INDEX idx_job_date ON scraped_jobs (date_posted, is_active)")
        cursor.execute("CREATE INDEX idx_job_salary ON scraped_jobs (min_amount, max_amount)")
        cursor.execute("CREATE INDEX idx_job_experience ON scraped_jobs (min_experience_years, max_experience_years)")
        
        # Create the composite unique constraint
        cursor.execute("CREATE UNIQUE INDEX idx_job_hash_run_unique ON scraped_jobs (job_hash, scraping_run_id)")
        
        # Re-insert all data
        if rows:
            placeholders = ", ".join(["?" for _ in column_names])
            insert_sql = f"INSERT INTO scraped_jobs ({', '.join(column_names)}) VALUES ({placeholders})"
            cursor.executemany(insert_sql, rows)
            print(f"✅ Migrated {len(rows)} jobs to new schema")
        
        conn.commit()
        print("✅ SQLite migration completed successfully!")
        
        # Verify the new constraint works
        cursor.execute("PRAGMA index_list(scraped_jobs)")
        indexes = cursor.fetchall()
        print("📋 New indexes created:")
        for index in indexes:
            print(f"   - {index[1]}")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if backup_path and os.path.exists(backup_path):
            print(f"🔄 Restoring from backup: {backup_path}")
            shutil.copy2(backup_path, db_path)
        return False
        
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("🔄 Starting SQLite deduplication fix migration...")
    success = migrate_sqlite()
    if success:
        print("🎉 Migration completed successfully!")
        print("💡 Different users can now scrape the same jobs without conflicts")
    else:
        print("❌ Migration failed - check the error messages above")
