"""
Management command to populate SystemLog entries from existing SensorReadings.
Use this to backfill logs after the SystemLog model was added.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from AppEnviroNode.models import SensorReading, SystemLog, SensorNode


class Command(BaseCommand):
    help = 'Populate SystemLog entries from existing SensorReadings'
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting SystemLog population from SensorReadings...'))
        
        # Check if logs already exist
        existing_count = SystemLog.objects.count()
        if existing_count > 0:
            self.stdout.write(self.style.WARNING(f'⚠️  {existing_count} SystemLogs already exist. Skipping...'))
            return
        
        # Get all SensorReadings
        readings = SensorReading.objects.select_related('node').all().order_by('timestamp')
        total = readings.count()
        
        if total == 0:
            self.stdout.write(self.style.WARNING('✓ No SensorReadings found. Nothing to log.'))
            return
        
        batch_size = 100
        created = 0
        
        self.stdout.write(f'Processing {total} SensorReadings...')
        
        for i, reading in enumerate(readings):
            # Determine severity based on AQI level
            severity = reading.aqi_level or 'moderate'
            
            # Create log entry
            SystemLog.objects.create(
                node=reading.node,
                reading=reading,
                event_type='reading',
                severity=severity,
                message=f"Node {reading.node.name} recorded AQI {reading.aqi}" if reading.aqi else f"Node {reading.node.name} recorded sensor reading",
                value=reading.aqi,
                sensor_type='aqi',
                created_at=reading.timestamp
            )
            created += 1
            
            # Progress indicator
            if (i + 1) % batch_size == 0:
                self.stdout.write(f'  ✓ Processed {i + 1}/{total}')
        
        self.stdout.write(self.style.SUCCESS(f'✅ Successfully created {created} SystemLog entries!'))
        
        # Create device status logs for nodes
        self.stdout.write(self.style.WARNING('Creating device status logs...'))
        
        nodes = SensorNode.objects.all()
        device_logs_created = 0
        
        for node in nodes:
            # Create initial online log for each node
            if node.last_reading:
                SystemLog.objects.create(
                    node=node,
                    event_type='device_online',
                    severity='good',
                    message=f"Node {node.name} initialized - Status: {node.status}",
                    created_at=node.created_at
                )
                device_logs_created += 1
        
        self.stdout.write(self.style.SUCCESS(f'✅ Created {device_logs_created} device status logs!'))
        
        # Summary
        final_count = SystemLog.objects.count()
        self.stdout.write(self.style.SUCCESS(f'\n✓ Total SystemLogs: {final_count}'))
