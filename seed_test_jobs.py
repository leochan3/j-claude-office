#!/usr/bin/env python3
"""
Seed the database with some test scraped jobs to test the filtering logic
"""

import sys
import os
sys.path.append('backend')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import ScrapedJob, ScrapingRun, TargetCompany
from datetime import datetime, timezone
import hashlib

# Use the same database path as backend
DATABASE_URL = "sqlite:///jobsearch.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_test_jobs():
    """Create test scraped jobs"""
    db = SessionLocal()
    try:
        # Create a scraping run
        scraping_run = ScrapingRun(
            run_type="test_seed",
            companies_scraped=["wayfair"],
            sites_used=["linkedin", "indeed"],
            search_parameters={
                "search_terms": ["product manager", "software engineer"],
                "companies": ["Wayfair"],
                "locations": ["USA"]
            },
            total_jobs_found=0,
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc)
        )
        db.add(scraping_run)
        db.flush()

        # Create target company
        target_company = TargetCompany(
            name="Wayfair",
            display_name="Wayfair",
            is_active=True,
            preferred_sites=["indeed", "linkedin"],
            search_terms=["product manager", "software engineer"],
            location_filters=["USA"]
        )
        db.add(target_company)
        db.flush()

        # Test jobs data
        test_jobs = [
            {
                "title": "Senior Product Manager - Growth",
                "company": "Wayfair",
                "location": "Boston, MA",
                "description": "Lead product management for growth initiatives. Drive product strategy and work with engineering teams to deliver features that increase user engagement and retention. Experience with A/B testing and data analysis required.",
                "min_amount": 140000,
                "max_amount": 160000,
                "site": "linkedin",
                "job_url": "https://linkedin.com/jobs/1",
            },
            {
                "title": "Product Manager - E-commerce Platform",
                "company": "Wayfair",
                "location": "Remote",
                "description": "Drive product strategy for our e-commerce platform. Work with cross-functional teams to improve user experience and conversion rates. Background in product management and technical expertise preferred.",
                "min_amount": 120000,
                "max_amount": 140000,
                "site": "indeed",
                "job_url": "https://indeed.com/viewjob?jk=1",
            },
            {
                "title": "Software Engineer - Backend",
                "company": "Wayfair",
                "location": "Boston, MA",
                "description": "Backend software engineer role working on microservices architecture. Python, Java, and cloud technologies. Build scalable systems to support millions of users.",
                "min_amount": 100000,
                "max_amount": 130000,
                "site": "linkedin",
                "job_url": "https://linkedin.com/jobs/2",
            },
            {
                "title": "VP of Product",
                "company": "Wayfair",
                "location": "Boston, MA",
                "description": "Lead the product organization. Executive role requiring 10+ years of product leadership experience. Drive product vision and strategy across multiple teams.",
                "min_amount": 250000,
                "max_amount": 300000,
                "site": "indeed",
                "job_url": "https://indeed.com/viewjob?jk=2",
            },
            {
                "title": "Data Analyst",
                "company": "Wayfair",
                "location": "Remote",
                "description": "Analyze business metrics and create reports. Work with product teams to understand user behavior and improve conversion rates.",
                "min_amount": 80000,
                "max_amount": 100000,
                "site": "glassdoor",
                "job_url": "https://glassdoor.com/job/1",
            },
        ]

        created_jobs = []
        for job_data in test_jobs:
            # Create job hash for deduplication
            job_content = f"{job_data['title']}-{job_data['company']}-{job_data['location']}"
            job_hash = hashlib.md5(job_content.encode()).hexdigest()

            scraped_job = ScrapedJob(
                job_url=job_data["job_url"],
                job_hash=job_hash,
                title=job_data["title"],
                company=job_data["company"],
                location=job_data["location"],
                description=job_data["description"],
                min_amount=job_data["min_amount"],
                max_amount=job_data["max_amount"],
                salary_interval="yearly",
                currency="USD",
                date_posted=datetime.now(timezone.utc).date(),
                date_scraped=datetime.now(timezone.utc),
                site=job_data["site"],
                is_remote=("Remote" in job_data["location"]),
                scraping_run_id=scraping_run.id
            )

            db.add(scraped_job)
            created_jobs.append(scraped_job)

        # Update scraping run with job count
        scraping_run.total_jobs_found = len(test_jobs)

        db.commit()
        print(f"✅ Created {len(created_jobs)} test jobs")
        for job in created_jobs:
            print(f"   📄 {job.title} at {job.company} (${job.min_amount}-${job.max_amount})")

        return created_jobs

    except Exception as e:
        print(f"❌ Error creating test jobs: {e}")
        db.rollback()
        return []
    finally:
        db.close()

if __name__ == "__main__":
    create_test_jobs()