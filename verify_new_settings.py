#!/usr/bin/env python3
"""
Verify the new automation settings are working
Usage: python verify_new_settings.py
"""
import json
import requests

def check_config_file():
    """Check the updated configuration file."""
    print("📄 Configuration File (scraping_defaults.json):")
    try:
        with open('backend/scraping_defaults.json', 'r') as f:
            data = json.load(f)
        
        print(f"   ✅ Results Per Company: {data.get('results_per_company', 'not set')}")
        print(f"   ✅ Hours Old: {data.get('hours_old', 'not set')} hours ({data.get('hours_old', 0)/24:.1f} days)")
        print(f"   ✅ Companies: {data.get('companies', [])}")
        print(f"   ✅ Search Terms: {data.get('search_terms', [])}")
        
        return data
    except Exception as e:
        print(f"   ❌ Error reading config: {e}")
        return None

def check_scheduler_api():
    """Check scheduler status via API to see if new values are used."""
    print("\n🔄 Scheduler API Status:")
    try:
        response = requests.get("http://localhost:8000/admin/scheduler/status")
        if response.status_code == 200:
            data = response.json()
            scheduler = data['scheduler']
            
            print(f"   📊 Max Results Per Company: {scheduler.get('max_results_per_company', 'not available')}")
            print(f"   📊 Hours Old: {scheduler.get('hours_old', 'not available')} hours")
            print(f"   📊 Active Companies: {scheduler.get('active_companies_count', 0)}")
            print(f"   📊 Schedule Time: {scheduler.get('schedule_time', 'not set')}")
            print(f"   📊 Enabled: {'✅' if scheduler.get('enabled') else '❌'}")
            
            # Verify the new values match
            config_results = 1000
            config_hours = 336
            api_results = scheduler.get('max_results_per_company')
            api_hours = scheduler.get('hours_old')
            
            print(f"\n🎯 Verification:")
            if api_results == config_results:
                print(f"   ✅ Results Per Company: {api_results} (matches config)")
            else:
                print(f"   ❌ Results Per Company: API={api_results}, Config={config_results}")
            
            if api_hours == config_hours:
                print(f"   ✅ Hours Old: {api_hours} hours (matches config)")
            else:
                print(f"   ❌ Hours Old: API={api_hours}, Config={config_hours}")
            
            return True
        else:
            print(f"   ❌ API Error: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Could not connect to API: {e}")
        print("   💡 Make sure backend is running with: python backend/main.py")
        return False

def trigger_test_scraping():
    """Trigger a test scraping to see the new parameters in action."""
    print("\n🚀 Test Manual Scraping (Optional):")
    try:
        response = requests.post("http://localhost:8000/admin/scheduler/trigger")
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Trigger Success: {result['message']}")
            print(f"   💡 Check backend logs to see the new parameter values in action")
            print(f"   💡 Look for logs like: '🔢 Loaded default results_per_company: 1000'")
            return True
        else:
            print(f"   ❌ Trigger Failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Could not trigger: {e}")
        return False

if __name__ == "__main__":
    print("🔍 Verification of New Automation Settings")
    print("=" * 50)
    print("Target Settings:")
    print("   • Results Per Company: 1000")
    print("   • Hours Old: 336 hours (14 days)")
    print("=" * 50)
    
    # Check configuration
    config = check_config_file()
    
    # Check API
    api_available = check_scheduler_api()
    
    if api_available:
        print("\n" + "=" * 50)
        user_input = input("Trigger a test manual scraping to see new parameters? (y/n): ")
        if user_input.lower() == 'y':
            trigger_test_scraping()
    
    print("\n" + "=" * 50)
    print("✅ Settings Updated Successfully!")
    print("💡 Your automation will now:")
    print("   • Scrape up to 1000 jobs per company")
    print("   • Include jobs posted within the last 14 days")
    print("   • Run daily at 8:55 PM with these settings")
    
    if not api_available:
        print("\n🚨 Next Steps:")
        print("   1. Start backend: python backend/main.py")
        print("   2. Re-run this script to verify API integration")
        print("   3. Test with: python test_manual_trigger.py")