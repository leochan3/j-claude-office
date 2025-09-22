"""
Job Scraping Service

This module handles proactive job scraping from various job boards,
deduplication, and storage in the local database.
"""

import asyncio
import time
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import pandas as pd
from jobspy import scrape_jobs
import requests
import time
from bs4 import BeautifulSoup
import re

from database import get_db, TargetCompany, ScrapedJob, ScrapingRun, create_job_hash, create_content_hash
from models import ScrapingRunCreate, BulkScrapingRequest


class JobScrapingService:
    """Service for scraping and managing job data."""

    def __init__(self):
        self.supported_sites = ["indeed", "linkedin", "glassdoor", "zip_recruiter"]
        self.session = requests.Session()
        # Set headers to mimic a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
    
    def extract_experience_years(self, description: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract minimum and maximum years of experience from job description."""
        if not description or not isinstance(description, str):
            return None, None
        
        # Common patterns for experience requirements
        patterns = [
            r"(\d+)\s*\+?\s*(?:years?|yrs?)\s*(?:and above|and up|or more|or greater|or higher|plus)?\s*(?:of)?\s*(?:relevant\s*)?(?:experience|exp)",
            r"minimum\s*(\d+)\s*(?:years?|yrs?)",
            r"at least\s*(\d+)\s*(?:years?|yrs?)",
            r"(\d+)[-–](\d+)\s*(?:years?|yrs?)",  # Range pattern
            r"(\d+)\s*to\s*(\d+)\s*(?:years?|yrs?)"  # Range pattern with "to"
        ]
        
        min_years = None
        max_years = None
        
        for pattern in patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            for match in matches:
                try:
                    if isinstance(match, tuple):
                        # Range pattern (min-max years)
                        years = [int(y) for y in match if y]
                        if len(years) == 2:
                            min_years = min(years) if min_years is None else min(min_years, min(years))
                            max_years = max(years) if max_years is None else max(max_years, max(years))
                        elif len(years) == 1:
                            year = years[0]
                            min_years = year if min_years is None else min(min_years, year)
                    else:
                        # Single number pattern
                        year = int(match)
                        min_years = year if min_years is None else min(min_years, year)
                except (ValueError, TypeError):
                    continue
        
        return min_years, max_years

    def _parse_salary_range(self, salary_text: str) -> tuple:
        """
        Parse salary range from text.
        Returns (min_salary, max_salary) as integers or (None, None) if not found.
        """
        if not salary_text:
            return None, None

        # Remove common currency symbols and clean text
        text = salary_text.replace(',', '').replace('$', '').replace('USD', '').lower()

        # Look for salary patterns
        patterns = [
            # $80,000 - $120,000
            r'(\d{2,3})(?:,?000)?\s*(?:-|to)\s*(\d{2,3})(?:,?000)?',
            # $80k - $120k
            r'(\d{2,3})k\s*(?:-|to)\s*(\d{2,3})k',
            # 80k-120k
            r'(\d{2,3})k?\s*-\s*(\d{2,3})k',
            # $80,000 to $120,000
            r'(\d{2,3})(?:,?000)?\s+to\s+(\d{2,3})(?:,?000)?',
            # Single salary: $100,000 or 100k
            r'(\d{2,3})(?:,?000|k)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    if len(match.groups()) == 2:
                        # Range found
                        min_val = int(match.group(1))
                        max_val = int(match.group(2))

                        # Convert to full amounts if needed
                        if 'k' in text or min_val < 1000:
                            min_val *= 1000
                            max_val *= 1000

                        return min_val, max_val
                    else:
                        # Single value found
                        val = int(match.group(1))
                        if 'k' in text or val < 1000:
                            val *= 1000
                        # Return as min salary, no max
                        return val, None
                except (ValueError, IndexError):
                    continue

        return None, None

    def _extract_salary_from_description(self, description_text: str) -> tuple:
        """
        Extract salary range from job description text using smart pattern matching.
        Returns (min_salary, max_salary) as integers or (None, None) if not found.
        """
        if not description_text:
            return None, None

        # Normalize text for easier pattern matching
        text = description_text.lower()

        # Look for salary range patterns in job descriptions
        salary_range_patterns = [
            # "salary range is $100,000 to $150,000"
            r'salary.*?range.*?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:to|and|-)\s*\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            # "compensation from $100k to $150k"
            r'compensation.*?from.*?\$(\d{1,3})k.*?to.*?\$(\d{1,3})k',
            # "pay range: $100,000 - $150,000"
            r'pay.*?range.*?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*-\s*\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            # "between $100k and $150k"
            r'between.*?\$(\d{1,3})k.*?and.*?\$(\d{1,3})k',
            # "$100,000 to $150,000" (direct range)
            r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:to|and|-)\s*\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            # "$100k - $150k" (K format)
            r'\$(\d{1,3})k\s*-\s*\$(\d{1,3})k',
        ]

        for pattern in salary_range_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                try:
                    groups = match.groups()
                    if len(groups) >= 2 and groups[0] and groups[1]:
                        # Clean and parse the salary values
                        min_str = groups[0].replace(',', '').replace('.00', '')
                        max_str = groups[1].replace(',', '').replace('.00', '')

                        min_val = int(min_str)
                        max_val = int(max_str)

                        # Handle K format - check if the original match contained 'k'
                        match_text = match.group().lower()
                        if 'k' in match_text and min_val < 1000:
                            min_val *= 1000
                            max_val *= 1000

                        # Sanity checks
                        if min_val > max_val:
                            min_val, max_val = max_val, min_val  # Swap if reversed

                        # Reject unrealistic salaries
                        if max_val > 3_000_000:  # Over 3M USD is likely an error
                            continue
                        if min_val < 20_000:  # Under 20K is likely not a full-time salary
                            continue

                        print(f"📝 Found salary range in description: {match.group()}")
                        return min_val, max_val

                except (ValueError, IndexError):
                    continue

        # If no range found, look for single salary and try to find the max nearby
        single_patterns = [
            r'salary.*?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'compensation.*?\$(\d{1,3})k',
            r'pay.*?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
        ]

        for pattern in single_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                try:
                    min_str = match.group(1).replace(',', '').replace('.00', '')
                    min_val = int(min_str)

                    # Handle K format
                    match_text = match.group().lower()
                    if 'k' in match_text and min_val < 1000:
                        min_val *= 1000

                    # Sanity check
                    if min_val < 20_000 or min_val > 3_000_000:
                        continue

                    # Look for another salary number within the next 100 characters
                    search_start = match.end()
                    search_end = min(len(text), search_start + 100)
                    remaining_text = text[search_start:search_end]

                    # Search for another salary amount
                    next_salary_patterns = [
                        r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
                        r'(\d{1,3})k',
                        r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)(?:\s*(?:usd|dollars?))?',
                    ]

                    for next_pattern in next_salary_patterns:
                        next_matches = re.finditer(next_pattern, remaining_text)
                        for next_match in next_matches:
                            try:
                                max_str = next_match.group(1).replace(',', '').replace('.00', '')
                                max_val = int(max_str)

                                # Handle K format for max value
                                next_match_text = next_match.group().lower()
                                if 'k' in next_match_text and max_val < 1000:
                                    max_val *= 1000

                                # Ensure max is greater than min and reasonable
                                if max_val > min_val and max_val <= 3_000_000:
                                    print(f"📝 Found salary pair in description: ${min_val:,} and ${max_val:,}")
                                    return min_val, max_val

                            except (ValueError, IndexError):
                                continue

                    # If no max found, return just the min
                    print(f"📝 Found single salary in description: ${min_val:,}")
                    return min_val, None

                except (ValueError, IndexError):
                    continue

        return None, None

    def _find_max_salary_in_description(self, description: str, min_salary: int) -> int:
        """
        Find max salary in job description using min salary as anchor point.
        Look for patterns like "from $120k to $180k" or "$120,000 - $180,000"
        """
        if not description or not min_salary:
            return None

        # Normalize the description
        text = description.lower().replace(',', '')

        # Convert min_salary to different formats for searching
        min_k = min_salary // 1000  # e.g., 120000 -> 120
        min_formatted = f"{min_salary:,}"  # e.g., 120000 -> "120,000"

        # Look for the min salary in various formats in the description
        min_patterns = [
            f"${min_k}k",
            f"${min_formatted.replace(',', '')}",
            f"{min_k}k",
            f"{min_salary}",
            f"{min_k} k"
        ]

        found_min_position = -1
        for pattern in min_patterns:
            pos = text.find(pattern.lower().replace(',', ''))
            if pos >= 0:
                found_min_position = pos
                break

        if found_min_position == -1:
            return None

        # Search for max salary within next 100 characters after min salary
        search_start = found_min_position
        search_end = min(len(text), search_start + 100)
        search_text = text[search_start:search_end]

        # Look for salary numbers after the min salary
        # Match various formats: $180k, $180000, 180k, 180000, 180 k, etc.
        salary_patterns = [
            r'\$(\d{1,3})k',               # $180k
            r'\$(\d{2,3}(?:\d{3})*)',      # $180000
            r'(\d{1,3})k',                 # 180k
            r'(\d{1,3})\s*k',              # 180 k
            r'\$(\d{1,3}(?:\d{3})*(?:\.\d{2})?)', # $180000.00
            r'(\d{2,3}(?:\d{3})*)',        # 180000
        ]

        potential_max_salaries = []

        for pattern in salary_patterns:
            matches = re.finditer(pattern, search_text)
            for match in matches:
                try:
                    value_str = match.group(1)
                    value = int(value_str.replace('.', '').replace(',', ''))

                    # Handle K format
                    if 'k' in match.group():
                        value *= 1000

                    # Only consider values higher than min_salary
                    if value > min_salary and value <= 3_000_000:  # Max 3M USD sanity check
                        potential_max_salaries.append(value)

                except (ValueError, IndexError):
                    continue

        # Return the first reasonable max salary found
        if potential_max_salaries:
            # Sort and take the first one (closest to min salary position)
            potential_max_salaries.sort()
            max_salary = potential_max_salaries[0]

            # Additional sanity check: max should be reasonable compared to min
            if max_salary > min_salary and max_salary < min_salary * 3:  # Not more than 3x the min
                return max_salary

        return None

    def fetch_linkedin_job_data(self, job_url: str) -> dict:
        """
        Attempt to fetch LinkedIn job description and salary information from job URL.
        Returns dict with description, min_salary, max_salary fields.
        """
        if not job_url or 'linkedin.com' not in job_url:
            return {"description": "", "min_salary": None, "max_salary": None}

        try:
            # Add delay to be respectful to LinkedIn
            time.sleep(1)

            # Try to fetch the job page
            response = self.session.get(job_url, timeout=10)
            response.raise_for_status()

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Try different selectors that LinkedIn might use for job descriptions
            description_selectors = [
                '.description__text',
                '.jobs-description-content__text',
                '.jobs-description__content',
                '[data-automation-id="jobPostingDescription"]',
                '.jobs-box__html-content',
                '.jobs-description',
                'section[data-automation-id="jobPostingDescription"]'
            ]

            description_text = ""
            for selector in description_selectors:
                elements = soup.select(selector)
                if elements:
                    # Get text from the first matching element
                    description_text = elements[0].get_text(strip=True, separator=' ')
                    if len(description_text) > 50:  # Only consider substantial descriptions
                        break

            # Clean up the description
            if description_text:
                # Remove excessive whitespace
                description_text = re.sub(r'\s+', ' ', description_text)
                # Limit length to prevent token overflow
                if len(description_text) > 2000:
                    description_text = description_text[:2000] + "..."

            # Try to extract salary information from LinkedIn page
            min_salary = None
            max_salary = None

            # Search for salary patterns in the entire page text
            full_text = soup.get_text()

            # Debug: Show any text containing "$" and "K" to help identify missed patterns
            dollar_k_patterns = re.findall(r'[^\n]*\$[^\n]*k[^\n]*', full_text, re.IGNORECASE)
            if dollar_k_patterns:
                print(f"🔍 Debug - Found {len(dollar_k_patterns)} lines with $...K patterns:")
                for i, pattern in enumerate(dollar_k_patterns[:5]):  # Show first 5
                    print(f"  {i+1}: {pattern.strip()}")
                # Check specifically for decimal K patterns like $68.6K/yr - $151.1K/yr
                decimal_k_patterns = re.findall(r'\$\d{1,3}\.\d+K[^\n]*', full_text, re.IGNORECASE)
                if decimal_k_patterns:
                    print(f"💡 Debug - Found {len(decimal_k_patterns)} decimal K patterns:")
                    for i, pattern in enumerate(decimal_k_patterns[:3]):  # Show first 3
                        print(f"  Decimal {i+1}: {pattern.strip()}")

            # Prioritize range patterns over single values - search for ranges FIRST
            range_patterns = [
                # $68.6K/yr - $151.1K/yr (decimal K format with /yr) - case insensitive
                r'\$(\d{1,3}(?:\.\d+)?)[kK]/yr\s*-\s*\$(\d{1,3}(?:\.\d+)?)[kK]/yr',
                # $68.6K - $151.1K (decimal K format range) - case insensitive
                r'\$(\d{1,3}(?:\.\d+)?)[kK]\s*-\s*\$(\d{1,3}(?:\.\d+)?)[kK]',
                # $120,000 - $180,000 (full number range)
                r'\$(\d{2,3}(?:,\d{3})*)\s*-\s*\$(\d{2,3}(?:,\d{3})*)',
                # Also try with spaces: $68.6 K/yr - $151.1 K/yr
                r'\$(\d{1,3}(?:\.\d+)?)\s*[kK]/yr\s*-\s*\$(\d{1,3}(?:\.\d+)?)\s*[kK]/yr',
                r'\$(\d{1,3}(?:\.\d+)?)\s*[kK]\s*-\s*\$(\d{1,3}(?:\.\d+)?)\s*[kK]',
                # Handle "from $X to $Y" format
                r'from\s*\$(\d{1,3}(?:\.\d+)?)[kK].*?to\s*\$(\d{1,3}(?:\.\d+)?)[kK]',
                # Handle malformed comma issues: $150,000 might show as $150/,000 or $150,,000
                r'\$(\d{2,3})[/,]*(\d{3})\s*-\s*\$(\d{2,3})[/,]*(\d{3})',
            ]

            single_patterns = [
                # Single salary patterns (only use if no ranges found) - case insensitive
                r'\$(\d{1,3}(?:\.\d+)?)[kK]/yr',  # $120.5k/yr or $120K/yr
                r'\$(\d{1,3}(?:\.\d+)?)[kK]',  # $120.5k or $120K
                r'\$(\d{1,3}(?:\.\d+)?)\s*[kK]/yr',  # $120.5 K/yr
                r'\$(\d{1,3}(?:\.\d+)?)\s*[kK]',  # $120.5 K
                r'\$(\d{2,3}(?:,\d{3})*)',  # $150,000
            ]

            # First, search specifically for salary ranges
            for pattern in range_patterns:
                matches = re.finditer(pattern, full_text, re.IGNORECASE)
                for match in matches:
                    # Get context around the match to verify it's salary related
                    start = max(0, match.start() - 100)
                    end = min(len(full_text), match.end() + 100)
                    context = full_text[start:end].lower()

                    # Check if context contains salary-related keywords
                    if any(word in context for word in ['salary', 'compensation', 'pay', 'annual', 'base', 'range']):
                        groups = match.groups()
                        match_text = match.group().lower()
                        print(f"🔍 RANGE match found: '{match.group()}' with groups: {groups}")

                        try:
                            if len(groups) == 2 and groups[1]:  # Standard range found
                                # Clean and handle decimal values
                                min_clean = groups[0].replace(',', '').replace('/', '')
                                max_clean = groups[1].replace(',', '').replace('/', '')
                                min_val = int(float(min_clean))
                                max_val = int(float(max_clean))

                                # Handle k format - check if the match contains 'k'
                                if 'k' in match_text:
                                    min_val *= 1000
                                    max_val *= 1000

                            elif len(groups) == 4 and groups[1] and groups[3]:  # Malformed comma pattern: $150[/,]*000 - $180[/,]*000
                                # Reconstruct the full numbers from separated parts
                                min_val = int(groups[0] + groups[1])  # e.g., "150" + "000" = 150000
                                max_val = int(groups[2] + groups[3])  # e.g., "180" + "000" = 180000
                            else:
                                continue

                            # Common processing for both patterns
                            min_salary = min_val
                            max_salary = max_val
                            print(f"💰 Found salary range: ${min_salary:,} - ${max_salary:,}")
                            # Found a range, stop searching
                            break

                        except (ValueError, IndexError):
                            continue
                # If we found a range, don't continue to single patterns
                if min_salary and max_salary:
                    break

            # Only search for single values if no range was found
            if not min_salary:
                for pattern in single_patterns:
                    matches = re.finditer(pattern, full_text, re.IGNORECASE)
                    for match in matches:
                        # Get context around the match to verify it's salary related
                        start = max(0, match.start() - 100)
                        end = min(len(full_text), match.end() + 100)
                        context = full_text[start:end].lower()

                        # Check if context contains salary-related keywords
                        if any(word in context for word in ['salary', 'compensation', 'pay', 'annual', 'base', 'range']):
                            groups = match.groups()
                            match_text = match.group().lower()
                            print(f"🔍 SINGLE match found: '{match.group()}' with groups: {groups}")

                            if len(groups) >= 1 and groups[0]:  # Single salary found
                                try:
                                    # Handle decimal values by converting to float first, then int
                                    val = int(float(groups[0].replace(',', '')))

                                    # Handle k format
                                    if 'k' in match_text:
                                        val *= 1000

                                    min_salary = val
                                    print(f"💰 Found salary: ${min_salary:,}")
                                    break
                                except (ValueError, IndexError):
                                    continue

                    if min_salary:  # Found salary, stop searching
                        break

            # Fallback: Search in job description if no salary found in page
            if not min_salary and description_text:
                print(f"🔍 Fallback: Searching for salary in job description text...")
                fallback_min, fallback_max = self._extract_salary_from_description(description_text)
                if fallback_min:
                    min_salary = fallback_min
                    max_salary = fallback_max
                    print(f"💰 Found salary in description: ${min_salary:,}" + (f" - ${max_salary:,}" if max_salary else ""))

            if not min_salary:
                print(f"⚠️  No salary found on LinkedIn page or description")

            result = {
                "description": description_text,
                "min_salary": min_salary,
                "max_salary": max_salary
            }

            if description_text:
                print(f"✅ Fetched LinkedIn description ({len(description_text)} chars)")
            if min_salary or max_salary:
                print(f"✅ Fetched LinkedIn salary: {min_salary}-{max_salary}")

            return result

        except requests.RequestException as e:
            print(f"⚠️  Failed to fetch LinkedIn job data: {e}")
            return {"description": "", "min_salary": None, "max_salary": None}
        except Exception as e:
            print(f"⚠️  Error parsing LinkedIn job page: {e}")
            return {"description": "", "min_salary": None, "max_salary": None}

    def enrich_linkedin_jobs(self, jobs_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich LinkedIn jobs with descriptions and salary information fetched from their URLs.
        """
        print(f"🔍 enrich_linkedin_jobs called with {len(jobs_data)} total jobs")
        enriched_jobs = []
        linkedin_count = 0
        enriched_count = 0
        salary_enriched_count = 0

        for job in jobs_data:
            # Process all LinkedIn jobs - enrich description if missing, always try to enrich salary
            if job.get('site') == 'linkedin':
                linkedin_count += 1
                job_url = job.get('job_url', '')
                if job_url:
                    existing_min = job.get('min_amount')
                    existing_max = job.get('max_amount')
                    print(f"🔍 Processing LinkedIn job: {job.get('title', '')[:50]}... (has_desc: {bool(job.get('description'))}, existing_salary: ${existing_min}-${existing_max})")
                    job_data = self.fetch_linkedin_job_data(job_url)

                    # Update description if empty
                    if job_data['description'] and not job.get('description'):
                        job['description'] = job_data['description']
                        enriched_count += 1
                        print(f"📝 Enriched LinkedIn job description: {job.get('title', '')[:50]}...")

                    # Update salary information if found (prioritize scraped data)
                    if job_data['min_salary'] or job_data['max_salary']:
                        if job_data['min_salary'] and not job.get('min_amount'):
                            job['min_amount'] = job_data['min_salary']
                        if job_data['max_salary'] and not job.get('max_amount'):
                            job['max_amount'] = job_data['max_salary']

                        # Only count as enriched if we actually added salary data
                        if (job_data['min_salary'] and not existing_min) or (job_data['max_salary'] and not existing_max):
                            salary_enriched_count += 1
                            print(f"💰 Enriched LinkedIn job salary: {job.get('title', '')[:50]}... (${job_data['min_salary']}-${job_data['max_salary']})")

                        # If we have min but no max, try to extract max from description
                        if job_data['min_salary'] and not job_data['max_salary'] and job.get('description'):
                            max_from_desc = self._find_max_salary_in_description(job.get('description'), job_data['min_salary'])
                            if max_from_desc:
                                job['max_amount'] = max_from_desc
                                print(f"📝 Found max salary in description: ${max_from_desc:,}")

            # For all jobs (not just LinkedIn), if we have min salary but no max, try to extract from description
            if job.get('min_amount') and not job.get('max_amount') and job.get('description'):
                max_from_desc = self._find_max_salary_in_description(job.get('description'), job.get('min_amount'))
                if max_from_desc:
                    job['max_amount'] = max_from_desc
                    print(f"📝 Found max salary in {job.get('site', 'unknown')} job description: ${max_from_desc:,}")

            enriched_jobs.append(job)

        if linkedin_count > 0:
            print(f"🔗 LinkedIn enrichment: {enriched_count}/{linkedin_count} jobs enhanced with descriptions")
            if salary_enriched_count > 0:
                print(f"💰 LinkedIn salary enrichment: {salary_enriched_count}/{linkedin_count} jobs enhanced with salary data")

        return enriched_jobs

    async def scrape_company_jobs(
        self,
        company_name: str,
        search_terms: List[str] = None,
        sites: List[str] = None,
        locations: List[str] = None,
        results_wanted: int = 1000,
        hours_old: int = 72,  # 3 days
        comprehensive_terms: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Scrape jobs for a specific company."""
        
        if not search_terms:
            # If no search terms provided, use comprehensive default terms for better coverage
            search_terms = ["software engineer", "developer", "data scientist", "product manager", "analyst", "designer"]
        elif len(search_terms) == 1 and search_terms[0].lower().strip() in ["all", "*", "all jobs"]:
            # Use comprehensive terms from frontend, or default comprehensive terms
            if comprehensive_terms:
                search_terms = comprehensive_terms
            else:
                # Fallback to default comprehensive terms
                search_terms = [
                    "tech", "analyst", "manager", "product", "engineer", "market", 
                    "finance", "business", "associate", "senior", "director", 
                    "president", "lead", "data", "science", "software", "cloud", 
                    "developer", "staff", "program", "quality", "security", "specialist"
                ]
        if not sites:
            sites = ["indeed"]
        if not locations:
            locations = ["USA", "Remote", "United States"]

        # Always add company name and "all" as search terms for better coverage
        if search_terms is None:
            search_terms = []
        search_terms = search_terms.copy()  # Don't modify the original list

        # Add company name if not already present
        company_term = company_name.lower().strip()
        if company_term not in [term.lower().strip() for term in search_terms]:
            search_terms.append(company_name)
            print(f"🎯 Added company name '{company_name}' as search term")

        # Add "all" for broader coverage if not already present
        if "all" not in [term.lower().strip() for term in search_terms]:
            search_terms.append("all")
            print(f"🎯 Added 'all' as search term for broader coverage")

        all_jobs = []
        search_analytics = {}  # Track results per search term
        
        print(f"🔍 Scraping jobs for {company_name}")
        
        for location in locations:
            for search_term in search_terms:
                # Create search term with company name
                if search_term.strip():
                    full_search_term = f"{search_term} {company_name}"
                else:
                    # If no specific search term, just search for the company name
                    full_search_term = company_name
                
                try:
                    print(f"  📍 Searching: '{full_search_term}' in {location}")
                    
                    # Call JobSpy
                    jobs_df = await asyncio.to_thread(
                        scrape_jobs,
                        site_name=sites,
                        search_term=full_search_term,
                        location=location,
                        results_wanted=results_wanted,
                        hours_old=hours_old,
                        country_indeed="USA",
                        verbose=1
                    )
                    
                    if jobs_df is not None and not jobs_df.empty:
                        # Filter jobs to include the target company (flexible matching)
                        company_filter = company_name.lower().strip()
                        # Use broader matching for better coverage - include partial matches
                        company_parts = company_filter.split()
                        mask = jobs_df['company'].str.lower().str.contains('|'.join(company_parts), na=False, regex=True)
                        jobs_df = jobs_df[mask]
                        
                        if not jobs_df.empty:
                            jobs_list = jobs_df.to_dict('records')
                            
                            # Track analytics for this search term
                            search_key = f"{search_term}@{location}"
                            search_analytics[search_key] = len(jobs_list)
                            
                            # Clean up NaN values
                            for job in jobs_list:
                                for key, value in job.items():
                                    if pd.isna(value):
                                        job[key] = None
                                # Add metadata
                                job['scraped_search_term'] = search_term
                                job['scraped_location'] = location
                            
                            all_jobs.extend(jobs_list)
                            print(f"  ✅ Found {len(jobs_list)} jobs for {company_name} using '{search_term}' in {location}")
                        else:
                            search_analytics[f"{search_term}@{location}"] = 0
                            print(f"  ❌ No jobs found for {company_name} using '{search_term}' in {location}")
                    else:
                        print(f"  ❌ No results from JobSpy for {company_name} in {location}")
                
                except Exception as e:
                    print(f"  ❌ Error scraping {company_name} in {location}: {str(e)}")
                    continue
                
                # Small delay between requests to be respectful
                await asyncio.sleep(0.5)
        
        # Remove duplicates based on job_url
        unique_jobs = {}
        for job in all_jobs:
            job_url = job.get('job_url', '')
            if job_url and job_url not in unique_jobs:
                unique_jobs[job_url] = job
            elif not job_url:
                # For jobs without URL, use title+company+location as key
                key = f"{job.get('title', '')}-{job.get('company', '')}-{job.get('location', '')}"
                if key not in unique_jobs:
                    unique_jobs[key] = job
        
        final_jobs = list(unique_jobs.values())

        # Enrich LinkedIn jobs with descriptions
        linkedin_jobs = [job for job in final_jobs if job.get('site') == 'linkedin']
        print(f"🔗 Enriching LinkedIn jobs with descriptions... ({len(linkedin_jobs)} LinkedIn jobs found)")
        final_jobs = self.enrich_linkedin_jobs(final_jobs)

        # Print analytics summary
        print(f"🎯 Total unique jobs found for {company_name}: {len(final_jobs)}")
        print(f"\n📊 SEARCH TERM PERFORMANCE ANALYTICS:")
        sorted_analytics = sorted(search_analytics.items(), key=lambda x: x[1], reverse=True)
        for search_key, count in sorted_analytics:
            if count > 0:
                print(f"  🏆 {search_key}: {count} jobs")
        
        return final_jobs, search_analytics
    
    def store_jobs_in_database(
        self, 
        jobs: List[Dict[str, Any]], 
        db: Session,
        target_company_id: str = None,
        scraping_run_id: str = None
    ) -> Tuple[int, int]:
        """Store jobs in database with deduplication. Returns (new_jobs, duplicates).

        Robust to duplicates by handling IntegrityError per-row and committing per insert
        to avoid rolling back the entire batch on a single duplicate.
        
        Note: Deduplication is now per-scraping-run to allow different users to scrape
        the same jobs, while still preventing duplicates within the same scraping session.
        """

        from sqlalchemy.exc import IntegrityError

        new_jobs_count = 0
        duplicate_jobs_count = 0

        # Site priority for deduplication (prefer Indeed over LinkedIn)
        site_priority = {"indeed": 1, "glassdoor": 2, "zip_recruiter": 3, "linkedin": 4}

        for job_data in jobs:
            # Create both hash types for comprehensive deduplication
            job_hash = create_job_hash(
                title=job_data.get('title', ''),
                company=job_data.get('company', ''),
                location=job_data.get('location', ''),
                job_url=job_data.get('job_url', '')
            )

            content_hash = create_content_hash(
                title=job_data.get('title', ''),
                company=job_data.get('company', ''),
                location=job_data.get('location', '')
            )

            current_site = job_data.get('site', '').lower()

            # Check for URL-based duplicates first (exact same job posting)
            try:
                url_duplicate = db.query(ScrapedJob).filter(
                    ScrapedJob.job_hash == job_hash,
                    ScrapedJob.scraping_run_id == scraping_run_id
                ).first()
                if url_duplicate:
                    duplicate_jobs_count += 1
                    continue
            except Exception:
                pass

            # Check for content-based duplicates (same job from different platforms)
            try:
                content_duplicate = db.query(ScrapedJob).filter(
                    ScrapedJob.content_hash == content_hash,
                    ScrapedJob.scraping_run_id == scraping_run_id
                ).first()

                if content_duplicate:
                    # Apply site priority logic - keep the job from preferred site
                    existing_site = content_duplicate.site.lower()
                    existing_priority = site_priority.get(existing_site, 999)
                    current_priority = site_priority.get(current_site, 999)

                    if current_priority < existing_priority:
                        # Current job is from a preferred site, replace the existing one
                        print(f"Replacing {existing_site} job with {current_site} job: {job_data.get('title', '')}")
                        db.delete(content_duplicate)
                        db.flush()  # Ensure deletion is committed before insert
                    else:
                        # Keep existing job from preferred site
                        print(f"Skipping {current_site} job, keeping {existing_site} job: {job_data.get('title', '')}")
                        duplicate_jobs_count += 1
                        continue
            except Exception as e:
                print(f"Error checking content duplicates: {e}")
                pass

            # Extract experience years
            min_exp, max_exp = self.extract_experience_years(
                job_data.get('description', '')
            )

            # Parse date_posted
            date_posted = None
            if job_data.get('date_posted'):
                try:
                    if isinstance(job_data['date_posted'], str):
                        date_posted = datetime.fromisoformat(job_data['date_posted'])
                    elif isinstance(job_data['date_posted'], datetime):
                        date_posted = job_data['date_posted']
                    else:
                        # JobSpy often returns date objects
                        from datetime import date
                        if isinstance(job_data['date_posted'], date):
                            date_posted = datetime.combine(job_data['date_posted'], datetime.min.time())
                except Exception as e:
                    print(f"Failed to parse date_posted: {job_data.get('date_posted')} - {e}")
                    date_posted = None

            # Create new job record - use direct apply URL if available
            job_url = job_data.get('job_url_direct') or job_data.get('job_url')
            scraped_job = ScrapedJob(
                job_hash=job_hash,
                content_hash=content_hash,
                job_url=job_url,
                title=job_data.get('title', ''),
                company=job_data.get('company', ''),
                location=job_data.get('location'),
                site=job_data.get('site', 'indeed'),
                description=job_data.get('description'),
                job_type=job_data.get('job_type'),
                is_remote=job_data.get('is_remote'),
                min_amount=job_data.get('min_amount'),
                max_amount=job_data.get('max_amount'),
                salary_interval=job_data.get('interval', 'yearly'),
                currency=job_data.get('currency', 'USD'),
                date_posted=date_posted,
                min_experience_years=min_exp,
                max_experience_years=max_exp,
                target_company_id=target_company_id,
                scraping_run_id=scraping_run_id
            )

            try:
                db.add(scraped_job)
                db.commit()
                new_jobs_count += 1
            except IntegrityError as ie:
                # Unique violation (duplicate hash) or similar
                db.rollback()
                duplicate_jobs_count += 1
            except Exception as e:
                # Unexpected error on this row, rollback and continue
                db.rollback()
                print(f"❌ Error storing job: {str(e)}")
                continue

        print(f"💾 Stored {new_jobs_count} new jobs, skipped {duplicate_jobs_count} duplicates")
        return new_jobs_count, duplicate_jobs_count
    
    async def bulk_scrape_companies(
        self, 
        request: BulkScrapingRequest,
        db: Session
    ) -> ScrapingRun:
        """Scrape multiple companies in bulk."""
        
        # Create scraping run record
        start_time = datetime.now(timezone.utc)
        scraping_run = ScrapingRun(
            run_type="bulk_manual",
            status="running",
            companies_scraped=request.company_names,
            sites_used=request.sites,
            search_parameters=request.model_dump(),
            started_at=start_time
        )
        db.add(scraping_run)
        db.commit()
        
        total_jobs_found = 0
        total_new_jobs = 0
        total_duplicates = 0
        all_company_analytics = {}
        
        try:
            for company_name in request.company_names:
                print(f"\n🏢 Processing company: {company_name}")
                
                # Get or create target company
                target_company = db.query(TargetCompany).filter(
                    TargetCompany.name.ilike(f"%{company_name}%")
                ).first()
                
                if not target_company:
                    target_company = TargetCompany(
                        name=company_name,
                        display_name=company_name,
                        preferred_sites=request.sites,
                        search_terms=request.search_terms,
                        location_filters=request.locations
                    )
                    db.add(target_company)
                    db.commit()
                
                # Scrape jobs for this company
                jobs, company_analytics = await self.scrape_company_jobs(
                    company_name=company_name,
                    search_terms=request.search_terms,
                    sites=request.sites,
                    locations=request.locations,
                    results_wanted=request.results_per_company,
                    hours_old=request.hours_old,
                    comprehensive_terms=getattr(request, 'comprehensive_terms', None)
                )
                
                # Store analytics for this company
                all_company_analytics[company_name] = company_analytics
                
                if jobs:
                    # Store jobs in database
                    new_jobs, duplicates = self.store_jobs_in_database(
                        jobs=jobs,
                        db=db,
                        target_company_id=target_company.id,
                        scraping_run_id=scraping_run.id
                    )
                    
                    total_jobs_found += len(jobs)
                    total_new_jobs += new_jobs
                    total_duplicates += duplicates
                    
                    # Update target company stats
                    target_company.last_scraped = datetime.now(timezone.utc)
                    target_company.total_jobs_found = db.query(ScrapedJob).filter(
                        ScrapedJob.target_company_id == target_company.id,
                        ScrapedJob.is_active == True
                    ).count()
                    
                    db.commit()
                
                # Delay between companies
                await asyncio.sleep(2)
            
            # Update scraping run with results
            scraping_run.status = "completed"
            scraping_run.completed_at = datetime.now(timezone.utc)
            scraping_run.duration_seconds = int((scraping_run.completed_at - start_time).total_seconds())
            scraping_run.total_jobs_found = total_jobs_found
            scraping_run.new_jobs_added = total_new_jobs
            scraping_run.duplicate_jobs_skipped = total_duplicates
            scraping_run.search_analytics = all_company_analytics
            
            db.commit()
            
            print(f"\n🎉 Scraping completed!")
            print(f"📊 Total jobs found: {total_jobs_found}")
            print(f"➕ New jobs added: {total_new_jobs}")
            print(f"🔄 Duplicates skipped: {total_duplicates}")
            
        except Exception as e:
            scraping_run.status = "failed"
            scraping_run.error_message = str(e)
            scraping_run.completed_at = datetime.now(timezone.utc)
            scraping_run.duration_seconds = int((datetime.now(timezone.utc) - start_time).total_seconds())
            scraping_run.search_analytics = all_company_analytics
            db.commit()
            print(f"❌ Scraping failed: {str(e)}")
            raise
        
        return scraping_run

    async def bulk_scrape_companies_with_progress(
        self,
        request: BulkScrapingRequest,
        db: Session,
        scraping_run: ScrapingRun,
        company_timeout_seconds: int = 900
    ) -> None:
        """Scrape companies with real-time progress updates and per-company timeout.

        Updates scraping_run.current_progress, totals, and analytics as it proceeds.
        """
        start_time = scraping_run.started_at
        if start_time and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        total_jobs_found = 0
        total_new_jobs = 0
        total_duplicates = 0
        all_company_analytics: Dict[str, Dict[str, int]] = {}

        try:
            total_companies = len(request.company_names)
            for company_index, company_name in enumerate(request.company_names, start=1):
                company_start = datetime.now(timezone.utc)

                # Initialize/Update progress for this company
                scraping_run.current_progress = {
                    "phase": "processing_company",
                    "total_companies": total_companies,
                    "completed_companies": company_index - 1,
                    "current_company": company_name,
                    "current_company_index": company_index,
                    "current_search_term": None,
                    "current_location": None,
                    "term_index": 0,
                    "total_terms": 0,
                    "jobs_found_current_company": 0,
                    "company_elapsed_seconds": 0,
                    "company_timeout": False
                }
                db.commit()

                print(f"\n🏢 Processing company: {company_name}")

                # Get or create target company
                target_company = db.query(TargetCompany).filter(
                    TargetCompany.name.ilike(f"%{company_name}%")
                ).first()

                if not target_company:
                    target_company = TargetCompany(
                        name=company_name,
                        display_name=company_name,
                        preferred_sites=request.sites,
                        search_terms=request.search_terms,
                        location_filters=request.locations
                    )
                    db.add(target_company)
                    db.commit()

                # Prepare terms
                if not request.search_terms:
                    terms = [
                        "software engineer", "developer", "data scientist",
                        "product manager", "analyst", "designer"
                    ]
                elif len(request.search_terms) == 1 and request.search_terms[0].lower().strip() in ["all", "*", "all jobs"]:
                    terms = getattr(request, 'comprehensive_terms', None) or [
                        "tech", "analyst", "manager", "product", "engineer", "market",
                        "finance", "business", "associate", "senior", "director",
                        "president", "lead", "data", "science", "software", "cloud",
                        "developer", "staff", "program", "quality", "security", "specialist"
                    ]
                else:
                    terms = request.search_terms.copy() if request.search_terms else []

                # Always add company name and "all" as search terms for better coverage
                company_term = company_name.lower().strip()
                if company_term not in [term.lower().strip() for term in terms]:
                    terms.append(company_name)
                    print(f"🎯 Added company name '{company_name}' as search term")

                # Add "all" for broader coverage
                if "all" not in [term.lower().strip() for term in terms]:
                    terms.append("all")
                    print(f"🎯 Added 'all' as search term for broader coverage")

                locations = request.locations or ["USA", "Remote", "United States"]
                sites = request.sites or ["indeed"]
                results_wanted = request.results_per_company or 1000
                hours_old = request.hours_old or 72

                # In-memory dedup structure for this company to avoid duplicate inserts
                company_unique_map: Dict[str, Dict[str, Any]] = {}
                company_jobs: List[Dict[str, Any]] = []  # will be filled from the map
                company_analytics: Dict[str, int] = {}

                # Set total terms for display (terms x locations)
                total_term_steps = len(terms) * len(locations)
                scraping_run.current_progress.update({
                    "total_terms": total_term_steps
                })
                db.commit()

                step_counter = 0
                # Iterate locations and terms
                for location in locations:
                    for term in terms:
                        step_counter += 1
                        # Check timeout
                        company_elapsed = int((datetime.now(timezone.utc) - company_start).total_seconds())
                        if company_elapsed > company_timeout_seconds:
                            scraping_run.current_progress.update({
                                "phase": "company_timeout",
                                "company_elapsed_seconds": company_elapsed,
                                "company_timeout": True
                            })
                            db.commit()
                            print(f"⏱️ Timeout reached for {company_name}, skipping remaining steps")
                            break

                        # Update progress for this step
                        scraping_run.current_progress.update({
                            "phase": "searching",
                            "current_search_term": term,
                            "current_location": location,
                            "term_index": step_counter,
                            "company_elapsed_seconds": company_elapsed
                        })
                        db.commit()

                        # Build full search term with company
                        full_search = f"{term} {company_name}" if term.strip() else company_name
                        try:
                            print(f"  📍 Searching: '{full_search}' in {location}")
                            jobs_df = await asyncio.to_thread(
                                scrape_jobs,
                                site_name=sites,
                                search_term=full_search,
                                location=location,
                                results_wanted=results_wanted,
                                hours_old=hours_old,
                                country_indeed="USA",
                                verbose=1
                            )

                            found_count = 0
                            newly_added_this_step = 0
                            if jobs_df is not None and not jobs_df.empty:
                                # Filter by company name permissively
                                company_parts = company_name.lower().strip().split()
                                mask = jobs_df['company'].str.lower().str.contains('|'.join(company_parts), na=False, regex=True)
                                jobs_df = jobs_df[mask]

                                if not jobs_df.empty:
                                    jobs_list = jobs_df.to_dict('records')
                                    # Clean NaNs and add metadata
                                    for job in jobs_list:
                                        for key, value in job.items():
                                            if pd.isna(value):
                                                job[key] = None
                                        job['scraped_search_term'] = term
                                        job['scraped_location'] = location
                                    # In-memory dedup by URL or title-company-location
                                    for job in jobs_list:
                                        job_url = job.get('job_url') or job.get('job_url_direct')
                                        if job_url and isinstance(job_url, str) and job_url.strip():
                                            key = f"url::{job_url.strip()}"
                                        else:
                                            key = f"tcl::{(job.get('title') or '').strip().lower()}|{(job.get('company') or '').strip().lower()}|{(job.get('location') or '').strip().lower()}"
                                        if key not in company_unique_map:
                                            company_unique_map[key] = job
                                            newly_added_this_step += 1
                                    found_count = len(jobs_list)

                            # Update analytics and progress
                            search_key = f"{term}@{location}"
                            company_analytics[search_key] = found_count
                            scraping_run.current_progress.update({
                                "last_step_found": found_count,
                                # count only newly added (deduped) jobs for company progress
                                "jobs_found_current_company": scraping_run.current_progress.get("jobs_found_current_company", 0) + newly_added_this_step
                            })
                            db.commit()
                            if found_count:
                                print(f"  ✅ Found {found_count} jobs")
                            else:
                                print(f"  ❌ No jobs found")

                        except Exception as e:
                            print(f"  ❌ Error: {str(e)}")
                            continue

                    # If timeout on inner loop, break outer too
                    if scraping_run.current_progress.get("company_timeout"):
                        break

                # Store results for this company (values of dedup map)
                company_jobs = list(company_unique_map.values())
                if company_jobs:
                    try:
                        new_jobs, duplicates = self.store_jobs_in_database(
                            jobs=company_jobs,
                            db=db,
                            target_company_id=target_company.id,
                            scraping_run_id=scraping_run.id
                        )
                    except Exception as e:
                        # If a unique violation slips through (race/parallel), continue gracefully
                        print(f"  ⚠️ Insert error (continuing): {str(e)}")
                        db.rollback()
                        # Recompute counts conservatively
                        new_jobs = 0
                        duplicates = len(company_jobs)

                    total_jobs_found += len(company_jobs)
                    total_new_jobs += new_jobs
                    total_duplicates += duplicates

                    # Update company stats
                    target_company.last_scraped = datetime.now(timezone.utc)
                    target_company.total_jobs_found = db.query(ScrapedJob).filter(
                        ScrapedJob.target_company_id == target_company.id,
                        ScrapedJob.is_active == True
                    ).count()

                # Save analytics per company
                all_company_analytics[company_name] = company_analytics

                # Update running totals and mark company completed
                scraping_run.total_jobs_found = total_jobs_found
                scraping_run.new_jobs_added = total_new_jobs
                scraping_run.duplicate_jobs_skipped = total_duplicates
                scraping_run.current_progress.update({
                    "phase": "company_completed",
                    "completed_companies": company_index,
                })
                db.commit()

                # Small delay for visibility
                await asyncio.sleep(1)

            # Finalize run
            scraping_run.status = "completed"
            scraping_run.completed_at = datetime.now(timezone.utc)
            scraping_run.duration_seconds = int((scraping_run.completed_at - start_time).total_seconds())
            scraping_run.search_analytics = all_company_analytics
            scraping_run.current_progress = {
                "phase": "completed",
                "total_companies": total_companies,
                "completed_companies": total_companies,
            }
            db.commit()
            print("\n🎉 Background scraping completed!")

        except Exception as e:
            scraping_run.status = "failed"
            scraping_run.error_message = str(e)
            scraping_run.completed_at = datetime.now(timezone.utc)
            scraping_run.current_progress = {
                "phase": "failed",
                "error": str(e)
            }
            db.commit()
    
    def search_local_jobs(
        self, 
        db: Session,
        search_term: str = None,
        company_names: List[str] = None,
        locations: List[str] = None,
        job_types: List[str] = None,
        is_remote: bool = None,
        min_salary: float = None,
        max_salary: float = None,
        max_experience_years: int = None,
        sites: List[str] = None,
        days_old: int = 30,
        limit: int = 100,
        offset: int = 0,
        exclude_keywords: str = None
    ) -> Tuple[List[ScrapedJob], int]:
        """Search jobs in local database."""
        
        print(f"🔎 SEARCH_LOCAL_JOBS called with: search_term={search_term}, sites={sites}, days_old={days_old}")
        
        # Build query
        query = db.query(ScrapedJob).filter(ScrapedJob.is_active == True)
        print(f"🗄️ Base query created, checking for active jobs")
        
        # Date filter
        if days_old:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
            query = query.filter(
                or_(
                    ScrapedJob.date_posted >= cutoff_date,
                    ScrapedJob.date_posted.is_(None)  # Include jobs without date_posted
                )
            )
        
        # Search term filter
        if search_term:
            search_filter = or_(
                ScrapedJob.title.ilike(f"%{search_term}%"),
                ScrapedJob.description.ilike(f"%{search_term}%"),
                ScrapedJob.company.ilike(f"%{search_term}%")
            )
            query = query.filter(search_filter)
        
        # Company filter
        if company_names:
            company_filter = or_(*[
                ScrapedJob.company.ilike(f"%{company}%") 
                for company in company_names
            ])
            query = query.filter(company_filter)
        
        # Location filter
        if locations:
            location_filter = or_(*[
                ScrapedJob.location.ilike(f"%{location}%") 
                for location in locations
            ])
            query = query.filter(location_filter)
        
        # Job type filter
        if job_types:
            query = query.filter(ScrapedJob.job_type.in_(job_types))
        
        # Remote filter
        if is_remote is not None:
            query = query.filter(ScrapedJob.is_remote == is_remote)
        
        # Salary filters
        if min_salary:
            query = query.filter(
                or_(
                    ScrapedJob.min_amount >= min_salary,
                    ScrapedJob.max_amount >= min_salary
                )
            )
        
        if max_salary:
            query = query.filter(
                or_(
                    ScrapedJob.min_amount <= max_salary,
                    ScrapedJob.max_amount <= max_salary
                )
            )
        
        # Experience filter
        if max_experience_years:
            query = query.filter(
                or_(
                    ScrapedJob.min_experience_years <= max_experience_years,
                    ScrapedJob.min_experience_years.is_(None)
                )
            )
        
        # Site filter
        if sites:
            query = query.filter(ScrapedJob.site.in_(sites))
        
        # Exclude keywords filter
        if exclude_keywords:
            exclude_terms = [term.strip().lower() for term in exclude_keywords.split(',') if term.strip()]
            if exclude_terms:
                # Exclude jobs that contain any of the exclude terms in the title
                exclude_filters = []
                for term in exclude_terms:
                    exclude_filters.append(~ScrapedJob.title.ilike(f'%{term}%'))
                query = query.filter(and_(*exclude_filters))
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        jobs = query.order_by(
            ScrapedJob.date_posted.desc().nullslast(),
            ScrapedJob.date_scraped.desc()
        ).offset(offset).limit(limit).all()
        
        return jobs, total_count


# Global instance
job_scraper = JobScrapingService()