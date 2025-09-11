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
from typing import List, Optional
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
                        logger.warning(f"⚠️ Company not found in database: {company_name}")
                        # Show available similar companies for debugging
                        similar = db.query(TargetCompany).filter(
                            TargetCompany.name.ilike(f"%{company_name.split()[0]}%")
                        ).limit(3).all()
                        if similar:
                            logger.info(f"   Similar companies found: {[c.name for c in similar]}")
                
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
                
                # Create CSV content
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header
                writer.writerow([
                    'Company', 'Title', 'Location', 'Description', 'Salary_Min', 'Salary_Max', 
                    'Salary_Interval', 'Currency', 'Date_Posted', 'Date_Scraped', 'Job_URL', 
                    'Site', 'Job_Type', 'Is_Remote', 'Min_Experience_Years', 'Max_Experience_Years'
                ])
                
                # Write job data
                for job in jobs:
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
                        job.max_experience_years or ''
                    ])
                
                # Save to temporary file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_filename = f"jobspy_daily_scraping_{timestamp}.csv"
                
                with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                    f.write(output.getvalue())
                
                logger.info(f"📄 Created CSV export: {csv_filename} with {len(jobs)} jobs")
                return csv_filename
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error creating jobs CSV: {e}")
            return None
    
    def send_notification_email(self, summary: dict, csv_filename: str = None):
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

{"📎 CSV file with job details is attached." if csv_filename else ""}

---
Generated by JobSpy Automated Scraping System
            """.strip()
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach CSV file if provided
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
                logger.info(f"📎 Attached CSV file: {attachment_filename} ({summary.get('total_jobs', 0)} jobs included)")
            
            # Send email
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_user, self.email_password)
            text = msg.as_string()
            server.sendmail(self.email_user, self.notification_email, text)
            server.quit()
            
            logger.info(f"📧 Notification email sent to {self.notification_email}")
            
            # Clean up temporary CSV file
            if csv_filename and os.path.exists(csv_filename):
                os.remove(csv_filename)
                logger.info(f"🗑️ Cleaned up temporary file: {csv_filename}")
            
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
                
                # Create CSV export
                csv_filename = self.create_jobs_csv(scraping_run.id)
                
                # Create daily job review list
                await self._create_daily_review_list(start_time, total_jobs)
                
                # Send notification
                self.send_notification_email(summary, csv_filename)
                
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
                
                for company in all_companies:
                    if company.name.lower() in target_names_lower:
                        companies_to_scrape.append(company)
                        logger.info(f"✅ Found target company: {company.name}")
                
                # Check for companies not found in database
                found_names = [c.name.lower() for c in companies_to_scrape]
                missing_companies = [name for name in target_company_names 
                                   if name.lower() not in found_names]
                
                if missing_companies:
                    logger.warning(f"⚠️  Companies not found in database: {', '.join(missing_companies)}")
                
                if not companies_to_scrape:
                    logger.warning("❌ No valid target companies found in database")
                    return
                    
            finally:
                db.close()
            
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
            company_names = [company.name for company in companies_to_scrape]
            
            logger.info(f"🚀 Will scrape {len(company_names)} companies with {len(search_terms)} search terms")
            logger.info(f"📝 Search terms: {', '.join(search_terms[:5])}{'...' if len(search_terms) > 5 else ''}")
            
            # Create bulk scraping request
            scraping_request = BulkScrapingRequest(
                company_names=company_names,
                search_terms=search_terms,
                results_per_company=self.max_results_per_company,
                sites=["indeed", "linkedin"],
                location="USA",
                job_types=[],
                days_old=7,
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
            
            # Create bulk scraping request
            scraping_request = BulkScrapingRequest(
                company_names=company_names,
                search_terms=search_terms,
                results_per_company=self.max_results_per_company,
                sites=["indeed", "linkedin"],  # Default sites
                location="USA",  # Default location
                job_types=[],  # All job types
                days_old=7,  # Jobs from last 7 days
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
            "max_results_per_company": self.max_results_per_company,
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