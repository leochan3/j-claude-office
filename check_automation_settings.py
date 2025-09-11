#!/usr/bin/env python3
"""
Script to check and configure automation scraping parameters
Usage: python check_automation_settings.py
"""
import sys
import os
import json
from datetime import datetime

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

def check_environment_variables():
    """Check automation-related environment variables."""
    print("🌍 Environment Variables:")
    
    env_vars = {
        "AUTO_SCRAPING_ENABLED": os.getenv("AUTO_SCRAPING_ENABLED", "true"),
        "AUTO_SCRAPING_TIME": os.getenv("AUTO_SCRAPING_TIME", "20:55"),
        "AUTO_SCRAPING_MAX_RESULTS": os.getenv("AUTO_SCRAPING_MAX_RESULTS", "100"),
        "AUTO_SCRAPING_SEARCH_TERMS": os.getenv("AUTO_SCRAPING_SEARCH_TERMS", ""),
        "EMAIL_NOTIFICATIONS_ENABLED": os.getenv("EMAIL_NOTIFICATIONS_ENABLED", "false"),
        "EMAIL_USER": os.getenv("EMAIL_USER", ""),
        "NOTIFICATION_EMAIL": os.getenv("NOTIFICATION_EMAIL", "")
    }
    
    for key, value in env_vars.items():
        status = "✅" if value and value != "false" else "❌"
        print(f"   {status} {key}: {value if value else '(not set)'}")
    
    return env_vars

def check_scraping_defaults():
    """Check scraping_defaults.json configuration."""
    print("\n📄 Scraping Defaults (scraping_defaults.json):")
    
    defaults_file = "backend/scraping_defaults.json"
    if not os.path.exists(defaults_file):
        print("   ❌ File not found")
        return None
    
    try:
        with open(defaults_file, 'r') as f:
            data = json.load(f)
        
        print(f"   ✅ Companies: {data.get('companies', [])}")
        print(f"   ✅ Search Terms: {data.get('search_terms', [])}")
        print(f"   ✅ Locations: {data.get('locations', [])}")
        print(f"   ✅ Hours Old: {data.get('hours_old', 'not set')}")
        print(f"   ✅ Results Per Company: {data.get('results_per_company', 'not set')}")
        
        return data
        
    except Exception as e:
        print(f"   ❌ Error reading file: {e}")
        return None

def get_current_automation_settings():
    """Get the current effective automation settings."""
    print("\n⚙️ Current Automation Settings:")
    
    # Simulate what scheduler.py does
    enabled = os.getenv("AUTO_SCRAPING_ENABLED", "true").lower() == "true"
    schedule_time = os.getenv("AUTO_SCRAPING_TIME", "20:55")
    max_results = int(os.getenv("AUTO_SCRAPING_MAX_RESULTS", "100"))
    
    # Check if defaults file has overrides
    defaults_data = None
    defaults_file = "backend/scraping_defaults.json"
    if os.path.exists(defaults_file):
        try:
            with open(defaults_file, 'r') as f:
                defaults_data = json.load(f)
        except:
            pass
    
    # Determine effective hours_old
    hours_old = defaults_data.get('hours_old') if defaults_data else None
    if not hours_old:
        hours_old = 168  # 7 days default (7 * 24 = 168)
    
    # Determine effective results_per_company
    results_per_company = defaults_data.get('results_per_company') if defaults_data else None
    if not results_per_company:
        results_per_company = max_results
    
    print(f"   📅 Schedule Time: {schedule_time} (daily)")
    print(f"   ✅ Enabled: {enabled}")
    print(f"   🔢 Results Per Company: {results_per_company}")
    print(f"   ⏰ Hours Old (Job Age Limit): {hours_old} hours ({hours_old/24:.1f} days)")
    print(f"   🏢 Companies: {len(defaults_data.get('companies', []))} configured")
    print(f"   🔍 Search Terms: {len(defaults_data.get('search_terms', []))} configured")
    
    return {
        "enabled": enabled,
        "schedule_time": schedule_time,
        "results_per_company": results_per_company,
        "hours_old": hours_old,
        "companies": defaults_data.get('companies', []) if defaults_data else [],
        "search_terms": defaults_data.get('search_terms', []) if defaults_data else []
    }

def show_configuration_examples():
    """Show examples of how to configure the parameters."""
    print("\n🛠️ How to Configure Automation Parameters:")
    print("\n1️⃣ Via Environment Variables (Temporary):")
    print("   export AUTO_SCRAPING_MAX_RESULTS=200")
    print("   export AUTO_SCRAPING_TIME=06:00")
    print("   export AUTO_SCRAPING_ENABLED=true")
    
    print("\n2️⃣ Via scraping_defaults.json (Persistent):")
    example_config = {
        "companies": ["Pfizer", "Johnson & Johnson", "Novartis"],
        "search_terms": ["all", "analyst", "manager", "scientist"],
        "locations": ["USA"],
        "hours_old": 48,  # 2 days
        "results_per_company": 150,
        "updated_at": datetime.now().isoformat()
    }
    print(json.dumps(example_config, indent=2))
    
    print("\n3️⃣ Parameter Explanations:")
    print("   • results_per_company: Max jobs to scrape per company (default: 100)")
    print("   • hours_old: Only scrape jobs posted within this timeframe")
    print("     - 24 = 1 day")
    print("     - 72 = 3 days (current setting)")
    print("     - 168 = 7 days (scheduler default)")
    print("   • companies: List of company names (must exist in database)")
    print("   • search_terms: Job titles/keywords to search for")

def check_scheduler_status():
    """Check if the scheduler is running via API."""
    print("\n🔄 Scheduler Status (via API):")
    try:
        import requests
        response = requests.get("http://localhost:8000/admin/scheduler/status")
        if response.status_code == 200:
            data = response.json()
            scheduler = data['scheduler']
            print(f"   📊 Running: {'✅' if scheduler['running'] else '❌'}")
            print(f"   📊 Enabled: {'✅' if scheduler['enabled'] else '❌'}")
            print(f"   📊 Next Run: {scheduler['next_run']}")
            print(f"   📊 Active Companies: {scheduler['active_companies_count']}")
            print(f"   📊 Max Results/Company: {scheduler['max_results_per_company']}")
            return True
        else:
            print(f"   ❌ API Error: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Could not connect to API: {e}")
        print("   💡 Make sure backend is running: python backend/main.py")
        return False

if __name__ == "__main__":
    print("⚙️ JobSpy Automation Configuration Check")
    print("=" * 50)
    
    # Check all configuration sources
    env_vars = check_environment_variables()
    defaults_data = check_scraping_defaults()
    settings = get_current_automation_settings()
    
    print("\n" + "=" * 50)
    
    # Check scheduler status
    api_available = check_scheduler_status()
    
    print("\n" + "=" * 50)
    
    # Show configuration examples
    show_configuration_examples()
    
    print("\n" + "=" * 50)
    print("📋 Summary:")
    print(f"   Current Results Per Company: {settings['results_per_company']}")
    print(f"   Current Hours Old Limit: {settings['hours_old']} hours")
    print(f"   Companies Configured: {len(settings['companies'])}")
    print(f"   Automation Status: {'✅ Enabled' if settings['enabled'] else '❌ Disabled'}")
    
    if not api_available:
        print("\n💡 To test changes:")
        print("   1. Start backend: python backend/main.py")
        print("   2. Test trigger: python test_manual_trigger.py")
    
    print("\n🎯 To modify settings, edit backend/scraping_defaults.json or set environment variables")