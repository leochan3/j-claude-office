from fastapi import FastAPI, HTTPException, Request, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import pandas as pd
from jobspy import scrape_jobs
import uvicorn
import requests
import io
from datetime import datetime, timedelta, timezone
import re
import os
from dotenv import load_dotenv
import json
import asyncio
from openai import OpenAI
import uuid
from sqlalchemy.orm import Session
from database import create_tables, get_db, SessionLocal, User, UserPreference, UserSavedJob, SearchHistory, SavedSearch, TargetCompany, ScrapedJob, ScrapingRun, DailyJobReviewList, DailyJobReviewItem, FilteredJobView
from models import (
    UserCreate, UserLogin, UserResponse, Token,
    UserPreferencesCreate, UserPreferencesUpdate, UserPreferencesResponse,
    SaveJobRequest as NewSaveJobRequest, SavedJobUpdate, SavedJobResponse as NewSavedJobResponse,
    SearchHistoryResponse, SavedSearchCreate, SavedSearchUpdate, SavedSearchResponse,
    AuthenticatedJobSearchRequest,
    TargetCompanyCreate, TargetCompanyUpdate, TargetCompanyResponse,
    ScrapedJobResponse, ScrapedJobSearchRequest, ScrapedJobSearchResponse,
    ScrapingRunCreate, ScrapingRunResponse, BulkScrapingRequest,
    ComprehensiveTermsCreate, ComprehensiveTermsResponse,
    ScrapingDefaultsCreate, ScrapingDefaultsResponse,
    DailyJobReviewListResponse, DailyJobReviewListSummary, DailyJobReviewItemResponse,
    UpdateReviewItemRequest, CreateDailyReviewRequest,
    FilteredJobViewResponse, FilteredJobSearchRequest, FilteredJobSearchResponse, FilteredJobDateRange
)
from auth import authenticate_user, create_access_token, get_current_active_user, ACCESS_TOKEN_EXPIRE_MINUTES
from user_service import UserService
from job_scraper import job_scraper
import time

# Load environment variables
load_dotenv()

# Initialize OpenAI client with better error handling
openai_client = None
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-nano")

# Environment validation
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

if OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here":
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print("OpenAI client initialized for AI filtering")
    except Exception as e:
        print(f"Failed to initialize OpenAI client: {e}")
        openai_client = None
else:
    print("OpenAI API key not found or not configured. AI filtering will not be available.")
    print("To enable AI features, add your OpenAI API key to .env file")

# Initialize database
create_tables()

app = FastAPI(
    title="JobSpy API with User Accounts",
    description="Job scraping API with user authentication, preferences, and personalized job management",
    version="3.0.0"
)

# Utilities
def ensure_scraping_runs_progress_columns(db: Session) -> None:
    """Ensure production DB has required JSON columns; no-op if already present."""
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.bind)
        columns = [col['name'] for col in inspector.get_columns('scraping_runs')]

        statements = []
        if 'search_analytics' not in columns:
            statements.append("ALTER TABLE scraping_runs ADD COLUMN search_analytics JSON")
        # Refresh columns list only if needed isn't strictly necessary, we append both checks
        if 'current_progress' not in columns:
            statements.append("ALTER TABLE scraping_runs ADD COLUMN current_progress JSON")

        if statements:
            for stmt in statements:
                db.execute(text(stmt))
            db.commit()
    except Exception:
        # Silently continue; creation will fail again with a clear error if truly broken
        pass

# Add CORS middleware to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
try:
    # Mount static files for frontend
    app.mount("/static", StaticFiles(directory="../frontend"), name="static")
    app.mount("/files", StaticFiles(directory="../"), name="files")
    print("✅ Static file serving enabled")
except Exception as e:
    print(f"⚠️  Static files not available: {e}")

# Serve main frontend at root path
@app.get("/app")
async def serve_frontend():
    """Serve the main job search frontend"""
    try:
        return FileResponse("../frontend/index.html")
    except:
        return {"message": "Frontend not available", "api_docs": "/docs"}

@app.get("/daily-review")
async def serve_daily_review_frontend():
    """Serve the daily job review frontend"""
    try:
        return FileResponse("../frontend/daily-review.html")
    except:
        return {"message": "Daily review frontend not available", "api_docs": "/docs"}

@app.get("/database-viewer")
async def serve_database_viewer():
    """Serve the database viewer admin interface"""
    try:
        return FileResponse("../database_viewer.html")
    except:
        return {"message": "Database viewer not available", "api_docs": "/docs"}

@app.get("/scraping-interface")
async def serve_scraping_interface():
    """Serve the scraping interface admin interface"""
    try:
        return FileResponse("../scraping_interface.html")
    except:
        return {"message": "Scraping interface not available", "api_docs": "/docs"}

@app.get("/user-management")
async def serve_user_management():
    """Serve the user management admin interface"""
    try:
        return FileResponse("../user_management.html")
    except:
        return {"message": "User management interface not available", "api_docs": "/docs"}

@app.get("/test-dashboard")
async def serve_test_dashboard():
    """Serve the comprehensive test dashboard"""
    try:
        return FileResponse("../comprehensive_test_dashboard.html")
    except:
        return {"message": "Test dashboard not available", "api_docs": "/docs"}

@app.get("/test-admin-users")
async def serve_test_admin_users():
    """Serve the admin users diagnostic tool"""
    try:
        return FileResponse("../test-admin-users.html")
    except:
        return {"message": "Admin users test not available", "api_docs": "/docs"}

# Saved Jobs Storage Management
SAVED_JOBS_FILE = "saved_jobs.json"

class JobSearchRequest(BaseModel):
    site_name: Optional[List[str]] = ["indeed"]  # Default to Indeed only
    search_term: str  # Job title/role only
    company_filter: Optional[str] = None  # Company to filter for (None = no filter)
    location: Optional[str] = "USA"  # Comma-separated locations supported, e.g. "New York, Boston, Los Angeles"
    distance: Optional[int] = 50
    job_type: Optional[str] = None  # fulltime, parttime, internship, contract
    is_remote: Optional[bool] = None
    results_wanted: Optional[int] = 1000  # Match your Jupyter example
    hours_old: Optional[int] = 10000  # Match your Jupyter example
    country_indeed: Optional[str] = "USA"
    easy_apply: Optional[bool] = None
    description_format: Optional[str] = "markdown"
    offset: Optional[int] = 0
    verbose: Optional[int] = 2  # More verbose to help debug
    max_years_experience: Optional[int] = None  # New: filter jobs by max years of experience
    exclude_keywords: Optional[str] = None  # Comma-separated keywords to exclude from job titles

class JobSearchResponse(BaseModel):
    success: bool
    message: str
    job_count: int
    jobs: List[dict]
    search_params: dict
    timestamp: str

# AI Filtering Models
class AIFilterRequest(BaseModel):
    jobs: List[Dict[str, Any]]  # The jobs to filter
    analysis_prompt: str  # What to analyze (e.g., "summarize years of experience required")
    filter_criteria: Optional[str] = None  # How to filter (e.g., "filter jobs requiring 5+ years")

class AIAnalysisResult(BaseModel):
    job_id: int
    job_title: str
    job_company: str
    analysis_result: str  # AI's analysis of this job
    meets_criteria: Optional[bool] = None  # Whether it meets filter criteria

class AIFilterResponse(BaseModel):
    success: bool
    message: str
    original_count: int
    analyzed_jobs: List[AIAnalysisResult]
    filtered_count: Optional[int] = None
    filtered_jobs: Optional[List[Dict[str, Any]]] = None
    timestamp: str

# Saved Jobs Models
class SaveJobRequest(BaseModel):
    job_data: Dict[str, Any]  # The complete job object
    notes: Optional[str] = ""  # User notes about the job

class SavedJob(BaseModel):
    id: str
    job_data: Dict[str, Any]
    notes: str
    saved_at: str
    applied: bool = False  # New field to track application status
    applied_at: Optional[str] = None  # When the job was applied to
    save_for_later: bool = False  # New field for save for later
    not_interested: bool = False  # New field for not interested
    tags: List[str] = []

class SavedJobResponse(BaseModel):
    success: bool
    message: str
    saved_job: Optional[SavedJob] = None

class SavedJobsListResponse(BaseModel):
    success: bool
    message: str
    saved_jobs: List[SavedJob]
    total_count: int
    timestamp: str

# Saved Jobs Utility Functions (defined after models)
def load_saved_jobs() -> List[SavedJob]:
    """Load saved jobs from JSON file, skipping invalid records but logging errors."""
    try:
        if os.path.exists(SAVED_JOBS_FILE):
            with open(SAVED_JOBS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                saved_jobs = []
                errors = []
                for idx, job_data in enumerate(data):
                    # Handle backward compatibility for existing jobs without applied status
                    if 'applied' not in job_data:
                        job_data['applied'] = False
                    if 'applied_at' not in job_data:
                        job_data['applied_at'] = None
                    if 'save_for_later' not in job_data:
                        job_data['save_for_later'] = False
                    if 'not_interested' not in job_data:
                        job_data['not_interested'] = False
                    try:
                        saved_jobs.append(SavedJob(**job_data))
                    except Exception as e:
                        print(f"Error loading saved job at index {idx}: {e}\nData: {job_data}")
                        errors.append((idx, str(e)))
                if not saved_jobs and errors:
                    raise Exception(f"All saved jobs failed to load. Errors: {errors}")
                return saved_jobs
        return []
    except Exception as e:
        print(f"Error loading saved jobs: {e}")
        raise

def save_jobs_to_file(saved_jobs: List[SavedJob]):
    """Save jobs list to JSON file"""
    try:
        data = [job.dict() for job in saved_jobs]
        with open(SAVED_JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving jobs to file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save jobs: {str(e)}")

def job_already_saved(job_data: Dict[str, Any], saved_jobs: List[SavedJob]) -> bool:
    """Check if a job is already saved based on job URL or title+company combination"""
    job_url = job_data.get('job_url', '')
    job_title = job_data.get('title', '').lower().strip()
    job_company = job_data.get('company', '').lower().strip()
    
    for saved_job in saved_jobs:
        saved_url = saved_job.job_data.get('job_url', '')
        saved_title = saved_job.job_data.get('title', '').lower().strip()
        saved_company = saved_job.job_data.get('company', '').lower().strip()
        
        # Check by URL first (most reliable)
        if job_url and saved_url and job_url == saved_url:
            return True
            
        # Check by title + company combination
        if job_title and job_company and saved_title and saved_company:
            if job_title == saved_title and job_company == saved_company:
                return True
    
    return False

def extract_max_years_experience(description: str) -> Optional[int]:
    """Extract the maximum years of experience required from a job description using improved regex patterns."""
    if not description or not isinstance(description, str):
        return None
    patterns = [
        r"(\d+)\s*\+?\s*(?:years?|yrs?)\s*(?:and above|and up|or more|or greater|or higher|plus)?\s*(?:of)?\s*(?:relevant\s*)?(?:experience|exp|in|as)?",
        r"minimum\s*(\d+)\s*(?:years?|yrs?)",
        r"at least\s*(\d+)\s*(?:years?|yrs?)",
        r"(\d+)[-–]year"
    ]
    matches = []
    for pattern in patterns:
        for match in re.findall(pattern, description, re.IGNORECASE):
            try:
                matches.append(int(match))
            except Exception:
                continue
    if matches:
        return max(matches)
    return None

def filter_jobs_by_excluded_keywords(jobs_list: List[dict], exclude_keywords: str) -> List[dict]:
    """Filter out jobs that contain excluded keywords in their title."""
    if not exclude_keywords or not exclude_keywords.strip():
        return jobs_list
        
    # Parse comma-separated keywords and clean them
    keywords = [keyword.strip().lower() for keyword in exclude_keywords.split(',') if keyword.strip()]
    
    if not keywords:
        return jobs_list
    
    # Create expanded keyword list to handle common abbreviations
    expanded_keywords = []
    for keyword in keywords:
        expanded_keywords.append(keyword)
        # Add common abbreviations
        if keyword == 'senior':
            expanded_keywords.extend(['sr.', 'sr', 'snr'])
        elif keyword == 'junior':
            expanded_keywords.extend(['jr.', 'jr'])
        elif keyword == 'principal':
            expanded_keywords.extend(['princ', 'prin'])
        elif keyword == 'lead':
            expanded_keywords.extend(['tech lead', 'team lead'])
        elif keyword == 'manager':
            expanded_keywords.extend(['mgr', 'mgmt'])
    
    filtered_jobs = []
    excluded_count = 0
    
    for job in jobs_list:
        job_title = job.get('title', '').lower()
        should_exclude = False
        
        # Check if any excluded keyword is in the job title
        for keyword in expanded_keywords:
            if keyword in job_title:
                should_exclude = True
                excluded_count += 1
                break
        
        if not should_exclude:
            filtered_jobs.append(job)
    
    if excluded_count > 0:
        print(f"Excluded {excluded_count} jobs containing keywords: {', '.join(keywords)}")
    
    return filtered_jobs

@app.get("/")
async def root():
    return {
        "message": "JobSpy API with User Accounts and Local Job Database is running!", 
        "frontends": [
            "/app - Main Job Search Interface",
            "/admin - 🛠️ Unified Admin Dashboard (All admin tools in one place)",
            "/admin/migration - 🔄 Database Migration Dashboard (SQLite to PostgreSQL)",
            "/database-viewer - Database Viewer (Admin)",
            "/scraping-interface - Job Scraping Interface (Admin)",
            "/user-management - User Management (Admin)",
            "/test-dashboard - Comprehensive Test Dashboard"
        ],
        "endpoints": [
            "/docs - API documentation",
            "/auth/register - User registration",
            "/auth/login - User login",
            "/search-jobs - Search for jobs via external APIs (authenticated)",
            "/search-jobs-local - Search jobs from local database (authenticated)",
            "/search-jobs-local-public - Search jobs from local database (public)",
            "/ai-filter-jobs - AI-powered job analysis and filtering",
            "/user/preferences - Manage user preferences",
            "/user/saved-jobs - Manage saved jobs",
            "/user/search-history - View search history",
            "/user/saved-searches - Manage saved search templates",
            "/admin/target-companies - Manage companies for scraping (authenticated)",
            "/admin/scrape-bulk - Bulk scrape jobs for companies (authenticated)",
            "/admin/scraping-runs - View scraping run history (authenticated)",
            "/admin/database-stats - Database statistics (authenticated)",
            "/database-stats-public - Database statistics (public for admin UI)",
            "/target-companies-public - Get companies (public for admin UI)",
            "/scrape-bulk-public - Bulk scrape jobs (public for admin UI)",
            "/admin/migrate-data - Migrate local SQLite to production PostgreSQL",
            "/admin/migration-stats - Get migration statistics and preview",
            "/admin/local-db-stats - Get local database statistics",
            "/supported-sites - Get supported job sites",
            "/supported-countries - Get supported countries",
            "/health - Health check"
        ],
        "features": {
            "user_accounts": True,
            "personalized_preferences": True,
            "job_session_storage": True,
            "local_job_database": True,
            "proactive_job_scraping": True,
            "intelligent_deduplication": True,
            "ai_filtering": openai_client is not None,
            "ai_model": OPENAI_MODEL if openai_client else "Not configured"
        }
    }

@app.get("/supported-sites")
async def get_supported_sites():
    """Get list of supported job sites"""
    return {
        "supported_sites": [
            "linkedin",
            "indeed", 
            "glassdoor",
            "zip_recruiter", 
            "google",
            "bayt",
            "naukri"
        ],
        "notes": {
            "linkedin": "Global search, may require rate limiting",
            "indeed": "Best scraper with no rate limiting, supports many countries",
            "glassdoor": "Supports many countries, requires country_indeed parameter",
            "zip_recruiter": "US/Canada only",
            "google": "Requires very specific search syntax in google_search_term",
            "bayt": "International search, uses search_term only",
            "naukri": "India-focused job board"
        }
    }

# Authentication Endpoints
@app.post("/auth/register", response_model=UserResponse)
async def register_user(user_create: UserCreate, db: Session = Depends(get_db)):
    """Register a new user account"""
    return UserService.create_user(db, user_create)

@app.post("/auth/login", response_model=Token)
async def login_user(user_login: UserLogin, db: Session = Depends(get_db)):
    """Login and get access token"""
    user = authenticate_user(db, user_login.username, user_login.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """Get current user information"""
    return UserResponse.model_validate(current_user)

# Admin User Management Endpoints (Public for admin interfaces)
@app.get("/admin/users-public")
async def get_all_users_public(db: Session = Depends(get_db)):
    """Get all users without authentication (for admin frontend)"""
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        
        # Calculate 7 days ago for recent activity
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        user_list = []
        for user in users:
            # Get user statistics (total)
            saved_jobs_count = db.query(UserSavedJob).filter(UserSavedJob.user_id == user.id).count()
            search_history_count = db.query(SearchHistory).filter(SearchHistory.user_id == user.id).count()
            saved_searches_count = db.query(SavedSearch).filter(SavedSearch.user_id == user.id).count()
            
            # Get recent activity (last 7 days)
            recent_saved_jobs = db.query(UserSavedJob).filter(
                UserSavedJob.user_id == user.id,
                UserSavedJob.saved_at >= seven_days_ago
            ).count()
            
            recent_searches = db.query(SearchHistory).filter(
                SearchHistory.user_id == user.id,
                SearchHistory.searched_at >= seven_days_ago
            ).count()
            
            user_info = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None,
                "stats": {
                    "saved_jobs_count": saved_jobs_count,
                    "search_history_count": search_history_count,
                    "saved_searches_count": saved_searches_count,
                    "recent_saved_jobs_7d": recent_saved_jobs,
                    "recent_searches_7d": recent_searches
                }
            }
            user_list.append(user_info)
        
        return {
            "success": True,
            "users": user_list,
            "total_count": len(user_list),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting users: {str(e)}"
        )

@app.get("/admin/user-details-public/{user_id}")
async def get_user_details_public(user_id: str, db: Session = Depends(get_db)):
    """Get detailed user information without authentication (for admin frontend)"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user preferences
        preferences = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        
        # Get saved jobs with categories
        saved_jobs = db.query(UserSavedJob).filter(UserSavedJob.user_id == user_id).all()
        saved_jobs_by_status = {
            "pending": [job for job in saved_jobs if not any([job.applied, job.save_for_later, job.not_interested])],
            "applied": [job for job in saved_jobs if job.applied],
            "save_for_later": [job for job in saved_jobs if job.save_for_later],
            "not_interested": [job for job in saved_jobs if job.not_interested]
        }
        
        # Get recent search history (last 10)
        recent_searches = db.query(SearchHistory).filter(
            SearchHistory.user_id == user_id
        ).order_by(SearchHistory.searched_at.desc()).limit(10).all()
        
        # Get saved searches
        saved_searches = db.query(SavedSearch).filter(SavedSearch.user_id == user_id).all()
        
        user_details = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            },
            "preferences": {
                "default_sites": preferences.default_sites if preferences else ["indeed"],
                "default_location": preferences.default_location if preferences else "USA",
                "default_job_type": preferences.default_job_type if preferences else None,
                "default_remote": preferences.default_remote if preferences else None,
                "min_salary": preferences.min_salary if preferences else None,
                "max_salary": preferences.max_salary if preferences else None
            } if preferences else None,
            "saved_jobs": {
                "total": len(saved_jobs),
                "by_status": {
                    "pending": len(saved_jobs_by_status["pending"]),
                    "applied": len(saved_jobs_by_status["applied"]),
                    "save_for_later": len(saved_jobs_by_status["save_for_later"]),
                    "not_interested": len(saved_jobs_by_status["not_interested"])
                },
                "recent_jobs": [
                    {
                        "id": job.id,
                        "job_title": job.job_data.get("title", "N/A"),
                        "job_company": job.job_data.get("company", "N/A"),
                        "saved_at": job.saved_at.isoformat() if job.saved_at else None,
                        "applied": job.applied,
                        "save_for_later": job.save_for_later,
                        "not_interested": job.not_interested
                    } for job in saved_jobs[-5:]  # Last 5 saved jobs
                ]
            },
            "search_activity": {
                "total_searches": len(recent_searches),
                "recent_searches": [
                    {
                        "search_term": search.search_term,
                        "location": search.location,
                        "results_count": search.results_count,
                        "searched_at": search.searched_at.isoformat() if search.searched_at else None
                    } for search in recent_searches
                ]
            },
            "saved_searches": {
                "total": len(saved_searches),
                "searches": [
                    {
                        "id": search.id,
                        "name": search.name,
                        "search_term": search.search_term,
                        "location": search.location,
                        "is_alert_active": search.is_alert_active,
                        "created_at": search.created_at.isoformat() if search.created_at else None
                    } for search in saved_searches
                ]
            }
        }
        
        return {
            "success": True,
            "user_details": user_details,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting user details: {str(e)}"
        )

@app.get("/admin/users-stats-public")
async def get_users_stats_public(db: Session = Depends(get_db)):
    """Get user statistics without authentication (for admin frontend)"""
    try:
        # Total users
        total_users = db.query(User).count()
        active_users = db.query(User).filter(User.is_active == True).count()
        
        # Recent registrations (last 30 days)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        recent_registrations = db.query(User).filter(
            User.created_at >= thirty_days_ago
        ).count()
        
        # User activity stats
        users_with_saved_jobs = db.query(UserSavedJob.user_id).distinct().count()
        users_with_search_history = db.query(SearchHistory.user_id).distinct().count()
        
        # Most active users (by saved jobs)
        from sqlalchemy import func, text
        most_active_users = db.query(
            User.username,
            func.count(UserSavedJob.id).label('saved_jobs_count')
        ).join(UserSavedJob, User.id == UserSavedJob.user_id).group_by(
            User.id, User.username
        ).order_by(func.count(UserSavedJob.id).desc()).limit(5).all()
        
        # Database-specific date queries - check engine dialect
        is_postgres = str(db.bind.dialect.name) == 'postgresql'
        
        if is_postgres:
            # PostgreSQL syntax
            daily_registrations = db.execute(text("""
                SELECT created_at::date as date, COUNT(*) as count
                FROM users 
                WHERE created_at >= :thirty_days_ago
                GROUP BY created_at::date
                ORDER BY date DESC
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
            
            daily_searches = db.execute(text("""
                SELECT searched_at::date as date, COUNT(*) as count
                FROM search_history 
                WHERE searched_at >= :thirty_days_ago
                GROUP BY searched_at::date
                ORDER BY date DESC
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
            
            daily_saved_jobs = db.execute(text("""
                SELECT saved_at::date as date, COUNT(*) as count
                FROM user_saved_jobs 
                WHERE saved_at >= :thirty_days_ago
                GROUP BY saved_at::date
                ORDER BY date DESC
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        else:
            # SQLite syntax
            daily_registrations = db.execute(text("""
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM users 
                WHERE created_at >= :thirty_days_ago
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
            
            daily_searches = db.execute(text("""
                SELECT DATE(searched_at) as date, COUNT(*) as count
                FROM search_history 
                WHERE searched_at >= :thirty_days_ago
                GROUP BY DATE(searched_at)
                ORDER BY date DESC
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
            
            daily_saved_jobs = db.execute(text("""
                SELECT DATE(saved_at) as date, COUNT(*) as count
                FROM user_saved_jobs 
                WHERE saved_at >= :thirty_days_ago
                GROUP BY DATE(saved_at)
                ORDER BY date DESC
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        
        # Top search terms (last 30 days)
        top_search_terms = db.execute(text("""
            SELECT search_term, COUNT(*) as count
            FROM search_history 
            WHERE searched_at >= :thirty_days_ago
            AND search_term IS NOT NULL
            GROUP BY search_term
            ORDER BY count DESC
            LIMIT 10
        """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        
        # Top companies being saved (last 30 days) - database-specific JSON extraction
        if is_postgres:
            companies_query = """
                SELECT job_data->>'company' as company, COUNT(*) as count
                FROM user_saved_jobs
                WHERE saved_at >= :thirty_days_ago
                AND job_data->>'company' IS NOT NULL
                GROUP BY job_data->>'company'
                ORDER BY count DESC
                LIMIT 10
            """
        else:
            companies_query = """
                SELECT JSON_EXTRACT(job_data, '$.company') as company, COUNT(*) as count
                FROM user_saved_jobs
                WHERE saved_at >= :thirty_days_ago
                AND JSON_EXTRACT(job_data, '$.company') IS NOT NULL
                GROUP BY JSON_EXTRACT(job_data, '$.company')
                ORDER BY count DESC
                LIMIT 10
            """
        
        top_saved_companies = db.execute(text(companies_query), {"thirty_days_ago": thirty_days_ago}).fetchall()
        
        # Weekly usage patterns (searches by day of week) - database-specific
        if is_postgres:
            weekly_patterns = db.execute(text("""
                SELECT 
                    EXTRACT(DOW FROM searched_at)::integer as day_of_week,
                    COUNT(*) as count
                FROM search_history 
                WHERE searched_at >= :thirty_days_ago
                GROUP BY EXTRACT(DOW FROM searched_at)
                ORDER BY day_of_week
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        else:
            # SQLite uses strftime for day of week (0=Sunday)
            weekly_patterns = db.execute(text("""
                SELECT 
                    CAST(strftime('%w', searched_at) AS INTEGER) as day_of_week,
                    COUNT(*) as count
                FROM search_history 
                WHERE searched_at >= :thirty_days_ago
                GROUP BY strftime('%w', searched_at)
                ORDER BY day_of_week
            """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        
        # Search-to-save conversion rate
        total_searches_30d = db.query(SearchHistory).filter(
            SearchHistory.searched_at >= thirty_days_ago
        ).count()
        total_saves_30d = db.query(UserSavedJob).filter(
            UserSavedJob.saved_at >= thirty_days_ago
        ).count()
        
        conversion_rate = (total_saves_30d / total_searches_30d * 100) if total_searches_30d > 0 else 0
        
        # Convert to list of dicts for JSON response
        daily_reg_data = [{"date": str(row.date), "count": row.count} for row in daily_registrations]
        daily_search_data = [{"date": str(row.date), "count": row.count} for row in daily_searches]
        daily_jobs_data = [{"date": str(row.date), "count": row.count} for row in daily_saved_jobs]
        top_terms_data = [{"term": row.search_term, "count": row.count} for row in top_search_terms]
        top_companies_data = [{"company": row.company, "count": row.count} for row in top_saved_companies]
        
        # Convert day of week numbers to names
        day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        weekly_data = [
            {"day": day_names[int(row.day_of_week)], "count": row.count} 
            for row in weekly_patterns
        ]
        
        return {
            "success": True,
            "stats": {
                "total_users": total_users,
                "active_users": active_users,
                "recent_registrations": recent_registrations,
                "users_with_saved_jobs": users_with_saved_jobs,
                "users_with_search_history": users_with_search_history,
                "daily_registrations": daily_reg_data,
                "daily_searches": daily_search_data,
                "daily_saved_jobs": daily_jobs_data,
                "top_search_terms": top_terms_data,
                "top_saved_companies": top_companies_data,
                "weekly_usage_patterns": weekly_data,
                "conversion_rate": round(conversion_rate, 2),
                "total_searches_30d": total_searches_30d,
                "total_saves_30d": total_saves_30d,
                "most_active_users": [
                    {"username": username, "saved_jobs_count": count}
                    for username, count in most_active_users
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting user stats: {str(e)}"
        )

# User Preferences Endpoints
@app.get("/user/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user preferences"""
    preferences = UserService.get_user_preferences(db, current_user.id)
    if not preferences:
        raise HTTPException(status_code=404, detail="User preferences not found")
    return UserPreferencesResponse.from_orm(preferences)

@app.put("/user/preferences", response_model=UserPreferencesResponse)
async def update_user_preferences(
    preferences_update: UserPreferencesUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update user preferences"""
    updated_preferences = UserService.update_user_preferences(
        db, current_user.id, preferences_update
    )
    return UserPreferencesResponse.from_orm(updated_preferences)

@app.get("/supported-countries")
async def get_supported_countries():
    """Get list of supported countries for Indeed/Glassdoor"""
    countries = [
        "Argentina", "Australia", "Austria", "Bahrain", "Belgium", "Brazil", 
        "Canada", "Chile", "China", "Colombia", "Costa Rica", "Czech Republic",
        "Denmark", "Ecuador", "Egypt", "Finland", "France", "Germany", "Greece", 
        "Hong Kong", "Hungary", "India", "Indonesia", "Ireland", "Israel", "Italy",
        "Japan", "Kuwait", "Luxembourg", "Malaysia", "Mexico", "Morocco", 
        "Netherlands", "New Zealand", "Nigeria", "Norway", "Oman", "Pakistan",
        "Panama", "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Romania",
        "Saudi Arabia", "Singapore", "South Africa", "South Korea", "Spain", 
        "Sweden", "Switzerland", "Taiwan", "Thailand", "Turkey", "Ukraine",
        "United Arab Emirates", "UK", "USA", "Uruguay", "Venezuela", "Vietnam"
    ]
    return {
        "supported_countries": countries,
        "note": "These countries are supported for Indeed and Glassdoor. LinkedIn searches globally, ZipRecruiter supports US/Canada only."
    }


def filter_jobs_by_company(jobs_df, company_filter):
    """A simplified, stricter filter for companies."""
    if not company_filter or jobs_df is None or jobs_df.empty:
        return jobs_df

    company_filter_clean = company_filter.lower().strip()
    
    print("--- Simplified Company Filtering ---")
    print(f"Filtering for companies that start with: '{company_filter_clean}'")

    # This prevents errors if the 'company' column contains non-string data
    jobs_df['company'] = jobs_df['company'].astype(str)

    mask = jobs_df['company'].str.lower().str.strip().str.startswith(company_filter_clean, na=False)
    
    filtered_df = jobs_df[mask].copy()
    
    print(f"Before: {len(jobs_df)} jobs. After: {len(filtered_df)} jobs.")
    print("---------------------------------")
    return filtered_df

def convert_job_search_to_local_search(
    effective_request: JobSearchRequest,
    job_titles: List[str] = None,
    companies: List[str] = None,
    locations: List[str] = None
) -> ScrapedJobSearchRequest:
    """Convert JobSearchRequest to ScrapedJobSearchRequest for local database search."""
    
    # Convert hours_old to days_old
    days_old = None
    if effective_request.hours_old:
        days_old = max(1, effective_request.hours_old // 24)  # Convert hours to days, minimum 1 day
    
    # Use the first job title if multiple provided, or the original search_term
    search_term = job_titles[0] if job_titles else effective_request.search_term
    
    return ScrapedJobSearchRequest(
        search_term=search_term if search_term and search_term.strip() else None,
        company_names=companies if companies else None,
        locations=locations if locations else None,
        job_types=[effective_request.job_type] if effective_request.job_type else None,
        is_remote=effective_request.is_remote,
        min_salary=None,  # JobSearchRequest doesn't have salary filters
        max_salary=None,
        max_experience_years=effective_request.max_years_experience,
        sites=effective_request.site_name,
        days_old=days_old or 30,  # Default to 30 days if not specified
        limit=effective_request.results_wanted or 10000,
        offset=getattr(effective_request, 'offset', 0)
    )

async def search_single_company(search_term: str, company: str, search_params: dict):
    """Search for jobs for a single company"""
    # Create search term with company
    actual_search_term = f"{search_term} {company}".strip()
    
    # Update search params with company-specific term
    company_search_params = search_params.copy()
    company_search_params["search_term"] = actual_search_term
    
    print(f"Searching for '{search_term}' at '{company}' with term: '{actual_search_term}'")
    
    try:
        # Call JobSpy for this company
        jobs_df = scrape_jobs(**company_search_params)
        
        if jobs_df is not None and not jobs_df.empty:
            print(f"Found {len(jobs_df)} jobs for company '{company}' before filtering")
            
            # Apply strict company filtering
            jobs_df = filter_jobs_by_company(jobs_df, company)
            
            print(f"Found {len(jobs_df)} jobs for company '{company}' after filtering")
            return jobs_df
        else:
            print(f"No jobs found for company '{company}'")
            return pd.DataFrame()
            
    except Exception as e:
        print(f"Error searching for company '{company}': {str(e)}")
        return pd.DataFrame()


@app.post("/search-jobs", response_model=JobSearchResponse)
async def search_jobs(
    request: AuthenticatedJobSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Search for jobs from local database with user preferences and search history tracking."""
    try:
        start_time = time.time()
        
        # Get user preferences to fill in missing values
        user_preferences = UserService.get_user_preferences(db, current_user.id)
        
        # Apply user preferences as defaults for missing values
        effective_request = JobSearchRequest(
            site_name=request.site_name or (user_preferences.default_sites if user_preferences else ["indeed"]),
            search_term=request.search_term,
            company_filter=request.company_filter or (user_preferences.default_company_filter if user_preferences else None),
            location=request.location or (user_preferences.default_location if user_preferences else "USA"),
            distance=request.distance or (user_preferences.default_distance if user_preferences else 50),
            job_type=request.job_type or (user_preferences.default_job_type if user_preferences else None),
            is_remote=request.is_remote if request.is_remote is not None else (user_preferences.default_remote if user_preferences else None),
            results_wanted=request.results_wanted or (user_preferences.default_results_wanted if user_preferences else 100),
            hours_old=request.hours_old or (user_preferences.default_hours_old if user_preferences else 168),
            country_indeed=request.country_indeed or (user_preferences.default_country if user_preferences else "USA"),
            max_years_experience=request.max_years_experience or (user_preferences.default_max_experience if user_preferences else None),
            exclude_keywords=request.exclude_keywords or (user_preferences.default_exclude_keywords if user_preferences else None)
        )
        
        # Parse multiple job titles (comma-separated)
        job_titles = [t.strip() for t in effective_request.search_term.split(',') if t.strip()]
        # Parse multiple companies (comma-separated)
        companies = []
        if effective_request.company_filter and effective_request.company_filter.strip():
            companies = [company.strip() for company in effective_request.company_filter.split(',') if company.strip()]
        # Parse multiple locations (comma-separated)
        locations = [loc.strip() for loc in effective_request.location.split(',') if loc.strip()] if effective_request.location else ["USA"]
        
        # Convert to local search request
        local_search_request = convert_job_search_to_local_search(
            effective_request, job_titles, companies, locations
        )
        
        print(f"🔍 Searching local database with: {local_search_request.model_dump()}")
        
        # Search local database
        jobs, total_count = job_scraper.search_local_jobs(
            db=db,
            search_term=local_search_request.search_term,
            company_names=local_search_request.company_names,
            locations=local_search_request.locations,
            job_types=local_search_request.job_types,
            is_remote=local_search_request.is_remote,
            min_salary=local_search_request.min_salary,
            max_salary=local_search_request.max_salary,
            max_experience_years=local_search_request.max_experience_years,
            sites=local_search_request.sites,
            days_old=local_search_request.days_old,
            limit=local_search_request.limit,
            offset=local_search_request.offset
        )
        
        print(f"📊 Found {len(jobs)} jobs from local database (total: {total_count})")
        
        # Convert to format expected by frontend  
        if jobs:
            jobs_list = []
            for job in jobs:
                job_dict = {
                    'title': job.title,
                    'company': job.company,
                    'location': job.location,
                    'job_url': job.job_url,
                    'description': job.description,
                    'job_type': job.job_type,
                    'is_remote': job.is_remote,
                    'min_amount': job.min_amount,
                    'max_amount': job.max_amount,
                    'interval': job.salary_interval,  # Fix: JobSpy uses 'interval' not 'salary_interval'
                    'currency': job.currency,
                    'date_posted': job.date_posted,  # Fix: Keep as datetime object for frontend compatibility
                    'site': job.site,
                    'min_experience_years': job.min_experience_years,
                    'max_experience_years': job.max_experience_years
                }
                jobs_list.append(job_dict)
            # Filter by excluded keywords if set
            if effective_request.exclude_keywords:
                jobs_list = filter_jobs_by_excluded_keywords(jobs_list, effective_request.exclude_keywords)
            
            filter_info = ""
            if companies:
                if len(companies) == 1:
                    filter_info = f" (company: {companies[0]})"
                else:
                    filter_info = f" (companies: {', '.join(companies)})"
            if len(job_titles) > 1:
                filter_info += f" (titles: {', '.join(job_titles)})"
            if len(locations) > 1:
                filter_info += f" (locations: {', '.join(locations)})"
            if effective_request.max_years_experience is not None:
                filter_info += f" (max YOE: {effective_request.max_years_experience})"
            
            # Save search to history if requested
            search_duration = int(time.time() - start_time)
            if getattr(request, 'save_search', True):  # Default to saving search history
                UserService.add_search_history(
                    db, current_user.id,
                    effective_request.dict(),
                    len(jobs_list),
                    search_duration
                )
            
            # Prepare search params for response
            search_params = {
                "site_name": effective_request.site_name,
                "search_term": effective_request.search_term,
                "company_filter": effective_request.company_filter,
                "location": effective_request.location,
                "distance": effective_request.distance,
                "job_type": effective_request.job_type,
                "is_remote": effective_request.is_remote,
                "results_wanted": effective_request.results_wanted,
                "hours_old": effective_request.hours_old,
                "country_indeed": effective_request.country_indeed,
                "max_years_experience": effective_request.max_years_experience,
                "exclude_keywords": effective_request.exclude_keywords
            }
            
            return JobSearchResponse(
                success=True,
                message=f"Found {len(jobs_list)} jobs from local database in {time.time() - start_time:.2f} seconds{filter_info}",
                job_count=len(jobs_list),
                jobs=jobs_list,
                search_params=search_params,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        else:
            filter_info = ""
            if companies:
                if len(companies) == 1:
                    filter_info = f" for company '{companies[0]}'"
                else:
                    filter_info = f" for companies: {', '.join(companies)}"
            if len(job_titles) > 1:
                filter_info += f" for titles: {', '.join(job_titles)}"
            if len(locations) > 1:
                filter_info += f" for locations: {', '.join(locations)}"
            # Still save search to history even if no results
            search_duration = int(time.time() - start_time)
            if getattr(request, 'save_search', True):
                UserService.add_search_history(
                    db, current_user.id,
                    effective_request.dict(),
                    0,
                    search_duration
                )
            
            # Prepare search params for response
            search_params = {
                "site_name": effective_request.site_name,
                "search_term": effective_request.search_term,
                "company_filter": effective_request.company_filter,
                "location": effective_request.location,
                "distance": effective_request.distance,
                "job_type": effective_request.job_type,
                "is_remote": effective_request.is_remote,
                "results_wanted": effective_request.results_wanted,
                "hours_old": effective_request.hours_old,
                "country_indeed": effective_request.country_indeed,
                "max_years_experience": effective_request.max_years_experience,
                "exclude_keywords": effective_request.exclude_keywords
            }
            
            return JobSearchResponse(
                success=True,
                message=f"No jobs found matching your criteria in local database{filter_info}",
                job_count=0,
                jobs=[],
                search_params=search_params,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error scraping jobs: {str(e)}"
        )

@app.post("/search-jobs-public", response_model=JobSearchResponse)
async def search_jobs_public(request: JobSearchRequest, db: Session = Depends(get_db)):
    """Search for jobs from local database without authentication (public endpoint)."""
    try:
        start_time = time.time()
        
        # Use the request as-is since it already has default values
        effective_request = request
        
        # Parse multiple job titles (comma-separated)
        job_titles = [t.strip() for t in effective_request.search_term.split(',') if t.strip()]
        # Parse multiple companies (comma-separated)
        companies = []
        if effective_request.company_filter and effective_request.company_filter.strip():
            companies = [company.strip() for company in effective_request.company_filter.split(',') if company.strip()]
        # Parse multiple locations (comma-separated)
        locations = [loc.strip() for loc in effective_request.location.split(',') if loc.strip()] if effective_request.location else ["USA"]
        
        # Convert to local search request
        local_search_request = convert_job_search_to_local_search(
            effective_request, job_titles, companies, locations
        )
        
        print(f"🔍 PUBLIC SEARCH - Searching local database with: {local_search_request.model_dump()}")
        print(f"🗄️ Database session type: {type(db)}")
        
        # Search local database
        try:
            print(f"🔍 About to call job_scraper.search_local_jobs...")
            print(f"🔍 job_scraper type: {type(job_scraper)}")
            print(f"🔍 job_scraper.search_local_jobs type: {type(job_scraper.search_local_jobs)}")
            jobs, total_count = job_scraper.search_local_jobs(
                db=db,
                search_term=local_search_request.search_term,
                company_names=local_search_request.company_names,
                locations=local_search_request.locations,
                job_types=local_search_request.job_types,
                is_remote=local_search_request.is_remote,
                min_salary=local_search_request.min_salary,
                max_salary=local_search_request.max_salary,
                max_experience_years=local_search_request.max_experience_years,
                sites=local_search_request.sites,
                days_old=local_search_request.days_old,
                limit=local_search_request.limit,
                offset=local_search_request.offset
            )
            print(f"📊 Found {len(jobs)} jobs from local database (total: {total_count})")
        except Exception as e:
            print(f"❌ ERROR in search_local_jobs: {str(e)}")
            import traceback
            print(f"❌ TRACEBACK: {traceback.format_exc()}")
            jobs, total_count = [], 0
        
        # Convert to format expected by frontend  
        if jobs:
            jobs_list = []
            for job in jobs:
                job_dict = {
                    'title': job.title,
                    'company': job.company,
                    'location': job.location,
                    'job_url': job.job_url,
                    'description': job.description,
                    'job_type': job.job_type,
                    'is_remote': job.is_remote,
                    'min_amount': job.min_amount,
                    'max_amount': job.max_amount,
                    'interval': job.salary_interval,  # Fix: JobSpy uses 'interval' not 'salary_interval'
                    'currency': job.currency,
                    'date_posted': job.date_posted,  # Fix: Keep as datetime object for frontend compatibility
                    'site': job.site,
                    'min_experience_years': job.min_experience_years,
                    'max_experience_years': job.max_experience_years
                }
                jobs_list.append(job_dict)
            
            # Filter by excluded keywords if set
            if effective_request.exclude_keywords:
                jobs_list = filter_jobs_by_excluded_keywords(jobs_list, effective_request.exclude_keywords)
            
            filter_info = ""
            if companies:
                if len(companies) == 1:
                    filter_info = f" (company: {companies[0]})"
                else:
                    filter_info = f" (companies: {', '.join(companies)})"
            if len(job_titles) > 1:
                filter_info += f" (titles: {', '.join(job_titles)})"
            if len(locations) > 1:
                filter_info += f" (locations: {', '.join(locations)})"
            if effective_request.max_years_experience is not None:
                filter_info += f" (max YOE: {effective_request.max_years_experience})"
            
            # Prepare search params for response
            search_params = {
                "site_name": effective_request.site_name,
                "search_term": effective_request.search_term,
                "company_filter": effective_request.company_filter,
                "location": effective_request.location,
                "distance": effective_request.distance,
                "job_type": effective_request.job_type,
                "is_remote": effective_request.is_remote,
                "results_wanted": effective_request.results_wanted,
                "hours_old": effective_request.hours_old,
                "country_indeed": effective_request.country_indeed,
                "max_years_experience": effective_request.max_years_experience,
                "exclude_keywords": effective_request.exclude_keywords
            }
            
            return JobSearchResponse(
                success=True,
                message=f"Found {len(jobs_list)} jobs from local database in {time.time() - start_time:.2f} seconds{filter_info}",
                job_count=len(jobs_list),
                jobs=jobs_list,
                search_params=search_params,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        else:
            filter_info = ""
            if companies:
                if len(companies) == 1:
                    filter_info = f" for company '{companies[0]}'"
                else:
                    filter_info = f" for companies: {', '.join(companies)}"
            if len(job_titles) > 1:
                filter_info += f" for titles: {', '.join(job_titles)}"
            if len(locations) > 1:
                filter_info += f" for locations: {', '.join(locations)}"
            
            # Prepare search params for response
            search_params = {
                "site_name": effective_request.site_name,
                "search_term": effective_request.search_term,
                "company_filter": effective_request.company_filter,
                "location": effective_request.location,
                "distance": effective_request.distance,
                "job_type": effective_request.job_type,
                "is_remote": effective_request.is_remote,
                "results_wanted": effective_request.results_wanted,
                "hours_old": effective_request.hours_old,
                "country_indeed": effective_request.country_indeed,
                "max_years_experience": effective_request.max_years_experience,
                "exclude_keywords": effective_request.exclude_keywords
            }
            
            return JobSearchResponse(
                success=True,
                message=f"No jobs found matching your criteria in local database{filter_info}",
                job_count=0,
                jobs=[],
                search_params=search_params,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error scraping jobs: {str(e)}"
        )

@app.post("/generate-resume-pdf")
async def generate_resume_pdf(request: dict):
    """Generate PDF from LaTeX code using Overleaf's reliable compilation service"""
    try:
        import base64
        import urllib.parse
        
        latex_code = request.get('latex_code', '')
        if not latex_code:
            raise HTTPException(status_code=400, detail="LaTeX code is required")
        
        print("🚀 Creating Overleaf compilation link...")
        
        # Method 1: Create Overleaf link with base64 encoded LaTeX
        try:
            # Encode LaTeX as base64 for Overleaf
            latex_bytes = latex_code.encode('utf-8')
            latex_base64 = base64.b64encode(latex_bytes).decode('utf-8')
            
            # Create Overleaf data URL
            data_url = f"data:application/x-tex;base64,{latex_base64}"
            
            # Create Overleaf link
            overleaf_url = f"https://www.overleaf.com/docs?snip_uri={urllib.parse.quote(data_url)}"
            
            print(f"✅ Created Overleaf link: {overleaf_url}")
            
            return {
                "success": True,
                "message": "LaTeX code ready for compilation in Overleaf",
                "compilation_method": "overleaf_online",
                "overleaf_url": overleaf_url,
                "instructions": [
                    "1. Click the Overleaf link above",
                    "2. Wait for the document to load in Overleaf",
                    "3. Click 'Recompile' to generate the PDF",
                    "4. Download the PDF from Overleaf",
                    "5. The document will be automatically saved to your Overleaf account"
                ],
                "latex_code_length": len(latex_code),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Base64 encoding failed: {str(e)}")
            # Fallback to URL-encoded method
            pass
        
        # Method 2: Create Overleaf link with URL-encoded LaTeX (fallback)
        try:
            # URL encode the LaTeX code
            encoded_latex = urllib.parse.quote(latex_code)
            
            # Create Overleaf link with encoded snippet
            overleaf_url = f"https://www.overleaf.com/docs?encoded_snip={encoded_latex}"
            
            print(f"✅ Created Overleaf link (URL-encoded): {overleaf_url}")
            
            return {
                "success": True,
                "message": "LaTeX code ready for compilation in Overleaf",
                "compilation_method": "overleaf_url_encoded",
                "overleaf_url": overleaf_url,
                "instructions": [
                    "1. Click the Overleaf link above",
                    "2. Wait for the document to load in Overleaf", 
                    "3. Click 'Recompile' to generate the PDF",
                    "4. Download the PDF from Overleaf",
                    "5. The document will be automatically saved to your Overleaf account"
                ],
                "latex_code_length": len(latex_code),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ URL encoding failed: {str(e)}")
            # Final fallback: return LaTeX code for manual compilation
            pass
        
        # Method 3: Return LaTeX code for manual compilation (final fallback)
        print("📄 Returning LaTeX code for manual compilation")
        
        return {
            "success": True,
            "message": "LaTeX code generated successfully - compile manually",
            "compilation_method": "manual_compilation",
            "latex_code": latex_code,
            "instructions": [
                "1. Copy the LaTeX code below",
                "2. Go to https://www.overleaf.com",
                "3. Create a new project",
                "4. Paste the LaTeX code",
                "5. Click 'Recompile' to generate the PDF",
                "6. Download the PDF"
            ],
            "latex_code_length": len(latex_code),
            "timestamp": datetime.now().isoformat()
        }
            
    except Exception as e:
        print(f"💥 Unexpected error in PDF generation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating PDF: {str(e)}. Please try the manual compilation method."
        )

# AI Filtering Functions
async def analyze_job_with_ai(job: Dict[str, Any], analysis_prompt: str, job_id: int, client) -> AIAnalysisResult:
    """Analyze a single job using OpenAI"""
    
    # Prepare job information for analysis
    job_info = {
        "title": job.get("title", "N/A"),
        "company": job.get("company", "N/A"),
        "location": job.get("location", "N/A"),
        "description": job.get("description", "N/A")[:5000],  # Increased limit for better analysis
        "job_type": job.get("job_type", "N/A"),
        "salary_min": job.get("min_amount", "N/A"),
        "salary_max": job.get("max_amount", "N/A"),
        "date_posted": job.get("date_posted", "N/A")
    }
    
    prompt = f"""
    Analyze this job posting based on the following request: "{analysis_prompt}"
    
    Job Information:
    - Title: {job_info['title']}
    - Company: {job_info['company']}
    - Location: {job_info['location']}
    - Type: {job_info['job_type']}
    - Salary: ${job_info['salary_min']} - ${job_info['salary_max']}
    - Posted: {job_info['date_posted']}
    - Description: {job_info['description']}
    
    IMPORTANT: Read the ENTIRE job description carefully. Look for experience requirements in sections like:
    - "Requirements", "Qualifications", "What we're looking for"
    - "Minimum X years", "X+ years", "At least X years", "X years of experience"
    - Any mention of "experience", "background", "expertise"
    
    If asking about years of experience:
    - Extract the MINIMUM number mentioned (e.g., "5" from "5+ years")
    - If multiple numbers are mentioned, use the minimum required
    - If no specific number is found, state "No specific experience requirement found"
    - Do NOT return 0 unless explicitly stated as "0 years" or "no experience required"
    
    Response format: Provide only the direct answer to the analysis request.
    """
    
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.1
        )
        
        analysis_result = response.choices[0].message.content.strip()
        
        return AIAnalysisResult(
            job_id=job_id,
            job_title=job_info['title'],
            job_company=job_info['company'],
            analysis_result=analysis_result
        )
    except Exception as e:
        return AIAnalysisResult(
            job_id=job_id,
            job_title=job_info['title'],
            job_company=job_info['company'],
            analysis_result=f"Analysis failed: {str(e)}"
        )

async def filter_jobs_with_ai(analyzed_jobs: List[AIAnalysisResult], filter_criteria: str, client) -> List[AIAnalysisResult]:
    """Apply AI filtering to analyzed jobs"""
    if not filter_criteria:
        # If no filtering criteria, return all jobs
        for job in analyzed_jobs:
            job.meets_criteria = True
        return analyzed_jobs
    
    # Prepare all analysis results for batch filtering
    analyses_text = "\n".join([
        f"Job {job.job_id}: {job.job_title} at {job.job_company} - Analysis: {job.analysis_result}"
        for job in analyzed_jobs
    ])
    
    prompt = f"""
    Based on the following job analyses, determine which jobs meet this criteria: "{filter_criteria}"
    
    Job Analyses:
    {analyses_text}
    
    For each job, respond with ONLY the job ID followed by either "YES" or "NO".
    Format: "Job 1: YES" or "Job 1: NO"
    
    Example response:
    Job 1: YES
    Job 2: NO
    Job 3: YES
    """
    
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1
        )
        
        filter_result = response.choices[0].message.content.strip()
        
        # Parse the filtering results
        filter_decisions = {}
        for line in filter_result.split('\n'):
            if ':' in line and ('YES' in line or 'NO' in line):
                try:
                    job_part, decision = line.split(':', 1)
                    job_id = int(job_part.strip().replace('Job', '').strip())
                    meets_criteria = 'YES' in decision.upper()
                    filter_decisions[job_id] = meets_criteria
                except:
                    continue
        
        # Apply filtering decisions
        for job in analyzed_jobs:
            job.meets_criteria = filter_decisions.get(job.job_id, False)
        
        return analyzed_jobs
        
    except Exception as e:
        # If filtering fails, mark all as not meeting criteria
        for job in analyzed_jobs:
            job.meets_criteria = False
        return analyzed_jobs

@app.post("/ai-filter-jobs", response_model=AIFilterResponse)
async def ai_filter_jobs(request: AIFilterRequest, http_request: Request):
    """Apply AI-powered analysis and filtering to job search results"""
    try:
        # Get API key from request header or fallback to environment
        api_key = http_request.headers.get("X-OpenAI-API-Key") or OPENAI_API_KEY
        
        if not api_key:
            raise HTTPException(
                status_code=400, 
                detail="OpenAI API key is required. Please provide it in the X-OpenAI-API-Key header or configure OPENAI_API_KEY in your environment."
            )
        
        # Initialize OpenAI client with the provided API key
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        start_time = datetime.now(timezone.utc)
        original_count = len(request.jobs)
        
        if original_count == 0:
            return AIFilterResponse(
                success=True,
                message="No jobs provided for analysis",
                original_count=0,
                analyzed_jobs=[],
                timestamp=start_time.isoformat()
            )
        
        print(f"Starting AI analysis of {original_count} jobs...")
        print(f"Analysis prompt: {request.analysis_prompt}")
        if request.filter_criteria:
            print(f"Filter criteria: {request.filter_criteria}")
        
        # Step 1: Analyze each job with AI
        analysis_tasks = [
            analyze_job_with_ai(job, request.analysis_prompt, i, client)
            for i, job in enumerate(request.jobs)
        ]
        
        # Process in batches to avoid rate limits (adjust batch size as needed)
        batch_size = 5
        analyzed_jobs = []
        
        for i in range(0, len(analysis_tasks), batch_size):
            batch = analysis_tasks[i:i + batch_size]
            batch_results = await asyncio.gather(*batch)
            analyzed_jobs.extend(batch_results)
            
            # Small delay between batches to respect rate limits
            if i + batch_size < len(analysis_tasks):
                await asyncio.sleep(1)
        
        print(f"Completed analysis of {len(analyzed_jobs)} jobs")
        
        # Step 2: Apply filtering if criteria provided
        filtered_jobs = None
        filtered_count = None
        
        if request.filter_criteria:
            print("Applying AI filtering...")
            analyzed_jobs = await filter_jobs_with_ai(analyzed_jobs, request.filter_criteria, client)
            
            # Extract jobs that meet criteria
            jobs_meeting_criteria = [
                job for job in analyzed_jobs if job.meets_criteria
            ]
            
            if jobs_meeting_criteria:
                filtered_jobs = [
                    request.jobs[job.job_id] for job in jobs_meeting_criteria
                ]
                filtered_count = len(filtered_jobs)
            else:
                filtered_jobs = []
                filtered_count = 0
            
            print(f"Filtered to {filtered_count} jobs meeting criteria")
        
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        
        message = f"Successfully analyzed {original_count} jobs in {duration:.1f} seconds"
        if filtered_count is not None:
            message += f" and filtered to {filtered_count} jobs"
        
        return AIFilterResponse(
            success=True,
            message=message,
            original_count=original_count,
            analyzed_jobs=analyzed_jobs,
            filtered_count=filtered_count,
            filtered_jobs=filtered_jobs,
            timestamp=end_time.isoformat()
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error in AI filtering: {str(e)}"
        )

# User Saved Jobs Endpoints

@app.post("/user/save-job")
async def save_job_for_user(
    request: NewSaveJobRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Save a job for the authenticated user"""
    saved_job = UserService.save_job(db, current_user.id, request)
    return {
        "success": True,
        "message": "Job saved successfully",
        "saved_job": NewSavedJobResponse.from_orm(saved_job)
    }

@app.get("/user/saved-jobs")
async def get_user_saved_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get saved jobs for the authenticated user"""
    saved_jobs = UserService.get_saved_jobs(db, current_user.id, skip, limit)
    return {
        "success": True,
        "message": f"Retrieved {len(saved_jobs)} saved jobs",
        "saved_jobs": [NewSavedJobResponse.from_orm(job) for job in saved_jobs],
        "total_count": len(saved_jobs),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/user/saved-jobs/categorized")
async def get_user_saved_jobs_categorized(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get saved jobs categorized by status for the authenticated user"""
    categorized_jobs = UserService.get_categorized_jobs(db, current_user.id)
    
    # Convert to response format
    categorized_response = {}
    for category, jobs in categorized_jobs.items():
        categorized_response[category] = [NewSavedJobResponse.from_orm(job) for job in jobs]
    
    return {
        "success": True,
        "message": f"Retrieved categorized saved jobs",
        "saved_jobs": categorized_response,
        "counts": {category: len(jobs) for category, jobs in categorized_jobs.items()},
        "timestamp": datetime.now().isoformat()
    }

@app.put("/user/saved-job/{job_id}")
async def update_user_saved_job(
    job_id: str,
    job_update: SavedJobUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update a saved job for the authenticated user"""
    updated_job = UserService.update_saved_job(db, current_user.id, job_id, job_update)
    if not updated_job:
        raise HTTPException(status_code=404, detail="Saved job not found")
    return {
        "success": True,
        "message": "Job updated successfully",
        "saved_job": NewSavedJobResponse.from_orm(updated_job)
    }

@app.delete("/user/saved-job/{job_id}")
async def delete_user_saved_job(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a saved job for the authenticated user"""
    deleted = UserService.delete_saved_job(db, current_user.id, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved job not found")
    return {
        "success": True,
        "message": "Job deleted successfully"
    }

# User Search History Endpoints

@app.get("/user/search-history")
async def get_user_search_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get search history for the authenticated user"""
    search_history = UserService.get_search_history(db, current_user.id, skip, limit)
    return {
        "success": True,
        "message": f"Retrieved {len(search_history)} search history entries",
        "search_history": [SearchHistoryResponse.from_orm(entry) for entry in search_history],
        "timestamp": datetime.now().isoformat()
    }

# User Saved Searches Endpoints

@app.post("/user/saved-searches", response_model=SavedSearchResponse)
async def create_saved_search(
    search_create: SavedSearchCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a saved search template for the authenticated user"""
    saved_search = UserService.create_saved_search(db, current_user.id, search_create)
    return SavedSearchResponse.from_orm(saved_search)

@app.get("/user/saved-searches")
async def get_saved_searches(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get saved search templates for the authenticated user"""
    saved_searches = UserService.get_saved_searches(db, current_user.id)
    return {
        "success": True,
        "message": f"Retrieved {len(saved_searches)} saved searches",
        "saved_searches": [SavedSearchResponse.from_orm(search) for search in saved_searches],
        "timestamp": datetime.now().isoformat()
    }

@app.put("/user/saved-searches/{search_id}")
async def update_saved_search(
    search_id: str,
    search_update: SavedSearchUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update a saved search template for the authenticated user"""
    updated_search = UserService.update_saved_search(db, current_user.id, search_id, search_update)
    if not updated_search:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {
        "success": True,
        "message": "Saved search updated successfully",
        "saved_search": SavedSearchResponse.from_orm(updated_search)
    }

@app.delete("/user/saved-searches/{search_id}")
async def delete_saved_search(
    search_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a saved search template for the authenticated user"""
    deleted = UserService.delete_saved_search(db, current_user.id, search_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {
        "success": True,
        "message": "Saved search deleted successfully"
    }

# Legacy Saved Jobs Endpoints (for backwards compatibility)

@app.post("/save-job", response_model=SavedJobResponse)
async def save_job(request: SaveJobRequest):
    """Save a job to the user's collection"""
    try:
        # Load current saved jobs
        saved_jobs = load_saved_jobs()
        
        # Check if job is already saved
        if job_already_saved(request.job_data, saved_jobs):
            return SavedJobResponse(
                success=False,
                message="Job is already saved to your collection"
            )
        
        # Create new saved job
        new_saved_job = SavedJob(
            id=str(uuid.uuid4()),
            job_data=request.job_data,
            notes=request.notes,
            saved_at=datetime.now().isoformat(),
            tags=[]
        )
        
        # Add to list and save
        saved_jobs.append(new_saved_job)
        save_jobs_to_file(saved_jobs)
        
        return SavedJobResponse(
            success=True,
            message="Job saved successfully",
            saved_job=new_saved_job
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error saving job: {str(e)}"
        )

@app.get("/saved-jobs", response_model=SavedJobsListResponse)
async def get_saved_jobs():
    """Get all saved jobs"""
    try:
        saved_jobs = load_saved_jobs()
        # Sort by saved_at date (newest first)
        saved_jobs.sort(key=lambda x: x.saved_at, reverse=True)
        return SavedJobsListResponse(
            success=True,
            message=f"Retrieved {len(saved_jobs)} saved jobs",
            saved_jobs=saved_jobs,
            total_count=len(saved_jobs),
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        print(f"Error in /saved-jobs endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving saved jobs: {str(e)}"
        )

@app.delete("/saved-job/{job_id}")
async def delete_saved_job(job_id: str):
    """Delete a saved job by ID"""
    try:
        saved_jobs = load_saved_jobs()
        
        # Find and remove the job
        original_count = len(saved_jobs)
        saved_jobs = [job for job in saved_jobs if job.id != job_id]
        
        if len(saved_jobs) == original_count:
            raise HTTPException(
                status_code=404,
                detail="Saved job not found"
            )
        
        # Save updated list
        save_jobs_to_file(saved_jobs)
        
        return {
            "success": True,
            "message": "Job removed from saved collection",
            "remaining_count": len(saved_jobs)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting saved job: {str(e)}"
        )

@app.put("/saved-job/{job_id}/notes")
async def update_job_notes(job_id: str, notes: str):
    """Update notes for a saved job"""
    try:
        saved_jobs = load_saved_jobs()
        
        # Find and update the job
        job_found = False
        for job in saved_jobs:
            if job.id == job_id:
                job.notes = notes
                job_found = True
                break
        
        if not job_found:
            raise HTTPException(
                status_code=404,
                detail="Saved job not found"
            )
        
        # Save updated list
        save_jobs_to_file(saved_jobs)
        
        return {
            "success": True,
            "message": "Job notes updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating job notes: {str(e)}"
        )

@app.put("/saved-job/{job_id}/applied")
async def mark_job_applied(job_id: str, applied: bool = Query(...)):
    """Mark a saved job as applied or not applied"""
    try:
        saved_jobs = load_saved_jobs()
        
        # Find and update the job
        job_found = False
        for job in saved_jobs:
            if job.id == job_id:
                job.applied = applied
                job.applied_at = datetime.now().isoformat() if applied else None
                job_found = True
                break
        
        if not job_found:
            raise HTTPException(
                status_code=404,
                detail="Saved job not found"
            )
        
        # Save updated list
        save_jobs_to_file(saved_jobs)
        
        status_text = "applied to" if applied else "marked as not applied"
        
        return {
            "success": True,
            "message": f"Job {status_text} successfully",
            "applied": applied,
            "applied_at": job.applied_at if applied else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating job application status: {str(e)}"
        )

@app.put("/saved-job/{job_id}/save-for-later")
async def mark_job_save_for_later(job_id: str, save_for_later: bool = Query(...)):
    """Mark a saved job as save for later or not"""
    try:
        saved_jobs = load_saved_jobs()
        job_found = False
        for job in saved_jobs:
            if job.id == job_id:
                job.save_for_later = save_for_later
                job_found = True
                break
        if not job_found:
            raise HTTPException(status_code=404, detail="Saved job not found")
        save_jobs_to_file(saved_jobs)
        status_text = "saved for later" if save_for_later else "removed from save for later"
        return {
            "success": True,
            "message": f"Job {status_text} successfully",
            "save_for_later": save_for_later
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating save for later status: {str(e)}")

@app.put("/saved-job/{job_id}/not-interested")
async def mark_job_not_interested(job_id: str, not_interested: bool = Query(...)):
    """Mark a saved job as not interested or not"""
    try:
        saved_jobs = load_saved_jobs()
        job_found = False
        for job in saved_jobs:
            if job.id == job_id:
                job.not_interested = not_interested
                job_found = True
                break
        if not job_found:
            raise HTTPException(status_code=404, detail="Saved job not found")
        save_jobs_to_file(saved_jobs)
        status_text = "marked as not interested" if not_interested else "removed from not interested"
        return {
            "success": True,
            "message": f"Job {status_text} successfully",
            "not_interested": not_interested
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating not interested status: {str(e)}")

@app.get("/saved-jobs/categorized")
async def get_saved_jobs_categorized():
    """Get saved jobs organized by application status"""
    try:
        saved_jobs = load_saved_jobs()
        saved_jobs.sort(key=lambda x: x.saved_at, reverse=True)
        saved_not_applied = [job for job in saved_jobs if not job.applied and not job.save_for_later and not job.not_interested]
        save_for_later_jobs = [job for job in saved_jobs if job.save_for_later and not job.not_interested]
        applied_jobs = [job for job in saved_jobs if job.applied and not job.not_interested]
        not_interested_jobs = [job for job in saved_jobs if job.not_interested]
        applied_jobs.sort(key=lambda x: x.applied_at or x.saved_at, reverse=True)
        return {
            "success": True,
            "message": f"Retrieved {len(saved_jobs)} saved jobs",
            "saved_jobs": {
                "saved_not_applied": saved_not_applied,
                "save_for_later": save_for_later_jobs,
                "applied": applied_jobs,
                "not_interested": not_interested_jobs
            },
            "counts": {
                "total": len(saved_jobs),
                "saved_not_applied": len(saved_not_applied),
                "save_for_later": len(save_for_later_jobs),
                "applied": len(applied_jobs),
                "not_interested": len(not_interested_jobs)
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving categorized saved jobs: {str(e)}")

# ==========================================
# JOB SCRAPING AND LOCAL SEARCH ENDPOINTS
# ==========================================

@app.post("/search-jobs-local", response_model=ScrapedJobSearchResponse)
async def search_jobs_local(
    request: ScrapedJobSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Search jobs from local database instead of external APIs."""
    try:
        start_time = datetime.now(timezone.utc)
        
        # Search local database
        jobs, total_count = job_scraper.search_local_jobs(
            db=db,
            search_term=request.search_term,
            company_names=request.company_names,
            locations=request.locations,
            job_types=request.job_types,
            is_remote=request.is_remote,
            min_salary=request.min_salary,
            max_salary=request.max_salary,
            max_experience_years=request.max_experience_years,
            sites=request.sites,
            days_old=request.days_old,
            limit=request.limit,
            offset=request.offset,
            exclude_keywords=request.exclude_keywords
        )
        
        # Convert to response format
        job_responses = [ScrapedJobResponse.from_orm(job) for job in jobs]
        
        # Save search to history if requested
        if getattr(request, 'save_search', True):
            search_duration = int((datetime.now(timezone.utc) - start_time).total_seconds())
            UserService.add_search_history(
                db, current_user.id,
                request.dict(),
                len(job_responses),
                search_duration
            )
        
        return ScrapedJobSearchResponse(
            success=True,
            message=f"Found {len(job_responses)} jobs from local database (total: {total_count})",
            total_count=total_count,
            jobs=job_responses,
            search_params=request.dict(),
            timestamp=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error searching local jobs: {str(e)}"
        )

@app.post("/search-jobs-local-public", response_model=ScrapedJobSearchResponse)
async def search_jobs_local_public(
    request: ScrapedJobSearchRequest,
    db: Session = Depends(get_db)
):
    """Search jobs from local database without authentication (public endpoint)."""
    try:
        # Search local database
        jobs, total_count = job_scraper.search_local_jobs(
            db=db,
            search_term=request.search_term,
            company_names=request.company_names,
            locations=request.locations,
            job_types=request.job_types,
            is_remote=request.is_remote,
            min_salary=request.min_salary,
            max_salary=request.max_salary,
            max_experience_years=request.max_experience_years,
            sites=request.sites,
            days_old=request.days_old,
            limit=request.limit,
            offset=request.offset,
            exclude_keywords=request.exclude_keywords
        )
        
        # Convert to response format
        job_responses = [ScrapedJobResponse.from_orm(job) for job in jobs]
        
        return ScrapedJobSearchResponse(
            success=True,
            message=f"Found {len(job_responses)} jobs from local database (total: {total_count})",
            total_count=total_count,
            jobs=job_responses,
            search_params=request.dict(),
            timestamp=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error searching local jobs: {str(e)}"
        )

# Target Company Management Endpoints
@app.post("/admin/target-companies", response_model=TargetCompanyResponse)
async def create_target_company(
    company_create: TargetCompanyCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new target company for scraping."""
    # Check if company already exists
    existing = db.query(TargetCompany).filter(
        TargetCompany.name.ilike(f"%{company_create.name}%")
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Company '{company_create.name}' already exists"
        )
    
    target_company = TargetCompany(
        name=company_create.name,
        display_name=company_create.display_name or company_create.name,
        preferred_sites=company_create.preferred_sites,
        search_terms=company_create.search_terms,
        location_filters=company_create.location_filters
    )
    
    db.add(target_company)
    db.commit()
    db.refresh(target_company)
    
    return TargetCompanyResponse.from_orm(target_company)

@app.get("/admin/target-companies")
async def get_target_companies(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all target companies."""
    companies = db.query(TargetCompany).filter(
        TargetCompany.is_active == True
    ).order_by(TargetCompany.name).all()
    
    return {
        "success": True,
        "companies": [TargetCompanyResponse.from_orm(company) for company in companies],
        "total_count": len(companies)
    }

@app.put("/admin/target-companies/{company_id}")
async def update_target_company(
    company_id: str,
    company_update: TargetCompanyUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update a target company."""
    company = db.query(TargetCompany).filter(TargetCompany.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Update fields
    update_data = company_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)
    
    db.commit()
    db.refresh(company)
    
    return {
        "success": True,
        "message": "Company updated successfully",
        "company": TargetCompanyResponse.from_orm(company)
    }

@app.delete("/admin/target-companies/{company_id}")
async def delete_target_company(
    company_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Soft delete a target company."""
    company = db.query(TargetCompany).filter(TargetCompany.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    company.is_active = False
    db.commit()
    
    return {
        "success": True,
        "message": f"Company '{company.name}' deactivated successfully"
    }

# Job Scraping Endpoints
@app.post("/admin/scrape-bulk", response_model=ScrapingRunResponse)
async def scrape_companies_bulk(
    request: BulkScrapingRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Scrape jobs for multiple companies in bulk."""
    try:
        # Ensure required columns exist (prod safety)
        ensure_scraping_runs_progress_columns(db)
        print(f"🚀 Starting bulk scraping for {len(request.company_names)} companies")
        
        # Start the scraping process
        scraping_run = await job_scraper.bulk_scrape_companies(request, db)
        
        return ScrapingRunResponse.from_orm(scraping_run)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during bulk scraping: {str(e)}"
        )

@app.get("/admin/scraping-runs")
async def get_scraping_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get scraping run history."""
    runs = db.query(ScrapingRun).order_by(
        ScrapingRun.started_at.desc()
    ).offset(offset).limit(limit).all()
    
    total_count = db.query(ScrapingRun).count()
    
    return {
        "success": True,
        "scraping_runs": [ScrapingRunResponse.from_orm(run) for run in runs],
        "total_count": total_count,
        "limit": limit,
        "offset": offset
    }

@app.get("/admin/scraping-runs/{run_id}")
async def get_scraping_run(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific scraping run."""
    run = db.query(ScrapingRun).filter(ScrapingRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Scraping run not found")
    
    return {
        "success": True,
        "scraping_run": ScrapingRunResponse.from_orm(run)
    }

@app.get("/admin/database-stats")
async def get_database_stats(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get database statistics."""
    try:
        # Count jobs by status
        total_jobs = db.query(ScrapedJob).filter(ScrapedJob.is_active == True).count()
        jobs_last_30_days = db.query(ScrapedJob).filter(
            ScrapedJob.is_active == True,
            ScrapedJob.date_scraped >= datetime.now(timezone.utc) - timedelta(days=30)
        ).count()
        
        # Count companies
        total_companies = db.query(TargetCompany).filter(TargetCompany.is_active == True).count()
        
        # Count scraping runs
        total_runs = db.query(ScrapingRun).count()
        successful_runs = db.query(ScrapingRun).filter(ScrapingRun.status == "completed").count()
        
        # Top companies by job count
        from sqlalchemy import func
        top_companies = db.query(
            ScrapedJob.company,
            func.count(ScrapedJob.id).label('job_count')
        ).filter(
            ScrapedJob.is_active == True
        ).group_by(ScrapedJob.company).order_by(
            func.count(ScrapedJob.id).desc()
        ).limit(10).all()
        
        return {
            "success": True,
            "stats": {
                "total_jobs": total_jobs,
                "jobs_last_30_days": jobs_last_30_days,
                "total_companies": total_companies,
                "total_scraping_runs": total_runs,
                "successful_runs": successful_runs,
                "success_rate": round((successful_runs / total_runs * 100) if total_runs > 0 else 0, 2),
                "top_companies": [
                    {"company": company, "job_count": count}
                    for company, count in top_companies
                ]
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting database stats: {str(e)}"
        )

# Public Admin Endpoints (for frontend interfaces)
@app.get("/database-stats-public")
async def get_database_stats_public(db: Session = Depends(get_db)):
    """Get database statistics without authentication (for admin frontend)."""
    try:
        # Count jobs by status
        total_jobs = db.query(ScrapedJob).filter(ScrapedJob.is_active == True).count()
        jobs_last_30_days = db.query(ScrapedJob).filter(
            ScrapedJob.is_active == True,
            ScrapedJob.date_scraped >= datetime.now(timezone.utc) - timedelta(days=30)
        ).count()
        
        # Count companies
        total_companies = db.query(TargetCompany).filter(TargetCompany.is_active == True).count()
        
        # Count scraping runs
        total_runs = db.query(ScrapingRun).count()
        successful_runs = db.query(ScrapingRun).filter(ScrapingRun.status == "completed").count()
        
        # Top companies by job count (all jobs) - show companies with 10+ jobs
        from sqlalchemy import func
        top_companies = db.query(
            ScrapedJob.company,
            func.count(ScrapedJob.id).label('job_count')
        ).filter(
            ScrapedJob.is_active == True
        ).group_by(ScrapedJob.company).having(
            func.count(ScrapedJob.id) >= 10
        ).order_by(
            func.count(ScrapedJob.id).desc()
        ).limit(20).all()
        
        return {
            "success": True,
            "stats": {
                "total_jobs": total_jobs,
                "jobs_last_30_days": jobs_last_30_days,
                "total_companies": total_companies,
                "total_scraping_runs": total_runs,
                "successful_runs": successful_runs,
                "success_rate": round((successful_runs / total_runs * 100) if total_runs > 0 else 0, 2),
                "top_companies": [
                    {"company": company, "job_count": count}
                    for company, count in top_companies
                ]
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting database stats: {str(e)}"
        )

@app.get("/all-companies-public")
async def get_all_companies_public(db: Session = Depends(get_db)):
    """Get all companies that have jobs in the database (public endpoint for admin UI)."""
    try:
        from sqlalchemy import func
        
        # Get all companies with their job counts from scraped jobs
        companies_with_jobs = db.query(
            ScrapedJob.company,
            func.count(ScrapedJob.id).label('job_count')
        ).filter(
            ScrapedJob.is_active == True,
            ScrapedJob.company.isnot(None),
            ScrapedJob.company != ''
        ).group_by(ScrapedJob.company).order_by(
            func.count(ScrapedJob.id).desc()
        ).all()
        
        # Convert to response format
        companies = []
        for company_name, job_count in companies_with_jobs:
            companies.append({
                "name": company_name,
                "job_count": job_count
            })
        
        return {
            "success": True,
            "companies": companies,
            "total_count": len(companies)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting companies: {str(e)}"
        )

@app.get("/target-companies-public")
async def get_target_companies_public(db: Session = Depends(get_db)):
    """Get all target companies without authentication (for admin frontend)."""
    try:
        from sqlalchemy import func
        
        # Get all active companies first
        companies = db.query(TargetCompany).filter(
            TargetCompany.is_active == True
        ).order_by(TargetCompany.name).all()
        
        # Calculate actual job counts for each company and filter out 0-job companies
        company_responses = []
        for company in companies:
            # Count actual jobs for this company
            actual_job_count = db.query(func.count(ScrapedJob.id)).filter(
                ScrapedJob.company.ilike(f'%{company.name}%'),
                ScrapedJob.is_active == True
            ).scalar() or 0
            
            # Only include companies that have jobs
            if actual_job_count > 0:
                # Update the company's job count
                company.total_jobs_found = actual_job_count
                
                # Create response object
                company_response = TargetCompanyResponse.from_orm(company)
                company_responses.append(company_response)
        
        # Commit any updates
        db.commit()
        
        return {
            "success": True,
            "companies": company_responses,
            "total_count": len(company_responses)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error getting companies: {str(e)}"
        )

@app.post("/scrape-bulk-public", response_model=ScrapingRunResponse)
async def scrape_companies_bulk_public(
    request: BulkScrapingRequest,
    db: Session = Depends(get_db)
):
    """Start bulk scraping in background and return immediately for progress tracking."""
    try:
        # Ensure required columns exist (prod safety)
        ensure_scraping_runs_progress_columns(db)
        print(f"🚀 Starting background bulk scraping for {len(request.company_names)} companies")
        
        # Create scraping run record immediately
        start_time = datetime.now(timezone.utc)
        scraping_run = ScrapingRun(
            run_type="bulk_manual",
            status="running",
            companies_scraped=request.company_names,
            sites_used=request.sites,
            search_parameters=request.model_dump(),
            started_at=start_time,
            current_progress={
                "phase": "starting",
                "total_companies": len(request.company_names),
                "completed_companies": 0,
                "current_company": None,
                "current_search_term": None
            }
        )
        db.add(scraping_run)
        db.commit()
        db.refresh(scraping_run)
        
        # Start scraping in background task
        asyncio.create_task(run_bulk_scraping_background(scraping_run.id, request))
        
        # Return immediately with "running" status
        return ScrapingRunResponse.from_orm(scraping_run)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error starting bulk scraping: {str(e)}"
        )

async def run_bulk_scraping_background(scraping_run_id: str, request: BulkScrapingRequest):
    """Run scraping in background and update progress."""
    # Create new database session for background task
    db = next(get_db())
    
    try:
        print(f"🔄 Background scraping started for run {scraping_run_id}")
        
        # Get the scraping run
        scraping_run = db.query(ScrapingRun).filter(ScrapingRun.id == scraping_run_id).first()
        if not scraping_run:
            print(f"❌ Scraping run {scraping_run_id} not found")
            return
        
        # Run the actual scraping with progress updates
        await job_scraper.bulk_scrape_companies_with_progress(request, db, scraping_run)
        
    except Exception as e:
        print(f"❌ Background scraping failed: {str(e)}")
        # Mark as failed
        scraping_run = db.query(ScrapingRun).filter(ScrapingRun.id == scraping_run_id).first()
        if scraping_run:
            scraping_run.status = "failed"
            scraping_run.error_message = str(e)
            scraping_run.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

@app.get("/scraping-runs/{run_id}/progress")
async def get_scraping_progress(
    run_id: str,
    db: Session = Depends(get_db)
):
    """Get real-time progress of a scraping run."""
    run = db.query(ScrapingRun).filter(ScrapingRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Scraping run not found")
    
    return {
        "success": True,
        "run_id": run_id,
        "status": run.status,
        "progress": getattr(run, "current_progress", None),
        "total_jobs_found": run.total_jobs_found or 0,
        "new_jobs_added": run.new_jobs_added or 0,
        "duplicate_jobs_skipped": run.duplicate_jobs_skipped or 0,
        "search_analytics": run.search_analytics or {},
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_seconds": run.duration_seconds
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/test-pdf-endpoint")
async def test_pdf_endpoint(request: dict):
    """Test endpoint to debug PDF generation issues"""
    try:
        latex_code = request.get('latex_code', '')
        
        if not latex_code:
            return {
                "status": "error",
                "message": "No LaTeX code provided",
                "received_data": 0,
                "timestamp": datetime.now().isoformat()
            }
        
        # Test with a simple LaTeX document
        test_latex = r"""
\documentclass{article}
\begin{document}
\title{Test Document}
\author{JobSpy Resume Builder}
\maketitle
\section{Test Section}
This is a test document generated by JobSpy Resume Builder.
\end{document}
        """
        
        print("🧪 Testing Overleaf link generation...")
        
        # Test the Overleaf link generation
        try:
            import base64
            import urllib.parse
            
            # Test base64 encoding
            latex_bytes = test_latex.encode('utf-8')
            latex_base64 = base64.b64encode(latex_bytes).decode('utf-8')
            data_url = f"data:application/x-tex;base64,{latex_base64}"
            overleaf_url = f"https://www.overleaf.com/docs?snip_uri={urllib.parse.quote(data_url)}"
            
            # Test URL encoding
            encoded_latex = urllib.parse.quote(test_latex)
            overleaf_url_encoded = f"https://www.overleaf.com/docs?encoded_snip={encoded_latex}"
            
            test_result = {
                "status": "success",
                "message": "Overleaf link generation test successful",
                "received_data": len(latex_code),
                "test_latex_length": len(test_latex),
                "base64_encoding_works": True,
                "url_encoding_works": True,
                "overleaf_base64_url_length": len(overleaf_url),
                "overleaf_encoded_url_length": len(overleaf_url_encoded),
                "timestamp": datetime.now().isoformat()
            }
            
            return test_result
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Overleaf link generation test failed: {str(e)}",
                "received_data": len(latex_code),
                "test_latex_length": len(test_latex),
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Test endpoint error: {str(e)}",
            "received_data": len(request.get('latex_code', '')),
            "timestamp": datetime.now().isoformat()
        }

@app.post("/download-latex-file")
async def download_latex_file(request: dict):
    """Download LaTeX code as a .tex file for manual compilation"""
    try:
        from fastapi.responses import StreamingResponse
        
        latex_code = request.get('latex_code', '')
        filename = request.get('filename', 'resume.tex')
        
        if not latex_code:
            raise HTTPException(status_code=400, detail="LaTeX code is required")
        
        # Ensure filename has .tex extension
        if not filename.endswith('.tex'):
            filename = f"{filename}.tex"
        
        print(f"📄 Creating LaTeX file download: {filename}")
        
        # Create file content with proper encoding
        file_content = latex_code.encode('utf-8')
        
        return StreamingResponse(
            io.BytesIO(file_content),
            media_type="application/x-tex",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Length": str(len(file_content))
            }
        )
            
    except Exception as e:
        print(f"💥 Error creating LaTeX file download: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating LaTeX file: {str(e)}"
        )

@app.delete("/admin/jobs/{job_id}")
async def delete_job(job_id: str, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Delete a specific job by ID"""
    try:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        db.delete(job)
        db.commit()
        
        return {"success": True, "message": f"Job '{job.title}' deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting job: {str(e)}")

@app.delete("/admin/companies/{company_name}/jobs")
async def delete_company_jobs(company_name: str, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Delete all jobs for a specific company"""
    try:
        jobs = db.query(ScrapedJob).filter(ScrapedJob.company.ilike(f"%{company_name}%")).all()
        if not jobs:
            raise HTTPException(status_code=404, detail=f"No jobs found for company '{company_name}'")
        
        job_count = len(jobs)
        for job in jobs:
            db.delete(job)
        
        db.commit()
        
        return {"success": True, "message": f"Deleted {job_count} jobs for company '{company_name}'"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting company jobs: {str(e)}")

# Public versions for admin UI (no auth required)
@app.delete("/admin/jobs-public/{job_id}")
async def delete_job_public(job_id: str, db: Session = Depends(get_db)):
    """Delete a specific job by ID (public endpoint for admin UI)"""
    try:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_title = job.title
        job_company = job.company
        
        db.delete(job)
        db.commit()
        
        return {"success": True, "message": f"Job '{job_title}' at {job_company} deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting job: {str(e)}")

@app.delete("/admin/company-jobs-public/{company_name}")
async def delete_any_company_jobs_public(company_name: str, db: Session = Depends(get_db)):
    """Delete all jobs for any company (public endpoint for admin UI)"""
    try:
        # Find all jobs for this company (exact match for consistency)
        jobs = db.query(ScrapedJob).filter(
            ScrapedJob.company == company_name,
            ScrapedJob.is_active == True
        ).all()
        
        if not jobs:
            raise HTTPException(status_code=404, detail=f"No active jobs found for company '{company_name}'")
        
        job_count = len(jobs)
        
        # Delete all jobs for this company
        for job in jobs:
            db.delete(job)
        
        # Update the target company's job count to 0 if it exists
        target_company = db.query(TargetCompany).filter(
            TargetCompany.name.ilike(f"%{company_name}%")
        ).first()
        
        if target_company:
            target_company.total_jobs_found = 0
        
        db.commit()
        
        return {
            "success": True, 
            "message": f"Deleted {job_count} jobs for company '{company_name}'",
            "deleted_count": job_count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting company jobs: {str(e)}")

@app.delete("/admin/companies-public/{company_name}/jobs")
async def delete_company_jobs_public(company_name: str, db: Session = Depends(get_db)):
    """Delete all jobs for a specific company (public endpoint for admin UI)"""
    try:
        # Find all jobs for this company
        jobs = db.query(ScrapedJob).filter(
            ScrapedJob.company.ilike(f"%{company_name}%"),
            ScrapedJob.is_active == True
        ).all()
        
        if not jobs:
            raise HTTPException(status_code=404, detail=f"No active jobs found for company '{company_name}'")
        
        job_count = len(jobs)
        
        # Delete all jobs for this company
        for job in jobs:
            db.delete(job)
        
        # Update the target company's job count to 0
        target_company = db.query(TargetCompany).filter(
            TargetCompany.name.ilike(f"%{company_name}%")
        ).first()
        
        if target_company:
            target_company.total_jobs_found = 0
        
        db.commit()
        
        return {
            "success": True, 
            "message": f"Deleted {job_count} jobs for company '{company_name}'",
            "deleted_count": job_count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting company jobs: {str(e)}")

@app.post("/admin/remove-duplicates-public")
async def remove_duplicate_jobs_public(db: Session = Depends(get_db)):
    """Remove duplicate jobs based on job_url (public endpoint for admin UI)"""
    try:
        # Find duplicates by job_url
        # Keep the most recent job for each URL and delete the rest
        from sqlalchemy import func
        
        # First, find all job_urls that have duplicates
        duplicate_urls = db.query(ScrapedJob.job_url).filter(
            ScrapedJob.job_url.isnot(None),
            ScrapedJob.job_url != ''
        ).group_by(ScrapedJob.job_url).having(
            func.count(ScrapedJob.id) > 1
        ).all()
        
        if not duplicate_urls:
            return {
                "success": True,
                "message": "No duplicates found",
                "duplicates_removed": 0
            }
        
        duplicate_urls = [url[0] for url in duplicate_urls]
        total_removed = 0
        
        # For each duplicate URL, keep only the most recent job
        for job_url in duplicate_urls:
            jobs_with_url = db.query(ScrapedJob).filter(
                ScrapedJob.job_url == job_url
            ).order_by(ScrapedJob.date_scraped.desc()).all()
            
            # Keep the first (most recent) and delete the rest
            jobs_to_delete = jobs_with_url[1:]  # Skip the first one
            
            for job in jobs_to_delete:
                db.delete(job)
                total_removed += 1
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Successfully removed {total_removed} duplicate jobs from {len(duplicate_urls)} unique URLs",
            "duplicates_removed": total_removed,
            "unique_urls_processed": len(duplicate_urls)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error removing duplicates: {str(e)}")

@app.post("/admin/remove-old-jobs-public")
async def remove_old_jobs_public(db: Session = Depends(get_db)):
    """Remove jobs older than 30 days (public endpoint for admin UI)"""
    try:
        from sqlalchemy import func
        from datetime import datetime, timedelta, timezone
        
        # Calculate 30 days ago
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Find jobs older than 30 days
        old_jobs = db.query(ScrapedJob).filter(
            ScrapedJob.is_active == True,
            ScrapedJob.date_posted.isnot(None),
            ScrapedJob.date_posted < thirty_days_ago
        ).all()
        
        if not old_jobs:
            return {
                "success": True,
                "message": "No jobs older than 30 days found",
                "jobs_removed": 0
            }
        
        jobs_removed = len(old_jobs)
        
        # Remove old jobs
        for job in old_jobs:
            db.delete(job)
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Successfully removed {jobs_removed} jobs older than 30 days",
            "jobs_removed": jobs_removed
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error removing old jobs: {str(e)}")

@app.get("/admin/comprehensive-terms-public")
async def get_comprehensive_terms_public():
    """Get current comprehensive search terms (public endpoint for admin UI)"""
    try:
        # For now, store in a simple JSON file
        terms_file = "comprehensive_terms.json"
        
        if os.path.exists(terms_file):
            with open(terms_file, 'r') as f:
                data = json.load(f)
                return {
                    "success": True,
                    "terms": data.get("terms", get_default_comprehensive_terms()),
                    "updated_at": data.get("updated_at")
                }
        else:
            # Return default terms
            return {
                "success": True,
                "terms": get_default_comprehensive_terms(),
                "updated_at": None
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading comprehensive terms: {str(e)}")

@app.post("/admin/comprehensive-terms-public")
async def save_comprehensive_terms_public(terms_data: ComprehensiveTermsCreate):
    """Save comprehensive search terms (public endpoint for admin UI)"""
    try:
        terms_file = "comprehensive_terms.json"
        
        data = {
            "terms": terms_data.terms,
            "updated_at": datetime.now().isoformat()
        }
        
        with open(terms_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        return {
            "success": True,
            "message": f"Successfully saved {len(terms_data.terms)} comprehensive search terms",
            "terms": terms_data.terms,
            "updated_at": data["updated_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving comprehensive terms: {str(e)}")

def get_default_comprehensive_terms():
    """Get default comprehensive search terms"""
    return [
        "tech", "analyst", "manager", "product", "engineer", "market", 
        "finance", "business", "associate", "senior", "director", 
        "president", "lead", "data", "science", "software", "cloud", 
        "developer", "staff", "program", "quality", "security", "specialist"
    ]

@app.get("/admin/scraping-defaults-public")
async def get_scraping_defaults_public():
    """Get current scraping default settings (public endpoint for admin UI)"""
    try:
        defaults_file = "scraping_defaults.json"
        
        if os.path.exists(defaults_file):
            with open(defaults_file, 'r') as f:
                data = json.load(f)
                return {
                    "success": True,
                    "companies": data.get("companies"),
                    "search_terms": data.get("search_terms"),
                    "locations": data.get("locations"),
                    "results_per_company": data.get("results_per_company"),
                    "hours_old": data.get("hours_old"),
                    "updated_at": data.get("updated_at")
                }
        else:
            # Return empty defaults
            return {
                "success": True,
                "companies": None,
                "search_terms": None,
                "locations": None,
                "results_per_company": None,
                "hours_old": None,
                "updated_at": None
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading scraping defaults: {str(e)}")

@app.post("/admin/scraping-defaults-public")
async def save_scraping_defaults_public(defaults_data: ScrapingDefaultsCreate):
    """Save scraping default settings (public endpoint for admin UI)"""
    try:
        defaults_file = "scraping_defaults.json"
        
        # Load existing data if it exists
        existing_data = {}
        if os.path.exists(defaults_file):
            with open(defaults_file, 'r') as f:
                existing_data = json.load(f)
        
        # Update only the fields that are provided (not None)
        data = existing_data.copy()
        if defaults_data.companies is not None:
            data["companies"] = defaults_data.companies
        if defaults_data.search_terms is not None:
            data["search_terms"] = defaults_data.search_terms
        if defaults_data.locations is not None:
            data["locations"] = defaults_data.locations
        if defaults_data.results_per_company is not None:
            data["results_per_company"] = defaults_data.results_per_company
        if defaults_data.hours_old is not None:
            data["hours_old"] = defaults_data.hours_old
        
        data["updated_at"] = datetime.now().isoformat()
        
        with open(defaults_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Build response message
        updated_fields = []
        if defaults_data.companies is not None:
            updated_fields.append(f"companies ({len(defaults_data.companies)} items)")
        if defaults_data.search_terms is not None:
            updated_fields.append(f"search terms ({len(defaults_data.search_terms)} items)")
        if defaults_data.locations is not None:
            updated_fields.append(f"locations ({len(defaults_data.locations)} items)")
        if defaults_data.results_per_company is not None:
            updated_fields.append(f"results per company ({defaults_data.results_per_company})")
        if defaults_data.hours_old is not None:
            updated_fields.append(f"hours old ({defaults_data.hours_old})")
        
        return {
            "success": True,
            "message": f"Successfully saved defaults for: {', '.join(updated_fields)}",
            "updated_fields": updated_fields,
            "updated_at": data["updated_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving scraping defaults: {str(e)}")

@app.post("/admin/migrate-schema")
async def migrate_database_schema(db: Session = Depends(get_db)):
    """Migrate database schema to add missing columns (admin only)"""
    try:
        from sqlalchemy import text, inspect

        inspector = inspect(db.bind)
        columns = [col['name'] for col in inspector.get_columns('scraping_runs')]

        added = []

        if 'search_analytics' not in columns:
            db.execute(text("ALTER TABLE scraping_runs ADD COLUMN search_analytics JSON"))
            added.append('search_analytics')

        # Refresh columns list before next check
        inspector = inspect(db.bind)
        columns = [col['name'] for col in inspector.get_columns('scraping_runs')]

        if 'current_progress' not in columns:
            db.execute(text("ALTER TABLE scraping_runs ADD COLUMN current_progress JSON"))
            added.append('current_progress')

        if added:
            db.commit()
            return {"success": True, "message": f"Added columns: {', '.join(added)}"}
        else:
            return {"success": True, "message": "Schema already up to date"}
            
    except Exception as e:
        return {
            "success": False, 
            "error": str(e),
            "message": "Migration failed"
        }

# Database Migration Endpoints
@app.post("/admin/migrate-data")
async def migrate_local_to_production(
    postgres_url: str,
    dry_run: bool = False,
    batch_size: int = 1000
):
    """Migrate local SQLite data to production PostgreSQL"""
    try:
        # Import migration functionality
        from migrate_sqlite_to_postgres import DatabaseMigrator
        
        # Check if local SQLite exists
        sqlite_path = "../jobsearch.db"
        if not os.path.exists(sqlite_path):
            raise HTTPException(status_code=404, detail="Local SQLite database not found")
        
        # Initialize migrator
        migrator = DatabaseMigrator(
            sqlite_path=sqlite_path,
            postgres_url=postgres_url,
            batch_size=batch_size
        )
        
        # Verify connections
        if not migrator.verify_connections():
            raise HTTPException(status_code=400, detail="Database connection verification failed")
        
        # Run migration (skip confirmation when called via API)
        results = migrator.run_full_migration(dry_run=dry_run, skip_confirmation=True)
        
        if 'error' in results:
            raise HTTPException(status_code=500, detail=f"Migration failed: {results['error']}")
        
        return {
            "success": True,
            "message": "Migration completed successfully" if not dry_run else "Migration simulation completed",
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Migration error: {str(e)}")

@app.get("/admin/migration-stats")
async def get_migration_stats():
    """Get statistics for migration preview"""
    try:
        from migrate_sqlite_to_postgres import DatabaseMigrator
        
        # Check if local SQLite exists
        sqlite_path = "../jobsearch.db"
        if not os.path.exists(sqlite_path):
            return {
                "sqlite_available": False,
                "message": "Local SQLite database not found"
            }
        
        # Get current DATABASE_URL for production stats
        postgres_url = os.getenv("DATABASE_URL")
        if not postgres_url:
            return {
                "sqlite_available": True,
                "postgres_available": False, 
                "message": "No production database URL configured"
            }
        
        # Initialize migrator to get stats
        migrator = DatabaseMigrator(
            sqlite_path=sqlite_path,
            postgres_url=postgres_url,
            batch_size=1000
        )
        
        # Get migration stats
        stats = migrator.get_migration_stats()
        
        return {
            "success": True,
            "sqlite_available": True,
            "postgres_available": True,
            "stats": stats
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/admin/local-db-stats")
async def get_local_database_stats():
    """Get local SQLite database statistics"""
    try:
        from migrate_sqlite_to_postgres import DatabaseMigrator
        
        # Use the migrator to get clean stats
        migrator = DatabaseMigrator("../jobsearch.db")
        local_stats = migrator.get_local_stats()
        
        # Return simplified stats format for UI compatibility
        return {
            "success": True,
            "stats": {
                "total_jobs": local_stats["sqlite_jobs"],
                "active_jobs": local_stats["sqlite_jobs"],
                "companies": local_stats["sqlite_companies"],
                "scraping_runs": local_stats["sqlite_scraping_runs"],
                "users": local_stats["sqlite_users"],
                "recent_jobs": 0,  # Simplified - could add this later if needed
                "top_companies": [],  # Simplified - could add this later if needed
                "sites": []  # Simplified - could add this later if needed
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting local stats: {str(e)}")

@app.get("/admin/migration")
async def serve_migration_dashboard():
    """Serve the database migration dashboard"""
    try:
        return FileResponse("../migration-dashboard.html")
    except:
        return {"message": "Migration dashboard not available", "api_docs": "/docs"}

@app.get("/admin")
async def serve_admin_dashboard():
    """Serve the unified admin dashboard"""
    try:
        return FileResponse("../admin-dashboard.html")
    except:
        return {"message": "Admin dashboard not available", "api_docs": "/docs"}

# ==========================================
# AUTOMATED SCRAPING SCHEDULER ENDPOINTS
# ==========================================

@app.get("/admin/scheduler/status")
async def get_scheduler_status_endpoint():
    """Get the current status of the automated scraping scheduler (public for admin UI)."""
    try:
        from scheduler import get_scheduler_status
        status = get_scheduler_status()
        return {
            "success": True,
            "scheduler": status
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting scheduler status: {str(e)}"
        )

@app.post("/admin/scheduler/start")
async def start_scheduler_endpoint():
    """Start the automated scraping scheduler (public for admin UI)."""
    try:
        from scheduler import start_auto_scraping
        start_auto_scraping()
        return {
            "success": True,
            "message": "Automated scraping scheduler started successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error starting scheduler: {str(e)}"
        )

@app.post("/admin/scheduler/stop")
async def stop_scheduler_endpoint():
    """Stop the automated scraping scheduler (public for admin UI)."""
    try:
        from scheduler import stop_auto_scraping
        stop_auto_scraping()
        return {
            "success": True,
            "message": "Automated scraping scheduler stopped successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error stopping scheduler: {str(e)}"
        )

@app.post("/admin/scheduler/trigger")
async def trigger_manual_scraping_endpoint(
    company_names: List[str] = Query(default=[], description="Specific companies to scrape (optional)"),
    search_terms: List[str] = Query(default=[], description="Custom search terms (optional)")
):
    """Trigger manual scraping immediately with optional company filtering (public for admin UI)."""
    try:
        from scheduler import trigger_manual_scraping
        
        # Filter out empty strings
        company_names = [name.strip() for name in company_names if name.strip()]
        search_terms = [term.strip() for term in search_terms if term.strip()]
        
        success = trigger_manual_scraping(
            company_names=company_names if company_names else None,
            search_terms=search_terms if search_terms else None
        )
        
        if success:
            if company_names:
                message = f"Manual scraping triggered for {len(company_names)} companies: {', '.join(company_names)}"
            else:
                message = "Manual scraping triggered for all companies. Check logs for progress."
                
            return {
                "success": True,
                "message": message,
                "company_names": company_names,
                "search_terms": search_terms
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to trigger manual scraping"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error triggering manual scraping: {str(e)}"
        )

# Daily Job Review Endpoints (Debug)
@app.get("/daily-review/debug/{date}")
async def debug_daily_review_list(date: str, db: Session = Depends(get_db)):
    """Debug daily review list creation"""
    try:
        from database import DailyJobReviewList, DailyJobReviewItem, ScrapedJob
        
        review_list = db.query(DailyJobReviewList).filter(
            DailyJobReviewList.date == date
        ).first()
        
        if not review_list:
            return {"error": "No review list found"}
        
        # Get one item for testing
        item = db.query(DailyJobReviewItem).join(
            ScrapedJob, DailyJobReviewItem.scraped_job_id == ScrapedJob.id
        ).filter(
            DailyJobReviewItem.review_list_id == review_list.id
        ).first()
        
        if not item:
            return {"error": "No items found"}
        
        job = item.scraped_job
        
        # Return raw data
        return {
            "review_list_id": review_list.id,
            "item_id": item.id,
            "job_data": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "min_amount": job.min_amount,
                "max_amount": job.max_amount,
                "min_experience_years": job.min_experience_years,
                "max_experience_years": job.max_experience_years,
                "target_company_id": job.target_company_id
            }
        }
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/daily-review/dates", response_model=List[str])
async def get_available_review_dates(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get list of available daily review dates."""
    try:
        from daily_job_review import daily_job_reviewer
        dates = daily_job_reviewer.get_available_review_dates(db, limit)
        return dates
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching review dates: {str(e)}"
        )

@app.get("/daily-review/summaries", response_model=List[DailyJobReviewListSummary])
async def get_daily_review_summaries(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get summary information for recent daily review lists."""
    try:
        from database import DailyJobReviewList
        from sqlalchemy import desc, func
        
        # Get recent review lists with job counts
        summaries = db.query(
            DailyJobReviewList.id,
            DailyJobReviewList.date,
            DailyJobReviewList.total_jobs_reviewed,
            DailyJobReviewList.jobs_selected_count,
            DailyJobReviewList.status,
            DailyJobReviewList.created_at,
            func.count(DailyJobReviewItem.id).label('jobs_count')
        ).outerjoin(
            DailyJobReviewItem,
            DailyJobReviewList.id == DailyJobReviewItem.review_list_id
        ).group_by(
            DailyJobReviewList.id
        ).order_by(
            desc(DailyJobReviewList.date)
        ).limit(limit).all()
        
        return [
            DailyJobReviewListSummary(
                id=s.id,
                date=s.date,
                total_jobs_reviewed=s.total_jobs_reviewed,
                jobs_selected_count=s.jobs_selected_count,
                jobs_count=s.jobs_count,
                status=s.status,
                created_at=s.created_at
            ) for s in summaries
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching review summaries: {str(e)}"
        )

@app.get("/daily-review/{date}", response_model=DailyJobReviewListResponse)
async def get_daily_review_list(
    date: str,
    db: Session = Depends(get_db)
):
    """Get the daily job review list for a specific date."""
    try:
        from database import DailyJobReviewList, DailyJobReviewItem, ScrapedJob
        
        # Get the review list with all related data
        review_list = db.query(DailyJobReviewList).filter(
            DailyJobReviewList.date == date
        ).first()
        
        if not review_list:
            raise HTTPException(
                status_code=404,
                detail=f"No daily review list found for date: {date}"
            )
        
        # Get review items with job data
        review_items = db.query(DailyJobReviewItem).join(
            ScrapedJob, DailyJobReviewItem.scraped_job_id == ScrapedJob.id
        ).filter(
            DailyJobReviewItem.review_list_id == review_list.id
        ).order_by(DailyJobReviewItem.final_rank).all()
        
        # Format the response
        formatted_items = []
        for item in review_items:
            job = item.scraped_job
            formatted_items.append(
                DailyJobReviewItemResponse(
                    id=item.id,
                    scraped_job_id=item.scraped_job_id,
                    relevance_score=item.relevance_score,
                    ai_score=item.ai_score,
                    final_rank=item.final_rank,
                    user_rating=item.user_rating,
                    user_notes=item.user_notes,
                    is_selected=item.is_selected,
                    is_dismissed=item.is_dismissed,
                    added_at=item.added_at,
                    reviewed_at=item.reviewed_at,
                    job=ScrapedJobResponse.from_orm(job)
                )
            )
        
        return DailyJobReviewListResponse(
            id=review_list.id,
            date=review_list.date,
            created_at=review_list.created_at,
            updated_at=review_list.updated_at,
            filter_config=review_list.filter_config,
            total_jobs_reviewed=review_list.total_jobs_reviewed,
            jobs_selected_count=review_list.jobs_selected_count,
            auto_generated=review_list.auto_generated,
            status=review_list.status,
            jobs=formatted_items
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching daily review list: {str(e)}"
        )

@app.post("/daily-review/create", response_model=DailyJobReviewListResponse)
async def create_daily_review_list(
    request: CreateDailyReviewRequest,
    db: Session = Depends(get_db)
):
    """Create a new daily job review list."""
    try:
        from daily_job_review import daily_job_reviewer
        from datetime import datetime
        
        target_date = request.target_date or datetime.now().strftime("%Y-%m-%d")
        
        review_list = daily_job_reviewer.create_daily_review_list(
            target_date=target_date,
            db=db,
            force_recreate=request.force_recreate
        )
        
        if not review_list:
            raise HTTPException(
                status_code=400,
                detail=f"No jobs qualified for daily review list on {target_date}"
            )
        
        # Return the created list using the get endpoint logic
        return await get_daily_review_list(target_date, db)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error creating daily review list: {str(e)}"
        )

@app.put("/daily-review/item/{item_id}", response_model=dict)
async def update_review_item(
    item_id: str,
    request: UpdateReviewItemRequest,
    db: Session = Depends(get_db)
):
    """Update the status/rating of a daily review item."""
    try:
        from daily_job_review import daily_job_reviewer
        
        success = daily_job_reviewer.update_review_item_status(
            item_id=item_id,
            is_selected=request.is_selected,
            is_dismissed=request.is_dismissed,
            user_rating=request.user_rating,
            user_notes=request.user_notes,
            db=db
        )
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Review item not found: {item_id}"
            )
        
        return {"message": "Review item updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating review item: {str(e)}"
        )

# Application lifecycle handlers
@app.on_event("startup")
async def startup_event():
    """Initialize the application and start the scheduler"""
    print("🚀 Starting JobSpy API server...")
    try:
        # Initialize database
        create_tables()
        print("✅ Database initialized")
        
        # Start the automated scraping scheduler
        from scheduler import start_auto_scraping
        start_auto_scraping()
        print("✅ Scheduler ready")
        
    except Exception as e:
        print(f"⚠️  Warning during startup: {e}")

# Auto-Scraping Configuration API Endpoints
@app.get("/api/autoscraping/config")
async def get_autoscraping_config(current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get current auto-scraping configuration for authenticated user"""
    try:
        # Get user's configuration using the service
        user_config = UserService.get_autoscraping_config_dict(db, current_user.id)

        # Get companies from database
        companies = db.query(TargetCompany).filter(TargetCompany.is_active == True).all()
        user_config["companies"] = [{"name": c.name, "active": c.is_active} for c in companies]

        # Add extra fields for compatibility
        user_config.update({
            "include_filtered": True,
            "exclude_executive": True,
            "executive_keywords": "president, director, vp, vice president, chief, head of",
            "seniority_filter": "",
            "default_locations": user_config.get("location", "USA")
        })

        return {"success": True, "config": user_config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading configuration: {str(e)}")

@app.get("/autoscraping")
async def autoscraping_config_page():
    """Serve the auto-scraping configuration page"""
    return FileResponse("../autoscraping-config.html")

@app.post("/api/autoscraping/config")
async def save_autoscraping_config(config: dict, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Save auto-scraping configuration for authenticated user"""
    try:
        # Validate required fields
        required_fields = ["enabled", "schedule_time", "max_results", "sites"]
        for field in required_fields:
            if field not in config:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

        # Validate schedule time format
        try:
            from datetime import datetime
            datetime.strptime(config["schedule_time"], "%H:%M")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid schedule time format. Use HH:MM")

        # Validate max_results range
        if not (10 <= config["max_results"] <= 1000):
            raise HTTPException(status_code=400, detail="Max results must be between 10 and 1000")

        # Update companies in database if provided (companies are still global)
        if "companies" in config and isinstance(config["companies"], list):
            # Get current company names from config
            config_company_names = [company_data["name"] for company_data in config["companies"] if "name" in company_data]

            # Get all existing companies from database
            existing_companies = db.query(TargetCompany).all()

            # Remove companies that are no longer in the config
            for existing_company in existing_companies:
                if existing_company.name not in config_company_names:
                    db.delete(existing_company)
                    print(f"🗑️ Removed company from database: {existing_company.name}")

            # Update existing companies or create new ones
            for company_data in config["companies"]:
                if "name" in company_data:
                    company = db.query(TargetCompany).filter(TargetCompany.name == company_data["name"]).first()
                    if not company:
                        # Create new company
                        company = TargetCompany(
                            name=company_data["name"],
                            display_name=company_data["name"],
                            is_active=company_data.get("active", True),
                            preferred_sites=config.get("sites", ["indeed"]),
                            search_terms=config.get("search_terms", []),
                            location_filters=[config.get("default_locations", "USA")]
                        )
                        db.add(company)
                        print(f"➕ Added new company to database: {company_data['name']}")
                    else:
                        # Update existing company
                        company.is_active = company_data.get("active", True)
                        print(f"🔄 Updated company in database: {company_data['name']}")

        # Save user-specific configuration to database (excluding companies)
        config_to_save = {k: v for k, v in config.items() if k not in ["companies", "include_filtered", "exclude_executive", "executive_keywords", "seniority_filter", "default_locations"]}

        # Set the notification email to user's email if not provided
        if not config_to_save.get("notification_email"):
            config_to_save["notification_email"] = current_user.email

        UserService.create_or_update_autoscraping_config(db, current_user.id, config_to_save)

        return {"success": True, "message": "Configuration saved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving configuration: {str(e)}")

@app.post("/api/autoscraping/test")
async def test_autoscraping_config(config: dict):
    """Test auto-scraping configuration without running full scrape"""
    try:
        # Validate configuration
        if not config.get("companies"):
            raise HTTPException(status_code=400, detail="No companies configured for testing")

        if not config.get("search_terms"):
            raise HTTPException(status_code=400, detail="No search terms configured for testing")

        # Simulate a small test scrape with first company and first search term
        test_company = config["companies"][0]["name"] if config["companies"] else "Google"
        test_search_term = config["search_terms"][0] if config["search_terms"] else "software engineer"

        return {
            "success": True,
            "message": f"Test validated successfully. Configuration is ready for '{test_search_term}' at {test_company}",
            "test_results": {
                "company": test_company,
                "search_term": test_search_term,
                "companies_count": len(config.get("companies", [])),
                "search_terms_count": len(config.get("search_terms", [])),
                "sites_configured": config.get("sites", ["indeed"])
            }
        }
    except Exception as e:
        return {"success": False, "message": f"Test failed: {str(e)}"}

@app.post("/api/autoscraping/run")
async def run_autoscraping_now(config: dict, current_user: User = Depends(get_current_active_user)):
    """Run auto-scraping immediately with current configuration"""
    try:
        from scheduler import AutoScrapingScheduler

        # Create scheduler instance
        scheduler = AutoScrapingScheduler()

        # Prepare company names from config
        company_names = [c["name"] for c in config.get("companies", []) if c.get("active", True)]
        if not company_names:
            raise HTTPException(status_code=400, detail="No active companies configured")

        search_terms = config.get("search_terms", ["software engineer"])
        if not search_terms:
            raise HTTPException(status_code=400, detail="No search terms configured")

        # Run scraping in background
        import asyncio
        import threading

        def run_scraping():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run the scraping
                loop.run_until_complete(
                    scheduler.run_targeted_scraping(
                        target_company_names=company_names,
                        custom_search_terms=search_terms,
                        user_id=current_user.id
                    )
                )
            except Exception as e:
                print(f"Error in background scraping: {e}")

        # Start scraping in background thread
        scraping_thread = threading.Thread(target=run_scraping)
        scraping_thread.daemon = True
        scraping_thread.start()

        return {
            "success": True,
            "message": f"Scraping started for {len(company_names)} companies with {len(search_terms)} search terms. Check your email for results."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting scraping: {str(e)}")

# Filtered Jobs API Endpoints
@app.get("/api/filtered-jobs", response_model=FilteredJobSearchResponse)
async def search_filtered_jobs(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    days_back: Optional[int] = Query(1, description="Get last N days"),
    min_enhanced_score: Optional[float] = Query(None, description="Minimum enhanced score"),
    ai_relevance_filter: Optional[str] = Query(None, description="Comma-separated AI relevance levels"),
    company_filter: Optional[str] = Query(None, description="Company name filter"),
    location_filter: Optional[str] = Query(None, description="Location filter"),
    job_type_filter: Optional[str] = Query(None, description="Job type filter"),
    is_remote: Optional[bool] = Query(None, description="Remote job filter"),
    limit: Optional[int] = Query(100, description="Number of jobs to return"),
    offset: Optional[int] = Query(0, description="Offset for pagination"),
    sort_by: Optional[str] = Query("enhanced_score", description="Sort field"),
    sort_order: Optional[str] = Query("desc", description="Sort order"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get filtered jobs with optional date range and filtering."""
    try:
        from sqlalchemy import and_, or_, desc, asc, func
        from datetime import date, timedelta

        # Build base query - filter by current user only
        query = db.query(FilteredJobView).join(ScrapedJob).filter(FilteredJobView.user_id == current_user.id)

        # Handle date filtering
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d").date()
                end = datetime.strptime(end_date, "%Y-%m-%d").date()
                query = query.filter(FilteredJobView.filter_date.between(start, end))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        elif days_back:
            end_date_obj = date.today()
            start_date_obj = end_date_obj - timedelta(days=days_back - 1)
            query = query.filter(FilteredJobView.filter_date.between(start_date_obj, end_date_obj))

        # Apply filters
        if min_enhanced_score is not None:
            query = query.filter(FilteredJobView.enhanced_score >= min_enhanced_score)

        if ai_relevance_filter:
            ai_levels = [level.strip() for level in ai_relevance_filter.split(",")]
            query = query.filter(FilteredJobView.ai_relevance.in_(ai_levels))

        if company_filter:
            query = query.filter(ScrapedJob.company.ilike(f"%{company_filter}%"))

        if location_filter:
            query = query.filter(ScrapedJob.location.ilike(f"%{location_filter}%"))

        if job_type_filter:
            query = query.filter(ScrapedJob.job_type.ilike(f"%{job_type_filter}%"))

        if is_remote is not None:
            query = query.filter(ScrapedJob.is_remote == is_remote)

        # Get total count
        total_count = query.count()

        # Apply sorting
        if sort_by == "enhanced_score":
            sort_field = FilteredJobView.enhanced_score
        elif sort_by == "filter_date":
            sort_field = FilteredJobView.filter_date
        elif sort_by == "date_posted":
            sort_field = ScrapedJob.date_posted
        else:
            sort_field = FilteredJobView.enhanced_score

        if sort_order == "desc":
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))

        # Apply pagination
        filtered_jobs = query.offset(offset).limit(limit).all()

        # Get available dates
        available_dates_query = db.query(FilteredJobView.filter_date.distinct()).order_by(desc(FilteredJobView.filter_date))
        available_dates = [str(date_obj[0]) for date_obj in available_dates_query.limit(30).all()]

        # Convert to response models
        job_responses = []
        for filtered_job in filtered_jobs:
            # Get the scraped job data
            scraped_job = db.query(ScrapedJob).filter(ScrapedJob.id == filtered_job.scraped_job_id).first()
            if scraped_job:
                scraped_job_response = ScrapedJobResponse.from_orm(scraped_job)

                filtered_job_response = FilteredJobViewResponse(
                    id=filtered_job.id,
                    scraped_job_id=filtered_job.scraped_job_id,
                    scraping_run_id=filtered_job.scraping_run_id,
                    filter_date=str(filtered_job.filter_date),
                    relevance_score=filtered_job.relevance_score,
                    enhanced_score=filtered_job.enhanced_score,
                    best_matching_keyword=filtered_job.best_matching_keyword,
                    ai_relevance=filtered_job.ai_relevance,
                    filter_criteria=filtered_job.filter_criteria,
                    created_at=filtered_job.created_at,
                    scraped_job=scraped_job_response
                )
                job_responses.append(filtered_job_response)

        search_params = {
            "start_date": start_date,
            "end_date": end_date,
            "days_back": days_back,
            "min_enhanced_score": min_enhanced_score,
            "ai_relevance_filter": ai_relevance_filter,
            "company_filter": company_filter,
            "location_filter": location_filter,
            "job_type_filter": job_type_filter,
            "is_remote": is_remote,
            "sort_by": sort_by,
            "sort_order": sort_order
        }

        return FilteredJobSearchResponse(
            success=True,
            message=f"Found {total_count} filtered jobs",
            total_count=total_count,
            filtered_jobs=job_responses,
            search_params=search_params,
            available_dates=available_dates,
            timestamp=datetime.now()
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching filtered jobs: {str(e)}")

@app.get("/api/filtered-jobs/dates", response_model=List[FilteredJobDateRange])
async def get_filtered_job_dates(current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get available date ranges for filtered jobs."""
    try:
        from sqlalchemy import func, desc

        # Get job counts by date for current user only
        date_counts = db.query(
            FilteredJobView.filter_date,
            func.count(FilteredJobView.id).label('job_count')
        ).filter(FilteredJobView.user_id == current_user.id).group_by(FilteredJobView.filter_date).order_by(desc(FilteredJobView.filter_date)).limit(30).all()

        ranges = []
        for date_obj, count in date_counts:
            ranges.append(FilteredJobDateRange(
                start_date=str(date_obj),
                end_date=str(date_obj),
                job_count=count
            ))

        return ranges

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting filtered job dates: {str(e)}")

@app.get("/filteredjobs")
async def filtered_jobs_page():
    """Serve the filtered jobs UI page"""
    return FileResponse("../filtered-jobs.html")

@app.get("/savedjobs")
async def saved_jobs_page():
    """Serve the saved jobs HTML page"""
    return FileResponse("../saved-jobs.html")

@app.post("/api/filtered-jobs/process-existing")
async def process_existing_scraped_jobs(
    days_back: int = Query(7, description="Process jobs from last N days"),
    min_relevance_score: float = Query(60, description="Minimum relevance score"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Process existing scraped jobs through AI filtering and populate filtered_job_views table."""
    try:
        from datetime import date, timedelta
        from sqlalchemy import and_, or_
        import pandas as pd
        
        # Get scraped jobs from the last N days
        cutoff_date = date.today() - timedelta(days=days_back)
        scraped_jobs = db.query(ScrapedJob).filter(
            and_(
                ScrapedJob.is_active == True,
                ScrapedJob.date_scraped >= cutoff_date
            )
        ).all()
        
        if not scraped_jobs:
            return {
                "success": True,
                "message": f"No scraped jobs found in the last {days_back} days",
                "processed_count": 0,
                "filtered_count": 0
            }
        
        print(f"🔄 Processing {len(scraped_jobs)} scraped jobs for filtering...")
        
        # Use the scheduler's filtering logic
        from scheduler import AutoScrapingScheduler
        scheduler = AutoScrapingScheduler()
        
        # Convert to DataFrame and calculate relevance scores
        jobs_data = []
        search_terms = ["software engineer", "product manager", "developer", "engineer"]  # Default search terms
        
        for job in scraped_jobs:
            # Calculate relevance score for each search term
            job_dict = {
                'title': job.title,
                'company': job.company,
                'location': job.location or 'Not specified',
                'description': job.description or '',
                'job_type': job.job_type or 'Not specified',
                'is_remote': job.is_remote or False,
                'min_amount': job.min_amount,
                'max_amount': job.max_amount,
                'currency': job.currency or 'USD',
                'date_posted': job.date_posted.isoformat() if job.date_posted else None,
                'scraped_job_id': job.id,
                'scraping_run_id': job.scraping_run_id
            }
            
            # Calculate relevance score using the best matching search term
            best_score = 0
            best_keyword = ""
            for search_term in search_terms:
                score = scheduler.calculate_relevance_score(job_dict, search_term)
                if score > best_score:
                    best_score = score
                    best_keyword = search_term
            
            # Get AI relevance evaluation
            ai_relevance = scheduler.evaluate_job_relevance_with_ai(job.title, job.description)
            
            jobs_data.append({
                'Title': job.title,
                'Company': job.company,
                'Location': job.location or 'Not specified',
                'Job_URL': job.job_url,
                'Description': job.description or '',
                'Job_Type': job.job_type or 'Not specified',
                'Is_Remote': job.is_remote or False,
                'Min_Salary': job.min_amount,
                'Max_Salary': job.max_amount,
                'Currency': job.currency if job.currency else 'USD',
                'Date_Posted': job.date_posted.isoformat() if job.date_posted else None,
                'Scraped_Job_ID': job.id,
                'Scraping_Run_ID': job.scraping_run_id,
                'Relevance_Score': best_score,
                'Best_Matching_Keyword': best_keyword,
                'AI_Relevance': ai_relevance
            })
        
        df = pd.DataFrame(jobs_data)
        
        # Create a temporary CSV file for processing
        import tempfile
        import os
        temp_csv = os.path.join(tempfile.gettempdir(), f"temp_scraped_jobs_{date.today().strftime('%Y%m%d')}.csv")
        df.to_csv(temp_csv, index=False)
        
        try:
            # Process through the filtering pipeline
            filtered_csv = scheduler.create_filtered_jobs_csv(temp_csv, current_user.id)
            
            if filtered_csv and os.path.exists(filtered_csv):
                # Load the filtered results
                df_filtered = pd.read_csv(filtered_csv)
                
                # Save to database
                scheduler.save_filtered_jobs_to_database(df_filtered)
                
                # Clean up temp files
                os.remove(temp_csv)
                os.remove(filtered_csv)
                
                return {
                    "success": True,
                    "message": f"Successfully processed {len(scraped_jobs)} scraped jobs",
                    "processed_count": len(scraped_jobs),
                    "filtered_count": len(df_filtered),
                    "filtered_csv": filtered_csv
                }
            else:
                return {
                    "success": False,
                    "message": "No jobs met the filtering criteria",
                    "processed_count": len(scraped_jobs),
                    "filtered_count": 0
                }
                
        except Exception as e:
            # Clean up temp file
            if os.path.exists(temp_csv):
                os.remove(temp_csv)
            raise e
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing existing jobs: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of the application"""
    print("🛑 Shutting down JobSpy API server...")
    try:
        # Stop the automated scraping scheduler if it's running
        try:
            from scheduler import stop_auto_scraping
            stop_auto_scraping()
            print("✅ Automated scraping scheduler stopped")
        except:
            print("✅ Scheduler was not running")
    except Exception as e:
        print(f"⚠️  Warning during shutdown: {e}")

if __name__ == "__main__":
    print(f"Starting JobSpy API server on {BACKEND_HOST}:{BACKEND_PORT}")
    print(f"API Documentation: http://localhost:{BACKEND_PORT}/docs")
    print(f"Health Check: http://localhost:{BACKEND_PORT}/health")
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, log_level="info" if DEBUG else "warning")