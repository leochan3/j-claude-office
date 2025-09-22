from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, JSON, Float, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
import uuid
import hashlib
import os
import re

# Database configuration: Use PostgreSQL in production, SQLite in development
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///../jobsearch.db")

# Convert postgresql:// to postgresql+psycopg:// to explicitly use psycopg3
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# SQLite-specific connection args only for SQLite databases
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # PostgreSQL with psycopg3
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    preferences = relationship("UserPreference", back_populates="user", uselist=False)
    autoscraping_config = relationship("UserAutoscrapingConfig", back_populates="user", uselist=False)
    saved_jobs = relationship("UserSavedJob", back_populates="user")
    search_history = relationship("SearchHistory", back_populates="user")

class UserPreference(Base):
    __tablename__ = "user_preferences"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Default search preferences
    default_sites = Column(JSON, default=["indeed"])  # List of preferred job sites
    default_search_term = Column(String)  # Default job title/search term
    default_company_filter = Column(String)  # Default company filter
    default_location = Column(String, default="USA")
    default_distance = Column(Integer, default=50)
    default_job_type = Column(String)  # full-time, part-time, contract, etc.
    default_remote = Column(Boolean)
    default_results_wanted = Column(Integer, default=100)
    default_hours_old = Column(Integer, default=168)  # 1 week
    default_country = Column(String, default="USA")
    default_max_experience = Column(Integer)
    default_exclude_keywords = Column(String)  # Comma-separated keywords to exclude from job titles
    
    # Salary preferences
    min_salary = Column(Integer)
    max_salary = Column(Integer)
    salary_currency = Column(String, default="USD")
    
    # Notification preferences
    email_notifications = Column(Boolean, default=True)
    job_alert_frequency = Column(String, default="daily")  # daily, weekly, none
    
    # UI preferences
    jobs_per_page = Column(Integer, default=20)
    default_sort = Column(String, default="date_posted")  # date_posted, relevance, salary
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="preferences")

class UserAutoscrapingConfig(Base):
    __tablename__ = "user_autoscraping_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)

    # Basic settings
    enabled = Column(Boolean, default=False)
    schedule_time = Column(String, default="02:00")  # HH:MM format
    max_results = Column(Integer, default=100)
    days_old = Column(Integer, default=7)

    # Site and search configuration
    sites = Column(JSON, default=["indeed", "linkedin"])  # List of job sites
    search_terms = Column(JSON, default=["software engineer", "product manager"])  # Search keywords
    exclude_keywords = Column(String, default="")  # Comma-separated exclusion keywords
    location = Column(String, default="")  # Job location
    distance = Column(Integer, default=25)  # Distance in miles/km

    # Companies and filters
    companies = Column(JSON, default=[])  # List of target companies
    min_relevance_score = Column(Integer, default=60)  # Minimum relevance score

    # AI configuration
    ai_enabled = Column(Boolean, default=True)
    ai_model = Column(String, default="gpt-4.1-nano")
    ai_prompt = Column(Text, default="Evaluate job relevance for product manager/engineer/software roles.\n\nRate as exactly one of: Highly Relevant, Somewhat Relevant, Somewhat Irrelevant, Irrelevant")
    target_roles = Column(String, default="product manager, engineer, software developer")

    # Email notifications
    email_enabled = Column(Boolean, default=True)
    notification_email = Column(String)  # Email address for notifications
    email_on_success = Column(Boolean, default=True)
    email_on_failure = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_run_at = Column(DateTime(timezone=True))

    # Relationships
    user = relationship("User", back_populates="autoscraping_config")

class UserSavedJob(Base):
    __tablename__ = "user_saved_jobs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Job data (stored as JSON)
    job_data = Column(JSON, nullable=False)
    
    # User-specific job metadata
    notes = Column(Text)
    tags = Column(JSON, default=[])  # List of user-defined tags
    
    # Job status tracking
    applied = Column(Boolean, default=False)
    applied_at = Column(DateTime(timezone=True))
    save_for_later = Column(Boolean, default=False)
    not_interested = Column(Boolean, default=False)
    interview_scheduled = Column(Boolean, default=False)
    interview_date = Column(DateTime(timezone=True))
    
    # Application tracking
    application_status = Column(String)  # applied, interview, rejected, offer, accepted
    application_notes = Column(Text)
    follow_up_date = Column(DateTime(timezone=True))
    
    # Timestamps
    saved_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="saved_jobs")

class SearchHistory(Base):
    __tablename__ = "search_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Search parameters
    search_term = Column(String, nullable=False)
    sites = Column(JSON)
    location = Column(String)
    distance = Column(Integer)
    job_type = Column(String)
    is_remote = Column(Boolean)
    results_wanted = Column(Integer)
    company_filter = Column(String)
    
    # Search results metadata
    results_count = Column(Integer)
    search_duration = Column(Integer)  # in seconds
    
    # Timestamps
    searched_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="search_history")

class SavedSearch(Base):
    __tablename__ = "saved_searches"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Search template
    name = Column(String, nullable=False)  # User-defined name for the search
    description = Column(Text)
    
    # Search parameters
    search_term = Column(String, nullable=False)
    sites = Column(JSON)
    location = Column(String)
    distance = Column(Integer)
    job_type = Column(String)
    is_remote = Column(Boolean)
    results_wanted = Column(Integer)
    company_filter = Column(String)
    
    # Alert settings
    is_alert_active = Column(Boolean, default=False)
    alert_frequency = Column(String, default="daily")  # daily, weekly
    last_alert_sent = Column(DateTime(timezone=True))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User")

class TargetCompany(Base):
    __tablename__ = "target_companies"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)  # Company name for searching
    display_name = Column(String)  # How to display the company name
    is_active = Column(Boolean, default=True)
    
    # Scraping preferences for this company
    preferred_sites = Column(JSON, default=["indeed"])  # Which sites to scrape
    search_terms = Column(JSON, default=[])  # Additional search terms for this company
    location_filters = Column(JSON, default=["USA"])  # Locations to search
    
    # Metadata
    last_scraped = Column(DateTime(timezone=True))
    total_jobs_found = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    scraped_jobs = relationship("ScrapedJob", back_populates="target_company")

class ScrapedJob(Base):
    __tablename__ = "scraped_jobs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Deduplication fields
    job_url = Column(String, index=True)  # Primary deduplication key
    job_hash = Column(String, nullable=False, index=True)  # Hash for deduplication (no longer globally unique)
    content_hash = Column(String, index=True)  # Content-based hash for cross-platform deduplication
    
    # Core job information
    title = Column(String, nullable=False, index=True)
    company = Column(String, nullable=False, index=True)
    location = Column(String, index=True)
    site = Column(String, nullable=False)  # indeed, linkedin, etc.
    
    # Job details
    description = Column(Text)
    job_type = Column(String)  # fulltime, parttime, etc.
    is_remote = Column(Boolean)
    
    # Salary information
    min_amount = Column(Float)
    max_amount = Column(Float)
    salary_interval = Column(String)  # yearly, monthly, hourly
    currency = Column(String)
    
    # Metadata
    date_posted = Column(DateTime(timezone=True))
    date_scraped = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)  # For soft deletion
    
    # Experience requirements (extracted from description)
    min_experience_years = Column(Integer)
    max_experience_years = Column(Integer)
    
    # Relationships
    target_company_id = Column(String, ForeignKey("target_companies.id"))
    target_company = relationship("TargetCompany", back_populates="scraped_jobs")
    scraping_run_id = Column(String, ForeignKey("scraping_runs.id"))
    scraping_run = relationship("ScrapingRun", back_populates="jobs")
    
    # Additional indexes for fast searching
    __table_args__ = (
        # Composite unique constraint: same job hash can exist multiple times, but not within same scraping run
        Index('idx_job_hash_run_unique', 'job_hash', 'scraping_run_id', unique=True),
        Index('idx_job_search', 'title', 'company', 'location'),
        Index('idx_job_date', 'date_posted', 'is_active'),
        Index('idx_job_salary', 'min_amount', 'max_amount'),
        Index('idx_job_experience', 'min_experience_years', 'max_experience_years'),
    )

class ScrapingRun(Base):
    __tablename__ = "scraping_runs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Run metadata
    run_type = Column(String, nullable=False)  # 'scheduled', 'manual', 'company_specific'
    status = Column(String, default='running')  # 'running', 'completed', 'failed'
    
    # Run parameters
    companies_scraped = Column(JSON)  # List of company IDs scraped
    sites_used = Column(JSON)  # Sites used for scraping
    search_parameters = Column(JSON)  # Full search parameters
    
    # Results
    total_jobs_found = Column(Integer, default=0)
    new_jobs_added = Column(Integer, default=0)
    duplicate_jobs_skipped = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Integer)
    
    # Error handling
    error_message = Column(Text)
    
    # Analytics data
    search_analytics = Column(JSON)  # Store search term performance data
    current_progress = Column(JSON)  # Real-time progress updates for UI polling
    
    # Relationships
    jobs = relationship("ScrapedJob", back_populates="scraping_run")

class DailyJobReviewList(Base):
    __tablename__ = "daily_job_review_lists"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Date and identification
    date = Column(String, nullable=False, index=True)  # Format: YYYY-MM-DD
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Configuration used for filtering
    filter_config = Column(JSON, nullable=False)  # Search terms, companies, etc.
    
    # Metadata
    total_jobs_reviewed = Column(Integer, default=0)
    jobs_selected_count = Column(Integer, default=0)
    auto_generated = Column(Boolean, default=True)
    
    # Status
    status = Column(String, default='pending')  # 'pending', 'reviewed', 'archived'
    
    # Relationships
    jobs = relationship("DailyJobReviewItem", back_populates="review_list", cascade="all, delete-orphan")
    
    # Ensure unique date per day
    __table_args__ = (
        Index('idx_daily_review_date', 'date'),
    )

class DailyJobReviewItem(Base):
    __tablename__ = "daily_job_review_items"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Relationships
    review_list_id = Column(String, ForeignKey("daily_job_review_lists.id"), nullable=False)
    review_list = relationship("DailyJobReviewList", back_populates="jobs")
    
    scraped_job_id = Column(String, ForeignKey("scraped_jobs.id"), nullable=False)
    scraped_job = relationship("ScrapedJob")
    
    # Scoring and ranking
    relevance_score = Column(Float, default=0)  # Calculated relevance score
    ai_score = Column(Float)  # Optional AI-generated score
    final_rank = Column(Integer)  # Final ranking position in the list
    
    # Review status
    user_rating = Column(Integer)  # 1-5 user rating after review
    user_notes = Column(Text)
    is_selected = Column(Boolean, default=False)  # Whether user selected this job
    is_dismissed = Column(Boolean, default=False)  # Whether user dismissed this job
    
    # Metadata
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_review_item_score', 'relevance_score', 'final_rank'),
        Index('idx_review_item_status', 'is_selected', 'is_dismissed'),
    )

class FilteredJobView(Base):
    """
    Stores daily filtered job selections with enhanced scoring.
    References existing ScrapedJob records instead of duplicating data.
    """
    __tablename__ = "filtered_job_views"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # User association - each filtered job belongs to a specific user
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Reference to the original scraped job
    scraped_job_id = Column(String, ForeignKey("scraped_jobs.id"), nullable=False)
    scraping_run_id = Column(String, ForeignKey("scraping_runs.id"), nullable=False)

    # Filtering metadata
    filter_date = Column(Date, nullable=False, index=True)  # Date when this job was filtered
    relevance_score = Column(Float, default=0)  # Base relevance score
    enhanced_score = Column(Float, default=0)   # Enhanced score with AI bonuses
    best_matching_keyword = Column(String)      # Keyword that gave highest score
    ai_relevance = Column(String)               # AI evaluation result

    # Filtering criteria used
    filter_criteria = Column(JSON)  # Store the filtering rules applied

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User")
    scraped_job = relationship("ScrapedJob", backref="filtered_views")
    scraping_run = relationship("ScrapingRun", backref="filtered_jobs")

    __table_args__ = (
        # Ensure unique job per user per filter date (prevent duplicates)
        Index('idx_filtered_job_user_date', 'user_id', 'scraped_job_id', 'filter_date', unique=True),
        Index('idx_filter_date_score', 'filter_date', 'enhanced_score'),
        Index('idx_filter_date_ai', 'filter_date', 'ai_relevance'),
        Index('idx_user_filter_date', 'user_id', 'filter_date'),
    )

def create_job_hash(title: str, company: str, location: str, job_url: str = None) -> str:
    """Create a hash for job deduplication."""
    # Keep original URL-based deduplication for exact URL matches
    if job_url and job_url.strip():
        hash_string = job_url.strip().lower()
    else:
        hash_string = f"{title.strip().lower()}|{company.strip().lower()}|{location.strip().lower()}"

    return hashlib.md5(hash_string.encode('utf-8')).hexdigest()

def create_content_hash(title: str, company: str, location: str) -> str:
    """Create a content-based hash for cross-platform deduplication."""
    # Normalize and clean the inputs for consistent hashing across platforms
    title_clean = re.sub(r'[^\w\s]', '', title.strip().lower())
    company_clean = re.sub(r'[^\w\s]', '', company.strip().lower())
    location_clean = re.sub(r'[^\w\s]', '', location.strip().lower())

    # Remove extra whitespace and standardize
    title_clean = ' '.join(title_clean.split())
    company_clean = ' '.join(company_clean.split())
    location_clean = ' '.join(location_clean.split())

    hash_string = f"{title_clean}|{company_clean}|{location_clean}"

    return hashlib.md5(hash_string.encode('utf-8')).hexdigest()

def create_tables():
    Base.metadata.create_all(bind=engine)

    # Add content_hash column to existing scraped_jobs table if it doesn't exist
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # Check if content_hash column exists
            if DATABASE_URL.startswith("sqlite"):
                result = conn.execute(text("PRAGMA table_info(scraped_jobs)"))
                columns = [row[1] for row in result.fetchall()]
                if 'content_hash' not in columns:
                    print("Adding content_hash column to scraped_jobs table...")
                    conn.execute(text("ALTER TABLE scraped_jobs ADD COLUMN content_hash VARCHAR"))
                    conn.commit()
                    print("✅ content_hash column added successfully")

                    # Populate content_hash for existing jobs
                    print("Populating content_hash for existing jobs...")
                    result = conn.execute(text("SELECT id, title, company, location FROM scraped_jobs WHERE content_hash IS NULL"))
                    jobs_to_update = result.fetchall()

                    for job in jobs_to_update:
                        job_id, title, company, location = job
                        content_hash = create_content_hash(title or '', company or '', location or '')
                        conn.execute(text("UPDATE scraped_jobs SET content_hash = :content_hash WHERE id = :job_id"),
                                   {"content_hash": content_hash, "job_id": job_id})

                    conn.commit()
                    print(f"✅ Updated content_hash for {len(jobs_to_update)} existing jobs")
            else:
                # PostgreSQL
                result = conn.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'scraped_jobs' AND column_name = 'content_hash'
                """))
                if not result.fetchone():
                    print("Adding content_hash column to scraped_jobs table...")
                    conn.execute(text("ALTER TABLE scraped_jobs ADD COLUMN content_hash VARCHAR"))
                    conn.commit()
                    print("✅ content_hash column added successfully")
    except Exception as e:
        print(f"Migration note: {e}")
        # Don't fail if migration has issues, just continue

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()