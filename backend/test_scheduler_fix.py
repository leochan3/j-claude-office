"""
Test the scheduler fix for the list strip error
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scheduler import AutoScrapingScheduler
from database import SessionLocal, User, ScrapingRun, ScrapedJob
import uuid
from datetime import datetime, timezone

def test_scheduler_fix():
    """Test that the scheduler can create filtered jobs without the list strip error."""
    print("🧪 Testing scheduler fix...")
    
    # Create a test user
    db = SessionLocal()
    try:
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            username=f"test_user_{int(datetime.now().timestamp())}",
            email=f"test_{int(datetime.now().timestamp())}@test.com",
            hashed_password="test_hash"
        )
        db.add(user)
        db.commit()
        
        # Create a test scraping run
        run_id = str(uuid.uuid4())
        run = ScrapingRun(
            id=run_id,
            run_type="manual",
            status="completed",
            companies_scraped=["Wayfair"],
            sites_used=["indeed"],
            search_parameters={"search_terms": ["product manager"]},
            total_jobs_found=1,
            new_jobs_added=1,
            duplicate_jobs_skipped=0
        )
        db.add(run)
        db.commit()
        
        # Create a test scraped job
        job = ScrapedJob(
            id=str(uuid.uuid4()),
            job_hash="test_hash_123",
            job_url="https://wayfair.com/jobs/123",
            title="Product Manager",
            company="Wayfair",
            location="Boston, MA",
            site="indeed",
            description="Great product manager role at Wayfair",
            scraping_run_id=run_id
        )
        db.add(job)
        db.commit()
        
        # Test the scheduler
        scheduler = AutoScrapingScheduler()
        
        # This should not raise the list strip error anymore
        result = scheduler.create_user_filtered_jobs(
            user_id=user_id,
            company_names=["Wayfair"],
            search_terms=["product manager", "engineer"]
        )
        
        print(f"✅ Scheduler test completed successfully! Result: {result}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        try:
            db.query(ScrapedJob).filter(ScrapedJob.scraping_run_id == run_id).delete()
            db.query(ScrapingRun).filter(ScrapingRun.id == run_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()
            print("🧹 Test data cleaned up")
        except:
            pass
        db.close()

if __name__ == "__main__":
    test_scheduler_fix()
