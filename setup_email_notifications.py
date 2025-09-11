#!/usr/bin/env python3
"""
Setup email notifications for JobSpy automation
Usage: python setup_email_notifications.py
"""
import os
import getpass

def show_current_email_config():
    """Show current email configuration."""
    print("📧 Current Email Configuration:")
    
    config = {
        "EMAIL_NOTIFICATIONS_ENABLED": os.getenv("EMAIL_NOTIFICATIONS_ENABLED", "false"),
        "SMTP_SERVER": os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
        "EMAIL_USER": os.getenv("EMAIL_USER", ""),
        "EMAIL_PASSWORD": os.getenv("EMAIL_PASSWORD", ""),
        "NOTIFICATION_EMAIL": os.getenv("NOTIFICATION_EMAIL", "")
    }
    
    for key, value in config.items():
        if "PASSWORD" in key and value:
            display_value = "*" * len(value)
        else:
            display_value = value if value else "(not set)"
        
        status = "✅" if value and value.lower() != "false" else "❌"
        print(f"   {status} {key}: {display_value}")
    
    return config

def create_env_file():
    """Create or update .env file with email settings."""
    print("\n📝 Email Configuration Setup")
    print("=" * 40)
    
    # Get user input
    print("\n🔧 Gmail/Google Workspace Setup (Recommended):")
    print("1. Go to: https://myaccount.google.com/apppasswords")
    print("2. Generate an 'App Password' for 'Mail'")
    print("3. Use that app password below (not your regular password)")
    
    print("\n📧 Enter your email settings:")
    
    email_user = input("Gmail address (sender): ").strip()
    if not email_user:
        print("❌ Email address is required")
        return False
    
    email_password = getpass.getpass("Gmail App Password (hidden): ").strip()
    if not email_password:
        print("❌ App password is required")
        return False
    
    notification_email = input(f"Notification email (recipient) [{email_user}]: ").strip()
    if not notification_email:
        notification_email = email_user
    
    smtp_server = input("SMTP Server [smtp.gmail.com]: ").strip()
    if not smtp_server:
        smtp_server = "smtp.gmail.com"
    
    smtp_port = input("SMTP Port [587]: ").strip()
    if not smtp_port:
        smtp_port = "587"
    
    # Create .env content
    env_content = f"""# JobSpy Email Notifications
EMAIL_NOTIFICATIONS_ENABLED=true
SMTP_SERVER={smtp_server}
SMTP_PORT={smtp_port}
EMAIL_USER={email_user}
EMAIL_PASSWORD={email_password}
NOTIFICATION_EMAIL={notification_email}

# Other settings (optional)
AUTO_SCRAPING_ENABLED=true
AUTO_SCRAPING_TIME=20:55
AUTO_SCRAPING_MAX_RESULTS=1000
"""
    
    # Write to .env file
    try:
        with open('.env', 'w') as f:
            f.write(env_content)
        
        print(f"\n✅ Created .env file with email configuration")
        print(f"📧 Sender: {email_user}")
        print(f"📨 Recipient: {notification_email}")
        print(f"🏢 SMTP: {smtp_server}:{smtp_port}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")
        return False

def test_email_settings():
    """Test email settings by triggering manual scraping."""
    print("\n🧪 Test Email Notifications:")
    
    restart_msg = """
⚠️  IMPORTANT: You must restart your backend server for .env changes to take effect!

1. Stop the current backend (Ctrl+C in the terminal)
2. Restart with: python backend/main.py
3. Then run: python test_manual_trigger.py
"""
    
    print(restart_msg)
    
    test_now = input("Have you restarted the backend? Test email now? (y/n): ").lower()
    if test_now == 'y':
        try:
            import requests
            response = requests.post("http://localhost:8000/admin/scheduler/trigger")
            if response.status_code == 200:
                print("✅ Manual scraping triggered!")
                print("📧 Check your email for the CSV report")
                print("📋 Also check backend logs for email sending status")
                return True
            else:
                print(f"❌ Trigger failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Could not trigger test: {e}")
            print("💡 Make sure backend is running and restarted")
            return False
    else:
        print("💡 Restart your backend and then run: python test_manual_trigger.py")
        return False

def show_troubleshooting():
    """Show email troubleshooting tips."""
    print(f"\n🔧 Email Troubleshooting:")
    print(f"")
    print(f"Gmail Setup:")
    print(f"   1. Enable 2-Factor Authentication")
    print(f"   2. Generate App Password: https://myaccount.google.com/apppasswords")
    print(f"   3. Use the 16-character app password (not your regular password)")
    print(f"")
    print(f"Common Issues:")
    print(f"   • 'Authentication failed' = Wrong app password")
    print(f"   • 'Connection refused' = Wrong SMTP server/port")
    print(f"   • 'Email not configured' = Need to restart backend after .env changes")
    print(f"")
    print(f"Other Email Providers:")
    print(f"   • Outlook: smtp-mail.outlook.com:587")
    print(f"   • Yahoo: smtp.mail.yahoo.com:587")
    print(f"   • Custom: Check your provider's SMTP settings")

if __name__ == "__main__":
    print("📧 JobSpy Email Notification Setup")
    print("=" * 50)
    
    # Show current config
    current_config = show_current_email_config()
    
    # Check if already configured
    if (current_config.get("EMAIL_NOTIFICATIONS_ENABLED", "").lower() == "true" and 
        current_config.get("EMAIL_USER") and 
        current_config.get("EMAIL_PASSWORD")):
        
        print("\n✅ Email notifications appear to be configured!")
        print("💡 If you're not receiving emails, the backend may need to be restarted")
        
        action = input("\nWhat would you like to do?\n1. Test current settings\n2. Reconfigure email\n3. Show troubleshooting\nChoice (1-3): ")
        
        if action == "1":
            test_email_settings()
        elif action == "2":
            create_env_file()
            test_email_settings()
        elif action == "3":
            show_troubleshooting()
    else:
        print("\n❌ Email notifications are not fully configured")
        setup = input("Would you like to set up email notifications now? (y/n): ")
        if setup.lower() == 'y':
            if create_env_file():
                test_email_settings()
            show_troubleshooting()
        else:
            print("💡 Run this script again when you're ready to configure email")
            show_troubleshooting()