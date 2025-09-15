from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

# User Authentication Models
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# User Preferences Models
class UserPreferencesCreate(BaseModel):
    default_sites: Optional[List[str]] = ["indeed"]
    default_search_term: Optional[str] = None
    default_company_filter: Optional[str] = None
    default_location: Optional[str] = "USA"
    default_distance: Optional[int] = 50
    default_job_type: Optional[str] = None
    default_remote: Optional[bool] = None
    default_results_wanted: Optional[int] = 100
    default_hours_old: Optional[int] = 168
    default_country: Optional[str] = "USA"
    default_max_experience: Optional[int] = None
    default_exclude_keywords: Optional[str] = None
    min_salary: Optional[int] = None
    max_salary: Optional[int] = None
    salary_currency: Optional[str] = "USD"
    email_notifications: Optional[bool] = True
    job_alert_frequency: Optional[str] = "daily"
    jobs_per_page: Optional[int] = 20
    default_sort: Optional[str] = "date_posted"

class UserPreferencesUpdate(BaseModel):
    default_sites: Optional[List[str]] = None
    default_search_term: Optional[str] = None
    default_company_filter: Optional[str] = None
    default_location: Optional[str] = None
    default_distance: Optional[int] = None
    default_job_type: Optional[str] = None
    default_remote: Optional[bool] = None
    default_results_wanted: Optional[int] = None
    default_hours_old: Optional[int] = None
    default_country: Optional[str] = None
    default_max_experience: Optional[int] = None
    default_exclude_keywords: Optional[str] = None
    min_salary: Optional[int] = None
    max_salary: Optional[int] = None
    salary_currency: Optional[str] = None
    email_notifications: Optional[bool] = None
    job_alert_frequency: Optional[str] = None
    jobs_per_page: Optional[int] = None
    default_sort: Optional[str] = None

class UserPreferencesResponse(BaseModel):
    id: str
    user_id: str
    default_sites: List[str]
    default_search_term: Optional[str]
    default_company_filter: Optional[str]
    default_location: str
    default_distance: int
    default_job_type: Optional[str]
    default_remote: Optional[bool]
    default_results_wanted: int
    default_hours_old: int
    default_country: str
    default_max_experience: Optional[int]
    default_exclude_keywords: Optional[str]
    min_salary: Optional[int]
    max_salary: Optional[int]
    salary_currency: str
    email_notifications: bool
    job_alert_frequency: str
    jobs_per_page: int
    default_sort: str
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Enhanced Job Models
class SaveJobRequest(BaseModel):
    job_data: Dict[str, Any]
    notes: Optional[str] = ""
    tags: Optional[List[str]] = []

class SavedJobUpdate(BaseModel):
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    applied: Optional[bool] = None
    save_for_later: Optional[bool] = None
    not_interested: Optional[bool] = None
    interview_scheduled: Optional[bool] = None
    interview_date: Optional[datetime] = None
    application_status: Optional[str] = None
    application_notes: Optional[str] = None
    follow_up_date: Optional[datetime] = None

class SavedJobResponse(BaseModel):
    id: str
    user_id: str
    job_data: Dict[str, Any]
    notes: Optional[str]
    tags: List[str]
    applied: bool
    applied_at: Optional[datetime]
    save_for_later: bool
    not_interested: bool
    interview_scheduled: bool
    interview_date: Optional[datetime]
    application_status: Optional[str]
    application_notes: Optional[str]
    follow_up_date: Optional[datetime]
    saved_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Search History Models
class SearchHistoryResponse(BaseModel):
    id: str
    search_term: str
    sites: Optional[List[str]]
    location: Optional[str]
    distance: Optional[int]
    job_type: Optional[str]
    is_remote: Optional[bool]
    results_wanted: Optional[int]
    company_filter: Optional[str]
    results_count: Optional[int]
    search_duration: Optional[int]
    searched_at: datetime
    
    class Config:
        from_attributes = True

# Saved Search Models
class SavedSearchCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    search_term: str
    sites: Optional[List[str]] = ["indeed"]
    location: Optional[str] = None
    distance: Optional[int] = None
    job_type: Optional[str] = None
    is_remote: Optional[bool] = None
    results_wanted: Optional[int] = None
    company_filter: Optional[str] = None
    is_alert_active: Optional[bool] = False
    alert_frequency: Optional[str] = "daily"

class SavedSearchUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    search_term: Optional[str] = None
    sites: Optional[List[str]] = None
    location: Optional[str] = None
    distance: Optional[int] = None
    job_type: Optional[str] = None
    is_remote: Optional[bool] = None
    results_wanted: Optional[int] = None
    company_filter: Optional[str] = None
    is_alert_active: Optional[bool] = None
    alert_frequency: Optional[str] = None

class SavedSearchResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    search_term: str
    sites: Optional[List[str]]
    location: Optional[str]
    distance: Optional[int]
    job_type: Optional[str]
    is_remote: Optional[bool]
    results_wanted: Optional[int]
    company_filter: Optional[str]
    is_alert_active: bool
    alert_frequency: str
    last_alert_sent: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Enhanced Job Search Request with User Context
class AuthenticatedJobSearchRequest(BaseModel):
    site_name: Optional[List[str]] = None  # Will use user preferences if None
    search_term: str
    company_filter: Optional[str] = None
    location: Optional[str] = None  # Will use user preferences if None
    distance: Optional[int] = None  # Will use user preferences if None
    job_type: Optional[str] = None  # Will use user preferences if None
    is_remote: Optional[bool] = None  # Will use user preferences if None
    results_wanted: Optional[int] = None  # Will use user preferences if None
    hours_old: Optional[int] = None  # Will use user preferences if None
    country_indeed: Optional[str] = None  # Will use user preferences if None
    max_years_experience: Optional[int] = None  # Will use user preferences if None
    exclude_keywords: Optional[str] = None  # Will use user preferences if None
    save_search: Optional[bool] = False  # Whether to save this search to history

# Target Company Management Models
class TargetCompanyCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    preferred_sites: Optional[List[str]] = ["indeed"]
    search_terms: Optional[List[str]] = []
    location_filters: Optional[List[str]] = ["USA"]

class TargetCompanyUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    preferred_sites: Optional[List[str]] = None
    search_terms: Optional[List[str]] = None
    location_filters: Optional[List[str]] = None
    is_active: Optional[bool] = None

class TargetCompanyResponse(BaseModel):
    id: str
    name: str
    display_name: Optional[str]
    is_active: bool
    preferred_sites: List[str]
    search_terms: List[str]
    location_filters: List[str]
    last_scraped: Optional[datetime]
    total_jobs_found: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Scraped Job Models
class ScrapedJobResponse(BaseModel):
    id: str
    job_url: Optional[str]
    title: str
    company: str
    location: Optional[str]
    site: str
    description: Optional[str]
    job_type: Optional[str]
    is_remote: Optional[bool]
    min_amount: Optional[float]
    max_amount: Optional[float]
    salary_interval: Optional[str]
    currency: Optional[str]
    date_posted: Optional[datetime]
    date_scraped: datetime
    min_experience_years: Optional[int]
    max_experience_years: Optional[int]
    target_company_id: Optional[str]
    
    @validator('currency', pre=True)
    def ensure_currency_default(cls, v):
        return v if v is not None else 'USD'
    
    class Config:
        from_attributes = True

class ScrapedJobSearchRequest(BaseModel):
    search_term: Optional[str] = None
    company_names: Optional[List[str]] = None
    locations: Optional[List[str]] = None
    job_types: Optional[List[str]] = None
    is_remote: Optional[bool] = None
    min_salary: Optional[float] = None
    max_salary: Optional[float] = None
    max_experience_years: Optional[int] = None
    sites: Optional[List[str]] = None
    days_old: Optional[int] = 30  # Default to last 30 days
    limit: Optional[int] = 10000
    offset: Optional[int] = 0
    exclude_keywords: Optional[str] = None  # Comma-separated keywords to exclude from job titles

class ScrapedJobSearchResponse(BaseModel):
    success: bool
    message: str
    total_count: int
    jobs: List[ScrapedJobResponse]
    search_params: Dict[str, Any]
    timestamp: datetime

# Job Scraping Models
class ScrapingRunCreate(BaseModel):
    run_type: str = "manual"  # 'scheduled', 'manual', 'company_specific'
    company_ids: Optional[List[str]] = None  # Specific companies to scrape
    sites: Optional[List[str]] = ["indeed"]
    search_terms: Optional[List[str]] = []
    locations: Optional[List[str]] = ["USA"]
    results_per_company: Optional[int] = 100

class ScrapingRunResponse(BaseModel):
    id: str
    run_type: str
    status: str
    companies_scraped: Optional[List[str]]
    sites_used: Optional[List[str]]
    search_parameters: Optional[Dict[str, Any]]
    total_jobs_found: int
    new_jobs_added: int
    duplicate_jobs_skipped: int
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    error_message: Optional[str]
    search_analytics: Optional[Dict[str, Dict[str, int]]] = None
    
    class Config:
        from_attributes = True

class BulkScrapingRequest(BaseModel):
    company_names: List[str]  # List of company names to scrape
    search_terms: Optional[List[str]] = []
    sites: Optional[List[str]] = ["indeed"]
    locations: Optional[List[str]] = ["USA"]
    results_per_company: Optional[int] = 1000
    hours_old: Optional[int] = 72  # 3 days
    comprehensive_terms: Optional[List[str]] = []
    auto_scraping: Optional[bool] = False  # Flag to indicate if this is automated scraping
    job_types: Optional[List[str]] = []  # Job types to filter by
    days_old: Optional[int] = None  # Alternative to hours_old for consistency
    is_remote: Optional[bool] = None  # Remote job preference

# Comprehensive Search Terms Models
class ComprehensiveTermsCreate(BaseModel):
    terms: List[str]

class ComprehensiveTermsResponse(BaseModel):
    terms: List[str]
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Scraping Default Settings Models
class ScrapingDefaultsCreate(BaseModel):
    companies: Optional[List[str]] = None
    search_terms: Optional[List[str]] = None
    locations: Optional[List[str]] = None
    results_per_company: Optional[int] = None
    hours_old: Optional[int] = None

class ScrapingDefaultsResponse(BaseModel):
    companies: Optional[List[str]]
    search_terms: Optional[List[str]]
    locations: Optional[List[str]]
    results_per_company: Optional[int]
    hours_old: Optional[int]
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Daily Job Review Models
class DailyJobReviewItemResponse(BaseModel):
    id: str
    scraped_job_id: str
    relevance_score: float
    ai_score: Optional[float]
    final_rank: int
    user_rating: Optional[int]
    user_notes: Optional[str]
    is_selected: bool
    is_dismissed: bool
    added_at: datetime
    reviewed_at: Optional[datetime]
    
    # Include the actual job data
    job: ScrapedJobResponse
    
    class Config:
        from_attributes = True

class DailyJobReviewListResponse(BaseModel):
    id: str
    date: str
    created_at: datetime
    updated_at: Optional[datetime]
    filter_config: Dict[str, Any]
    total_jobs_reviewed: int
    jobs_selected_count: int
    auto_generated: bool
    status: str
    
    jobs: List[DailyJobReviewItemResponse]
    
    class Config:
        from_attributes = True

class DailyJobReviewListSummary(BaseModel):
    id: str
    date: str
    total_jobs_reviewed: int
    jobs_selected_count: int
    jobs_count: int  # Number of jobs in the review list
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class UpdateReviewItemRequest(BaseModel):
    is_selected: Optional[bool] = None
    is_dismissed: Optional[bool] = None
    user_rating: Optional[int] = None
    user_notes: Optional[str] = None

class CreateDailyReviewRequest(BaseModel):
    target_date: Optional[str] = None  # YYYY-MM-DD format, defaults to today
    force_recreate: bool = False

# Filtered Job View Models
class FilteredJobViewResponse(BaseModel):
    id: str
    scraped_job_id: str
    scraping_run_id: str
    filter_date: str  # YYYY-MM-DD format
    relevance_score: float
    enhanced_score: float
    best_matching_keyword: Optional[str]
    ai_relevance: Optional[str]
    filter_criteria: Optional[Dict[str, Any]]
    created_at: datetime

    # Include the scraped job data
    scraped_job: ScrapedJobResponse

    class Config:
        from_attributes = True

class FilteredJobSearchRequest(BaseModel):
    start_date: Optional[str] = None  # YYYY-MM-DD format
    end_date: Optional[str] = None    # YYYY-MM-DD format
    days_back: Optional[int] = 1      # Alternative to date range: get last N days
    min_enhanced_score: Optional[float] = None
    ai_relevance_filter: Optional[List[str]] = None  # ["Highly Relevant", "Somewhat Relevant"]
    company_filter: Optional[str] = None
    location_filter: Optional[str] = None
    job_type_filter: Optional[str] = None
    is_remote: Optional[bool] = None
    limit: Optional[int] = 100
    offset: Optional[int] = 0
    sort_by: Optional[str] = "enhanced_score"  # "enhanced_score", "filter_date", "date_posted"
    sort_order: Optional[str] = "desc"  # "asc", "desc"

class FilteredJobSearchResponse(BaseModel):
    success: bool
    message: str
    total_count: int
    filtered_jobs: List[FilteredJobViewResponse]
    search_params: Dict[str, Any]
    available_dates: List[str]  # Available filter dates
    timestamp: datetime

class FilteredJobDateRange(BaseModel):
    start_date: str
    end_date: str
    job_count: int