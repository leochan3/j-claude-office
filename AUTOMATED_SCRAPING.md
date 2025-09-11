# Automated Job Scraping System

The JobSpy application now includes an **automated daily job scraping system** that runs in the background and scrapes jobs from your target companies automatically.

## 🚀 Features

- **Daily Automatic Scraping**: Runs at a configurable time each day (default: 2:00 AM)
- **Smart Company Management**: Only scrapes companies that haven't been scraped in the last 23 hours
- **Configurable Search Terms**: Use default search terms or company-specific ones
- **Multiple Job Sites**: Supports Indeed, LinkedIn, and other job boards
- **API Control**: Start/stop/trigger scraping via API endpoints
- **Background Operation**: Runs independently without blocking the main application

## 📋 Prerequisites

1. **Target Companies**: Add companies to scrape via the admin interface at `/admin#companies`
2. **Environment Configuration**: Set up your `.env` file with scraping preferences
3. **Dependencies**: Install the `schedule` package (already in requirements.txt)

## 🔧 Configuration

Configure automated scraping in your `.env` file:

```env
# Enable/disable automated scraping
AUTO_SCRAPING_ENABLED=true

# Time to run daily scraping (24-hour format)
AUTO_SCRAPING_TIME=02:00

# Maximum results per company per scraping run
AUTO_SCRAPING_MAX_RESULTS=100

# Default search terms (comma-separated)
AUTO_SCRAPING_SEARCH_TERMS=software engineer,developer,product manager,data scientist

# Default scraping settings
DEFAULT_SCRAPING_SITES=indeed,linkedin
DEFAULT_SCRAPING_LOCATION=USA
DEFAULT_SCRAPING_DAYS_OLD=7
```

## 🎯 How It Works

### 1. **Target Company Setup**
- Add companies via `/admin#companies` interface
- Each company can have:
  - Custom search terms (optional)
  - Preferred job sites (optional) 
  - Location filters (optional)
- Companies marked as `is_active = true` will be included in automated scraping

### 2. **Daily Scheduling**
- Scheduler runs at the configured time (`AUTO_SCRAPING_TIME`)
- Checks which companies need scraping (not scraped in last 23 hours)
- Combines all search terms from companies + default terms
- Executes bulk scraping for all qualifying companies

### 3. **Smart Deduplication**
- Uses existing job deduplication logic (job_hash)
- Only stores new jobs, skips duplicates
- Updates `last_scraped` timestamp for each company

## 🎮 API Endpoints

### Get Scheduler Status
```http
GET /admin/scheduler/status
Authorization: Bearer <token>
```

Returns current scheduler information:
```json
{
  "success": true,
  "scheduler": {
    "enabled": true,
    "running": true,
    "schedule_time": "02:00",
    "next_run": "2024-01-15T02:00:00Z",
    "active_companies_count": 5,
    "max_results_per_company": 100,
    "default_search_terms": ["software engineer", "developer"]
  }
}
```

### Start Scheduler
```http
POST /admin/scheduler/start
Authorization: Bearer <token>
```

### Stop Scheduler
```http
POST /admin/scheduler/stop
Authorization: Bearer <token>
```

### Trigger Manual Scraping
```http
POST /admin/scheduler/trigger
Authorization: Bearer <token>
```

Runs scraping immediately (bypasses schedule).

## 🔄 Manual Operation

If you need to trigger scraping outside the schedule:

### Option 1: API Endpoint
Use the `/admin/scheduler/trigger` endpoint (requires authentication).

### Option 2: Trigger File
Create a trigger file to run scraping on the next check cycle:
```bash
# This will trigger scraping within 1 minute
touch /tmp/trigger_scraping
```

### Option 3: Direct API Call
Use the existing bulk scraping endpoints:
- `/admin/scrape-bulk` (authenticated)
- `/scrape-bulk-public` (public)

## 📊 Monitoring & Logs

### Application Logs
The scheduler logs all activities:
```
🚀 Starting automated daily scraping at 2024-01-15T02:00:00Z
📋 Found 5 active target companies
🔍 Will scrape 3 companies with 8 search terms
✅ Automated scraping completed successfully!
   Duration: 45.3 seconds
   Scraping run ID: 12345
```

### Database Tracking
- **ScrapingRun**: Track each automated scraping session
- **TargetCompany.last_scraped**: Know when each company was last scraped
- **ScrapedJob**: All scraped jobs with deduplication

### Admin Interface
Monitor scraping activity at:
- `/admin#scraping` - View scraping runs and progress
- `/admin#companies` - Manage target companies
- `/admin#stats` - Overall database statistics

## 🚨 Troubleshooting

### Scheduler Not Running
1. Check logs for startup errors
2. Verify `AUTO_SCRAPING_ENABLED=true` in `.env`
3. Restart the application

### No Companies Being Scraped
1. Check that target companies exist and are active
2. Verify companies haven't been scraped recently (< 23 hours)
3. Check logs for specific error messages

### Scraping Failures
1. Check job board rate limits (especially LinkedIn)
2. Verify internet connectivity
3. Review search terms and company names for accuracy
4. Check individual company scraping preferences

### Performance Issues
1. Reduce `AUTO_SCRAPING_MAX_RESULTS` per company
2. Limit number of active target companies
3. Adjust scraping schedule to off-peak hours
4. Use fewer job sites (Indeed is typically faster)

## 💡 Best Practices

### Search Terms
- Use specific, relevant terms for your industry
- Include common variations (e.g., "software engineer", "SWE", "developer")
- Avoid overly broad terms that return irrelevant results

### Company Management  
- Keep target company list focused and relevant
- Regularly review and update company preferences
- Disable companies you're no longer interested in

### Timing
- Schedule during off-peak hours (2-4 AM is recommended)
- Allow sufficient time between manual and automated scraping
- Consider time zones if using remote job boards

### Rate Limiting
- Indeed: Generally no rate limits
- LinkedIn: More restrictive, may need longer intervals
- Consider using proxies for heavy usage

## 🔮 Future Enhancements

Possible improvements for future versions:
- Email notifications for successful/failed runs
- Slack/Discord webhook integration
- Per-company scheduling (different intervals)
- Intelligent retry logic for failed scrapes
- Integration with external job alert services
- Advanced filtering based on job descriptions
- Historical analytics and trend reporting

## 📞 Support

If you encounter issues:
1. Check the application logs
2. Verify your configuration in `.env`
3. Test with manual scraping first
4. Review the API documentation at `/docs`

The automated scraping system is designed to be robust and low-maintenance, running quietly in the background to keep your job database fresh and up-to-date!