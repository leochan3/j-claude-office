from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from database import User, UserPreference, UserAutoscrapingConfig, UserSavedJob, SearchHistory, SavedSearch
from models import (
    UserCreate, UserPreferencesCreate, UserPreferencesUpdate,
    SaveJobRequest, SavedJobUpdate, SavedSearchCreate, SavedSearchUpdate
)
from auth import get_password_hash
from datetime import datetime, timezone
from typing import List, Optional
import uuid

class UserService:
    
    @staticmethod
    def create_user(db: Session, user_create: UserCreate) -> User:
        """Create a new user with default preferences."""
        # Check if username or email already exists
        existing_user = db.query(User).filter(
            (User.username == user_create.username) | (User.email == user_create.email)
        ).first()
        
        if existing_user:
            if existing_user.username == user_create.username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already registered"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
        
        # Create new user
        hashed_password = get_password_hash(user_create.password)
        db_user = User(
            username=user_create.username,
            email=user_create.email,
            hashed_password=hashed_password,
            full_name=user_create.full_name
        )
        
        try:
            db.add(db_user)
            db.flush()  # Flush to get the user ID
            
            # Create default preferences for the user
            default_preferences = UserPreference(user_id=db_user.id)
            db.add(default_preferences)
            
            db.commit()
            db.refresh(db_user)
            return db_user
            
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user"
            )
    
    @staticmethod
    def get_user_by_username(db: Session, username: str) -> Optional[User]:
        """Get user by username."""
        return db.query(User).filter(User.username == username).first()
    
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """Get user by email."""
        return db.query(User).filter(User.email == email).first()
    
    @staticmethod
    def get_user_preferences(db: Session, user_id: str) -> Optional[UserPreference]:
        """Get user preferences."""
        return db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    
    @staticmethod
    def update_user_preferences(
        db: Session, 
        user_id: str, 
        preferences_update: UserPreferencesUpdate
    ) -> UserPreference:
        """Update user preferences."""
        db_preferences = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        
        if not db_preferences:
            # Create default preferences if they don't exist
            db_preferences = UserPreference(user_id=user_id)
            db.add(db_preferences)
        
        # Update only provided fields
        update_data = preferences_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_preferences, field, value)
        
        db_preferences.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_preferences)
        return db_preferences
    
    @staticmethod
    def save_job(db: Session, user_id: str, job_request: SaveJobRequest) -> UserSavedJob:
        """Save a job for a user."""
        # Check if job already saved by this user using job_url or title+company
        job_url = job_request.job_data.get('job_url')
        job_title = job_request.job_data.get('title')
        job_company = job_request.job_data.get('company')
        
        # Query for existing jobs by this user
        existing_jobs = db.query(UserSavedJob).filter(UserSavedJob.user_id == user_id).all()
        
        for existing_job in existing_jobs:
            existing_job_url = existing_job.job_data.get('job_url')
            
            # If both jobs have URLs, only check by URL (most reliable)
            if job_url and existing_job_url:
                if existing_job_url == job_url:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Job already saved"
                    )
            # Only check by title + company if at least one job lacks a URL
            elif (job_title and job_company and 
                  existing_job.job_data.get('title') == job_title and 
                  existing_job.job_data.get('company') == job_company):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Job already saved"
                )
        
        db_job = UserSavedJob(
            user_id=user_id,
            job_data=job_request.job_data,
            notes=job_request.notes,
            tags=job_request.tags
        )
        
        db.add(db_job)
        db.commit()
        db.refresh(db_job)
        return db_job
    
    @staticmethod
    def get_saved_jobs(
        db: Session, 
        user_id: str, 
        skip: int = 0, 
        limit: int = 100
    ) -> List[UserSavedJob]:
        """Get user's saved jobs."""
        return db.query(UserSavedJob).filter(
            UserSavedJob.user_id == user_id
        ).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_saved_job(db: Session, user_id: str, job_id: str) -> Optional[UserSavedJob]:
        """Get a specific saved job."""
        return db.query(UserSavedJob).filter(
            UserSavedJob.user_id == user_id,
            UserSavedJob.id == job_id
        ).first()
    
    @staticmethod
    def update_saved_job(
        db: Session, 
        user_id: str, 
        job_id: str, 
        job_update: SavedJobUpdate
    ) -> Optional[UserSavedJob]:
        """Update a saved job."""
        db_job = db.query(UserSavedJob).filter(
            UserSavedJob.user_id == user_id,
            UserSavedJob.id == job_id
        ).first()
        
        if not db_job:
            return None
        
        # Update only provided fields
        update_data = job_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field == 'applied' and value:
                setattr(db_job, 'applied_at', datetime.now(timezone.utc))
            setattr(db_job, field, value)
        
        db_job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_job)
        return db_job
    
    @staticmethod
    def delete_saved_job(db: Session, user_id: str, job_id: str) -> bool:
        """Delete a saved job."""
        db_job = db.query(UserSavedJob).filter(
            UserSavedJob.user_id == user_id,
            UserSavedJob.id == job_id
        ).first()
        
        if not db_job:
            return False
        
        db.delete(db_job)
        db.commit()
        return True
    
    @staticmethod
    def get_categorized_jobs(db: Session, user_id: str) -> dict:
        """Get jobs categorized by status."""
        all_jobs = db.query(UserSavedJob).filter(UserSavedJob.user_id == user_id).all()
        
        categorized = {
            "all": all_jobs,
            "applied": [job for job in all_jobs if job.applied],
            "save_for_later": [job for job in all_jobs if job.save_for_later],
            "not_interested": [job for job in all_jobs if job.not_interested],
            "interview_scheduled": [job for job in all_jobs if job.interview_scheduled],
            "pending": [job for job in all_jobs if not any([
                job.applied, job.save_for_later, job.not_interested, job.interview_scheduled
            ])]
        }
        
        return categorized
    
    @staticmethod
    def add_search_history(
        db: Session, 
        user_id: str, 
        search_params: dict, 
        results_count: int = 0,
        search_duration: int = 0
    ):
        """Add a search to user's history."""
        search_history = SearchHistory(
            user_id=user_id,
            search_term=search_params.get('search_term') or '',  # Handle None values
            sites=search_params.get('site_name', []),
            location=search_params.get('location'),
            distance=search_params.get('distance'),
            job_type=search_params.get('job_type'),
            is_remote=search_params.get('is_remote'),
            results_wanted=search_params.get('results_wanted'),
            company_filter=search_params.get('company_filter'),
            results_count=results_count,
            search_duration=search_duration
        )
        
        db.add(search_history)
        db.commit()
        return search_history
    
    @staticmethod
    def get_search_history(
        db: Session, 
        user_id: str, 
        skip: int = 0, 
        limit: int = 50
    ) -> List[SearchHistory]:
        """Get user's search history."""
        return db.query(SearchHistory).filter(
            SearchHistory.user_id == user_id
        ).order_by(SearchHistory.searched_at.desc()).offset(skip).limit(limit).all()
    
    @staticmethod
    def create_saved_search(
        db: Session, 
        user_id: str, 
        search_create: SavedSearchCreate
    ) -> SavedSearch:
        """Create a saved search template."""
        db_search = SavedSearch(
            user_id=user_id,
            **search_create.dict()
        )
        
        db.add(db_search)
        db.commit()
        db.refresh(db_search)
        return db_search
    
    @staticmethod
    def get_saved_searches(db: Session, user_id: str) -> List[SavedSearch]:
        """Get user's saved searches."""
        return db.query(SavedSearch).filter(SavedSearch.user_id == user_id).all()
    
    @staticmethod
    def update_saved_search(
        db: Session, 
        user_id: str, 
        search_id: str, 
        search_update: SavedSearchUpdate
    ) -> Optional[SavedSearch]:
        """Update a saved search."""
        db_search = db.query(SavedSearch).filter(
            SavedSearch.user_id == user_id,
            SavedSearch.id == search_id
        ).first()
        
        if not db_search:
            return None
        
        update_data = search_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_search, field, value)
        
        db_search.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_search)
        return db_search
    
    @staticmethod
    def delete_saved_search(db: Session, user_id: str, search_id: str) -> bool:
        """Delete a saved search."""
        db_search = db.query(SavedSearch).filter(
            SavedSearch.user_id == user_id,
            SavedSearch.id == search_id
        ).first()
        
        if not db_search:
            return False
        
        db.delete(db_search)
        db.commit()
        return True

    # Autoscraping Configuration Methods
    @staticmethod
    def get_autoscraping_config(db: Session, user_id: str) -> Optional[UserAutoscrapingConfig]:
        """Get user's autoscraping configuration."""
        return db.query(UserAutoscrapingConfig).filter(
            UserAutoscrapingConfig.user_id == user_id
        ).first()

    @staticmethod
    def create_or_update_autoscraping_config(db: Session, user_id: str, config_data: dict) -> UserAutoscrapingConfig:
        """Create or update user's autoscraping configuration."""
        # Check if config already exists
        existing_config = db.query(UserAutoscrapingConfig).filter(
            UserAutoscrapingConfig.user_id == user_id
        ).first()

        if existing_config:
            # Update existing config
            for field, value in config_data.items():
                if hasattr(existing_config, field):
                    setattr(existing_config, field, value)
            existing_config.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing_config)
            return existing_config
        else:
            # Create new config
            new_config = UserAutoscrapingConfig(
                user_id=user_id,
                **config_data
            )
            db.add(new_config)
            db.commit()
            db.refresh(new_config)
            return new_config

    @staticmethod
    def get_autoscraping_config_dict(db: Session, user_id: str) -> dict:
        """Get user's autoscraping configuration as a dictionary with defaults."""
        config = UserService.get_autoscraping_config(db, user_id)

        if not config:
            # Return default configuration if none exists
            return {
                "enabled": False,
                "schedule_time": "02:00",
                "max_results": 100,
                "days_old": 7,
                "sites": ["indeed", "linkedin"],
                "search_terms": ["software engineer", "product manager"],
                "exclude_keywords": "",
                "location": "",
                "distance": 25,
                "companies": [],
                "min_relevance_score": 60,
                "ai_enabled": True,
                "ai_model": "gpt-4.1-nano",
                "ai_prompt": "Evaluate job relevance for product manager/engineer/software roles.\n\nRate as exactly one of: Highly Relevant, Somewhat Relevant, Somewhat Irrelevant, Irrelevant",
                "target_roles": "product manager, engineer, software developer",
                "email_enabled": True,
                "notification_email": "",
                "email_on_success": True,
                "email_on_failure": True
            }

        # Convert database model to dictionary
        return {
            "enabled": config.enabled,
            "schedule_time": config.schedule_time,
            "max_results": config.max_results,
            "days_old": config.days_old,
            "sites": config.sites or ["indeed", "linkedin"],
            "search_terms": config.search_terms or ["software engineer", "product manager"],
            "exclude_keywords": config.exclude_keywords or "",
            "location": config.location or "",
            "distance": config.distance,
            "companies": config.companies or [],
            "min_relevance_score": config.min_relevance_score,
            "ai_enabled": config.ai_enabled,
            "ai_model": config.ai_model,
            "ai_prompt": config.ai_prompt,
            "target_roles": config.target_roles,
            "email_enabled": config.email_enabled,
            "notification_email": config.notification_email or "",
            "email_on_success": config.email_on_success,
            "email_on_failure": config.email_on_failure
        }