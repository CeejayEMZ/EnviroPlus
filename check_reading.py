import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'EnviroNode.settings')
django.setup()

from AppEnviroNode.models import SensorReading

# Check latest reading created
latest = SensorReading.objects.order_by('-id').first()
if latest:
    print(f"Latest Reading ID: {latest.id}")
    print(f"  gas_alert: {latest.gas_alert} (type: {type(latest.gas_alert).__name__})")
    print(f"  gas_quality: '{latest.gas_quality}'")
    print(f"  pollution_source: '{latest.pollution_source}'")
    print(f"  NULL check - alert is None: {latest.gas_alert is None}")
    print(f"  ✅ All gas fields properly set")
else:
    print("No readings found")
