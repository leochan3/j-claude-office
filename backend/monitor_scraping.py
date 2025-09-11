#!/usr/bin/env python3
"""
Simple script to monitor automated scraping progress
Usage: python monitor_scraping.py
"""
import os
import time
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def check_scheduler_status():
    """Check the current scheduler status."""
    try:
        response = requests.get(f"{BASE_URL}/admin/scheduler/status")
        if response.ok:
            data = response.json()
            scheduler = data['scheduler']
            print(f"\n📊 Scheduler Status:")
            print(f"   Running: {'✅' if scheduler['running'] else '❌'}")
            print(f"   Enabled: {'✅' if scheduler['enabled'] else '❌'}")
            print(f"   Next Run: {scheduler['next_run']}")
            print(f"   Companies: {scheduler['active_companies_count']}")
            print(f"   Max Results/Company: {scheduler['max_results_per_company']}")
            print(f"   Search Terms: {', '.join(scheduler['default_search_terms'][:3])}{'...' if len(scheduler['default_search_terms']) > 3 else ''}")
        else:
            print(f"❌ Failed to get scheduler status: {response.status_code}")
    except Exception as e:
        print(f"❌ Error checking scheduler: {e}")

def trigger_manual_scraping():
    """Trigger manual scraping."""
    try:
        response = requests.post(f"{BASE_URL}/admin/scheduler/trigger")
        if response.ok:
            data = response.json()
            print(f"✅ {data['message']}")
            return True
        else:
            print(f"❌ Failed to trigger scraping: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error triggering scraping: {e}")
        return False

def check_database_stats():
    """Check database statistics to see scraping results."""
    try:
        response = requests.get(f"{BASE_URL}/database-stats-public")
        if response.ok:
            data = response.json()
            stats = data['statistics']
            print(f"\n📊 Database Stats:")
            print(f"   Users: {stats.get('users', 'N/A')}")
            print(f"   Target Companies: {stats.get('target_companies', 'N/A')}")
            print(f"   Scraped Jobs: {stats.get('scraped_jobs', 'N/A')}")
            print(f"   Scraping Runs: {stats.get('scraping_runs', 'N/A')}")
        else:
            print(f"❌ Failed to get database stats: {response.status_code}")
    except Exception as e:
        print(f"❌ Error checking database: {e}")

def main():
    print("🔍 JobSpy Scraping Monitor")
    print("=" * 50)
    
    while True:
        print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        
        # Show menu
        print("\nOptions:")
        print("  1. Check scheduler status")
        print("  2. Trigger manual scraping")
        print("  3. Check database stats")
        print("  4. Monitor continuously (10s intervals)")
        print("  5. Exit")
        
        try:
            choice = input("\nEnter choice (1-5): ").strip()
            
            if choice == '1':
                check_scheduler_status()
            elif choice == '2':
                print("🚀 Triggering manual scraping...")
                if trigger_manual_scraping():
                    print("📝 Check server logs for progress")
                    print("💡 Tip: Run the backend with 'python main.py' to see live logs")
            elif choice == '3':
                check_database_stats()
            elif choice == '4':
                print("🔄 Monitoring continuously... (Press Ctrl+C to stop)")
                try:
                    while True:
                        print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')}")
                        check_scheduler_status()
                        check_database_stats()
                        time.sleep(10)
                except KeyboardInterrupt:
                    print("\n👋 Stopped monitoring")
            elif choice == '5':
                print("👋 Goodbye!")
                break
            else:
                print("❌ Invalid choice")
                
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()