#!/bin/bash
# Quick script to scrape your target healthcare/pharma companies
# Usage: ./scrape_healthcare.sh

echo "🏥 Triggering scraping for healthcare/pharma companies..."
echo "🎯 Target companies: Johnson & Johnson, Medtronic, Pfizer"

curl -X POST "http://localhost:8000/admin/scheduler/trigger?company_names=Johnson%20%26%20Johnson&company_names=Medtronic&company_names=Pfizer" \
  -H "Content-Type: application/json" | python -m json.tool

echo ""
echo "📝 Check server logs to monitor progress:"
echo "   Look for: '🎯 Starting targeted scraping for 3 companies'"
echo "   Progress: Individual company processing will be shown"
echo "   Complete: '✅ Targeted scraping completed successfully!'"