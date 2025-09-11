#!/usr/bin/env python3
"""
Test script for targeted company scraping
Usage: python test_targeted_scraping.py
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def get_available_companies():
    """Get list of available companies from database."""
    try:
        response = requests.get(f"{BASE_URL}/target-companies-public")
        if response.ok:
            data = response.json()
            companies = data.get('companies', [])
            print(f"📋 Available companies ({len(companies)}):")
            for i, company in enumerate(companies[:20], 1):  # Show first 20
                print(f"   {i:2d}. {company['name']}")
            if len(companies) > 20:
                print(f"   ... and {len(companies) - 20} more")
            return [c['name'] for c in companies]
        else:
            print(f"❌ Failed to get companies: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Error getting companies: {e}")
        return []

def trigger_targeted_scraping(company_names, search_terms=None):
    """Trigger scraping for specific companies."""
    try:
        params = {}
        if company_names:
            params['company_names'] = company_names
        if search_terms:
            params['search_terms'] = search_terms
            
        response = requests.post(f"{BASE_URL}/admin/scheduler/trigger", params=params)
        
        if response.ok:
            data = response.json()
            print(f"✅ {data['message']}")
            return True
        else:
            print(f"❌ Failed to trigger scraping: {response.status_code}")
            print(f"Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error triggering scraping: {e}")
        return False

def main():
    print("🎯 Targeted Company Scraping Test")
    print("=" * 50)
    
    # Get available companies
    available_companies = get_available_companies()
    
    if not available_companies:
        print("❌ No companies available. Make sure server is running.")
        return
    
    while True:
        print("\n🎯 Choose scraping options:")
        print("  1. Scrape specific companies")
        print("  2. Scrape all companies (default)")
        print("  3. Test with sample companies")
        print("  4. Exit")
        
        try:
            choice = input("\nEnter choice (1-4): ").strip()
            
            if choice == '1':
                # Manual company selection
                print("\n📝 Enter company names (comma-separated):")
                print("Example: Google, Microsoft, Apple")
                company_input = input("Companies: ").strip()
                
                if not company_input:
                    print("❌ No companies entered")
                    continue
                
                company_names = [name.strip() for name in company_input.split(',')]
                
                # Optional search terms
                print("\n🔍 Enter search terms (comma-separated, or press Enter for default):")
                print("Example: software engineer, developer, product manager")
                search_input = input("Search terms: ").strip()
                
                search_terms = [term.strip() for term in search_input.split(',')] if search_input else None
                
                print(f"\n🚀 Triggering scraping for: {', '.join(company_names)}")
                if search_terms:
                    print(f"🔍 Search terms: {', '.join(search_terms)}")
                
                if trigger_targeted_scraping(company_names, search_terms):
                    print("\n📝 Check server logs to see progress:")
                    print("   - Look for '🎯 Starting targeted scraping'")
                    print("   - Progress will show company by company")
                    print("   - Final results will show '✅ Targeted scraping completed'")
                
            elif choice == '2':
                print("\n🌍 Triggering scraping for ALL companies...")
                if trigger_targeted_scraping(None):
                    print("📝 Check server logs for progress")
                    
            elif choice == '3':
                # Test with sample companies
                sample_companies = ['Google', 'Microsoft', 'Apple']
                sample_search_terms = ['software engineer', 'developer']
                
                print(f"\n🧪 Testing with sample companies: {', '.join(sample_companies)}")
                print(f"🔍 Search terms: {', '.join(sample_search_terms)}")
                
                if trigger_targeted_scraping(sample_companies, sample_search_terms):
                    print("📝 Check server logs for progress")
                    
            elif choice == '4':
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