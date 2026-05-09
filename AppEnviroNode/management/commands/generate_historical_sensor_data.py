"""
Management command to generate realistic historical sensor data for March 28 - May 10, 2026.
Inserts data for ENVIRONODE_002 and ENVIRONODE_003 with realistic daily patterns,
traffic rush hour peaks, and proper AQI calculation.

Usage:
    python manage.py generate_historical_sensor_data
"""

import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from AppEnviroNode.models import SensorNode, SensorReading
from AppEnviroNode.utils import calculate_aqi


class Command(BaseCommand):
    help = 'Generate realistic historical sensor data (March 28 - May 10, 2026)'

    # CSV baseline PM2.5 data (daily values for trend anchoring)
    CSV_DATA = {
        '2026-03-28': {'pm25': 20.81, 'range': (15.98, 25.81)},
        '2026-03-29': {'pm25': 19.55, 'range': (13.8, 27.96)},
        '2026-03-30': {'pm25': 19.16, 'range': (16.38, 25.97)},
        '2026-03-31': {'pm25': 20.48, 'range': (16.98, 34.85)},
        '2026-04-01': {'pm25': 16.04, 'range': (10.81, 28.63)},
        '2026-04-02': {'pm25': 11.67, 'range': (3.66, 19.35)},
        '2026-04-03': {'pm25': 12.44, 'range': (9.19, 22.21)},
        '2026-04-04': {'pm25': 21.48, 'range': (13.63, 38.5)},
        '2026-04-05': {'pm25': 24.3, 'range': (18.09, 40.24)},
        '2026-04-06': {'pm25': 15.95, 'range': (9.86, 27.77)},
        '2026-04-07': {'pm25': 19.03, 'range': (9.56, 30.14)},
        '2026-04-08': {'pm25': 16.2, 'range': (5.82, 26.24)},
        '2026-04-09': {'pm25': 10.3, 'range': (4.09, 21.27)},
        '2026-04-10': {'pm25': 18.52, 'range': (9.84, 26.43)},
        '2026-04-11': {'pm25': 24.18, 'range': (17.48, 35.14)},
        '2026-04-12': {'pm25': 20.27, 'range': (15.99, 28.37)},
        '2026-04-13': {'pm25': 16.72, 'range': (12.25, 24.72)},
        '2026-04-14': {'pm25': 18.17, 'range': (11.47, 26.19)},
        '2026-04-15': {'pm25': 19.46, 'range': (12.16, 33.22)},
        '2026-04-16': {'pm25': 24.02, 'range': (17.29, 34.93)},
        '2026-04-17': {'pm25': 29.47, 'range': (21.31, 36.0)},
        '2026-04-18': {'pm25': 29.89, 'range': (25.35, 36.27)},
        '2026-04-19': {'pm25': 34.69, 'range': (24.93, 56.43)},
        '2026-04-20': {'pm25': 31.14, 'range': (25.56, 54.91)},
        '2026-04-21': {'pm25': 25.31, 'range': (21.14, 32.72)},
        '2026-04-22': {'pm25': 25.42, 'range': (21.93, 33.93)},
        '2026-04-23': {'pm25': 26.19, 'range': (20.63, 31.97)},
        '2026-04-24': {'pm25': 23.94, 'range': (19.88, 29.49)},
        '2026-04-25': {'pm25': 18.59, 'range': (14.07, 27.78)},
        '2026-04-26': {'pm25': 10.64, 'range': (5.26, 21.03)},
        '2026-04-27': {'pm25': 5.19, 'range': (2.2, 14.77)},
        '2026-04-28': {'pm25': 5.7, 'range': (3.68, 10.6)},
        '2026-04-29': {'pm25': 12.15, 'range': (5.14, 30.81)},
        '2026-04-30': {'pm25': 12.5, 'range': (5.56, 31.44)},
        '2026-05-01': {'pm25': 8.09, 'range': (4.51, 17.85)},
        '2026-05-02': {'pm25': 7.53, 'range': (4.04, 14.54)},
        '2026-05-03': {'pm25': 6.9, 'range': (1.83, 18.94)},
        '2026-05-04': {'pm25': 10.25, 'range': (5.17, 21.07)},
        '2026-05-05': {'pm25': 6.84, 'range': (1.04, 16.35)},
        '2026-05-06': {'pm25': 10.24, 'range': (5.62, 22.19)},
        '2026-05-07': {'pm25': 6.52, 'range': (2.13, 16.16)},
        '2026-05-08': {'pm25': 7.95, 'range': (4.33, 17.94)},
        '2026-05-09': {'pm25': 5.99, 'range': (3.86, 11.21)},
        '2026-05-10': {'pm25': 5.99, 'range': (3.86, 11.21)},  # Estimate for May 10
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without saving to database (validation only)',
        )
        parser.add_argument(
            '--node',
            type=str,
            default='both',
            choices=['002', '003', 'both'],
            help='Which node(s) to generate data for',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== Historical Sensor Data Generator ===\n'))

        # Nodes to generate data for
        node_macs = []
        if options['node'] in ['002', 'both']:
            node_macs.append('ENVIRONODE_002')
        if options['node'] in ['003', 'both']:
            node_macs.append('ENVIRONODE_003')

        # Verify nodes exist
        nodes = {}
        for mac in node_macs:
            try:
                node = SensorNode.objects.get(mac_address=mac)
                nodes[mac] = node
                self.stdout.write(f'✓ Found {mac}: {node.name}')
            except SensorNode.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'✗ Node {mac} not found!'))
                return

        self.stdout.write('\n' + self.style.WARNING('Starting data generation...'))

        start_date = datetime(2026, 3, 28)
        end_date = datetime(2026, 5, 10)

        total_readings_generated = 0

        for node_mac, node in nodes.items():
            readings = self._generate_readings_for_node(node, start_date, end_date)
            total_readings_generated += len(readings)

            if not options['dry_run']:
                self.stdout.write(f'\nInserting {len(readings)} readings for {node_mac}...')
                self._insert_readings_batch(readings)
                node.last_reading = readings[-1].timestamp
                node.status = 'active'
                node.save()
                self.stdout.write(self.style.SUCCESS(f'✓ Successfully inserted {len(readings)} readings'))

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(f'\n[DRY RUN] Would generate {total_readings_generated} total readings')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'\n✓ Successfully generated {total_readings_generated} readings total')
            )

    def _generate_readings_for_node(self, node, start_date, end_date):
        """Generate all readings for a node across date range."""
        readings = []
        current_date = start_date

        while current_date < end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            daily_data = self.CSV_DATA.get(date_str, {'pm25': 20, 'range': (10, 35)})

            # Generate 288 readings per day (5-minute intervals)
            daily_readings = self._generate_daily_readings(
                node,
                current_date,
                daily_data['pm25'],
                daily_data['range']
            )
            readings.extend(daily_readings)
            current_date += timedelta(days=1)

        return readings

    def _generate_daily_readings(self, node, base_date, target_pm25, pm25_range):
        """Generate 288 readings (5-minute intervals) for a single day."""
        readings = []
        min_pm25, max_pm25 = pm25_range

        # Create hourly PM2.5 multipliers to simulate traffic patterns
        hourly_multipliers = self._generate_hourly_pattern()

        for minute_offset in range(0, 24 * 60, 5):  # 5-minute intervals
            hour = minute_offset // 60
            minute = minute_offset % 60

            timestamp = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            timestamp = timezone.make_aware(timestamp)

            # Apply hourly pattern to PM2.5
            hour_multiplier = hourly_multipliers[hour]
            pm25 = target_pm25 * hour_multiplier

            # Add small random fluctuation
            pm25 += random.gauss(0, pm25 * 0.05)  # 5% gaussian noise
            pm25 = max(min_pm25, min(max_pm25, pm25))  # Clamp to daily range

            # Generate correlated sensor values
            pm1_0 = pm25 * random.uniform(0.4, 0.7)
            pm10 = pm25 * random.uniform(1.3, 1.6)

            # Temperature: simulate daily cycle
            # Cooler at night (1-5 AM), warmest 1-3 PM
            if hour < 6:
                base_temp = 24 + random.gauss(0, 1)
            elif 12 <= hour < 15:
                # Peak heat
                if base_date.month in [3]:  # Late March
                    base_temp = 30 + random.gauss(0, 1)
                elif base_date.month == 4:  # April
                    base_temp = 32 + random.gauss(0, 1)
                else:  # May
                    base_temp = 35 + random.gauss(0, 1.5)
            else:
                if base_date.month in [3]:
                    base_temp = 28 + random.gauss(0, 1)
                elif base_date.month == 4:
                    base_temp = 30 + random.gauss(0, 1)
                else:
                    base_temp = 32 + random.gauss(0, 1.5)

            # Humidity: inverse relationship with heat, higher at night
            if hour < 6:
                humidity = 75 + random.gauss(0, 3)
            elif 12 <= hour < 15:
                humidity = 55 + random.gauss(0, 3)
            else:
                humidity = 65 + random.gauss(0, 3)

            humidity = max(30, min(99, humidity))

            # Pressure: slight variation, no extreme jumps
            pressure = 1013 + random.gauss(0, 2)

            # Gas resistance: lower when polluted (PM2.5 higher)
            # Inverse relationship: higher PM2.5 = lower resistance
            base_gas = 100 - (pm25 * 2)  # Rough inverse
            gas_resistance = max(10, base_gas + random.gauss(0, 5))

            # System status (mostly normal, occasional degraded)
            if random.random() < 0.95:
                system_status = 'normal'
            else:
                system_status = 'degraded'

            # Create reading
            reading = SensorReading(
                node=node,
                pm1_0=max(0, pm1_0),
                pm2_5=max(0, pm25),
                pm10=max(0, pm10),
                temperature=base_temp,
                humidity=humidity,
                pressure=pressure,
                gas_resistance=gas_resistance,
                system_status=system_status,
                pms_status='ok',
                bme_status='ok',
                latency_ms=random.randint(50, 200),
                is_anomaly=False,
                timestamp=timestamp,
            )
            
            # Calculate AQI before adding to list (since bulk_create bypasses save())
            if max(0, pm25) is not None:
                reading.aqi, reading.aqi_level = calculate_aqi(max(0, pm25))
            
            readings.append(reading)

        return readings

    def _generate_hourly_pattern(self):
        """
        Generate hourly multipliers for PM2.5 to simulate traffic patterns.
        
        Rush hours (11 AM-1 PM, 5 PM-7 PM): higher pollution
        Dead hours (1 AM-5 AM): lower pollution
        Normal hours: moderate pollution
        """
        multipliers = {}

        for hour in range(24):
            if 1 <= hour < 5:
                # Dead hours: low pollution (0.7-0.85x baseline)
                multipliers[hour] = random.uniform(0.7, 0.85)
            elif (11 <= hour < 13) or (17 <= hour < 19):
                # Rush hours: high pollution (1.3-1.6x baseline)
                multipliers[hour] = random.uniform(1.3, 1.6)
            elif 5 <= hour < 11:
                # Morning: gradual increase (0.95-1.1x)
                multipliers[hour] = random.uniform(0.95, 1.1)
            elif 13 <= hour < 17:
                # Midday: moderate (1.0-1.15x)
                multipliers[hour] = random.uniform(1.0, 1.15)
            else:
                # Evening: gradual decrease (1.0-1.2x)
                multipliers[hour] = random.uniform(1.0, 1.2)

        return multipliers

    @transaction.atomic
    def _insert_readings_batch(self, readings, batch_size=1000):
        """Insert readings in batches for performance."""
        for i in range(0, len(readings), batch_size):
            batch = readings[i:i + batch_size]
            SensorReading.objects.bulk_create(batch, batch_size=batch_size)
            self.stdout.write(f'  Inserted batch {i // batch_size + 1}/{(len(readings) + batch_size - 1) // batch_size}')
