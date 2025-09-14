"""
Automated Job Scraping Scheduler

This module handles automatic daily job scraping for all active target companies.
It runs as a background service and can be configured through environment variables.
"""

import asyncio
import schedule
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
import os
import logging
import json
import smtplib
import csv
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from sqlalchemy.orm import Session

from database import SessionLocal, TargetCompany
from job_scraper import job_scraper
from models import BulkScrapingRequest
from daily_job_review import daily_job_reviewer
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutoScrapingScheduler:
    """Handles automatic daily job scraping for target companies."""
    
    def __init__(self):
        self.job_scraper = job_scraper  # Use the global instance
        self.is_running = False
        self.scheduler_thread = None
        
        # Configuration from environment variables
        self.enabled = os.getenv("AUTO_SCRAPING_ENABLED", "true").lower() == "true"
        self.schedule_time = os.getenv("AUTO_SCRAPING_TIME", "20:55")  # Default: 8:55 PM
        self.max_results_per_company = int(os.getenv("AUTO_SCRAPING_MAX_RESULTS", "100"))
        self.default_search_terms = os.getenv("AUTO_SCRAPING_SEARCH_TERMS", "").split(",")
        self.default_search_terms = [term.strip() for term in self.default_search_terms if term.strip()]
        
        if not self.default_search_terms:
            self.default_search_terms = ["clinical", "medical", "research", "regulatory", "quality", "scientist", "manager", "director", "analyst", "biomedical"]
        
        # Email notification configuration
        self.email_enabled = os.getenv("EMAIL_NOTIFICATIONS_ENABLED", "false").lower() == "true"
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.email_user = os.getenv("EMAIL_USER", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")
        self.notification_email = os.getenv("NOTIFICATION_EMAIL", "")

        # OpenAI configuration for AI relevance evaluation
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        self.openai_client = None
        if self.openai_api_key and self.openai_api_key != "your_openai_api_key_here":
            try:
                self.openai_client = OpenAI(api_key=self.openai_api_key)
                logger.info("OpenAI client initialized for AI relevance evaluation")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
        else:
            logger.info("OpenAI API key not configured - AI relevance evaluation will be skipped")

        logger.info(f"AutoScrapingScheduler initialized:")
        logger.info(f"  - Enabled: {self.enabled}")
        logger.info(f"  - Schedule time: {self.schedule_time}")
        logger.info(f"  - Max results per company: {self.max_results_per_company}")
        logger.info(f"  - Default search terms: {self.default_search_terms}")
        logger.info(f"  - Email notifications: {self.email_enabled}")
    
    def get_active_companies(self) -> List[TargetCompany]:
        """Get target companies for scraping based on saved defaults or all active companies."""
        db = SessionLocal()
        try:
            # First, try to load companies from scraping defaults
            default_companies = self._get_default_company_names()
            
            if default_companies:
                # Use specific companies from defaults
                companies = []
                for company_name in default_companies:
                    # Try exact match first
                    company = db.query(TargetCompany).filter(
                        TargetCompany.name.ilike(company_name),
                        TargetCompany.is_active == True
                    ).first()
                    
                    # If not found, try partial match
                    if not company:
                        company = db.query(TargetCompany).filter(
                            TargetCompany.name.ilike(f"%{company_name}%"),
                            TargetCompany.is_active == True
                        ).first()
                    
                    if company:
                        companies.append(company)
                        logger.info(f"✅ Found target company: {company.name}")
                    else:
                        # Auto-create missing company
                        logger.info(f"🔧 Company '{company_name}' not found in database, creating it automatically...")
                        new_company = self._create_target_company(db, company_name)
                        if new_company:
                            companies.append(new_company)
                            logger.info(f"✅ Created and added target company: {new_company.name}")
                        else:
                            logger.warning(f"❌ Failed to create company: {company_name}")
                
                if companies:
                    logger.info(f"🎯 Using {len(companies)} specific target companies from defaults")
                    return companies
                else:
                    logger.warning("❌ No valid companies found from defaults, falling back to all companies")
            
            # Fallback: use all active companies
            companies = db.query(TargetCompany).filter(
                TargetCompany.is_active == True
            ).all()
            logger.info(f"Found {len(companies)} active target companies (using all companies)")
            return companies
        finally:
            db.close()
    
    def _get_default_company_names(self) -> List[str]:
        """Get default company names from scraping defaults file."""
        try:
            defaults_file = "scraping_defaults.json"
            if os.path.exists(defaults_file):
                with open(defaults_file, 'r') as f:
                    data = json.load(f)
                    companies = data.get('companies', [])
                    if companies:
                        logger.info(f"📋 Loaded {len(companies)} default companies: {', '.join(companies)}")
                        return companies
        except Exception as e:
            logger.error(f"Error loading default companies: {e}")
        
        return []
    
    def _create_target_company(self, db: Session, company_name: str) -> Optional[TargetCompany]:
        """Create a new target company in the database with sensible defaults."""
        try:
            # Get default search terms from config
            default_search_terms = self._get_default_search_terms()
            
            # Create new company with intelligent defaults
            new_company = TargetCompany(
                name=company_name.title(),  # Capitalize properly
                display_name=company_name.title(),
                preferred_sites=["indeed", "linkedin", "glassdoor"],
                search_terms=default_search_terms,
                location_filters=["USA", "United States"],
                is_active=True
            )
            
            db.add(new_company)
            db.commit()
            db.refresh(new_company)
            
            logger.info(f"🏢 Auto-created target company: {new_company.name}")
            logger.info(f"   Search terms: {new_company.search_terms}")
            logger.info(f"   Sites: {new_company.preferred_sites}")
            
            return new_company
            
        except Exception as e:
            logger.error(f"Failed to create target company '{company_name}': {e}")
            db.rollback()
            return None
    
    def _get_default_hours_old(self) -> int:
        """Get default hours_old from scraping defaults file."""
        try:
            defaults_file = "scraping_defaults.json"
            if os.path.exists(defaults_file):
                with open(defaults_file, 'r') as f:
                    data = json.load(f)
                    hours_old = data.get('hours_old')
                    if hours_old:
                        logger.info(f"⏰ Loaded default hours_old: {hours_old} hours ({hours_old/24:.1f} days)")
                        return hours_old
        except Exception as e:
            logger.error(f"Error loading default hours_old: {e}")
        
        # Default fallback
        return 168  # 7 days
    
    def _get_default_results_per_company(self) -> int:
        """Get default results_per_company from scraping defaults file."""
        try:
            defaults_file = "scraping_defaults.json"
            if os.path.exists(defaults_file):
                with open(defaults_file, 'r') as f:
                    data = json.load(f)
                    results = data.get('results_per_company')
                    if results:
                        logger.info(f"🔢 Loaded default results_per_company: {results}")
                        return results
        except Exception as e:
            logger.error(f"Error loading default results_per_company: {e}")
        
        # Fallback to environment variable or default
        return self.max_results_per_company
    
    def _get_scoring_config(self) -> dict:
        """Get scoring configuration from scraping defaults file."""
        try:
            defaults_file = "scraping_defaults.json"
            if os.path.exists(defaults_file):
                with open(defaults_file, 'r') as f:
                    data = json.load(f)
                    
                    # Support both single keyword (backward compatibility) and multiple keywords
                    keywords = []
                    if 'scoring_keywords' in data and isinstance(data['scoring_keywords'], list):
                        keywords = [kw.strip() for kw in data['scoring_keywords'] if kw.strip()]
                    elif 'scoring_keyword' in data and data['scoring_keyword']:
                        keywords = [data['scoring_keyword'].strip()]
                    
                    config = {
                        'scoring_keywords': keywords,
                        'expected_salary': data.get('expected_salary', 0)
                    }
                    logger.info(f"🔧 Loaded scoring config: keywords={keywords}, salary={config['expected_salary']}")
                    return config
        except Exception as e:
            logger.error(f"Error loading scoring config: {e}")
        
        return {'scoring_keywords': [], 'expected_salary': 0}
    
    def calculate_relevance_score(self, job: Dict[str, Any], search_term: str, expected_salary: int = None) -> int:
        """Calculate job relevance score using the same logic as the main app."""
        score = 0
        if not search_term or not search_term.strip():
            return 0
        
        # Get job details
        title = (job.get('title', '') or '').lower().strip()
        description = (job.get('description', '') or '').lower().strip()
        company = (job.get('company', '') or '').lower().strip()
        search = search_term.lower().strip()
        
        # Split search term into words, filter out common stop words
        stop_words = {'and', 'or', 'the', 'a', 'an', 'in', 'at', 'for', 'with', 'by', 'to', 'of', 'from'}
        search_words = [word for word in search.split() if len(word) > 1 and word not in stop_words]
        
        if not search_words:
            return 0
        
        # 1. Exact title match (highest score)
        if title == search:
            score += 100
        
        # 2. Title contains full search phrase
        if search in title:
            score += 80
        
        # 3. All search words in title (high score)
        title_words = title.split()
        title_words_matched = [sw for sw in search_words if any(sw in tw or tw in sw for tw in title_words)]
        
        if len(title_words_matched) == len(search_words):
            score += 60  # All words found
        elif title_words_matched:
            score += (len(title_words_matched) / len(search_words)) * 40  # Partial match
        
        # 4. Individual word matches in title (position matters)
        for search_word in search_words:
            for title_index, title_word in enumerate(title_words):
                if search_word in title_word:
                    # Earlier position in title = higher score
                    position_bonus = max(0, 10 - title_index * 2)
                    score += 15 + position_bonus
                elif title_word in search_word and len(title_word) > 2:
                    score += 8  # Partial word match
        
        # 5. Description matches (lower weight)
        if description:
            for search_word in search_words:
                matches = description.count(search_word)
                if matches:
                    score += min(matches * 5, 20)  # Cap at 20 points per word
            
            # Bonus for search phrase in description
            if search in description:
                score += 15
        
        # 6. Company name relevance (small bonus)
        if company:
            for search_word in search_words:
                if search_word in company:
                    score += 5
        
        # 7. Job type matching bonus
        job_type = (job.get('job_type', '') or '').lower()
        if job_type and (search in job_type or ('full' in job_type and 'full' in search)):
            score += 8
        
        # 8. Salary matching with rewards and penalties
        if expected_salary and expected_salary > 0:
            min_salary = job.get('min_amount')
            max_salary = job.get('max_amount')
            
            if min_salary and max_salary:
                # Calculate median salary for the job
                median_job_salary = (min_salary + max_salary) / 2
                salary_diff = abs(expected_salary - median_job_salary)
                percentage_diff = salary_diff / expected_salary
                
                # Salary scoring with rewards and penalties
                if percentage_diff <= 0.15:
                    salary_score = 30  # Within 15% - excellent match
                elif percentage_diff <= 0.25:
                    salary_score = 25  # Within 25% - very good match
                elif percentage_diff <= 0.40:
                    salary_score = 10  # Within 40% - acceptable match
                elif percentage_diff <= 0.60:
                    salary_score = -15  # 40-60% - penalty for poor match
                elif percentage_diff <= 0.80:
                    salary_score = -30  # 60-80% - bigger penalty
                else:
                    salary_score = -50  # Above 80% - major penalty
                
                score += salary_score
                
            elif min_salary or max_salary:
                # Only one salary bound available
                available_salary = min_salary or max_salary
                salary_diff = abs(expected_salary - available_salary)
                percentage_diff = salary_diff / expected_salary
                
                # Same scoring logic for partial data
                if percentage_diff <= 0.15:
                    salary_score = 30
                elif percentage_diff <= 0.25:
                    salary_score = 25
                elif percentage_diff <= 0.40:
                    salary_score = 10
                elif percentage_diff <= 0.60:
                    salary_score = -15
                elif percentage_diff <= 0.80:
                    salary_score = -30
                else:
                    salary_score = -50
                
                score += salary_score
            else:
                # No salary data - give small bonus as neutral reward
                score += 10
        
        # 9. Recency bonus (newer posts get higher ranking)
        if job.get('date_posted'):
            try:
                from datetime import datetime
                post_date = datetime.fromisoformat(str(job['date_posted']).replace('Z', '+00:00'))
                now = datetime.now(post_date.tzinfo)
                days_since_posted = (now - post_date).days
                
                # Recency bonus: max 15 points for posts within last week, declining over time
                if days_since_posted <= 1:
                    score += 15  # Posted within last day
                elif days_since_posted <= 3:
                    score += 12  # Posted within last 3 days
                elif days_since_posted <= 7:
                    score += 8   # Posted within last week
                elif days_since_posted <= 14:
                    score += 5   # Posted within last 2 weeks
                elif days_since_posted <= 30:
                    score += 2   # Posted within last month
            except:
                # Invalid date, skip recency bonus
                pass
        
        return round(score)
    
    def calculate_multi_keyword_score(self, job: Dict[str, Any], keywords: List[str], expected_salary: int = None) -> Dict[str, Any]:
        """Calculate relevance scores for multiple keywords and return the highest score."""
        if not keywords:
            logger.info("🔍 No keywords provided for scoring")
            return {'score': 0, 'best_keyword': '', 'all_scores': {}}
        
        all_scores = {}
        best_score = 0
        best_keyword = ''
        
        for keyword in keywords:
            if keyword.strip():
                score = self.calculate_relevance_score(job, keyword.strip(), expected_salary)
                all_scores[keyword] = score
                
                if score > best_score:
                    best_score = score
                    best_keyword = keyword
        
        return {
            'score': best_score,
            'best_keyword': best_keyword,
            'all_scores': all_scores
        }
    
    def _get_default_search_terms(self) -> List[str]:
        """Get default search terms from scraping defaults file."""
        try:
            defaults_file = "scraping_defaults.json"
            if os.path.exists(defaults_file):
                with open(defaults_file, 'r') as f:
                    data = json.load(f)
                    search_terms = data.get('search_terms', [])
                    if search_terms:
                        logger.info(f"📝 Loaded {len(search_terms)} default search terms: {', '.join(search_terms)}")
                        return search_terms
        except Exception as e:
            logger.error(f"Error loading default search terms: {e}")
        
        return []

    def evaluate_job_relevance_with_ai(self, job_title: str, job_description: str = None) -> str:
        """
        Use AI to evaluate job relevance and return one of four levels:
        'Highly Relevant', 'Somewhat Relevant', 'Somewhat Irrelevant', 'Irrelevant'

        If job_description is empty, use job_title only.
        """
        if not self.openai_client:
            return "AI Not Configured"

        try:
            # Use description if available, otherwise fall back to title
            content_to_analyze = job_description.strip() if job_description and job_description.strip() else job_title.strip()

            if not content_to_analyze:
                return "No Content"

            # Create simplified prompt for GPT-5 Nano
            job_content = f"Title: {job_title}"
            if content_to_analyze != job_title:
                # Truncate description to keep token usage low
                description_short = content_to_analyze[:300]
                job_content += f"\nDescription: {description_short}"

            prompt = f"""Evaluate job relevance for product manager/engineer/software roles.

{job_content}

Rate as exactly one of: Highly Relevant, Somewhat Relevant, Somewhat Irrelevant, Irrelevant"""

            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "You are a job relevance evaluator. Respond with only the exact relevance level."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=15,
                temperature=0.1
            )

            relevance = response.choices[0].message.content.strip()

            # Validate response is one of the expected values
            valid_responses = ["Highly Relevant", "Somewhat Relevant", "Somewhat Irrelevant", "Irrelevant"]
            if relevance not in valid_responses:
                logger.warning(f"AI returned unexpected relevance: {relevance}")
                return "AI Error"

            return relevance

        except Exception as e:
            logger.error(f"Error in AI job relevance evaluation: {e}")
            return "AI Error"

    def create_filtered_jobs_csv(self, original_csv_path: str) -> str:
        """
        Create a filtered and scored CSV based on relevance criteria.

        Filtering rules:
        1. Remove jobs with Relevance_Score < 60
        2. Remove jobs where AI_Relevance = "Irrelevant"
        3. Exclude jobs with "president", "director", "VP" in title
        4. Boost scores based on AI_Relevance:
           - "Highly Relevant": +50
           - "Somewhat Relevant": +25
           - "Somewhat Irrelevant": +0
        5. Sort by final score (descending)
        """
        try:
            import pandas as pd

            # Read the original CSV
            df = pd.read_csv(original_csv_path)
            logger.info(f"📊 Processing {len(df)} jobs for filtering...")

            # Initial count
            original_count = len(df)

            # Filter 1: Remove low relevance scores (< 60)
            df = df[df['Relevance_Score'] >= 60]
            after_score_filter = len(df)
            logger.info(f"🔍 After relevance score filter (≥60): {after_score_filter} jobs remaining")

            # Filter 2: Remove "Irrelevant" AI evaluations
            df = df[df['AI_Relevance'] != 'Irrelevant']
            after_ai_filter = len(df)
            logger.info(f"🤖 After AI relevance filter (not Irrelevant): {after_ai_filter} jobs remaining")

            # Filter 3: Exclude executive positions
            exclusion_keywords = ['president', 'director', 'vp', 'vice president', 'chief', 'head of']
            title_mask = True
            for keyword in exclusion_keywords:
                title_mask = title_mask & (~df['Title'].str.contains(keyword, case=False, na=False))

            df = df[title_mask]
            after_title_filter = len(df)
            logger.info(f"🚫 After title exclusion filter: {after_title_filter} jobs remaining")

            if len(df) == 0:
                logger.warning("⚠️ No jobs remaining after filtering!")
                return None

            # Create enhanced score based on AI relevance
            def calculate_enhanced_score(row):
                base_score = row['Relevance_Score']
                ai_relevance = row['AI_Relevance']

                if ai_relevance == 'Highly Relevant':
                    return base_score + 50
                elif ai_relevance == 'Somewhat Relevant':
                    return base_score + 25
                elif ai_relevance == 'Somewhat Irrelevant':
                    return base_score  # No boost
                else:
                    return base_score  # For any unexpected values

            df['Enhanced_Score'] = df.apply(calculate_enhanced_score, axis=1)

            # Sort by enhanced score (descending)
            df = df.sort_values('Enhanced_Score', ascending=False)

            # Create filtered CSV filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filtered_csv_filename = f"jobspy_filtered_jobs_{timestamp}.csv"

            # Reorder columns to show Enhanced_Score prominently
            columns = ['Enhanced_Score', 'Company', 'Title', 'Location', 'Description',
                      'Salary_Min', 'Salary_Max', 'Salary_Interval', 'Currency',
                      'Date_Posted', 'Date_Scraped', 'Job_URL', 'Site', 'Job_Type',
                      'Is_Remote', 'Min_Experience_Years', 'Max_Experience_Years',
                      'Relevance_Score', 'Best_Matching_Keyword', 'AI_Relevance']

            # Ensure all columns exist (in case some are missing)
            available_columns = [col for col in columns if col in df.columns]
            df_filtered = df[available_columns]

            # Save filtered CSV
            df_filtered.to_csv(filtered_csv_filename, index=False)

            # Log filtering summary
            logger.info(f"📋 FILTERING SUMMARY:")
            logger.info(f"   📥 Original jobs: {original_count}")
            logger.info(f"   🎯 After relevance score ≥60: {after_score_filter}")
            logger.info(f"   🤖 After AI relevance filter: {after_ai_filter}")
            logger.info(f"   🚫 After title exclusions: {after_title_filter}")
            logger.info(f"   📤 Final filtered list: {len(df_filtered)} jobs")
            logger.info(f"   📈 Top enhanced score: {df_filtered['Enhanced_Score'].max():.0f}")
            logger.info(f"   📉 Lowest enhanced score: {df_filtered['Enhanced_Score'].min():.0f}")

            # Log top 3 jobs for preview
            logger.info(f"🏆 TOP 3 FILTERED JOBS:")
            for i, (_, job) in enumerate(df_filtered.head(3).iterrows()):
                logger.info(f"   {i+1}. {job['Title']} at {job['Company']} (Score: {job['Enhanced_Score']:.0f})")

            logger.info(f"📄 Created filtered CSV: {filtered_csv_filename}")
            return filtered_csv_filename

        except Exception as e:
            logger.error(f"Error creating filtered CSV: {e}")
            return None

    def create_jobs_csv(self, scraping_run_id: int) -> str:
        """Create a CSV file with the jobs from the latest scraping run."""
        try:
            db = SessionLocal()
            try:
                from database import ScrapedJob
                
                # Get jobs from the specific scraping run
                jobs = db.query(ScrapedJob).filter(
                    ScrapedJob.scraping_run_id == scraping_run_id
                ).all()
                
                if not jobs:
                    logger.warning("No jobs found for CSV export")
                    return None
                
                # Get scoring configuration
                scoring_config = self._get_scoring_config()
                scoring_keywords = scoring_config.get('scoring_keywords', [])
                expected_salary = scoring_config.get('expected_salary', 0)
                
                if scoring_keywords:
                    logger.info(f"📊 Applying relevance scoring with keywords: {scoring_keywords}, expected salary: ${expected_salary:,}")
                else:
                    logger.info("📊 No scoring keywords configured - all jobs will have score 0")
                
                # Create CSV content
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header with Relevance_Score, Best_Keyword, and AI_Relevance columns
                writer.writerow([
                    'Company', 'Title', 'Location', 'Description', 'Salary_Min', 'Salary_Max',
                    'Salary_Interval', 'Currency', 'Date_Posted', 'Date_Scraped', 'Job_URL',
                    'Site', 'Job_Type', 'Is_Remote', 'Min_Experience_Years', 'Max_Experience_Years',
                    'Relevance_Score', 'Best_Matching_Keyword', 'AI_Relevance'
                ])
                
                # Write job data with relevance scores
                jobs_with_scores = 0
                for job_index, job in enumerate(jobs):
                    # Convert job to dict for scoring function
                    job_dict = {
                        'title': job.title,
                        'description': job.description,
                        'company': job.company,
                        'job_type': job.job_type,
                        'min_amount': job.min_amount,
                        'max_amount': job.max_amount,
                        'date_posted': job.date_posted
                    }
                    
                    # Calculate relevance score for multiple keywords
                    relevance_score = 0
                    best_keyword = ''
                    if scoring_keywords:
                        scoring_result = self.calculate_multi_keyword_score(
                            job_dict, 
                            scoring_keywords, 
                            expected_salary if expected_salary > 0 else None
                        )
                        relevance_score = scoring_result['score']
                        best_keyword = scoring_result['best_keyword']
                        
                        # Log first few scores for debugging
                        if job_index < 3:
                            logger.info(f"🔍 Job {job_index+1}: '{job.title}' scored {relevance_score} (best: '{best_keyword}')")
                        if relevance_score > 0:
                            jobs_with_scores += 1

                    # Get AI relevance evaluation
                    ai_relevance = "Not Evaluated"
                    if self.openai_client:
                        try:
                            ai_relevance = self.evaluate_job_relevance_with_ai(
                                job.title or '',
                                job.description or ''
                            )
                            # Log AI evaluation for first few jobs
                            if job_index < 3:
                                logger.info(f"🤖 AI evaluation for '{job.title}': {ai_relevance}")
                        except Exception as e:
                            logger.warning(f"AI evaluation failed for job {job_index+1}: {e}")
                            ai_relevance = "AI Error"
                    else:
                        ai_relevance = "AI Not Configured"

                    writer.writerow([
                        job.company or '',
                        job.title or '',
                        job.location or '',
                        (job.description or '').replace('\n', ' ').replace('\r', '') if job.description else '',
                        job.min_amount or '',
                        job.max_amount or '',
                        job.salary_interval or '',
                        job.currency or '',
                        job.date_posted.strftime('%Y-%m-%d') if job.date_posted else '',
                        job.date_scraped.strftime('%Y-%m-%d %H:%M:%S') if job.date_scraped else '',
                        job.job_url or '',
                        job.site or '',
                        job.job_type or '',
                        'Yes' if job.is_remote else 'No',
                        job.min_experience_years or '',
                        job.max_experience_years or '',
                        relevance_score,
                        best_keyword,
                        ai_relevance
                    ])
                
                # Save to temporary file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_filename = f"jobspy_daily_scraping_{timestamp}.csv"
                
                with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                    f.write(output.getvalue())
                
                # Log scoring summary if keywords were used
                ai_status = "with AI relevance evaluation" if self.openai_client else "without AI evaluation (OpenAI not configured)"
                if scoring_keywords:
                    logger.info(f"📄 Created CSV export: {csv_filename} with {len(jobs)} jobs, multi-keyword relevance scores, {ai_status}")
                    logger.info(f"📊 Scoring keywords used: {', '.join(scoring_keywords)}")
                    logger.info(f"📊 Jobs with scores > 0: {jobs_with_scores} out of {len(jobs)}")
                else:
                    logger.info(f"📄 Created CSV export: {csv_filename} with {len(jobs)} jobs (no keyword scoring applied), {ai_status}")

                # Create filtered version if AI evaluation is available
                filtered_csv_filename = None
                if self.openai_client:
                    logger.info("🎯 Creating filtered and enhanced CSV...")
                    filtered_csv_filename = self.create_filtered_jobs_csv(csv_filename)

                # Return both filenames as a tuple
                return csv_filename, filtered_csv_filename
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error creating jobs CSV: {e}")
            return None
    
    def send_notification_email(self, summary: dict, csv_filename: str = None, filtered_csv_filename: str = None):
        """Send email notification with scraping results."""
        if not self.email_enabled or not self.notification_email:
            logger.info("📧 Email notifications disabled or email not configured")
            return
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.email_user
            msg['To'] = self.notification_email
            msg['Subject'] = f"🤖 JobSpy Daily Scraping Report - {summary.get('date', 'Unknown')}"
            
            # Create email body
            body = f"""
JobSpy Daily Scraping Report
============================

📊 SUMMARY:
• Total Companies Scraped: {summary.get('companies_scraped', 0)}
• Total Jobs Found: {summary.get('total_jobs', 0)}
• New Jobs Added: {summary.get('new_jobs', 0)}
• Duration: {summary.get('duration', 'Unknown')}
• Success Rate: {summary.get('success_rate', 'Unknown')}

🏢 COMPANIES:
{summary.get('company_details', 'No details available')}

🔍 SEARCH TERMS USED:
{', '.join(summary.get('search_terms', []))}

⏰ SCRAPING TIME:
Started: {summary.get('start_time', 'Unknown')}
Completed: {summary.get('end_time', 'Unknown')}

📎 ATTACHMENTS:
{"• Complete Job List: JobSpy_Daily_Jobs.csv - All scraped jobs with AI analysis" if csv_filename else ""}
{"• Filtered Job List: JobSpy_Filtered_Jobs.csv - High-quality jobs (score ≥60, no executives)" if filtered_csv_filename else ""}

---
Generated by JobSpy Automated Scraping System
            """.strip()
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach original CSV file if provided
            if csv_filename and os.path.exists(csv_filename):
                with open(csv_filename, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())

                encoders.encode_base64(part)
                # Create a more user-friendly filename for the attachment
                attachment_filename = f"JobSpy_Daily_Jobs_{summary.get('date', datetime.now().strftime('%Y-%m-%d'))}.csv"
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{attachment_filename}"'
                )
                msg.attach(part)
                logger.info(f"📎 Attached complete CSV: {attachment_filename} ({summary.get('total_jobs', 0)} jobs included)")

            # Attach filtered CSV file if provided
            if filtered_csv_filename and os.path.exists(filtered_csv_filename):
                with open(filtered_csv_filename, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())

                encoders.encode_base64(part)
                # Create a more user-friendly filename for the filtered attachment
                filtered_attachment_filename = f"JobSpy_Filtered_Jobs_{summary.get('date', datetime.now().strftime('%Y-%m-%d'))}.csv"
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{filtered_attachment_filename}"'
                )
                msg.attach(part)
                logger.info(f"📎 Attached filtered CSV: {filtered_attachment_filename} (high-quality jobs only)")
            
            # Send email
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_user, self.email_password)
            text = msg.as_string()
            server.sendmail(self.email_user, self.notification_email, text)
            server.quit()
            
            logger.info(f"📧 Notification email sent to {self.notification_email}")
            
            # Clean up temporary CSV files
            if csv_filename and os.path.exists(csv_filename):
                os.remove(csv_filename)
                logger.info(f"🗑️ Cleaned up temporary file: {csv_filename}")

            if filtered_csv_filename and os.path.exists(filtered_csv_filename):
                os.remove(filtered_csv_filename)
                logger.info(f"🗑️ Cleaned up temporary filtered file: {filtered_csv_filename}")
            
        except Exception as e:
            logger.error(f"Failed to send notification email: {e}")
    
    async def _send_completion_notification(self, scraping_run, company_names, search_terms, start_time, end_time, duration):
        """Send notification email when scraping completes successfully."""
        try:
            # Get job statistics from the scraping run
            db = SessionLocal()
            try:
                from database import ScrapedJob
                
                total_jobs = db.query(ScrapedJob).filter(
                    ScrapedJob.scraping_run_id == scraping_run.id
                ).count()
                
                # Get job counts by company
                company_details = ""
                for company_name in company_names:
                    company_job_count = db.query(ScrapedJob).filter(
                        ScrapedJob.scraping_run_id == scraping_run.id,
                        ScrapedJob.company.ilike(f"%{company_name}%")
                    ).count()
                    company_details += f"• {company_name}: {company_job_count} jobs\n"
                
                # Create summary
                summary = {
                    'date': start_time.strftime('%Y-%m-%d'),
                    'companies_scraped': len(company_names),
                    'total_jobs': total_jobs,
                    'new_jobs': total_jobs,  # Assuming all jobs are new for now
                    'duration': f"{duration.total_seconds():.1f} seconds",
                    'success_rate': '100%',
                    'company_details': company_details.strip(),
                    'search_terms': search_terms,
                    'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
                    'end_time': end_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                }
                
                # Create CSV export (both original and filtered versions)
                csv_result = self.create_jobs_csv(scraping_run.id)
                if isinstance(csv_result, tuple):
                    csv_filename, filtered_csv_filename = csv_result
                else:
                    # Backward compatibility if only one filename is returned
                    csv_filename = csv_result
                    filtered_csv_filename = None

                # Create daily job review list
                await self._create_daily_review_list(start_time, total_jobs)

                # Send notification with both CSV files
                self.send_notification_email(summary, csv_filename, filtered_csv_filename)
                
                logger.info(f"📧 Notification sent with {total_jobs} jobs from {len(company_names)} companies")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Failed to send completion notification: {e}")
    
    async def _create_daily_review_list(self, scraping_date, total_jobs_scraped):
        """Create a daily job review list after scraping completes."""
        try:
            # Only create review list if we scraped jobs
            if total_jobs_scraped > 0:
                target_date = scraping_date.strftime("%Y-%m-%d")
                
                db = SessionLocal()
                try:
                    review_list = daily_job_reviewer.create_daily_review_list(
                        target_date=target_date,
                        db=db,
                        force_recreate=True  # Recreate after new scraping
                    )
                    
                    if review_list:
                        logger.info(f"📋 Created daily review list for {target_date} with {review_list.jobs_selected_count} jobs")
                    else:
                        logger.warning(f"📋 No jobs qualified for daily review list on {target_date}")
                        
                finally:
                    db.close()
            else:
                logger.info("📋 Skipping daily review list creation - no jobs scraped")
                
        except Exception as e:
            logger.error(f"Failed to create daily review list: {e}")
    
    async def _send_failure_notification(self, error_message, start_time):
        """Send notification email when scraping fails."""
        try:
            summary = {
                'date': start_time.strftime('%Y-%m-%d'),
                'companies_scraped': 0,
                'total_jobs': 0,
                'new_jobs': 0,
                'duration': 'Failed',
                'success_rate': '0%',
                'company_details': f"❌ Scraping failed with error: {error_message}",
                'search_terms': [],
                'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
                'end_time': 'N/A - Failed'
            }
            
            self.send_notification_email(summary)
            logger.info("📧 Failure notification sent")
            
        except Exception as e:
            logger.error(f"Failed to send failure notification: {e}")
    
    def should_scrape_company(self, company: TargetCompany) -> bool:
        """Check if a company should be scraped based on last scrape time."""
        if not company.last_scraped:
            logger.info(f"Company '{company.name}' has never been scraped - will scrape")
            return True
        
        # Check if it's been more than 23 hours since last scrape (allow some buffer)
        # Handle timezone-naive datetime from database
        last_scraped = company.last_scraped
        if last_scraped.tzinfo is None:
            last_scraped = last_scraped.replace(tzinfo=timezone.utc)
        
        time_since_last_scrape = datetime.now(timezone.utc) - last_scraped
        should_scrape = time_since_last_scrape > timedelta(hours=23)
        
        if should_scrape:
            logger.info(f"Company '{company.name}' last scraped {time_since_last_scrape.total_seconds()/3600:.1f} hours ago - will scrape")
        else:
            logger.info(f"Company '{company.name}' was scraped recently - skipping")
        
        return should_scrape
    
    async def run_targeted_scraping(self, target_company_names, custom_search_terms=None):
        """Execute scraping for specific companies."""
        if not self.enabled:
            logger.info("Auto-scraping is disabled")
            return
        
        start_time = datetime.now(timezone.utc)
        logger.info(f"🎯 Starting targeted scraping for {len(target_company_names)} companies at {start_time}")
        logger.info(f"🏢 Target companies: {', '.join(target_company_names)}")
        
        try:
            # Get all active companies from database
            db = SessionLocal()
            try:
                all_companies = db.query(TargetCompany).filter(
                    TargetCompany.is_active == True
                ).all()
                
                # Filter to only target companies (case-insensitive match)
                target_names_lower = [name.lower() for name in target_company_names]
                companies_to_scrape = []
                seen_names_lower = set()

                for company in all_companies:
                    if company.name.lower() in target_names_lower and company.name.lower() not in seen_names_lower:
                        companies_to_scrape.append(company)
                        seen_names_lower.add(company.name.lower())
                        logger.info(f"✅ Found target company: {company.name}")
                
                # Check for companies not found in database and auto-create them
                found_names = [c.name.lower() for c in companies_to_scrape]
                missing_companies = [name for name in target_company_names 
                                   if name.lower() not in found_names]
                
                if missing_companies:
                    logger.info(f"🔧 {len(missing_companies)} companies not found in database, creating them automatically...")
                    for company_name in missing_companies:
                        new_company = self._create_target_company(db, company_name)
                        if new_company:
                            companies_to_scrape.append(new_company)
                            logger.info(f"✅ Created and added target company: {new_company.name}")
                        else:
                            logger.warning(f"❌ Failed to create company: {company_name}")
                
                if not companies_to_scrape:
                    logger.warning("❌ No companies available for scraping (creation may have failed)")
                    return
                
                # Extract data while session is still active
                company_names = [company.name for company in companies_to_scrape]
                
                # Use custom search terms or company-specific terms
                search_terms = set()
                if custom_search_terms:
                    search_terms.update(custom_search_terms)
                    logger.info(f"🔍 Using custom search terms: {', '.join(custom_search_terms)}")
                else:
                    # Use company-specific search terms or defaults
                    for company in companies_to_scrape:
                        if company.search_terms:
                            search_terms.update(company.search_terms)
                        else:
                            search_terms.update(self.default_search_terms)
                    logger.info(f"🔍 Using default/company-specific search terms")
                
                search_terms = list(search_terms)
                    
            finally:
                db.close()
            
            logger.info(f"🚀 Will scrape {len(company_names)} companies with {len(search_terms)} search terms")
            logger.info(f"📝 Search terms: {', '.join(search_terms[:5])}{'...' if len(search_terms) > 5 else ''}")
            
            # Get configuration values
            results_per_company = self._get_default_results_per_company()
            hours_old = self._get_default_hours_old()
            days_old = max(1, hours_old // 24)  # Convert hours to days
            
            # Create bulk scraping request
            scraping_request = BulkScrapingRequest(
                company_names=company_names,
                search_terms=search_terms,
                results_per_company=results_per_company,
                sites=["indeed", "linkedin"],
                location="USA",
                job_types=[],
                days_old=days_old,
                is_remote=None,
                auto_scraping=True
            )
            
            # Execute scraping with progress logging
            db = SessionLocal()
            try:
                logger.info("⏳ Starting job scraping process...")
                scraping_run = await self.job_scraper.bulk_scrape_companies(scraping_request, db)
                
                # Update last_scraped timestamp
                for company in companies_to_scrape:
                    company.last_scraped = datetime.now(timezone.utc)
                    db.merge(company)
                
                db.commit()
                
                end_time = datetime.now(timezone.utc)
                duration = end_time - start_time
                
                if scraping_run:
                    logger.info(f"✅ Targeted scraping completed successfully!")
                    logger.info(f"⏱️  Duration: {duration.total_seconds():.1f} seconds")
                    logger.info(f"📊 Run ID: {scraping_run.id}")
                    logger.info(f"🎯 Companies scraped: {len(company_names)}")
                    
                    # Send notification email with results
                    await self._send_completion_notification(scraping_run, company_names, search_terms, start_time, end_time, duration)
                else:
                    logger.error("❌ Targeted scraping failed - no scraping run created")
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Targeted scraping failed: {str(e)}", exc_info=True)
            
            # Send failure notification
            await self._send_failure_notification(str(e), start_time if 'start_time' in locals() else datetime.now())
    
    async def run_daily_scraping(self):
        """Execute the daily scraping routine."""
        if not self.enabled:
            logger.info("Auto-scraping is disabled")
            return
        
        start_time = datetime.now(timezone.utc)
        logger.info(f"🚀 Starting automated daily scraping at {start_time}")
        
        try:
            # Get active companies
            companies = self.get_active_companies()
            if not companies:
                logger.warning("No active target companies found - skipping scraping")
                return
            
            # Filter companies that need scraping
            companies_to_scrape = [c for c in companies if self.should_scrape_company(c)]
            
            if not companies_to_scrape:
                logger.info("No companies need scraping at this time")
                return
            
            # Prepare company names for bulk scraping
            company_names = [company.name for company in companies_to_scrape]
            
            # Determine search terms - use saved defaults, company-specific, or fallback defaults
            search_terms = set()
            
            # First try to get search terms from scraping defaults file
            default_search_terms = self._get_default_search_terms()
            if default_search_terms:
                search_terms.update(default_search_terms)
                logger.info(f"🔍 Using search terms from defaults: {', '.join(default_search_terms)}")
            else:
                # Fallback to company-specific or built-in defaults
                for company in companies_to_scrape:
                    if company.search_terms:
                        search_terms.update(company.search_terms)
                    else:
                        search_terms.update(self.default_search_terms)
                logger.info(f"🔍 Using fallback search terms")
            
            search_terms = list(search_terms)
            
            logger.info(f"Will scrape {len(company_names)} companies with {len(search_terms)} search terms")
            logger.info(f"Companies: {', '.join(company_names)}")
            logger.info(f"Search terms: {', '.join(search_terms)}")
            
            # Get configuration values
            results_per_company = self._get_default_results_per_company()
            hours_old = self._get_default_hours_old()
            days_old = max(1, hours_old // 24)  # Convert hours to days
            
            # Create bulk scraping request
            scraping_request = BulkScrapingRequest(
                company_names=company_names,
                search_terms=search_terms,
                results_per_company=results_per_company,
                sites=["indeed", "linkedin"],  # Default sites
                location="USA",  # Default location
                job_types=[],  # All job types
                days_old=days_old,  # Jobs from configuration
                is_remote=None,  # Both remote and non-remote
                auto_scraping=True  # Flag to indicate this is auto-scraping
            )
            
            # Execute scraping
            db = SessionLocal()
            try:
                scraping_run = await self.job_scraper.bulk_scrape_companies(scraping_request, db)
                
                # Update last_scraped timestamp for scraped companies
                for company in companies_to_scrape:
                    company.last_scraped = datetime.now(timezone.utc)
                    db.merge(company)
                
                db.commit()
                
                end_time = datetime.now(timezone.utc)
                duration = end_time - start_time
                
                logger.info(f"✅ Automated scraping completed successfully!")
                logger.info(f"   Duration: {duration.total_seconds():.1f} seconds")
                logger.info(f"   Scraping run ID: {scraping_run.id}")
                
                # Send notification email with results
                await self._send_completion_notification(scraping_run, company_names, search_terms, start_time, end_time, duration)
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Automated scraping failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Send failure notification
            await self._send_failure_notification(str(e), start_time if 'start_time' in locals() else datetime.now())
    
    def schedule_daily_scraping(self):
        """Set up the daily scraping schedule."""
        if not self.enabled:
            logger.info("Auto-scraping is disabled - not scheduling")
            return
        
        # Schedule daily scraping
        schedule.every().day.at(self.schedule_time).do(
            lambda: asyncio.run(self.run_daily_scraping())
        )
        
        logger.info(f"📅 Scheduled daily scraping at {self.schedule_time}")
        
        # Also allow manual trigger via special time check
        schedule.every(1).minutes.do(self._check_manual_trigger)
    
    def _check_manual_trigger(self):
        """Check for manual trigger file to run scraping immediately."""
        import tempfile
        trigger_file = os.path.join(tempfile.gettempdir(), "trigger_scraping")
        if os.path.exists(trigger_file):
            logger.info("🔄 Manual trigger detected - running scraping now")
            try:
                # Read trigger data to get specific companies/search terms
                trigger_data = {}
                try:
                    with open(trigger_file, 'r') as f:
                        import json
                        trigger_data = json.load(f)
                except:
                    # Fallback for old format
                    trigger_data = {}
                
                os.remove(trigger_file)
                
                # Run scraping with specific parameters if provided
                company_names = trigger_data.get("company_names", [])
                search_terms = trigger_data.get("search_terms", [])
                
                if company_names:
                    asyncio.run(self.run_targeted_scraping(company_names, search_terms))
                else:
                    asyncio.run(self.run_daily_scraping())
                    
            except Exception as e:
                logger.error(f"Manual scraping failed: {e}")
    
    def start_scheduler(self):
        """Start the background scheduler."""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return
        
        self.is_running = True
        self.schedule_daily_scraping()
        
        def run_scheduler():
            logger.info("🎯 Scheduler thread started")
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            logger.info("🛑 Scheduler thread stopped")
        
        self.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("✅ Auto-scraping scheduler started successfully")
    
    def stop_scheduler(self):
        """Stop the background scheduler."""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        schedule.clear()
        logger.info("🛑 Auto-scraping scheduler stopped")
    
    def get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled scraping time."""
        jobs = schedule.get_jobs()
        if jobs:
            next_run = min(job.next_run for job in jobs if job.next_run)
            return next_run
        return None
    
    def get_status(self) -> dict:
        """Get scheduler status information."""
        next_run = self.get_next_run_time()
        active_companies = len(self.get_active_companies())
        
        return {
            "enabled": self.enabled,
            "running": self.is_running,
            "schedule_time": self.schedule_time,
            "next_run": next_run.isoformat() if next_run else None,
            "active_companies_count": active_companies,
            "max_results_per_company": self._get_default_results_per_company(),
            "hours_old": self._get_default_hours_old(),
            "default_search_terms": self.default_search_terms
        }

# Global scheduler instance
auto_scraper = AutoScrapingScheduler()

def start_auto_scraping():
    """Start the automatic scraping service."""
    auto_scraper.start_scheduler()

def stop_auto_scraping():
    """Stop the automatic scraping service."""
    auto_scraper.stop_scheduler()

def trigger_manual_scraping(company_names=None, search_terms=None):
    """Trigger manual scraping by creating trigger file with optional parameters."""
    try:
        import tempfile
        trigger_data = {
            "timestamp": str(datetime.now()),
            "company_names": company_names or [],
            "search_terms": search_terms or []
        }
        
        trigger_file = os.path.join(tempfile.gettempdir(), "trigger_scraping")
        with open(trigger_file, "w") as f:
            import json
            json.dump(trigger_data, f)
        
        if company_names:
            logger.info(f"✅ Manual scraping trigger created for companies: {', '.join(company_names)}")
        else:
            logger.info("✅ Manual scraping trigger created for all companies")
        logger.info(f"📁 Trigger file location: {trigger_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to create manual trigger: {e}")
        return False

def get_scheduler_status():
    """Get current scheduler status."""
    return auto_scraper.get_status()