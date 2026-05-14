"""
Test script to verify node profile logic works correctly
"""

import sys
import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'EnviroNode.settings')

# Add the project to path
sys.path.insert(0, '/c/Users/rodri/OneDrive/Desktop/SmAIR/EnviroNode')

django.setup()

# Now import the Command class
from AppEnviroNode.management.commands.generate_environode_002_data import Command

def test_node_profiles():
    """Test node profiles for different node IDs"""
    
    # Instantiate the command
    cmd = Command()
    
    # Test node IDs
    test_nodes = [3, 4, 13, 18, 14, 19, 1, 2, 5, 6]
    
    print("=" * 80)
    print("NODE PROFILE TEST RESULTS")
    print("=" * 80)
    
    for node_id in test_nodes:
        profile = cmd._get_node_profile(node_id)
        hash_val = hash(str(node_id)) % 10
        
        print(f"\n{'=' * 80}")
        print(f"Node ID: {node_id}")
        print(f"Hash(node_id) % 10: {hash_val}")
        print(f"{'=' * 80}")
        print(f"  Name:                  {profile['name']}")
        print(f"  Behavior:              {profile['behavior']}")
        print(f"  Description:           {profile['description']}")
        print(f"  PM2.5 Volatility:      {profile['pm25_volatility']}")
        print(f"  Spike Frequency:       {profile['spike_frequency']}")
        print(f"  Spike Decay:           {profile['spike_decay']}")
        print(f"  PM10 Ceiling:          {profile['pm10_ceiling']}")
        print(f"  Temperature Boost:     {profile['temperature_peak_boost']}")
        print(f"  Humidity Volatility:   {profile['humidity_volatility']}")
        print(f"  Event Types:           {', '.join(profile['event_types'])}")
    
    # Summary section
    print(f"\n{'=' * 80}")
    print("SUMMARY: NODES 3 AND 4 PROFILES")
    print(f"{'=' * 80}")
    
    profile_3 = cmd._get_node_profile(3)
    profile_4 = cmd._get_node_profile(4)
    
    print(f"\nNODE 3:")
    print(f"  ✓ Behavior:            {profile_3['behavior']}")
    print(f"  ✓ PM10 Ceiling:        {profile_3['pm10_ceiling']}")
    print(f"  ✓ Event Types:         {profile_3['event_types']}")
    
    print(f"\nNODE 4:")
    print(f"  ✓ Behavior:            {profile_4['behavior']}")
    print(f"  ✓ PM10 Ceiling:        {profile_4['pm10_ceiling']}")
    print(f"  ✓ Event Types:         {profile_4['event_types']}")
    
    print(f"\n{'=' * 80}")
    print("TEST VERIFICATION")
    print(f"{'=' * 80}")
    
    # Verify expectations
    checks = [
        ("Node 3 is transport-dominant", profile_3['behavior'] == 'transport-dominant'),
        ("Node 4 is human-density", profile_4['behavior'] == 'human-density'),
        ("Node 3 PM10 ceiling is 4.0", profile_3['pm10_ceiling'] == 4.0),
        ("Node 4 PM10 ceiling is 3.0", profile_4['pm10_ceiling'] == 3.0),
        ("Node 3 has traffic event types", 'jeepney_convoy' in profile_3['event_types']),
        ("Node 4 has market event types", 'market_crowd' in profile_4['event_types']),
    ]
    
    all_pass = True
    for check_name, check_result in checks:
        status = "✓ PASS" if check_result else "✗ FAIL"
        print(f"  {status}: {check_name}")
        if not check_result:
            all_pass = False
    
    print(f"\n{'=' * 80}")
    if all_pass:
        print("✓ ALL TESTS PASSED!")
    else:
        print("✗ SOME TESTS FAILED!")
    print(f"{'=' * 80}\n")

if __name__ == '__main__':
    test_node_profiles()
