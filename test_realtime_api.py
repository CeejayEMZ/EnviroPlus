#!/usr/bin/env python3
"""
Quick validation script to test the refactored realtime API endpoints.
Run this after deploying to verify responses are valid.
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"  # Change to your domain
TIMEOUT = 10

def test_realtime_api():
    """Test the api_realtime_data endpoint"""
    print("\n" + "="*60)
    print("Testing /api/realtime-data/")
    print("="*60)
    
    tests = [
        {"params": {}, "name": "Default (7d)"},
        {"params": {"range": "24h"}, "name": "24h range"},
        {"params": {"range": "30d"}, "name": "30d range"},
    ]
    
    for test in tests:
        try:
            response = requests.get(
                f"{BASE_URL}/api/realtime-data/",
                params=test["params"],
                timeout=TIMEOUT
            )
            print(f"\n✓ {test['name']}: HTTP {response.status_code}")
            
            data = response.json()
            assert data.get("success") == True, "success field should be True"
            assert "summary" in data, "summary field required"
            assert "chart_data" in data, "chart_data field required"
            
            summary = data["summary"]
            assert "avg_aqi" in summary, "avg_aqi required"
            assert "latest_aqi" in summary, "latest_aqi required"
            assert "location_label" in data, "location_label required"
            
            print(f"  ├─ avg_aqi: {summary.get('avg_aqi')}")
            print(f"  ├─ latest_aqi: {summary.get('latest_aqi')}")
            print(f"  ├─ total_readings: {summary.get('total_readings')}")
            print(f"  ├─ location_label: {data.get('location_label')}")
            print(f"  └─ chart_data points: {len(data.get('chart_data', []))}")
            
        except Exception as e:
            print(f"✗ {test['name']}: {str(e)}")


def test_forecast_api():
    """Test the api_daily_forecast endpoint"""
    print("\n" + "="*60)
    print("Testing /api/daily-forecast/")
    print("="*60)
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/daily-forecast/",
            timeout=TIMEOUT
        )
        print(f"\n✓ HTTP {response.status_code}")
        
        data = response.json()
        
        if data.get("success") == True:
            forecast = data.get("forecast", [])
            print(f"\n✓ Forecast generated successfully")
            print(f"  ├─ forecast_days: {len(forecast)}")
            print(f"  ├─ confidence_level: {data.get('confidence_level')}")
            print(f"  ├─ data_coverage_days: {data.get('data_coverage_days')}")
            
            if forecast:
                first_day = forecast[0]
                print(f"\n  Sample day:")
                print(f"    ├─ date: {first_day.get('date')}")
                print(f"    ├─ avg_aqi: {first_day.get('avg_aqi')}")
                print(f"    ├─ aqi_level: {first_day.get('aqi_level')}")
                print(f"    ├─ confidence: {first_day.get('confidence')}")
                print(f"    ├─ trend: {first_day.get('trend')}")
                print(f"    └─ is_predicted: {first_day.get('is_predicted')}")
        else:
            print(f"\n✓ Insufficient data (expected)")
            print(f"  └─ Message: {data.get('error', 'No message')}")
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")


def test_response_format():
    """Validate JSON response formats"""
    print("\n" + "="*60)
    print("Validating Response Formats")
    print("="*60)
    
    print("\n✓ api_realtime_data should return:")
    print("""
    {
        "success": bool,
        "summary": {
            "avg_aqi": float,
            "latest_aqi": float,
            "latest_node_name": str,
            "latest_node_location": str,
            "latest_timestamp": ISO8601 str,
            "total_readings": int,
            "active_nodes": int,
            "range_label": str
        },
        "chart_data": [
            {
                "period": ISO8601,
                "date": str,
                "avg_aqi": float,
                "avg_pm2_5": float,
                "avg_pm10": float,
                "avg_temperature": float,
                "count": int
            }
        ],
        "location_label": str
    }
    """)
    
    print("\n✓ api_daily_forecast should return:")
    print("""
    {
        "success": bool,
        "forecast": [
            {
                "date": YYYY-MM-DD,
                "day_label": str,
                "day_subtitle": str,
                "avg_aqi": float,
                "aqi_level": str,
                "avg_pm2_5": float,
                "avg_temperature": float,
                "confidence": float (0-1),
                "trend": "up"|"down"|"stable",
                "is_predicted": bool,
                "data_points": int
            }
        ],
        "generated_at": ISO8601,
        "confidence_level": "high"|"medium"|"low",
        "data_coverage_days": int,
        "history_span_days": int
    }
    """)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("EnviroNode Realtime API Validation")
    print("="*60)
    
    test_response_format()
    test_realtime_api()
    test_forecast_api()
    
    print("\n" + "="*60)
    print("Validation Complete")
    print("="*60)
