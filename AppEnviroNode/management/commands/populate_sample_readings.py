from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from AppEnviroNode.models import SensorNode, SensorReading


class Command(BaseCommand):
    help = 'Create sample sensor nodes and 24 hourly readings for each node'

    SAMPLE_NODES = [
        {
            'mac_address': '02:EN:00:00:00:01',
            'name': 'Sample Node - City Hall',
            'location': 'City Hall',
            'latitude': 14.5995,
            'longitude': 120.9842,
        },
        {
            'mac_address': '02:EN:00:00:00:02',
            'name': 'Sample Node - Public Market',
            'location': 'Public Market',
            'latitude': 14.6042,
            'longitude': 120.9822,
        },
        {
            'mac_address': '02:EN:00:00:00:03',
            'name': 'Sample Node - Riverside Park',
            'location': 'Riverside Park',
            'latitude': 14.5921,
            'longitude': 120.9798,
        },
    ]

    READING_PROFILES = [
        {'pm1_0': 8.2, 'pm2_5': 14.0, 'pm10': 22.5, 'temperature': 28.4, 'humidity': 68.0, 'pressure': 1009.4, 'gas_resistance': 92.0, 'mq135_raw': 280},
        {'pm1_0': 18.6, 'pm2_5': 34.0, 'pm10': 58.0, 'temperature': 30.1, 'humidity': 73.0, 'pressure': 1007.8, 'gas_resistance': 61.0, 'mq135_raw': 470},
        {'pm1_0': 5.4, 'pm2_5': 9.0, 'pm10': 15.0, 'temperature': 27.2, 'humidity': 64.0, 'pressure': 1011.2, 'gas_resistance': 118.0, 'mq135_raw': 190},
    ]

    def handle(self, *args, **options):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        created_nodes = 0
        created_readings = 0

        with transaction.atomic():
            for node_data, profile in zip(self.SAMPLE_NODES, self.READING_PROFILES):
                node, node_created = SensorNode.objects.get_or_create(
                    mac_address=node_data['mac_address'],
                    defaults={
                        **node_data,
                        'organization': 'EMBO',
                        'status': 'active',
                        'is_active': True,
                    },
                )
                created_nodes += int(node_created)

                for hours_ago in range(24):
                    timestamp = now - timedelta(hours=hours_ago)
                    reading, reading_created = SensorReading.objects.get_or_create(
                        node=node,
                        timestamp=timestamp,
                        defaults={
                            **profile,
                            'gas_quality': 'good' if profile['pm2_5'] < 15 else 'moderate',
                            'pollution_source': 'traffic' if profile['pm2_5'] >= 15 else 'unknown',
                            'system_status': 'normal',
                            'pms_status': 'ok',
                            'bme_status': 'ok',
                            'latency_ms': 120,
                            'is_anomaly': False,
                        },
                    )
                    created_readings += int(reading_created)

                latest_reading = node.readings.order_by('-timestamp').first()
                node.last_reading = latest_reading.timestamp
                node.status = 'active'
                node.is_active = True
                node.save(update_fields=['last_reading', 'status', 'is_active', 'updated_at'])

        self.stdout.write(self.style.SUCCESS(
            f'Created {created_nodes} sample nodes and {created_readings} sample readings.'
        ))
        self.stdout.write('Sample data uses the MAC address prefix 02:EN:00:00:00.')