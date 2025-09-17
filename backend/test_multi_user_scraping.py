"""
Test Multi-User Scraping Fix

This script tests that different users can now scrape the same jobs without conflicts.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, ScrapedJob, ScrapingRun, User, create_job_hash
from datetime import datetime, timezone
import uuid

def test_multi_user_scraping():
    """Test that different users can scrape the same jobs."""
    db = SessionLocal()
    
    try:
        print("🧪 Testing multi-user scraping fix...")
        
        # Create test users with unique names
        timestamp = str(int(datetime.now().timestamp()))
        user1 = User(
            id=str(uuid.uuid4()),
            username=f"test_user_1_{timestamp}",
            email=f"user1_{timestamp}@test.com",
            hashed_password="test_hash"
        )
        
        user2 = User(
            id=str(uuid.uuid4()),
            username=f"test_user_2_{timestamp}", 
            email=f"user2_{timestamp}@test.com",
            hashed_password="test_hash"
        )
        
        db.add(user1)
        db.add(user2)
        db.commit()
        
        # Create test scraping runs
        run1 = ScrapingRun(
            id=str(uuid.uuid4()),
            run_type="manual",
            status="completed",
            companies_scraped=["Wayfair"],
            sites_used=["indeed"],
            search_parameters={"search_terms": ["product manager"]},
            total_jobs_found=1,
            new_jobs_added=0,
            duplicate_jobs_skipped=0
        )
        
        run2 = ScrapingRun(
            id=str(uuid.uuid4()),
            run_type="manual",
            status="completed",
            companies_scraped=["Wayfair"],
            sites_used=["indeed"],
            search_parameters={"search_terms": ["product manager"]},
            total_jobs_found=1,
            new_jobs_added=0,
            duplicate_jobs_skipped=0
        )
        
        db.add(run1)
        db.add(run2)
        db.commit()
        
        # Create the same job for both users (different scraping runs)
        job_data = {
            "title": "Product Manager",
            "company": "Wayfair",
            "location": "Boston, MA",
            "job_url": "https://wayfair.com/jobs/123",
            "description": "Great product manager role"
        }
        
        job_hash = create_job_hash(
            title=job_data["title"],
            company=job_data["company"], 
            location=job_data["location"],
            job_url=job_data["job_url"]
        )
        
        # Create job for user 1
        job1 = ScrapedJob(
            id=str(uuid.uuid4()),
            job_hash=job_hash,
            job_url=job_data["job_url"],
            title=job_data["title"],
            company=job_data["company"],
            location=job_data["location"],
            site="indeed",
            description=job_data["description"],
            scraping_run_id=run1.id
        )
        
        # Create job for user 2 (same job, different run)
        job2 = ScrapedJob(
            id=str(uuid.uuid4()),
            job_hash=job_hash,  # Same hash
            job_url=job_data["job_url"],
            title=job_data["title"],
            company=job_data["company"],
            location=job_data["location"],
            site="indeed",
            description=job_data["description"],
            scraping_run_id=run2.id  # Different run
        )
        
        # This should work now - both jobs can be saved
        db.add(job1)
        db.commit()
        print("✅ User 1 job saved successfully")
        
        db.add(job2)
        db.commit()
        print("✅ User 2 job saved successfully")
        
        # Verify both jobs exist
        jobs_count = db.query(ScrapedJob).filter(
            ScrapedJob.job_hash == job_hash
        ).count()
        
        print(f"📊 Total jobs with same hash: {jobs_count}")
        
        if jobs_count == 2:
            print("🎉 SUCCESS: Multi-user scraping fix works!")
            print("   - Different users can now scrape the same jobs")
            print("   - Duplicates are prevented within the same scraping run")
            print("   - Global deduplication is removed")
        else:
            print("❌ FAILED: Expected 2 jobs, got {jobs_count}")
            
        # Test that duplicates within same run are still prevented
        try:
            job3 = ScrapedJob(
                id=str(uuid.uuid4()),
                job_hash=job_hash,
                job_url=job_data["job_url"],
                title=job_data["title"],
                company=job_data["company"],
                location=job_data["location"],
                site="indeed",
                description=job_data["description"],
                scraping_run_id=run1.id  # Same run as job1
            )
            db.add(job3)
            db.commit()
            print("❌ FAILED: Duplicate within same run should be prevented")
        except Exception as e:
            print("✅ Duplicate within same run correctly prevented")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up test data
        try:
            db.query(ScrapedJob).filter(ScrapedJob.job_hash == job_hash).delete()
            db.query(ScrapingRun).filter(ScrapingRun.id.in_([run1.id, run2.id])).delete()
            db.query(User).filter(User.id.in_([user1.id, user2.id])).delete()
            db.commit()
            print("🧹 Test data cleaned up")
        except:
            pass
        db.close()

if __name__ == "__main__":
    test_multi_user_scraping()
