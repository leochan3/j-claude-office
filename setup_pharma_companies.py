#!/usr/bin/env python3
"""
Script to add major pharmaceutical companies to the target companies database
Usage: python setup_pharma_companies.py
"""
import sys
import os

# Add backend to path so we can import database modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from database import SessionLocal, TargetCompany

# Major pharmaceutical companies
PHARMA_COMPANIES = [
    {
        "name": "Pfizer",
        "display_name": "Pfizer Inc.",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "Johnson & Johnson", 
        "display_name": "Johnson & Johnson",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "Roche",
        "display_name": "Roche Holding AG",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "Novartis",
        "display_name": "Novartis AG",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "Merck & Co",
        "display_name": "Merck & Co., Inc.",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "AbbVie",
        "display_name": "AbbVie Inc.",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "GSK",
        "display_name": "GlaxoSmithKline plc",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    },
    {
        "name": "AstraZeneca",
        "display_name": "AstraZeneca PLC",
        "search_terms": ["all", "analyst", "manager", "scientist", "clinical", "research", "regulatory"]
    }
]

def add_company(company_data):
    """Add a single company to the database."""
    db = SessionLocal()
    try:
        # Check if company already exists
        existing = db.query(TargetCompany).filter(
            TargetCompany.name.ilike(f"%{company_data['name']}%")
        ).first()
        
        if existing:
            print(f"   ✅ {company_data['name']} already exists")
            return existing, False
        
        # Create new company entry
        company = TargetCompany(
            name=company_data["name"],
            display_name=company_data["display_name"],
            preferred_sites=["indeed", "linkedin", "glassdoor"],
            search_terms=company_data["search_terms"],
            location_filters=["USA", "United States"],
            is_active=True
        )
        
        db.add(company)
        db.commit()
        db.refresh(company)
        
        print(f"   ✅ Added {company_data['name']}")
        return company, True
        
    except Exception as e:
        print(f"   ❌ Error adding {company_data['name']}: {e}")
        db.rollback()
        return None, False
    finally:
        db.close()

def setup_pharma_companies():
    """Add all pharmaceutical companies to the database."""
    print("🏥 Setting up pharmaceutical companies...")
    
    added_count = 0
    existing_count = 0
    
    for company_data in PHARMA_COMPANIES:
        company, was_added = add_company(company_data)
        if was_added:
            added_count += 1
        elif company:
            existing_count += 1
    
    print(f"\n📊 Setup Summary:")
    print(f"   • New companies added: {added_count}")
    print(f"   • Already existed: {existing_count}")
    print(f"   • Total pharmaceutical companies: {added_count + existing_count}")
    
    return added_count > 0

def list_all_companies():
    """List all companies in the database."""
    db = SessionLocal()
    try:
        companies = db.query(TargetCompany).filter(TargetCompany.is_active == True).all()
        
        if not companies:
            print("📋 No active target companies found")
            return []
        
        print(f"\n📋 Active Target Companies ({len(companies)}):")
        for company in companies:
            search_terms_preview = ", ".join(company.search_terms[:3]) if company.search_terms else "None"
            if len(company.search_terms) > 3:
                search_terms_preview += "..."
            print(f"   • {company.name}")
            print(f"     Display: {company.display_name}")
            print(f"     Search Terms: {search_terms_preview}")
        
        return companies
        
    except Exception as e:
        print(f"❌ Error listing companies: {e}")
        return []
    finally:
        db.close()

if __name__ == "__main__":
    print("🏥 Pharmaceutical Companies Database Setup")
    print("=" * 50)
    
    # Setup companies
    changes_made = setup_pharma_companies()
    
    print("\n" + "=" * 50)
    
    # List all companies
    list_all_companies()
    
    print("\n" + "=" * 50)
    
    if changes_made:
        print("✅ Database updated successfully!")
        print("💡 Your scraping_defaults.json is already configured for Pfizer")
        print("🚀 Ready to run manual scraping!")
        print("\nNext steps:")
        print("1. Run: python test_manual_trigger.py")
        print("2. Check backend logs for scraping progress")
        print("3. Enable email notifications to receive CSV reports")
    else:
        print("✅ All companies already exist in database")
        print("🚀 Ready to run manual scraping!")