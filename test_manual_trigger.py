#!/usr/bin/env python3
"""
Test script to trigger manual scraping via API
Usage: python test_manual_trigger.py
"""
import requests
import json

def trigger_manual_scraping():
    """Trigger manual scraping via API."""
    api_url = "http://localhost:8000/admin/scheduler/trigger"
    
    try:
        print("🚀 Triggering manual scraping...")
        response = requests.post(api_url)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Success: {result['message']}")
            return True
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to backend server")
        print("Make sure the backend is running on http://localhost:8000")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def check_scheduler_status():
    """Check the current scheduler status."""
    try:
        response = requests.get("http://localhost:8000/admin/scheduler/status")
        if response.status_code == 200:
            data = response.json()
            scheduler = data['scheduler']
            print(f"\n📊 Scheduler Status:")
            print(f"   Running: {'✅' if scheduler['running'] else '❌'}")
            print(f"   Enabled: {'✅' if scheduler['enabled'] else '❌'}")
            print(f"   Next Run: {scheduler['next_run']}")
            print(f"   Companies: {scheduler['active_companies_count']}")
            print(f"   Max Results/Company: {scheduler['max_results_per_company']}")
            return True
        else:
            print(f"❌ Failed to get scheduler status: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error checking scheduler: {e}")
        return False

if __name__ == "__main__":
    print("🔍 JobSpy Manual Trigger Test")
    print("=" * 40)
    
    # Check status first
    if check_scheduler_status():
        print("\n" + "=" * 40)
        # Trigger manual scraping
        trigger_manual_scraping()
    
    print("\n📝 Note: Check the backend logs for detailed scraping progress")