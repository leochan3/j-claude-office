"""
Daily Job Review System

This module handles the automated creation of daily job review lists by filtering
and ranking newly scraped jobs based on user preferences and relevance scores.
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func

from database import (
    SessionLocal, ScrapedJob, DailyJobReviewList, DailyJobReviewItem,
    TargetCompany, ScrapingRun
)

logger = logging.getLogger(__name__)

class DailyJobReviewManager:
    """Manages the creation and processing of daily job review lists."""
    
    def __init__(self):
        # Default configuration - can be overridden by .env or saved preferences
        self.config = {
            "search_terms": ["analyst", "manager", "business", "commercial", "strategy", "finance"],
            "companies": [],  # Empty means use all companies from daily scraping
            "min_relevance_score": 20,  # Minimum score to include in review
            "max_jobs_per_day": 50,  # Maximum jobs in daily review list
            "salary_preference": {
                "min_salary": None,
                "expected_salary": None
            },
            "exclude_keywords": ["intern", "internship", "student", "entry level"],
            "location_preference": ["US", "United States"],
            "job_types": [],  # Empty means all job types
            "days_lookback": 1,  # How many days back to look for new jobs
        }
        
        # Load configuration from environment or file
        self._load_configuration()
        
        logger.info(f"DailyJobReviewManager initialized with config: {self.config}")
    
    def _load_configuration(self):
        """Load configuration from environment variables or config files."""
        
        # Load from scraping_defaults.json if available
        try:
            defaults_file = "scraping_defaults.json"
            if os.path.exists(defaults_file):
                with open(defaults_file, 'r') as f:
                    defaults = json.load(f)
                    
                if defaults.get('search_terms'):
                    self.config['search_terms'] = defaults['search_terms']
                    
                if defaults.get('companies'):
                    self.config['companies'] = defaults['companies']
                    
                logger.info(f"Loaded configuration from {defaults_file}")
        except Exception as e:
            logger.warning(f"Could not load scraping defaults: {e}")
        
        # Load from environment variables if set
        if os.getenv("DAILY_REVIEW_SEARCH_TERMS"):
            terms = os.getenv("DAILY_REVIEW_SEARCH_TERMS", "").split(",")
            self.config['search_terms'] = [term.strip() for term in terms if term.strip()]
        
        if os.getenv("DAILY_REVIEW_MIN_SCORE"):
            self.config['min_relevance_score'] = int(os.getenv("DAILY_REVIEW_MIN_SCORE", "20"))
            
        if os.getenv("DAILY_REVIEW_MAX_JOBS"):
            self.config['max_jobs_per_day'] = int(os.getenv("DAILY_REVIEW_MAX_JOBS", "50"))
    
    def calculate_relevance_score(self, job: ScrapedJob, search_terms: List[str], expected_salary: Optional[int] = None) -> float:
        """
        Calculate relevance score for a job based on search terms and preferences.
        This mirrors the frontend scoring algorithm for consistency.
        """
        if not search_terms:
            return 0
        
        score = 0
        title = (job.title or '').lower().strip()
        description = (job.description or '').lower().strip()
        company = (job.company or '').lower().strip()
        
        # Combine all search terms into one search string
        search_string = ' '.join(search_terms).lower().strip()
        
        # Split search into words, filter out common stop words
        stop_words = {'and', 'or', 'the', 'a', 'an', 'in', 'at', 'for', 'with', 'by', 'to', 'of', 'from'}
        search_words = [word for word in search_string.split() 
                       if len(word) > 1 and word not in stop_words]
        
        if not search_words:
            return 0
        
        # 1. Exact phrase match in title (highest score)
        if search_string in title:
            score += 100
        
        # 2. Exact phrase match in description
        if search_string in description:
            score += 80
        
        # 3. All search words in title (high score)
        title_words = title.split()
        title_words_matched = [word for word in search_words 
                              if any(word in title_word or title_word in word for title_word in title_words)]
        
        if len(title_words_matched) == len(search_words):
            score += 60  # All words found
        else:
            score += len(title_words_matched) * 15  # Partial match
        
        # 4. Search words in description
        desc_matches = sum(1 for word in search_words if word in description)
        score += desc_matches * 10
        
        # 5. Company name bonus (if company matches search terms)
        if any(word in company for word in search_words):
            score += 25
        
        # 6. Salary preference bonus
        if expected_salary and job.min_amount and job.max_amount:
            avg_salary = (job.min_amount + job.max_amount) / 2
            if avg_salary >= expected_salary * 0.8:  # Within 80% of expected
                if avg_salary >= expected_salary:
                    score += 20  # At or above expected
                else:
                    score += 10  # Close to expected
        
        # 7. Recent posting bonus
        if job.date_posted:
            try:
                # Handle both timezone-aware and timezone-naive datetimes
                now = datetime.now(timezone.utc) if job.date_posted.tzinfo else datetime.now()
                days_old = (now - job.date_posted).days
                if days_old <= 3:
                    score += 15  # Recently posted
                elif days_old <= 7:
                    score += 5   # Posted this week
            except (TypeError, AttributeError):
                # Skip bonus if date comparison fails
                pass
        
        # 8. Remote work bonus (if preferred)
        if job.is_remote:
            score += 10
        
        # 9. Penalty for exclude keywords
        exclude_keywords = self.config.get('exclude_keywords', [])
        for keyword in exclude_keywords:
            if keyword.lower() in title or keyword.lower() in description:
                score -= 30  # Significant penalty
        
        return max(0, score)  # Ensure score is not negative
    
    def get_jobs_for_review(self, target_date: str, db: Session) -> List[ScrapedJob]:
        """
        Get jobs that should be included in the daily review for the given date.
        """
        # Parse target date
        try:
            review_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"Invalid date format: {target_date}. Use YYYY-MM-DD")
        
        # Calculate date range for job lookback
        # Note: ScrapedJob.date_scraped is timezone-naive, so we use naive datetimes
        end_date = datetime.combine(review_date, datetime.min.time())
        start_date = end_date - timedelta(days=self.config['days_lookback'])
        
        logger.info(f"Looking for jobs between {start_date} and {end_date}")
        
        # Build query for jobs in the date range
        query = db.query(ScrapedJob).filter(
            and_(
                ScrapedJob.date_scraped >= start_date,
                ScrapedJob.date_scraped < end_date + timedelta(days=1),
                ScrapedJob.is_active == True
            )
        )
        
        # Filter by companies if specified
        if self.config['companies']:
            company_filters = []
            for company_name in self.config['companies']:
                company_filters.append(ScrapedJob.company.ilike(f"%{company_name}%"))
            
            from sqlalchemy import or_
            query = query.filter(or_(*company_filters))
        
        # Filter by location if specified
        if self.config['location_preference']:
            location_filters = []
            for location in self.config['location_preference']:
                location_filters.append(ScrapedJob.location.ilike(f"%{location}%"))
            
            from sqlalchemy import or_
            query = query.filter(or_(*location_filters))
        
        # Filter by job types if specified
        if self.config['job_types']:
            from sqlalchemy import or_
            type_filters = []
            for job_type in self.config['job_types']:
                type_filters.append(ScrapedJob.job_type.ilike(f"%{job_type}%"))
            query = query.filter(or_(*type_filters))
        
        jobs = query.all()
        logger.info(f"Found {len(jobs)} jobs in date range for review")
        
        return jobs
    
    def create_daily_review_list(self, target_date: str, db: Session, force_recreate: bool = False) -> DailyJobReviewList:
        """
        Create a daily job review list for the given date.
        """
        # Check if review list already exists for this date
        existing_list = db.query(DailyJobReviewList).filter(
            DailyJobReviewList.date == target_date
        ).first()
        
        if existing_list and not force_recreate:
            logger.info(f"Daily review list already exists for {target_date}")
            return existing_list
        
        # Delete existing list if force recreating
        if existing_list and force_recreate:
            logger.info(f"Deleting existing review list for {target_date}")
            db.delete(existing_list)
            db.commit()
        
        # Get jobs for review
        jobs = self.get_jobs_for_review(target_date, db)
        
        if not jobs:
            logger.warning(f"No jobs found for review on {target_date}")
            return None
        
        # Calculate relevance scores for all jobs
        scored_jobs = []
        search_terms = self.config['search_terms']
        expected_salary = self.config['salary_preference'].get('expected_salary')
        
        for job in jobs:
            score = self.calculate_relevance_score(job, search_terms, expected_salary)
            
            if score >= self.config['min_relevance_score']:
                scored_jobs.append((job, score))
        
        if not scored_jobs:
            logger.warning(f"No jobs met minimum score threshold of {self.config['min_relevance_score']}")
            return None
        
        # Sort by score (descending) and limit to max jobs
        scored_jobs.sort(key=lambda x: x[1], reverse=True)
        top_jobs = scored_jobs[:self.config['max_jobs_per_day']]
        
        logger.info(f"Selected {len(top_jobs)} jobs for daily review (scores: {top_jobs[0][1]:.1f} to {top_jobs[-1][1]:.1f})")
        
        # Create the daily review list
        review_list = DailyJobReviewList(
            date=target_date,
            filter_config=self.config,
            total_jobs_reviewed=len(jobs),
            jobs_selected_count=len(top_jobs),
            auto_generated=True,
            status='pending'
        )
        
        db.add(review_list)
        db.flush()  # Get the ID
        
        # Add review items
        for rank, (job, score) in enumerate(top_jobs, 1):
            review_item = DailyJobReviewItem(
                review_list_id=review_list.id,
                scraped_job_id=job.id,
                relevance_score=score,
                final_rank=rank
            )
            db.add(review_item)
        
        db.commit()
        
        logger.info(f"Created daily review list for {target_date} with {len(top_jobs)} jobs")
        return review_list
    
    def get_review_list(self, target_date: str, db: Session) -> Optional[DailyJobReviewList]:
        """Get the review list for a specific date."""
        return db.query(DailyJobReviewList).filter(
            DailyJobReviewList.date == target_date
        ).first()
    
    def get_available_review_dates(self, db: Session, limit: int = 30) -> List[str]:
        """Get list of available review dates, most recent first."""
        dates = db.query(DailyJobReviewList.date).order_by(
            desc(DailyJobReviewList.date)
        ).limit(limit).all()
        
        return [date[0] for date in dates]
    
    def update_review_item_status(self, item_id: str, is_selected: bool = None, 
                                 is_dismissed: bool = None, user_rating: int = None, 
                                 user_notes: str = None, db: Session = None) -> bool:
        """Update the review status of a specific job item."""
        item = db.query(DailyJobReviewItem).filter(
            DailyJobReviewItem.id == item_id
        ).first()
        
        if not item:
            return False
        
        if is_selected is not None:
            item.is_selected = is_selected
        if is_dismissed is not None:
            item.is_dismissed = is_dismissed
        if user_rating is not None:
            item.user_rating = user_rating
        if user_notes is not None:
            item.user_notes = user_notes
        
        if any([is_selected, is_dismissed, user_rating, user_notes]):
            item.reviewed_at = datetime.now(timezone.utc)
        
        db.commit()
        return True

# Global instance
daily_job_reviewer = DailyJobReviewManager()

def create_daily_review_list(target_date: str = None, force_recreate: bool = False) -> Optional[DailyJobReviewList]:
    """
    Create a daily review list for the specified date (defaults to today).
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    
    db = SessionLocal()
    try:
        return daily_job_reviewer.create_daily_review_list(target_date, db, force_recreate)
    finally:
        db.close()

def get_daily_review_list(target_date: str = None) -> Optional[DailyJobReviewList]:
    """
    Get the daily review list for the specified date (defaults to today).
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    
    db = SessionLocal()
    try:
        return daily_job_reviewer.get_review_list(target_date, db)
    finally:
        db.close()