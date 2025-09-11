#!/usr/bin/env python3
"""
Script to add Pfizer to the target companies database
Usage: python add_pfizer_company.py
"""
import sys
import os

# Add backend to path so we can import database modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from database import SessionLocal, TargetCompany

def add_pfizer_company():
    """Add Pfizer to the target companies table."""
    db = SessionLocal()
    try:
        # Check if Pfizer already exists
        existing = db.query(TargetCompany).filter(
            TargetCompany.name.ilike("%pfizer%")
        ).first()
        
        if existing:
            print(f"✅ Pfizer already exists in database: {existing.name}")
            print(f"   Status: {'Active' if existing.is_active else 'Inactive'}")
            return existing
        
        # Create new Pfizer entry
        pfizer = TargetCompany(
            name="Pfizer",
            display_name="Pfizer Inc.",
            preferred_sites=["indeed", "linkedin", "glassdoor"],
            search_terms=["all", "analyst", "manager", "scientist", "clinical", "research"],
            location_filters=["USA", "United States"],
            is_active=True
        )
        
        db.add(pfizer)
        db.commit()
        db.refresh(pfizer)
        
        print("✅ Successfully added Pfizer to target companies!")
        print(f"   ID: {pfizer.id}")
        print(f"   Name: {pfizer.name}")
        print(f"   Display Name: {pfizer.display_name}")
        print(f"   Active: {pfizer.is_active}")
        
        return pfizer
        
    except Exception as e:
        print(f"❌ Error adding Pfizer: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def list_all_target_companies():
    """List all companies in the target companies table."""
    db = SessionLocal()
    try:
        companies = db.query(TargetCompany).all()
        
        if not companies:
            print("📋 No target companies found in database")
            return []
        
        print(f"\n📋 Found {len(companies)} target companies:")
        for company in companies:
            status = "Active" if company.is_active else "Inactive"
            print(f"   • {company.name} ({company.display_name}) - {status}")
        
        return companies
        
    except Exception as e:
        print(f"❌ Error listing companies: {e}")
        return []
    finally:
        db.close()

if __name__ == "__main__":
    print("🏢 Target Company Database Setup")
    print("=" * 40)
    
    # List existing companies first
    list_all_target_companies()
    
    print("\n" + "=" * 40)
    
    # Add Pfizer
    add_pfizer_company()
    
    print("\n" + "=" * 40)
    
    # List companies again to confirm
    print("📋 Updated company list:")
    list_all_target_companies()
    
    print("\n✅ Ready to run manual scraping with Pfizer!")
    print("💡 Tip: Now run 'python test_manual_trigger.py' to test scraping")