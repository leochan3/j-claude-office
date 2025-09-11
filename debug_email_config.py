#!/usr/bin/env python3
"""
Debug email configuration issues
Usage: python debug_email_config.py
"""
import os
import sys
from pathlib import Path

def check_env_file():
    """Check if .env file exists and what's in it."""
    print("🔍 Checking .env file:")
    
    env_file = Path(".env")
    if not env_file.exists():
        print("   ❌ .env file not found in current directory")
        print(f"   📁 Looking in: {os.getcwd()}")
        return False
    
    try:
        with open(env_file, 'r') as f:
            content = f.read()
        
        print(f"   ✅ .env file found ({len(content)} chars)")
        
        # Check for key email variables
        email_vars = [
            "EMAIL_NOTIFICATIONS_ENABLED",
            "EMAIL_USER", 
            "EMAIL_PASSWORD",
            "NOTIFICATION_EMAIL"
        ]
        
        print("   📧 Email variables in .env:")
        found_vars = 0
        for var in email_vars:
            if var in content:
                # Get the value (simple parsing)
                for line in content.split('\n'):
                    if line.startswith(f"{var}="):
                        value = line.split('=', 1)[1]
                        if "PASSWORD" in var and value:
                            display_value = "*" * len(value)
                        else:
                            display_value = value
                        print(f"      ✅ {var}={display_value}")
                        found_vars += 1
                        break
            else:
                print(f"      ❌ {var} not found")
        
        if found_vars == len(email_vars):
            print("   🎉 All email variables found in .env!")
            return True
        else:
            print(f"   ⚠️  Only {found_vars}/{len(email_vars)} email variables found")
            return False
            
    except Exception as e:
        print(f"   ❌ Error reading .env file: {e}")
        return False

def check_environment_variables():
    """Check if email variables are loaded in current environment."""
    print("\n🌍 Environment Variables (what Python sees):")
    
    email_vars = {
        "EMAIL_NOTIFICATIONS_ENABLED": os.getenv("EMAIL_NOTIFICATIONS_ENABLED"),
        "SMTP_SERVER": os.getenv("SMTP_SERVER"),
        "SMTP_PORT": os.getenv("SMTP_PORT"),
        "EMAIL_USER": os.getenv("EMAIL_USER"),
        "EMAIL_PASSWORD": os.getenv("EMAIL_PASSWORD"),
        "NOTIFICATION_EMAIL": os.getenv("NOTIFICATION_EMAIL")
    }
    
    configured_count = 0
    for key, value in email_vars.items():
        if value:
            configured_count += 1
            if "PASSWORD" in key:
                display_value = "*" * len(value)
            else:
                display_value = value
            print(f"   ✅ {key}: {display_value}")
        else:
            print(f"   ❌ {key}: (not set)")
    
    if configured_count >= 4:  # Need at least the main 4 variables
        print(f"   🎉 Email appears to be configured ({configured_count}/6 variables)")
        return True
    else:
        print(f"   ❌ Email not fully configured ({configured_count}/6 variables)")
        return False

def check_scheduler_initialization():
    """Check how scheduler would initialize with current environment."""
    print("\n⚙️ Scheduler Email Configuration (simulated):")
    
    # Simulate what scheduler.py does
    email_enabled = os.getenv("EMAIL_NOTIFICATIONS_ENABLED", "false").lower() == "true"
    email_user = os.getenv("EMAIL_USER", "")
    email_password = os.getenv("EMAIL_PASSWORD", "")
    notification_email = os.getenv("NOTIFICATION_EMAIL", "")
    
    print(f"   📧 EMAIL_NOTIFICATIONS_ENABLED: {email_enabled}")
    print(f"   👤 EMAIL_USER: {email_user if email_user else '(empty)'}")
    print(f"   🔐 EMAIL_PASSWORD: {'*' * len(email_password) if email_password else '(empty)'}")
    print(f"   📨 NOTIFICATION_EMAIL: {notification_email if notification_email else '(empty)'}")
    
    # This is the exact logic from scheduler.py
    will_send_email = email_enabled and notification_email and email_user and email_password
    
    print(f"\n   🎯 Will send emails: {'✅ YES' if will_send_email else '❌ NO'}")
    
    if not will_send_email:
        reasons = []
        if not email_enabled:
            reasons.append("EMAIL_NOTIFICATIONS_ENABLED is not 'true'")
        if not email_user:
            reasons.append("EMAIL_USER is empty")
        if not email_password:
            reasons.append("EMAIL_PASSWORD is empty")
        if not notification_email:
            reasons.append("NOTIFICATION_EMAIL is empty")
        
        print("   ❌ Reasons emails won't send:")
        for reason in reasons:
            print(f"      • {reason}")
    
    return will_send_email

def provide_fix_instructions():
    """Provide step-by-step fix instructions."""
    print(f"\n🔧 How to Fix Email Issues:")
    print(f"")
    print(f"1️⃣ Create/Update .env file:")
    print(f"   python setup_email_notifications.py")
    print(f"")
    print(f"2️⃣ RESTART your backend server:")
    print(f"   • Press Ctrl+C in backend terminal")
    print(f"   • Run: python backend/main.py")
    print(f"")
    print(f"3️⃣ Test email:")
    print(f"   python test_manual_trigger.py")
    print(f"")
    print(f"4️⃣ Check for this log line:")
    print(f"   ✅ Should see: 'Email notifications: True'")
    print(f"   ❌ Instead of: 'Email notifications: False'")
    print(f"")
    print(f"💡 The key issue: Backend server caches environment variables!")
    print(f"   You MUST restart it after creating/updating .env file")

if __name__ == "__main__":
    print("🐛 JobSpy Email Configuration Debug")
    print("=" * 50)
    
    # Step 1: Check .env file
    env_file_ok = check_env_file()
    
    # Step 2: Check environment variables
    env_vars_ok = check_environment_variables()
    
    # Step 3: Check scheduler logic
    scheduler_ok = check_scheduler_initialization()
    
    print("\n" + "=" * 50)
    print("📊 Diagnosis Summary:")
    
    if env_file_ok and env_vars_ok and scheduler_ok:
        print("   ✅ Configuration looks correct!")
        print("   💡 If emails still don't work, check:")
        print("      • Gmail app password is correct")
        print("      • Backend server was restarted after .env changes")
        print("      • Check spam folder")
    elif env_file_ok and not env_vars_ok:
        print("   ⚠️  .env file exists but variables not loaded")
        print("   🔄 RESTART your backend server to load .env file")
    elif not env_file_ok:
        print("   ❌ .env file missing or incomplete")
        print("   🔧 Run: python setup_email_notifications.py")
    else:
        print("   ❌ Email configuration has issues")
        print("   🔧 Follow the fix instructions below")
    
    print("\n" + "=" * 50)
    provide_fix_instructions()