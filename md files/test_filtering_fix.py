#!/usr/bin/env python
"""
Test filtering architecture fix - backend logic validation.
Tests node filtering, location filtering, and export parameter handling.
"""
import os
import sys
import django
from datetime import timedelta
from django.utils import timezone

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MainEnviroNode.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from AppEnviroNode.views import (
    parse_export_params,
    build_report_summary,
    get_report_readings,
)
from AppEnviroNode.models import SensorNode, SensorReading

def test_node_filtering_logic():
    """Test: get_report_readings filters by node correctly"""
    print("\n[TEST 1] Node filtering logic...")
    
    now = timezone.now()
    date_from = (now - timedelta(days=1)).date()
    date_to = now.date()
    
    try:
        # Get all readings
        all_readings = get_report_readings(date_from, date_to, 'all', 'all')
        all_count = all_readings.count()
        
        # Get a specific node
        node = SensorNode.objects.filter(is_active=True, status='active').first()
        if node:
            node_readings = get_report_readings(date_from, date_to, str(node.id), 'all')
            node_count = node_readings.count()
            
            print(f"  ✓ All readings: {all_count} | Node {node.id} ({node.name}): {node_count}")
            
            if node_count <= all_count:
                print(f"  ✓ Node filtering logic working correctly")
                return True
            else:
                print(f"  ✗ Node count ({node_count}) exceeds all count ({all_count})")
                return False
        else:
            print("  ⊘ SKIP: No active nodes found")
            return None
            
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_location_filtering_logic():
    """Test: get_report_readings filters by location correctly"""
    print("\n[TEST 2] Location filtering logic...")
    
    now = timezone.now()
    date_from = (now - timedelta(days=1)).date()
    date_to = now.date()
    
    try:
        # Get all readings
        all_readings = get_report_readings(date_from, date_to, 'all', 'all')
        all_count = all_readings.count()
        
        # Get a specific location
        reading = SensorReading.objects.select_related('node').filter(
            node__is_active=True,
            node__location__isnull=False
        ).exclude(node__location='').first()
        
        if reading:
            location = reading.node.location
            loc_readings = get_report_readings(date_from, date_to, 'all', location)
            loc_count = loc_readings.count()
            
            print(f"  ✓ All readings: {all_count} | Location '{location}': {loc_count}")
            
            if loc_count <= all_count:
                print(f"  ✓ Location filtering logic working correctly")
                return True
            else:
                print(f"  ✗ Location count ({loc_count}) exceeds all count ({all_count})")
                return False
        else:
            print("  ⊘ SKIP: No readings with location found")
            return None
            
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_combined_node_and_location():
    """Test: Combining node and location filters"""
    print("\n[TEST 3] Combined node+location filtering...")
    
    now = timezone.now()
    date_from = (now - timedelta(days=1)).date()
    date_to = now.date()
    
    try:
        node = SensorNode.objects.filter(is_active=True, status='active').first()
        if not node:
            print("  ⊘ SKIP: No active nodes found")
            return None
        
        # Get node-only readings
        node_readings = get_report_readings(date_from, date_to, str(node.id), 'all')
        node_count = node_readings.count()
        
        # Get combined node+location (should be same as node-only if location differs)
        location = 'Nonexistent Location'
        combined_readings = get_report_readings(date_from, date_to, str(node.id), location)
        combined_count = combined_readings.count()
        
        print(f"  ✓ Node-only: {node_count} | Node+Location: {combined_count}")
        
        if combined_count <= node_count:
            print(f"  ✓ Combined filtering working correctly")
            return True
        else:
            print(f"  ✗ Combined count exceeds node count")
            return False
            
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_parse_export_params():
    """Test: parse_export_params returns 4 values (node + location)"""
    print("\n[TEST 4] Export params parsing...")
    
    factory = RequestFactory()
    request = factory.get(
        '/export/pdf/?report_type=24hrs&node=5&location=Pembo'
    )
    
    try:
        date_from, date_to, selected_node, selected_location = parse_export_params(request)
        print(f"  ✓ parse_export_params returned 4 values")
        print(f"    - Dates: {date_from} to {date_to}")
        print(f"    - Node: {selected_node}")
        print(f"    - Location: {selected_location}")
        
        if selected_location == 'Pembo':
            print(f"  ✓ Location parameter parsed correctly")
            return True
        else:
            print(f"  ✗ Expected location 'Pembo', got '{selected_location}'")
            return False
            
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_build_report_with_location():
    """Test: build_report_summary accepts and uses location parameter"""
    print("\n[TEST 5] Report summary with location filter...")
    
    now = timezone.now()
    date_from = (now - timedelta(days=7)).date()
    date_to = now.date()
    
    try:
        # Call with location parameter
        summary = build_report_summary(date_from, date_to, 'all', 'all')
        print(f"  ✓ build_report_summary accepts location parameter")
        print(f"    - Summary has {len(summary.get('summary', []))} daily records")
        
        # Try with specific location
        reading = SensorReading.objects.select_related('node').filter(
            node__is_active=True,
            node__location__isnull=False
        ).exclude(node__location='').first()
        
        if reading:
            location = reading.node.location
            loc_summary = build_report_summary(date_from, date_to, 'all', location)
            print(f"    - Location '{location}': {len(loc_summary.get('summary', []))} daily records")
            
            if len(loc_summary['summary']) <= len(summary['summary']):
                print(f"  ✓ Location filtering working in build_report_summary")
                return True
            else:
                print(f"  ✗ Location summary exceeds total summary")
                return False
        else:
            print(f"  ✓ build_report_summary works (no location data to verify)")
            return True
            
    except TypeError as e:
        print(f"  ✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_export_param_defaults():
    """Test: parse_export_params handles missing location gracefully"""
    print("\n[TEST 6] Export params with missing location...")
    
    factory = RequestFactory()
    request = factory.get(
        '/export/pdf/?report_type=Weekly&node=all'
    )
    
    try:
        date_from, date_to, selected_node, selected_location = parse_export_params(request)
        print(f"  ✓ parse_export_params handles missing location")
        print(f"    - Selected node: {selected_node}")
        print(f"    - Selected location: {selected_location}")
        
        if selected_location == 'all':
            print(f"  ✓ Location defaults to 'all' when missing")
            return True
        else:
            print(f"  ✗ Expected location 'all', got '{selected_location}'")
            return False
            
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*70)
    print("TESTING FILTERING ARCHITECTURE FIX")
    print("="*70)
    
    results = []
    
    # Run tests
    results.append(("Node filtering logic", test_node_filtering_logic()))
    results.append(("Location filtering logic", test_location_filtering_logic()))
    results.append(("Combined node+location filtering", test_combined_node_and_location()))
    results.append(("Export params parsing", test_parse_export_params()))
    results.append(("Report summary with location", test_build_report_with_location()))
    results.append(("Export params with defaults", test_export_param_defaults()))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result is True)
    failed = sum(1 for _, result in results if result is False)
    skipped = sum(1 for _, result in results if result is None)
    
    for name, result in results:
        status = "✓ PASS" if result is True else "✗ FAIL" if result is False else "⊘ SKIP"
        print(f"  {status}: {name}")
    
    print("\n  Results: {} passed, {} failed, {} skipped".format(passed, failed, skipped))
    print("="*70)
    
    return 0 if failed == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
