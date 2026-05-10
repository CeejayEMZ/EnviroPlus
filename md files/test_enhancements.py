#!/usr/bin/env python
"""
Comprehensive test suite for EnviroNode backend enhancements.
Tests: Anomaly detection, validation, backward compatibility, and alert generation.

USAGE:
    python manage.py shell < test_enhancements.py
"""

import json
import sys
from datetime import timedelta
from django.utils import timezone
from django.test import Client
from AppEnviroNode.models import SensorNode, SensorReading, Alert, SystemLog
from AppEnviroNode.utils import (
    detect_pm_anomaly,
    validate_sensor_data,
    check_latency_issue,
    calculate_aqi
)

# =============================================================================
# TEST SETUP
# =============================================================================

print("\n" + "=" * 80)
print("ENVIRONODE BACKEND ENHANCEMENTS - COMPREHENSIVE TEST SUITE")
print("=" * 80 + "\n")

client = Client()
test_mac = "AA:BB:CC:DD:EE:FF"
test_results = {
    'passed': 0,
    'failed': 0,
    'tests': []
}

def test(name, condition, details=""):
    """Test helper function."""
    global test_results
    status = "✓ PASS" if condition else "✗ FAIL"
    test_results['tests'].append({
        'name': name,
        'passed': condition,
        'details': details
    })
    if condition:
        test_results['passed'] += 1
    else:
        test_results['failed'] += 1
    print(f"{status:8} | {name}")
    if details:
        print(f"         | {details}")

# =============================================================================
# TEST 1: UTILITY FUNCTIONS
# =============================================================================

print("\n--- TEST GROUP 1: Utility Functions ---\n")

# Test 1.1: Anomaly Detection - Spike
pm_spike, reason = detect_pm_anomaly(100, 30)
test("Anomaly Detection: PM2.5 Spike (100→30)", pm_spike and "spike" in reason.lower(), 
     f"Reason: {reason}")

# Test 1.2: Anomaly Detection - Drop
pm_drop, reason = detect_pm_anomaly(5, 70)
test("Anomaly Detection: PM2.5 Drop (70→5)", pm_drop and "drop" in reason.lower(),
     f"Reason: {reason}")

# Test 1.3: Anomaly Detection - Unrealistic Zero
pm_zero, reason = detect_pm_anomaly(2, 65)
test("Anomaly Detection: Unrealistic Zero (65→2)", pm_zero and "near-zero" in reason.lower(),
     f"Reason: {reason}")

# Test 1.4: No Anomaly Detection
no_anomaly, reason = detect_pm_anomaly(35, 30)
test("No Anomaly: Normal Variation (30→35)", not no_anomaly,
     f"Reason: {reason}")

# Test 1.5: Sensor Data Validation - Critical System
critical_data = {
    'system_status': 'critical',
    'pm2_5': 50,
    'temperature': 25
}
validation = validate_sensor_data(critical_data)
test("Validation: System Critical Status", not validation['is_valid'],
     f"Issues: {validation['issues']}")

# Test 1.6: Sensor Data Validation - PMS Error
pms_error_data = {
    'system_status': 'normal',
    'pms_status': 'error',
    'bme_status': 'ok',
    'pm2_5': 50,
    'temperature': 25
}
validation = validate_sensor_data(pms_error_data)
test("Validation: PMS Sensor Error", not validation['is_valid'],
     f"Issues: {validation['issues']}")

# Test 1.7: Sensor Data Validation - Out of Range
invalid_temp_data = {
    'system_status': 'normal',
    'temperature': 75,  # Out of realistic range
}
validation = validate_sensor_data(invalid_temp_data)
test("Validation: Temperature Out of Range", not validation['is_valid'],
     f"Issues: {validation['issues']}")

# Test 1.8: Sensor Data Validation - Valid
valid_data = {
    'system_status': 'normal',
    'pms_status': 'ok',
    'bme_status': 'ok',
    'pm2_5': 35,
    'pm10': 60,
    'temperature': 28,
    'humidity': 65
}
validation = validate_sensor_data(valid_data)
test("Validation: Valid Sensor Data", validation['is_valid'],
     f"Trusted fields: {list(validation['trusted_fields'].keys())}")

# Test 1.9: Latency Check - High
high_latency_issue, severity, msg = check_latency_issue(5500)
test("Latency Check: 5500ms → Critical", high_latency_issue and severity == 'critical',
     f"Message: {msg}")

# Test 1.10: Latency Check - Warning
warning_latency_issue, severity, msg = check_latency_issue(3000)
test("Latency Check: 3000ms → Warning", warning_latency_issue and severity == 'warning',
     f"Message: {msg}")

# =============================================================================
# TEST 2: BACKWARD COMPATIBILITY
# =============================================================================

print("\n--- TEST GROUP 2: Backward Compatibility ---\n")

# Clean up test data
SensorReading.objects.filter(node__mac_address=test_mac).delete()
SensorNode.objects.filter(mac_address=test_mac).delete()

# Test 2.1: Old API Format (No new fields)
old_payload = {
    'mac_address': test_mac,
    'pm1_0': 10.5,
    'pm2_5': 25.3,
    'pm10': 45.2,
    'temperature': 28.5,
    'humidity': 65.0,
    'pressure': 1013.25,
    'gas_resistance': 120.5
}

response = client.post(
    '/api/sensor-data/',
    data=json.dumps(old_payload),
    content_type='application/json'
)
old_compatible = response.status_code == 201 and response.json()['success']
test("Backward Compatibility: Old API Format Works", old_compatible,
     f"Response: {response.json()}")

# Verify reading was created
reading_created = SensorReading.objects.filter(node__mac_address=test_mac).exists()
test("Backward Compatibility: Reading Created", reading_created,
     f"Reading count: {SensorReading.objects.filter(node__mac_address=test_mac).count()}")

# Verify new fields have defaults
last_reading = SensorReading.objects.filter(node__mac_address=test_mac).latest('id')
test("Backward Compatibility: New Fields Have Defaults",
     last_reading.system_status == 'normal' and last_reading.is_anomaly == False,
     f"system_status={last_reading.system_status}, is_anomaly={last_reading.is_anomaly}")

# =============================================================================
# TEST 3: NEW FIELDS ACCEPTANCE
# =============================================================================

print("\n--- TEST GROUP 3: New Fields Acceptance ---\n")

# Clean up
SensorReading.objects.filter(node__mac_address=test_mac).delete()

# Test 3.1: API Accepts system_status
new_payload = {
    'mac_address': test_mac,
    'pm2_5': 25.3,
    'temperature': 28.5,
    'system_status': 'degraded',
    'pms_status': 'ok',
    'bme_status': 'ok',
    'latency_ms': 150
}

response = client.post(
    '/api/sensor-data/',
    data=json.dumps(new_payload),
    content_type='application/json'
)
new_fields_accepted = response.status_code == 201
test("New Fields: API Accepts New Fields", new_fields_accepted,
     f"Status: {response.status_code}")

# Verify fields were stored
last_reading = SensorReading.objects.filter(node__mac_address=test_mac).latest('id')
test("New Fields: system_status Stored Correctly",
     last_reading.system_status == 'degraded',
     f"Stored: {last_reading.system_status}")

test("New Fields: latency_ms Stored Correctly",
     last_reading.latency_ms == 150,
     f"Stored: {last_reading.latency_ms}")

# =============================================================================
# TEST 4: ANOMALY DETECTION IN API
# =============================================================================

print("\n--- TEST GROUP 4: Anomaly Detection in API ---\n")

# Clean up
SensorReading.objects.filter(node__mac_address=test_mac).delete()
SensorNode.objects.filter(mac_address=test_mac).delete()

# Create baseline reading
baseline = {
    'mac_address': test_mac,
    'pm2_5': 30.0,
    'temperature': 28.5
}
response = client.post('/api/sensor-data/', data=json.dumps(baseline), content_type='application/json')

# Test 4.1: Detect spike
spike_payload = {
    'mac_address': test_mac,
    'pm2_5': 95.0,  # Spike from 30 to 95
    'temperature': 28.5
}
response = client.post('/api/sensor-data/', data=json.dumps(spike_payload), content_type='application/json')
anomaly_detected_spike = response.json().get('is_anomaly', False)
test("Anomaly Detection: API Detects Spike", anomaly_detected_spike,
     f"Response anomaly flag: {anomaly_detected_spike}")

# Verify alert was created
alerts_for_spike = Alert.objects.filter(
    node__mac_address=test_mac,
    title='Anomalous Sensor Reading'
)
test("Anomaly Detection: Alert Created for Spike", alerts_for_spike.exists(),
     f"Alert count: {alerts_for_spike.count()}")

# Test 4.2: Verify SystemLog entry
logs_for_anomaly = SystemLog.objects.filter(
    node__mac_address=test_mac,
    event_type='anomaly_detected'
)
test("Anomaly Detection: SystemLog Entry Created", logs_for_anomaly.exists(),
     f"Log count: {logs_for_anomaly.count()}")

# =============================================================================
# TEST 5: SENSOR ERROR ALERTS
# =============================================================================

print("\n--- TEST GROUP 5: Sensor Error Alerts ---\n")

# Clean up
SensorReading.objects.filter(node__mac_address=test_mac).delete()
SensorNode.objects.filter(mac_address=test_mac).delete()
Alert.objects.filter(node__mac_address=test_mac).delete()

# Test 5.1: PMS Error Alert
pms_error_payload = {
    'mac_address': test_mac,
    'pm2_5': 30,
    'pms_status': 'error',
    'bme_status': 'ok',
    'system_status': 'normal'
}
response = client.post('/api/sensor-data/', data=json.dumps(pms_error_payload), content_type='application/json')
pms_error_alert = Alert.objects.filter(
    node__mac_address=test_mac,
    title='Sensor Failure: PMS5003'
).exists()
test("Sensor Error: PMS5003 Error Alert Created", pms_error_alert,
     f"Alert exists: {pms_error_alert}")

# Clean up for BME test
Alert.objects.filter(node__mac_address=test_mac).delete()

# Test 5.2: BME Error Alert
bme_error_payload = {
    'mac_address': test_mac,
    'pm2_5': 30,
    'pms_status': 'ok',
    'bme_status': 'error',
    'system_status': 'normal'
}
response = client.post('/api/sensor-data/', data=json.dumps(bme_error_payload), content_type='application/json')
bme_error_alert = Alert.objects.filter(
    node__mac_address=test_mac,
    title='Sensor Failure: BME680'
).exists()
test("Sensor Error: BME680 Error Alert Created", bme_error_alert,
     f"Alert exists: {bme_error_alert}")

# =============================================================================
# TEST 6: CRITICAL SYSTEM STATUS
# =============================================================================

print("\n--- TEST GROUP 6: Critical System Status ---\n")

# Clean up
SensorReading.objects.filter(node__mac_address=test_mac).delete()
SensorNode.objects.filter(mac_address=test_mac).delete()
Alert.objects.filter(node__mac_address=test_mac).delete()

# Test 6.1: Critical system status handling
critical_payload = {
    'mac_address': test_mac,
    'pm2_5': 25,
    'system_status': 'critical'
}
response = client.post('/api/sensor-data/', data=json.dumps(critical_payload), content_type='application/json')

# Check node status
node = SensorNode.objects.get(mac_address=test_mac)
test("Critical Status: Node Set to Inactive", node.status == 'inactive',
     f"Node status: {node.status}")

# Check alert creation
critical_alert = Alert.objects.filter(
    node__mac_address=test_mac,
    title='Critical System Failure'
).exists()
test("Critical Status: Critical Alert Created", critical_alert,
     f"Alert exists: {critical_alert}")

# Check SystemLog entry
critical_log = SystemLog.objects.filter(
    node__mac_address=test_mac,
    event_type='system',
    severity='hazardous'
).exists()
test("Critical Status: SystemLog Entry Created", critical_log,
     f"Log exists: {critical_log}")

# =============================================================================
# TEST 7: LATENCY LOGGING
# =============================================================================

print("\n--- TEST GROUP 7: Latency Logging ---\n")

# Clean up
SensorReading.objects.filter(node__mac_address=test_mac).delete()
SensorNode.objects.filter(mac_address=test_mac).delete()

# Test 7.1: High latency creates log entry
high_latency_payload = {
    'mac_address': test_mac,
    'pm2_5': 25,
    'latency_ms': 3500  # High latency
}
response = client.post('/api/sensor-data/', data=json.dumps(high_latency_payload), content_type='application/json')

latency_log = SystemLog.objects.filter(
    node__mac_address=test_mac,
    event_type='high_latency'
).exists()
test("Latency Logging: High Latency Log Created", latency_log,
     f"Log exists: {latency_log}")

# =============================================================================
# TEST SUMMARY
# =============================================================================

print("\n" + "=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print(f"\nTotal Tests: {test_results['passed'] + test_results['failed']}")
print(f"Passed: {test_results['passed']}")
print(f"Failed: {test_results['failed']}")

if test_results['failed'] == 0:
    print("\n🎉 ALL TESTS PASSED!")
else:
    print(f"\n⚠️  {test_results['failed']} test(s) failed")
    print("\nFailed tests:")
    for test in test_results['tests']:
        if not test['passed']:
            print(f"  - {test['name']}")
            if test['details']:
                print(f"    Details: {test['details']}")

print("\n" + "=" * 80)
print("END OF TEST SUITE")
print("=" * 80 + "\n")

# Exit with appropriate code
sys.exit(0 if test_results['failed'] == 0 else 1)
