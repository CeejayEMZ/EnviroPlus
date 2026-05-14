#!/usr/bin/env python
"""
Test script to verify API key authentication for sensor data endpoint.
Tests: Valid key, Invalid key, Missing key scenarios.
"""

import os
import sys
import django
import json
import requests
from django.test import Client

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MainEnviroNode.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from AppEnviroNode.models import SensorNode, SensorNodeAPIKey, SensorReading

def test_api_authentication():
    print("\n" + "="*70)
    print("🔐 API KEY AUTHENTICATION TESTS")
    print("="*70)
    
    client = Client()
    api_endpoint = '/api/sensor-data/'
    
    # Create test node if not exists
    node, created = SensorNode.objects.get_or_create(
        mac_address='AA:BB:CC:DD:EE:FF',
        defaults={'name': 'TEST_NODE_AUTH', 'organization': 'Test'}
    )
    print(f"\n✓ Test Node: {node.name} ({node.mac_address})")
    
    # Create/Get API key
    api_key_obj, created = SensorNodeAPIKey.objects.get_or_create(node=node)
    api_key = api_key_obj.api_key
    if created:
        print(f"✓ API Key Created: {api_key[:16]}...{api_key[-8:]}")
    else:
        print(f"✓ API Key Exists: {api_key[:16]}...{api_key[-8:]}")
    
    # Test payload
    test_payload = {
        'mac_address': 'AA:BB:CC:DD:EE:FF',
        'pm1_0': 5.0,
        'pm2_5': 12.5,
        'pm10': 25.0,
        'temperature': 28.5,
        'humidity': 65.0,
        'pressure': 1013.25,
        'gas_resistance': 120.5,
        'system_status': 'normal',
        'pms_status': 'ok',
        'bme_status': 'ok',
        'latency_ms': 45
    }
    
    # TEST 1: Missing Authorization header
    print("\n" + "-"*70)
    print("TEST 1: Missing Authorization Header")
    print("-"*70)
    response = client.post(
        api_endpoint,
        data=json.dumps(test_payload),
        content_type='application/json'
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 401, "Should reject missing auth header"
    print("✅ PASS: Correctly rejected missing Authorization header")
    
    # TEST 2: Invalid API key
    print("\n" + "-"*70)
    print("TEST 2: Invalid API Key")
    print("-"*70)
    response = client.post(
        api_endpoint,
        data=json.dumps(test_payload),
        content_type='application/json',
        HTTP_AUTHORIZATION='Bearer invalid_key_12345'
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 401, "Should reject invalid API key"
    print("✅ PASS: Correctly rejected invalid API key")
    
    # TEST 3: Valid API key
    print("\n" + "-"*70)
    print("TEST 3: Valid API Key with Correct MAC")
    print("-"*70)
    response = client.post(
        api_endpoint,
        data=json.dumps(test_payload),
        content_type='application/json',
        HTTP_AUTHORIZATION=f'Bearer {api_key}'
    )
    print(f"Status Code: {response.status_code}")
    resp_data = response.json()
    print(f"Response: {resp_data}")
    assert response.status_code == 201, f"Should accept valid API key. Got {response.status_code}"
    assert resp_data.get('success') == True, "Should indicate success"
    print("✅ PASS: Correctly accepted valid API key")
    
    # TEST 4: MAC mismatch
    print("\n" + "-"*70)
    print("TEST 4: Valid API Key with WRONG MAC Address")
    print("-"*70)
    wrong_payload = test_payload.copy()
    wrong_payload['mac_address'] = 'FF:EE:DD:CC:BB:AA'  # Different MAC
    response = client.post(
        api_endpoint,
        data=json.dumps(wrong_payload),
        content_type='application/json',
        HTTP_AUTHORIZATION=f'Bearer {api_key}'
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 403, "Should reject MAC mismatch"
    print("✅ PASS: Correctly rejected MAC address mismatch")
    
    # TEST 5: Check API key was updated with last_used
    print("\n" + "-"*70)
    print("TEST 5: API Key Usage Tracking")
    print("-"*70)
    api_key_obj.refresh_from_db()
    print(f"Last Used: {api_key_obj.last_used}")
    assert api_key_obj.last_used is not None, "last_used should be set after use"
    print("✅ PASS: API key usage was tracked")
    
    # Summary
    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED!")
    print("="*70)
    print("\nSUMMARY:")
    print("- Missing Authorization header → 401 ✓")
    print("- Invalid API key → 401 ✓")
    print("- Valid API key + correct MAC → 201 ✓")
    print("- Valid API key + wrong MAC → 403 ✓")
    print("- API key usage tracking → ✓")
    print("\n🔐 Security Feature Implemented: API Key Authentication")
    print("="*70 + "\n")

if __name__ == '__main__':
    try:
        test_api_authentication()
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
