#!/usr/bin/env python3
"""
Clear all data from the database for a fresh start
"""

import sys
import os
sys.path.append('backend')

# Set up direct database connection to match backend
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import (
    User, FilteredJobView, UserSavedJob, UserAutoscrapingConfig,
    ScrapedJob, ScrapingRun, TargetCompany, Base
)

# Use the same database path as backend
DATABASE_URL = "sqlite:///jobsearch.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def clear_all_data():
    """Clear all data from all tables"""
    db = SessionLocal()
    try:
        print("🗑️  Clearing all data from database...")

        # Delete in order to respect foreign key constraints
        deleted_saved_jobs = db.query(UserSavedJob).count()
        db.query(UserSavedJob).delete()
        print(f"   ✅ Deleted {deleted_saved_jobs} saved jobs")

        deleted_filtered_jobs = db.query(FilteredJobView).count()
        db.query(FilteredJobView).delete()
        print(f"   ✅ Deleted {deleted_filtered_jobs} filtered jobs")

        deleted_scraped_jobs = db.query(ScrapedJob).count()
        db.query(ScrapedJob).delete()
        print(f"   ✅ Deleted {deleted_scraped_jobs} scraped jobs")

        deleted_scraping_runs = db.query(ScrapingRun).count()
        db.query(ScrapingRun).delete()
        print(f"   ✅ Deleted {deleted_scraping_runs} scraping runs")

        deleted_target_companies = db.query(TargetCompany).count()
        db.query(TargetCompany).delete()
        print(f"   ✅ Deleted {deleted_target_companies} target companies")

        deleted_autoscraping_configs = db.query(UserAutoscrapingConfig).count()
        db.query(UserAutoscrapingConfig).delete()
        print(f"   ✅ Deleted {deleted_autoscraping_configs} autoscraping configs")

        deleted_users = db.query(User).count()
        db.query(User).delete()
        print(f"   ✅ Deleted {deleted_users} users")

        db.commit()
        print("🎉 Database cleared successfully!")

    except Exception as e:
        print(f"❌ Error clearing database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    clear_all_data()