"""
Management command to generate high-traffic urban roadside sensor data for ENVIRONODE_002.
Represents a busy, polluted urban environment with strong rush hour peaks and sustained pollution.

Usage:
    python manage.py generate_node2_hightraffic_data
"""

import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from AppEnviroNode.models import SensorNode, SensorReading
from AppEnviroNode.utils import calculate_aqi


class Command(BaseCommand):
    help = 'Generate high-traffic urban roadside sensor data for ENVIRONODE_002'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without saving to database (validation only)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== High-Traffic Urban Node Data Generator (Node 002) ===\n'))

        # Get Node 002
        try:
            node = SensorNode.objects.get(mac_address='ENVIRONODE_002')
            self.stdout.write(f'✓ Found ENVIRONODE_002: {node.name}')
        except SensorNode.DoesNotExist:
            self.stdout.write(self.style.ERROR('✗ Node ENVIRONODE_002 not found!'))
            return

        self.stdout.write('\n' + self.style.WARNING('Starting data generation...'))

        # Date range: March 30 - May 11, 2026
        start_date = datetime(2026, 3, 30)
        end_date = datetime(2026, 5, 11)

        readings = self._generate_readings_for_node(node, start_date, end_date)
        total_readings_generated = len(readings)

        if not options['dry_run']:
            self.stdout.write(f'\nInserting {len(readings)} readings...')
            self._insert_readings_batch(readings)
            node.last_reading = readings[-1].timestamp
            node.status = 'active'
            node.save()
            self.stdout.write(self.style.SUCCESS(f'✓ Successfully inserted {len(readings)} readings'))
        else:
            self.stdout.write(
                self.style.WARNING(f'\n[DRY RUN] Would generate {total_readings_generated} readings')
            )

    def _generate_readings_for_node(self, node, start_date, end_date):
        """Generate all readings for Node 002 across date range."""
        readings = []
        current_date = start_date

        while current_date < end_date:
            # Determine if weekend
            is_weekend = current_date.weekday() >= 5
            
            date_str = current_date.strftime('%Y-%m-%d')
            
            # Generate 288 readings per day (5-minute intervals)
            daily_readings = self._generate_daily_readings(
                node,
                current_date,
                is_weekend
            )
            readings.extend(daily_readings)
            current_date += timedelta(days=1)

        return readings

    def _generate_daily_readings(self, node, base_date, is_weekend):
        """Generate 288 readings (5-minute intervals) for a single day with high-traffic profile."""
        readings = []
        
        # Create hourly PM2.5 multipliers for high-traffic environment
        hourly_multipliers = self._generate_hightraffic_hourly_pattern(is_weekend)
        
        # Base pollution level varies by month (seasonal drift)
        month = base_date.month
        if month == 3:
            base_pm25 = random.uniform(45, 55)
        elif month == 4:
            base_pm25 = random.uniform(55, 70)
        else:  # May
            base_pm25 = random.uniform(50, 65)

        for minute_offset in range(0, 24 * 60, 5):  # 5-minute intervals
            hour = minute_offset // 60
            minute = minute_offset % 60

            timestamp = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            timestamp = timezone.make_aware(timestamp)

            # Apply hourly traffic pattern to PM2.5
            hour_multiplier = hourly_multipliers[hour]
            pm25 = base_pm25 * hour_multiplier

            # Add realistic environmental events
            # - Occasional bus/truck events (sharp spikes)
            # - Short dips (wind events)
            # - general fluctuation
            if random.random() < 0.02:  # 2% chance of vehicle event
                pm25 *= random.uniform(1.4, 2.0)
            elif random.random() < 0.01:  # 1% chance of wind cleanup
                pm25 *= random.uniform(0.6, 0.8)
            
            # Add realistic gaussian noise
            pm25 += random.gauss(0, pm25 * 0.08)  # 8% noise (higher than Node 003)
            
            # Clamp to realistic bounds for high-traffic area
            pm25 = max(15, min(160, pm25))

            # Generate correlated sensor values with high-traffic profile
            # High-traffic = lower fuel efficiency, more combustion products
            pm1_0 = pm25 * random.uniform(0.35, 0.55)  # More fine particles from combustion
            pm10 = pm25 * random.uniform(1.4, 1.8)      # More coarse dust from traffic

            # Temperature: urban heat island effect
            # Higher than Node 003 due to pavement, engines, lack of vegetation
            if hour < 6:
                base_temp = 25 + random.gauss(0, 1.2)
            elif 12 <= hour < 15:
                # Peak heat - strongest urban heat island
                if base_date.month == 3:
                    base_temp = 32 + random.gauss(0, 1.5)
                elif base_date.month == 4:
                    base_temp = 34 + random.gauss(0, 1.5)
                else:  # May
                    base_temp = 37 + random.gauss(0, 1.5)
            else:
                if base_date.month == 3:
                    base_temp = 29 + random.gauss(0, 1.2)
                elif base_date.month == 4:
                    base_temp = 31 + random.gauss(0, 1.2)
                else:
                    base_temp = 33 + random.gauss(0, 1.5)

            # Humidity: inverse with heat, but more variable due to traffic exhaust
            if hour < 6:
                humidity = 72 + random.gauss(0, 4)
            elif 12 <= hour < 15:
                humidity = 50 + random.gauss(0, 4)
            else:
                humidity = 62 + random.gauss(0, 4)

            humidity = max(25, min(99, humidity))

            # Pressure: slight variation
            pressure = 1013 + random.gauss(0, 2.5)

            # Gas resistance: significantly lower due to high pollution
            base_gas = 80 - (pm25 * 0.5)  # More aggressive inverse
            gas_resistance = max(5, base_gas + random.gauss(0, 8))

            # System status: mostly normal, rare degradation
            if random.random() < 0.03:
                system_status = 'degraded'
            else:
                system_status = 'normal'

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
                latency_ms=random.randint(60, 220),
                is_anomaly=False,
                timestamp=timestamp,
            )
            
            # Calculate AQI before adding to list
            if max(0, pm25) is not None:
                reading.aqi, reading.aqi_level = calculate_aqi(max(0, pm25))
            
            readings.append(reading)

        return readings

    def _generate_hightraffic_hourly_pattern(self, is_weekend):
        """
        Generate hourly multipliers for high-traffic urban environment.
        
        Strong rush hours:
        - 6 AM – 9 AM (morning commute)
        - 11 AM – 2 PM (midday traffic)
        - 5 PM – 9 PM (evening commute)
        
        Dead hours still elevated:
        - 1 AM – 4 AM (city never sleeps, some trucks)
        """
        multipliers = {}

        for hour in range(24):
            if is_weekend:
                # Weekend: slightly lower but still busy
                if 1 <= hour < 4:
                    multipliers[hour] = random.uniform(1.0, 1.2)  # Still active
                elif 6 <= hour < 9:
                    multipliers[hour] = random.uniform(1.4, 1.7)
                elif 11 <= hour < 14:
                    multipliers[hour] = random.uniform(1.5, 1.8)
                elif 17 <= hour < 20:
                    multipliers[hour] = random.uniform(1.3, 1.6)
                else:
                    multipliers[hour] = random.uniform(1.0, 1.3)
            else:
                # Weekday: strong peaks
                if 1 <= hour < 4:
                    # Dead hours but still urban (not pristine)
                    multipliers[hour] = random.uniform(0.85, 1.0)
                elif 4 <= hour < 6:
                    multipliers[hour] = random.uniform(1.0, 1.3)
                elif 6 <= hour < 9:
                    # Morning commute: INTENSE
                    multipliers[hour] = random.uniform(1.7, 2.2)
                elif 9 <= hour < 11:
                    multipliers[hour] = random.uniform(1.2, 1.5)
                elif 11 <= hour < 14:
                    # Midday: high sustained
                    multipliers[hour] = random.uniform(1.6, 2.0)
                elif 14 <= hour < 17:
                    multipliers[hour] = random.uniform(1.3, 1.6)
                elif 17 <= hour < 20:
                    # Evening commute: INTENSE
                    multipliers[hour] = random.uniform(1.8, 2.3)
                elif 20 <= hour < 22:
                    multipliers[hour] = random.uniform(1.2, 1.5)
                else:
                    multipliers[hour] = random.uniform(0.95, 1.2)

        return multipliers

    @transaction.atomic
    def _insert_readings_batch(self, readings, batch_size=1000):
        """Insert readings in batches for performance."""
        for i in range(0, len(readings), batch_size):
            batch = readings[i:i + batch_size]
            SensorReading.objects.bulk_create(batch, batch_size=batch_size)
            self.stdout.write(f'  Inserted batch {i // batch_size + 1}/{(len(readings) + batch_size - 1) // batch_size}')
