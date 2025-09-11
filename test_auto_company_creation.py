#!/usr/bin/env python3
"""
Test automatic company creation functionality
Usage: python test_auto_company_creation.py
"""
import sys
import os
import json
import requests

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

def update_config_with_test_company(test_company="Apple"):
    """Update scraping_defaults.json with a test company."""
    config_file = "backend/scraping_defaults.json"
    
    print(f"🔧 Setting test company: {test_company}")
    
    try:
        # Read current config
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        # Update with test company
        config["companies"] = [test_company.lower()]
        config["updated_at"] = "2025-09-11T16:00:00.000000"
        
        # Write back
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ Updated scraping_defaults.json with company: {test_company}")
        return True
        
    except Exception as e:
        print(f"❌ Error updating config: {e}")
        return False

def check_company_in_database(company_name):
    """Check if company exists in database via API."""
    try:
        response = requests.get("http://localhost:8000/admin/target-companies")
        if response.status_code == 200:
            companies = response.json()
            for company in companies:
                if company['name'].lower() == company_name.lower():
                    print(f"✅ Found {company_name} in database: ID={company['id']}")
                    return True
            print(f"❌ {company_name} not found in database")
            return False
        else:
            print(f"❌ Could not check database: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return False

def trigger_scraping():
    """Trigger manual scraping to test auto-company creation."""
    print(f"\n🚀 Triggering manual scraping...")
    try:
        response = requests.post("http://localhost:8000/admin/scheduler/trigger")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Scraping triggered: {result['message']}")
            return True
        else:
            print(f"❌ Trigger failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Could not trigger scraping: {e}")
        return False

def monitor_logs():
    """Show what to look for in the logs."""
    print(f"\n👀 Watch backend logs for these messages:")
    print(f"")
    print(f"🔧 Auto-creation:")
    print(f"   INFO:scheduler:🔧 Company 'apple' not found in database, creating it automatically...")
    print(f"   INFO:scheduler:🏢 Auto-created target company: Apple")
    print(f"   INFO:scheduler:✅ Created and added target company: Apple")
    print(f"")
    print(f"📊 Successful scraping:")
    print(f"   INFO:scheduler:✅ Found target company: Apple")
    print(f"   INFO:scheduler:🏢 Processing company: Apple")
    print(f"   INFO:scheduler:🔍 Scraping jobs for Apple")

if __name__ == "__main__":
    print("🧪 Auto-Company Creation Test")
    print("=" * 50)
    
    # Choose test company (something not likely in database)
    test_company = "Apple"
    
    print(f"Testing with company: {test_company}")
    
    # Step 1: Check if company exists before test
    print(f"\n1️⃣ Pre-test: Check if {test_company} exists in database")
    company_exists_before = check_company_in_database(test_company)
    
    # Step 2: Update config file
    print(f"\n2️⃣ Update configuration file")
    if not update_config_with_test_company(test_company):
        print("❌ Failed to update config. Exiting.")
        exit(1)
    
    # Step 3: Check API availability
    print(f"\n3️⃣ Check if backend is running")
    try:
        response = requests.get("http://localhost:8000/health")
        if response.status_code != 200:
            print("❌ Backend not responding. Start with: python backend/main.py")
            exit(1)
        print("✅ Backend is running")
    except:
        print("❌ Backend not running. Start with: python backend/main.py")
        exit(1)
    
    # Step 4: Trigger scraping
    print(f"\n4️⃣ Trigger manual scraping (this will auto-create the company)")
    if trigger_scraping():
        # Step 5: Wait and check if company was created
        print(f"\n5️⃣ Wait a moment for scraping to complete...")
        print(f"   (Check backend terminal for detailed logs)")
        
        import time
        time.sleep(3)  # Give it a moment
        
        print(f"\n6️⃣ Check if {test_company} was created in database")
        company_exists_after = check_company_in_database(test_company)
        
        if company_exists_after and not company_exists_before:
            print(f"\n🎉 SUCCESS! Auto-company creation worked!")
            print(f"   • {test_company} was automatically created during scraping")
            print(f"   • You can now add any company to scraping_defaults.json")
            print(f"   • No need to manually create companies in database")
        elif company_exists_after and company_exists_before:
            print(f"\n✅ Company existed before test (cannot verify auto-creation)")
        else:
            print(f"\n❌ Auto-creation may have failed. Check backend logs.")
    
    # Show log monitoring instructions
    monitor_logs()
    
    print(f"\n" + "=" * 50)
    print(f"💡 Now you can add any company to scraping_defaults.json!")
    print(f"💡 The system will automatically create missing companies.")
    print(f"💡 No more 'Company not found in database' errors!")