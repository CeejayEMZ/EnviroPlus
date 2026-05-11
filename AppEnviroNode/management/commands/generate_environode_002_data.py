"""
Management command to generate highly chaotic, realistic sensor data for ENVIRONODE_002.
Deployed in a busy urban roadside area in Metro Manila with heavy traffic exposure.

DATE RANGE: March 31, 2026 - May 11, 2026
TIMEZONE: Asia/Manila (UTC+8)
MAC ADDRESS: ENVIRONODE_002

CHARACTERISTICS:
- Heavier traffic exposure
- Stronger PM fluctuations
- More human activity
- More vehicle congestion
- More roadside dust
- Occasional crowd surges
- Stronger evening pollution buildup
- Urban heat island effect
- More chaotic sensor behavior during prototyping

USAGE:
    python manage.py generate_environode_002_data [--dry-run] [--delete-existing]
"""

import random
import os
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from AppEnviroNode.models import SensorNode, SensorReading
from AppEnviroNode.utils import calculate_aqi
import pytz


class Command(BaseCommand):
    help = 'Generate highly chaotic, realistic historical sensor data for ENVIRONODE_002'

    # WAQI PM2.5 Daily Baselines (Pateros Bridge, Philippines)
    WAQI_PM25_BASELINES = {
        '2026-03-31': {'median': 23.88, 'q1': 22.97, 'q3': 29.55, 'min': 21.1, 'max': 35.46},
        '2026-04-01': {'median': 18.63, 'q1': 14.17, 'q3': 20.58, 'min': 11.49, 'max': 29.53},
        '2026-04-02': {'median': 13.83, 'q1': 9.31, 'q3': 19.32, 'min': 4.55, 'max': 29.4},
        '2026-04-03': {'median': 16.48, 'q1': 14.72, 'q3': 20.09, 'min': 8.77, 'max': 29.21},
        '2026-04-04': {'median': 21.38, 'q1': 19.86, 'q3': 27.1, 'min': 16.98, 'max': 42.75},
        '2026-04-05': {'median': 28.67, 'q1': 25.17, 'q3': 31.15, 'min': 23.31, 'max': 41.32},
        '2026-04-06': {'median': 20.66, 'q1': 17.41, 'q3': 26.32, 'min': 12.13, 'max': 36.34},
        '2026-04-07': {'median': 19.72, 'q1': 12.09, 'q3': 27.24, 'min': 7.53, 'max': 33.04},
        '2026-04-08': {'median': 16.22, 'q1': 10.73, 'q3': 23.32, 'min': 5.11, 'max': 27.64},
        '2026-04-09': {'median': 13.34, 'q1': 9.31, 'q3': 17.93, 'min': 5.12, 'max': 24.31},
        '2026-04-10': {'median': 22.02, 'q1': 16.68, 'q3': 24.9, 'min': 8.26, 'max': 27.02},
        '2026-04-11': {'median': 26.12, 'q1': 21.58, 'q3': 31.23, 'min': 15.73, 'max': 44.22},
        '2026-04-12': {'median': 23.6, 'q1': 18.8, 'q3': 27.16, 'min': 15.89, 'max': 32.94},
        '2026-04-13': {'median': 16.55, 'q1': 14.3, 'q3': 23.01, 'min': 11.05, 'max': 27.02},
        '2026-04-14': {'median': 19.98, 'q1': 17.32, 'q3': 22.61, 'min': 14.91, 'max': 24.36},
        '2026-04-15': {'median': 23.11, 'q1': 18.7, 'q3': 26.75, 'min': 16.72, 'max': 35.43},
        '2026-04-16': {'median': 24.74, 'q1': 23.74, 'q3': 27.83, 'min': 22.01, 'max': 39.64},
        '2026-04-17': {'median': 33.49, 'q1': 29.79, 'q3': 34.69, 'min': 26.34, 'max': 41.13},
        '2026-04-18': {'median': 31.49, 'q1': 28.29, 'q3': 35.07, 'min': 26.86, 'max': 40.32},
        '2026-04-19': {'median': 33.5, 'q1': 30.55, 'q3': 48.17, 'min': 29.8, 'max': 54.79},
        '2026-04-20': {'median': 35.56, 'q1': 32.07, 'q3': 41.0, 'min': 29.56, 'max': 56.94},
        '2026-04-21': {'median': 29.38, 'q1': 27.6, 'q3': 34.56, 'min': 25.69, 'max': 41.66},
        '2026-04-22': {'median': 28.27, 'q1': 27.07, 'q3': 29.48, 'min': 25.66, 'max': 34.18},
        '2026-04-23': {'median': 28.32, 'q1': 26.07, 'q3': 31.0, 'min': 25.21, 'max': 40.64},
        '2026-04-24': {'median': 27.35, 'q1': 25.64, 'q3': 29.16, 'min': 23.33, 'max': 35.53},
        '2026-04-25': {'median': 24.38, 'q1': 18.66, 'q3': 27.75, 'min': 16.88, 'max': 30.88},
        '2026-04-26': {'median': 15.94, 'q1': 11.17, 'q3': 18.89, 'min': 7.93, 'max': 26.69},
        '2026-04-27': {'median': 11.54, 'q1': 9.93, 'q3': 15.16, 'min': 4.97, 'max': 18.41},
        '2026-04-28': {'median': 11.4, 'q1': 9.15, 'q3': 16.5, 'min': 6.62, 'max': 19.21},
        '2026-04-29': {'median': 14.57, 'q1': 12.18, 'q3': 23.69, 'min': 9.85, 'max': 27.03},
        '2026-04-30': {'median': 16.13, 'q1': 9.52, 'q3': 22.17, 'min': 6.4, 'max': 43.38},
        '2026-05-01': {'median': 13.07, 'q1': 8.84, 'q3': 19.26, 'min': 5.6, 'max': 33.75},
        '2026-05-02': {'median': 12.94, 'q1': 9.69, 'q3': 15.51, 'min': 6.68, 'max': 18.97},
        '2026-05-03': {'median': 11.33, 'q1': 7.75, 'q3': 16.5, 'min': 4.96, 'max': 29.5},
        '2026-05-04': {'median': 11.13, 'q1': 8.04, 'q3': 17.69, 'min': 5.56, 'max': 21.62},
        '2026-05-05': {'median': 11.92, 'q1': 7.49, 'q3': 17.61, 'min': 2.07, 'max': 37.73},
        '2026-05-06': {'median': 13.29, 'q1': 9.83, 'q3': 18.22, 'min': 7.1, 'max': 30.33},
        '2026-05-07': {'median': 11.69, 'q1': 7.4, 'q3': 15.28, 'min': 3.94, 'max': 26.9},
        '2026-05-08': {'median': 12.22, 'q1': 10.73, 'q3': 15.91, 'min': 7.44, 'max': 24.71},
        '2026-05-09': {'median': 11.49, 'q1': 8.17, 'q3': 15.09, 'min': 5.0, 'max': 33.05},
        '2026-05-10': {'median': 10.9, 'q1': 6.94, 'q3': 15.29, 'min': 2.45, 'max': 22.18},
        '2026-05-11': {'median': 11.0, 'q1': 7.0, 'q3': 15.5, 'min': 2.5, 'max': 23.0},
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without saving to database'
        )
        parser.add_argument(
            '--delete-existing',
            action='store_true',
            help='Delete existing ENVIRONODE_002 data before generation'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('ENVIRONODE_002 Urban Roadside Data Generator'))
        self.stdout.write(self.style.SUCCESS('Busy Metro Manila Location'))
        self.stdout.write(self.style.SUCCESS('Heavy Traffic Exposure'))
        self.stdout.write(self.style.SUCCESS('=' * 50 + '\n'))

        # Get or create node
        node, created = SensorNode.objects.get_or_create(
            mac_address='ENVIRONODE_002',
            defaults={
                'name': 'Urban Roadside - High Traffic Monitor',
                'location': 'Busy Urban Roadside, Manila, Philippines',
                'organization': 'SmAIR Environmental',
                'status': 'active',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(self.style.WARNING(f'[CREATE] New node: {node.name}'))
        else:
            self.stdout.write(f'[FOUND] Node: {node.name}')

        # Handle deletion
        if options['delete_existing']:
            count, _ = SensorReading.objects.filter(node=node).delete()
            self.stdout.write(self.style.WARNING(f'Deleted {count} existing readings\n'))

        # Generate data
        start_date = timezone.make_aware(
            datetime(2026, 3, 31, 0, 0, 0),
            pytz.timezone('Asia/Manila')
        )
        end_date = timezone.make_aware(
            datetime(2026, 5, 11, 23, 59, 59),
            pytz.timezone('Asia/Manila')
        )

        self.stdout.write(f'Generating data from {start_date} to {end_date}')
        self.stdout.write('Please wait...\n')

        readings = self._generate_all_readings(node, start_date, end_date)

        if not options['dry_run']:
            self.stdout.write(f'Inserting {len(readings)} readings into database...\n')
            self._insert_readings_batch(readings)
            node.last_reading = readings[-1].timestamp
            node.status = 'active'
            node.save()
            self._print_summary_stats(readings)
        else:
            self.stdout.write(self.style.WARNING(f'[DRY RUN] Would insert {len(readings)} readings\n'))
            if len(readings) > 0:
                self._print_summary_stats(readings)

    def _generate_all_readings(self, node, start_dt, end_dt):
        """Generate all readings across the entire date range."""
        readings = []
        manila_tz = pytz.timezone('Asia/Manila')

        current_date = start_dt.date()
        end_date = end_dt.date()

        total_days = (end_date - current_date).days + 1
        day_count = 0

        while current_date <= end_date:
            day_count += 1
            is_prototyping = current_date <= datetime(2026, 4, 14).date()
            phase_name = "PROTO" if is_prototyping else "STABLE"

            date_str = current_date.strftime('%Y-%m-%d')
            baseline = self.WAQI_PM25_BASELINES.get(
                date_str,
                {'median': 20.0, 'q1': 15.0, 'q3': 25.0, 'min': 10.0, 'max': 35.0}
            )

            day_readings = self._generate_daily_readings(
                node, current_date, baseline, is_prototyping, manila_tz
            )
            readings.extend(day_readings)

            progress = f"Day {day_count}/{total_days} ({date_str}) [{phase_name}] - {len(day_readings)} readings"
            self.stdout.write(progress)

            current_date += timedelta(days=1)

        return readings

    def _generate_daily_readings(self, node, day, baseline, is_prototyping, manila_tz):
        """Generate readings for a single day with chaotic urban patterns."""
        readings = []
        
        # ✨ NODE PERSONALITY DIFFERENTIATION LAYER
        node_profile = self._get_node_profile(node.id)
        
        # Determine day characteristics
        day_of_week = day.weekday()  # 0=Monday, 6=Sunday
        is_weekend = day_of_week >= 5
        is_friday = day_of_week == 4
        is_sunday = day_of_week == 6
        
        # Prototyping phase: 40% chance of major issues
        if is_prototyping:
            issue_roll = random.random()
            if issue_roll < 0.25:
                # Major outage with reboot/recovery
                return self._generate_broken_day(node, day, baseline, manila_tz)
            elif issue_roll < 0.45:
                # Severe calibration drift with delayed corrections
                return self._generate_calibration_drift_day(node, day, baseline, manila_tz)
            elif issue_roll < 0.60:
                # Intermittent data with duplicates and gaps
                return self._generate_intermittent_day(node, day, baseline, manila_tz)
        
        # Generate hourly surge profiles (urban traffic patterns)
        is_rainy = random.random() < 0.12
        hourly_surges = self._generate_urban_surge_patterns(
            day, day_of_week, is_friday, is_sunday, node_profile
        )
        
        # ⚡ NODE-SPECIFIC EVENTS (Independent per node)
        event_hour = None
        event_severity = 0
        event_type = None
        if random.random() < 0.20:  # 20% chance of special event
            event_hour = random.randint(6, 20)
            event_severity = random.choice([1, 1, 2])  # Mostly minor, sometimes major
            # Use node-specific event generation
            event_type = self._maybe_generate_event(node_profile, event_hour, event_severity)
        
        # Start with slight delay (realistic sensor startup)
        current_time = manila_tz.localize(
            datetime.combine(day, datetime.min.time())
        ) + timedelta(minutes=random.randint(0, 90))
        
        end_of_day = manila_tz.localize(
            datetime.combine(day, datetime.max.time().replace(hour=23, minute=59))
        )
        
        last_pm25 = baseline['median']
        last_pm10 = baseline['median'] * 1.3
        
        while current_time <= end_of_day:
            hour = current_time.hour
            minute = current_time.minute
            
            # Generate aggressive PM2.5 with traffic surges
            hour_surge = hourly_surges.get(hour, {}).get('multiplier', 1.0)
            pm25 = self._generate_chaotic_pm25(
                baseline, 
                hour_surge,
                last_pm25,
                is_rainy,
                is_weekend,
                hour,
                event_hour,
                event_severity,
                node_profile,
                event_type
            )
            last_pm25 = pm25
            
            # Generate PM10 with dust-heavy spikes (roadside characteristic)
            pm10_multiplier = self._generate_pm10_multiplier(
                hour, event_hour, event_severity, node_profile, event_type
            )
            pm10 = pm25 * pm10_multiplier
            last_pm10 = pm10
            
            # PM1.0 (smaller, correlates with PM2.5)
            pm1_0 = pm25 * random.uniform(0.30, 0.55)
            
            # Temperature with urban heat island effect (node-specific)
            temperature = self._generate_urban_heated_temp(hour, day, is_rainy, node_profile)
            
            # Humidity with more noise (node-specific)
            humidity = self._generate_chaotic_humidity(hour, temperature, is_rainy, node_profile)
            
            # Pressure variations
            pressure = self._generate_pressure_variation(hour)
            
            # Gas resistance with strong inverse pollution
            gas_resistance = self._generate_gas_resistance(pm25, pm10)
            
            # System status with higher error rates
            system_status, pms_status, bme_status = self._generate_chaotic_health(
                is_prototyping, event_hour, hour
            )
            
            # Latency with traffic-induced spikes
            latency_ms = self._generate_urban_latency(system_status, is_prototyping, hour)
            
            reading = SensorReading(
                node=node,
                pm1_0=self._round_2dp(max(0.0, pm1_0)),
                pm2_5=self._round_2dp(max(0.0, pm25)),
                pm10=self._round_2dp(max(0.0, pm10)),
                temperature=self._round_2dp(temperature),
                humidity=self._round_2dp(max(0.0, min(100.0, humidity))),
                pressure=self._round_2dp(pressure),
                gas_resistance=self._round_2dp(max(0.5, gas_resistance)),
                aqi=0,
                aqi_level=None,
                system_status=system_status,
                pms_status=pms_status,
                bme_status=bme_status,
                latency_ms=latency_ms,
                is_anomaly=False,
                timestamp=current_time,
            )
            
            # Calculate AQI
            if reading.pm2_5 is not None:
                reading.aqi, reading.aqi_level = calculate_aqi(reading.pm2_5)
            
            readings.append(reading)
            
            # Urban roadside: more varied intervals (1-12 minutes)
            if random.random() < 0.15:
                # Traffic burst: rapid succession
                interval = random.randint(1, 3)
            else:
                interval = random.randint(3, 12)
            
            current_time += timedelta(minutes=interval)
        
        return readings

    def _generate_broken_day(self, node, day, baseline, manila_tz):
        """Simulate a day with severe outage and recovery."""
        readings = []
        
        # Data stops for 4-12 hours, then resumes with warmup instability
        outage_start_hour = random.randint(3, 12)
        outage_duration = random.randint(4, 12)
        
        current_time = manila_tz.localize(datetime.combine(day, datetime.min.time()))
        end_of_day = manila_tz.localize(
            datetime.combine(day, datetime.max.time().replace(hour=23, minute=59))
        )
        
        node_profile = {'behavior': 'mixed'}  # Default for error scenarios
        
        warmup_complete = False
        warmup_readings = 0
        
        while current_time <= end_of_day:
            hour = current_time.hour
            
            # Check if in outage window
            if outage_start_hour <= hour < outage_start_hour + outage_duration:
                current_time += timedelta(minutes=random.randint(30, 120))
                continue
            
            # Check if in warmup recovery
            if hour >= outage_start_hour + outage_duration and not warmup_complete:
                warmup_readings += 1
                if warmup_readings > 20:
                    warmup_complete = True
                
                # Sensor warmup: readings are unstable
                pm25 = baseline['median'] + random.gauss(0, baseline['median'] * 0.15)
                temperature = 25 + random.uniform(-2, 5)  # Unstable
                humidity = 60 + random.uniform(-10, 10)
            else:
                pm25 = baseline['median'] + random.gauss(0, baseline['median'] * 0.08)
                temperature = self._generate_urban_heated_temp(hour, day, False, node_profile)
                humidity = self._generate_chaotic_humidity(hour, temperature, False, node_profile)
            
            pm10 = pm25 * random.uniform(1.4, 2.1)
            pm1_0 = pm25 * random.uniform(0.35, 0.55)
            pressure = 1013 + random.gauss(0, 1.5)
            gas_resistance = max(5, 100 - pm25 * 1.5 + random.gauss(0, 5))
            
            # Worse health during prototyping outage
            system_status, pms_status, bme_status = 'degraded', 'ok', 'error'
            if warmup_readings < 10:
                system_status = 'critical'
            
            latency_ms = random.randint(80, 450)
            
            reading = SensorReading(
                node=node,
                pm1_0=self._round_2dp(max(0.0, pm1_0)),
                pm2_5=self._round_2dp(max(0.0, pm25)),
                pm10=self._round_2dp(max(0.0, pm10)),
                temperature=self._round_2dp(temperature),
                humidity=self._round_2dp(max(0.0, min(100.0, humidity))),
                pressure=self._round_2dp(pressure),
                gas_resistance=self._round_2dp(max(0.5, gas_resistance)),
                aqi=0,
                aqi_level=None,
                system_status=system_status,
                pms_status=pms_status,
                bme_status=bme_status,
                latency_ms=latency_ms,
                is_anomaly=False,
                timestamp=current_time,
            )
            
            if reading.pm2_5 is not None:
                reading.aqi, reading.aqi_level = calculate_aqi(reading.pm2_5)
            
            readings.append(reading)
            current_time += timedelta(minutes=random.randint(2, 10))
        
        return readings

    def _generate_calibration_drift_day(self, node, day, baseline, manila_tz):
        """Simulate a day with sensor calibration drift that gradually corrects."""
        readings = []
        
        # Readings start 10-30% too high, gradually correct
        drift_start_hour = random.randint(2, 6)
        drift_correction_duration = random.randint(8, 14)  # Hours to return to normal
        
        current_time = manila_tz.localize(datetime.combine(day, datetime.min.time()))
        end_of_day = manila_tz.localize(
            datetime.combine(day, datetime.max.time().replace(hour=23, minute=59))
        )
        
        node_profile = {'behavior': 'mixed'}  # Default for error scenarios
        
        while current_time <= end_of_day:
            hour = current_time.hour
            
            pm25 = baseline['median'] + random.gauss(0, baseline['median'] * 0.08)
            
            # Apply drift if in drift window
            if hour >= drift_start_hour:
                hours_since_drift = hour - drift_start_hour
                if hours_since_drift < drift_correction_duration:
                    # Gradually reduce drift from 20% to 0%
                    drift_percent = (1.0 - (hours_since_drift / drift_correction_duration)) * 0.20
                    pm25 *= (1.0 + drift_percent)
            
            temperature = self._generate_urban_heated_temp(hour, day, False, node_profile)
            humidity = self._generate_chaotic_humidity(hour, temperature, False, node_profile)
            
            pm10 = pm25 * random.uniform(1.3, 2.0)
            pm1_0 = pm25 * random.uniform(0.35, 0.55)
            pressure = 1013 + random.gauss(0, 1.5)
            gas_resistance = max(5, 100 - pm25 * 1.5 + random.gauss(0, 5))
            
            system_status = 'degraded' if hour < drift_start_hour + drift_correction_duration else 'normal'
            pms_status = 'error' if hour < drift_start_hour + drift_correction_duration else 'ok'
            bme_status = 'ok'
            
            latency_ms = random.randint(50, 300)
            
            reading = SensorReading(
                node=node,
                pm1_0=self._round_2dp(max(0.0, pm1_0)),
                pm2_5=self._round_2dp(max(0.0, pm25)),
                pm10=self._round_2dp(max(0.0, pm10)),
                temperature=self._round_2dp(temperature),
                humidity=self._round_2dp(max(0.0, min(100.0, humidity))),
                pressure=self._round_2dp(pressure),
                gas_resistance=self._round_2dp(max(0.5, gas_resistance)),
                aqi=0,
                aqi_level=None,
                system_status=system_status,
                pms_status=pms_status,
                bme_status=bme_status,
                latency_ms=latency_ms,
                is_anomaly=False,
                timestamp=current_time,
            )
            
            if reading.pm2_5 is not None:
                reading.aqi, reading.aqi_level = calculate_aqi(reading.pm2_5)
            
            readings.append(reading)
            current_time += timedelta(minutes=random.randint(2, 10))
        
        return readings

    def _generate_intermittent_day(self, node, day, baseline, manila_tz):
        """Simulate a day with intermittent readings, gaps, and duplicates."""
        readings = []
        
        current_time = manila_tz.localize(datetime.combine(day, datetime.min.time()))
        end_of_day = manila_tz.localize(
            datetime.combine(day, datetime.max.time().replace(hour=23, minute=59))
        )
        
        while current_time <= end_of_day:
            hour = current_time.hour
            
            # 25% chance of gap (no data for 30-90 minutes)
            if random.random() < 0.25:
                current_time += timedelta(minutes=random.randint(30, 90))
                continue
            
            pm25 = baseline['median'] + random.gauss(0, baseline['median'] * 0.10)
            temperature = self._generate_urban_heated_temp(hour, day, False, {'behavior': 'mixed'})
            humidity = self._generate_chaotic_humidity(hour, temperature, False, {'behavior': 'mixed'})
            
            pm10 = pm25 * random.uniform(1.3, 2.0)
            pm1_0 = pm25 * random.uniform(0.35, 0.55)
            pressure = 1013 + random.gauss(0, 1.5)
            gas_resistance = max(5, 100 - pm25 * 1.5 + random.gauss(0, 5))
            
            system_status = random.choice(['normal', 'degraded', 'degraded'])
            pms_status = 'ok' if random.random() < 0.85 else 'error'
            bme_status = 'ok' if random.random() < 0.80 else 'error'
            
            latency_ms = random.randint(40, 400)
            
            # Generate 1-3 readings at same timestamp (packet retry)
            num_reads = random.choices([1, 2, 3], weights=[70, 20, 10])[0]
            for _ in range(num_reads):
                reading = SensorReading(
                    node=node,
                    pm1_0=self._round_2dp(max(0.0, pm1_0 + random.gauss(0, pm1_0 * 0.02))),
                    pm2_5=self._round_2dp(max(0.0, pm25 + random.gauss(0, pm25 * 0.02))),
                    pm10=self._round_2dp(max(0.0, pm10 + random.gauss(0, pm10 * 0.03))),
                    temperature=self._round_2dp(temperature + random.gauss(0, 0.3)),
                    humidity=self._round_2dp(max(0.0, min(100.0, humidity + random.gauss(0, 1)))),
                    pressure=self._round_2dp(pressure + random.gauss(0, 0.5)),
                    gas_resistance=self._round_2dp(max(0.5, gas_resistance + random.gauss(0, 3))),
                    aqi=0,
                    aqi_level=None,
                    system_status=system_status,
                    pms_status=pms_status,
                    bme_status=bme_status,
                    latency_ms=latency_ms,
                    is_anomaly=False,
                    timestamp=current_time,
                )
                
                if reading.pm2_5 is not None:
                    reading.aqi, reading.aqi_level = calculate_aqi(reading.pm2_5)
                
                readings.append(reading)
            
            current_time += timedelta(minutes=random.randint(3, 12))
        
        return readings

    # ✨ 🧬 NEW FEATURE: NODE PROFILES
    def _get_node_profile(self, node_id):
        """
        Return deterministic but distinct profiles based on node ID.
        
        NODE 3 (Market + Transport Junction):
        - behavior: "transport-dominant chaos"
        - extreme PM2.5 rush spikes
        - PM10 surges from braking dust
        - frequent short-lived pollution bursts (5–20 min)
        - strong evening congestion peak (VERY HIGH)
        - unstable wind clearing effects
        
        NODE 4 (Market + Pedestrian Dense Area):
        - behavior: "human-density pollution volatility"
        - slower PM rise but longer sustained peaks
        - crowd-driven mid-day plateau pollution
        - weaker traffic spikes than Node 3
        - humidity variability higher due to human density
        - occasional "event crowd surges"
        """
        # Deterministic profile based on node ID last digit
        node_id_hash = hash(str(node_id)) % 10
        
        # Nodes 3 and 4 behavior differentiation
        if node_id_hash in [3, 8]:  # Node 3 variant
            return {
                'id': node_id,
                'behavior': 'transport-dominant',
                'name': 'Transport Junction Node',
                'description': 'Traffic inferno intersection sensor',
                'pm25_volatility': 'high',
                'spike_frequency': 'high',
                'spike_decay': 'fast',
                'pm10_ceiling': 4.0,
                'temperature_peak_boost': 1.2,
                'humidity_volatility': 'high',
                'event_types': ['jeepney_convoy', 'truck_cluster', 'roadside_dust']
            }
        elif node_id_hash in [4, 9]:  # Node 4 variant
            return {
                'id': node_id,
                'behavior': 'human-density',
                'name': 'Market Pedestrian Node',
                'description': 'Dense market pedestrian pollution sensor',
                'pm25_volatility': 'medium',
                'spike_frequency': 'low',
                'spike_decay': 'slow',
                'pm10_ceiling': 3.0,
                'temperature_peak_boost': -0.5,
                'humidity_volatility': 'medium',
                'event_types': ['market_crowd', 'festival_surge', 'food_market_steam']
            }
        else:
            # Default: mixed behavior
            return {
                'id': node_id,
                'behavior': 'mixed',
                'name': 'Mixed Zone Node',
                'description': 'General urban pollution sensor',
                'pm25_volatility': 'medium',
                'spike_frequency': 'medium',
                'spike_decay': 'medium',
                'pm10_ceiling': 3.5,
                'temperature_peak_boost': 0.5,
                'humidity_volatility': 'medium',
                'event_types': ['traffic', 'construction', 'weather']
            }

    # ⚡ EVENT SYSTEM (NEW REQUIREMENT)
    def _maybe_generate_event(self, node_profile, event_hour, event_severity):
        """
        Generate independent stochastic events per node.
        
        Events must:
        - NOT trigger at same time across nodes
        - NOT reuse same random seed timing
        - last 5–25 minutes only
        - decay naturally
        """
        behavior_type = node_profile.get('behavior', 'mixed')
        event_types = node_profile.get('event_types', [])
        
        if not event_types:
            return None
        
        # Select a random event type for this node
        event_type = random.choice(event_types)
        
        if behavior_type == 'transport-dominant':
            # NODE 3 Events: Transport-specific
            if event_type == 'jeepney_convoy':
                return {
                    'type': 'jeepney_convoy',
                    'intensity': event_severity,
                    'duration_minutes': random.randint(8, 20),
                    'pm25_multiplier': 1.5 + (event_severity * 0.5),
                    'pm10_multiplier': 3.0 + (event_severity * 0.8),
                    'description': 'Multiple jeepneys in convoy'
                }
            elif event_type == 'truck_cluster':
                return {
                    'type': 'truck_cluster',
                    'intensity': event_severity,
                    'duration_minutes': random.randint(10, 25),
                    'pm25_multiplier': 1.8 + (event_severity * 0.6),
                    'pm10_multiplier': 3.5 + (event_severity * 0.8),
                    'description': 'Heavy truck traffic cluster'
                }
            elif event_type == 'roadside_dust':
                return {
                    'type': 'roadside_dust',
                    'intensity': event_severity,
                    'duration_minutes': random.randint(5, 15),
                    'pm25_multiplier': 1.3 + (event_severity * 0.4),
                    'pm10_multiplier': 3.8 + (event_severity * 0.5),
                    'description': 'Roadside dust burst from vehicles'
                }
        else:  # human-density
            # NODE 4 Events: Crowd and market-specific
            if event_type == 'market_crowd':
                return {
                    'type': 'market_crowd',
                    'intensity': event_severity,
                    'duration_minutes': random.randint(12, 25),
                    'pm25_multiplier': 1.2 + (event_severity * 0.4),
                    'pm10_multiplier': 2.3 + (event_severity * 0.4),
                    'humidity_multiplier': 1.3,
                    'description': 'Market crowd surge'
                }
            elif event_type == 'festival_surge':
                return {
                    'type': 'festival_surge',
                    'intensity': event_severity,
                    'duration_minutes': random.randint(15, 25),
                    'pm25_multiplier': 1.4 + (event_severity * 0.5),
                    'pm10_multiplier': 2.5 + (event_severity * 0.5),
                    'humidity_multiplier': 1.4,
                    'description': 'Festival/holiday crowd surge'
                }
            elif event_type == 'food_market_steam':
                return {
                    'type': 'food_market_steam',
                    'intensity': event_severity,
                    'duration_minutes': random.randint(8, 20),
                    'pm25_multiplier': 1.1 + (event_severity * 0.3),
                    'humidity_multiplier': 1.5 + (event_severity * 0.2),
                    'description': 'Food market steam/cooking surge'
                }
        
        return None

    def _generate_urban_surge_patterns(self, day, day_of_week, is_friday, is_sunday, node_profile):
        """Generate hourly traffic surge patterns specific to urban Manila."""
        profiles = {}
        
        # 🧠 IMPORTANT: REMOVE SYNCHRONIZATION BUG
        # Each node gets independent hourly multiplier jitter (±0.15 random drift per node per hour)
        node_drift_seed = hash(str(node_profile.get('id', 'default'))) % 1000000
        
        for hour in range(24):
            base_multiplier = 1.0
            
            # NODE-SPECIFIC DRIFT: ±0.15 random jitter per node per hour
            node_specific_jitter = random.Random(node_drift_seed + hour).uniform(-0.15, 0.15)
            drift_factor = 1.0 + node_specific_jitter
            
            if 0 <= hour < 5:
                # Very early morning: clean
                multiplier = random.uniform(0.55, 0.75)
            elif 5 <= hour < 6:
                # Predawn preparation
                multiplier = random.uniform(0.65, 0.85)
            elif 6 <= hour < 8:
                # Early morning: first traffic wave starting
                if day_of_week == 0:  # Monday: extra heavy
                    multiplier = random.uniform(1.25, 1.55)
                else:
                    multiplier = random.uniform(1.15, 1.45)
            elif 8 <= hour < 10:
                # Morning rush peak: VERY HEAVY
                if is_friday:
                    multiplier = random.uniform(1.50, 1.85)
                elif day_of_week >= 5:  # Weekend: lighter
                    multiplier = random.uniform(0.95, 1.15)
                else:
                    multiplier = random.uniform(1.40, 1.75)
            elif 10 <= hour < 12:
                # Mid-morning: declining
                if day_of_week >= 5:
                    multiplier = random.uniform(0.85, 1.05)
                else:
                    multiplier = random.uniform(1.05, 1.25)
            elif 12 <= hour < 13:
                # Lunch: school/office lunch time
                multiplier = random.uniform(1.20, 1.45)
            elif 13 <= hour < 16:
                # Afternoon: moderate, slightly declining
                if day_of_week == 6:  # Sunday: clean
                    multiplier = random.uniform(0.80, 0.95)
                else:
                    multiplier = random.uniform(1.0, 1.15)
            elif 16 <= hour < 18:
                # Afternoon into evening: pickup
                multiplier = random.uniform(1.15, 1.35)
            elif 18 <= hour < 20:
                # Evening rush PEAK: ABSOLUTE MAXIMUM
                if is_friday:
                    multiplier = random.uniform(1.65, 2.10)
                elif day_of_week >= 5:
                    multiplier = random.uniform(1.25, 1.55)
                else:
                    multiplier = random.uniform(1.55, 1.95)
            elif 20 <= hour < 22:
                # Night: traffic declining
                multiplier = random.uniform(1.10, 1.35)
            else:
                # Late night: low
                multiplier = random.uniform(0.70, 0.90)
            
            # Apply node-specific drift
            multiplier = multiplier * drift_factor
            # Ensure realistic bounds
            multiplier = max(0.5, min(2.2, multiplier))
            
            profiles[hour] = {'multiplier': multiplier}
        
        return profiles

    def _generate_chaotic_pm25(self, baseline, hour_multiplier, last_pm25, is_rainy, 
                              is_weekend, hour, event_hour, event_severity, node_profile, event_type=None):
        """Generate highly variable PM2.5 with aggressive urban patterns and node-specific behavior."""
        # Base from hour
        base_pm25 = baseline['median'] * hour_multiplier
        
        # 🧬 NODE-SPECIFIC PM2.5 RULES
        behavior_type = node_profile.get('behavior', 'mixed')
        
        if behavior_type == 'transport-dominant':
            # NODE 3: Sharp spikes, higher amplitude (x2.2 rush multipliers), faster decay
            noise_multiplier = 0.14  # Higher volatility
            spike_probability = 0.12  # More frequent spikes
            spike_amplitude = (1.2, 1.9)  # Sharper spikes
        else:  # 'human-density'
            # NODE 4: Smoother rise, longer sustained plateau, slower decay
            noise_multiplier = 0.08  # Lower volatility
            spike_probability = 0.05  # Less frequent spikes
            spike_amplitude = (1.1, 1.5)  # Smaller spike amplitude
        
        # Add aggressive noise (not smoothed)
        noise = random.gauss(0, baseline['median'] * noise_multiplier)
        
        # Random continuity weight (sometimes breaks continuity for realism)
        # NODE 3: Less continuity (more chaotic), NODE 4: More continuity (more stable)
        if behavior_type == 'transport-dominant':
            continuity_weight = random.uniform(0.35, 0.75)  # More breaks = more chaos
        else:
            continuity_weight = random.uniform(0.55, 0.85)  # More continuity = stability
        
        pm25 = last_pm25 * continuity_weight + base_pm25 * (1 - continuity_weight) + noise
        
        # Event surge (node-specific intensity)
        if event_hour is not None and hour == event_hour:
            if behavior_type == 'transport-dominant':
                # NODE 3: Intense burst
                if event_severity == 1:
                    pm25 *= random.uniform(1.4, 1.8)
                else:
                    pm25 *= random.uniform(2.0, 2.8)
            else:
                # NODE 4: Slower, sustained rise
                if event_severity == 1:
                    pm25 *= random.uniform(1.2, 1.4)
                else:
                    pm25 *= random.uniform(1.5, 2.0)
        
        # Random traffic burst spikes (NODE-SPECIFIC)
        if random.random() < spike_probability:
            pm25 *= random.uniform(spike_amplitude[0], spike_amplitude[1])
        
        # Rain cleanup (node-specific recovery)
        if is_rainy:
            if behavior_type == 'transport-dominant':
                # NODE 3: Fast PM drop but rebound spikes after rain
                pm25 *= random.uniform(0.55, 0.80)
            else:
                # NODE 4: Slower cleaning, more stable recovery
                pm25 *= random.uniform(0.70, 0.90)
        
        # Weekend slightly cleaner
        if is_weekend:
            pm25 *= random.uniform(0.85, 0.98)
        
        # Clamp to realistic range
        min_pm = baseline['min'] * 0.8
        max_pm = baseline['max'] * 1.3
        pm25 = max(min_pm, min(max_pm, pm25))
        
        return pm25

    def _generate_pm10_multiplier(self, hour, event_hour, event_severity, node_profile, event_type=None):
        """Generate PM10 multiplier that can spike independently from PM2.5 with node-specific rules."""
        behavior_type = node_profile.get('behavior', 'mixed')
        
        # 🧬 NODE-SPECIFIC PM10 RULES
        if behavior_type == 'transport-dominant':
            # NODE 3: PM10 can spike up to 4.0x PM2.5 during traffic bursts
            base_multiplier = random.uniform(1.6, 2.2)  # Higher baseline
        else:
            # NODE 4: PM10 limited to 2.5–3.0x PM2.5, more stable dust baseline
            base_multiplier = random.uniform(1.4, 1.7)  # Lower, more stable baseline
        
        # Rush hours: more dust from vehicle turbulence
        if hour in [7, 8, 9, 18, 19, 20]:
            if behavior_type == 'transport-dominant':
                base_multiplier *= random.uniform(1.2, 1.5)  # More dramatic spikes
            else:
                base_multiplier *= random.uniform(1.05, 1.15)  # Smaller adjustment
        
        # Event can cause dust surge (node-specific)
        if event_hour is not None and hour == event_hour:
            if behavior_type == 'transport-dominant':
                # NODE 3: Intense dust event
                if event_severity == 1:
                    base_multiplier *= random.uniform(1.5, 2.0)
                else:
                    base_multiplier *= random.uniform(3.0, 4.0)  # Up to 4.0x
            else:
                # NODE 4: More moderate dust response
                if event_severity == 1:
                    base_multiplier *= random.uniform(1.2, 1.4)
                else:
                    base_multiplier *= random.uniform(1.8, 2.5)  # Up to 2.5x
        
        # Random dust events (jeepney, truck, construction nearby)
        # NODE 3: More frequent dust events
        if behavior_type == 'transport-dominant':
            if random.random() < 0.15:  # More frequent
                base_multiplier *= random.uniform(1.6, 2.3)
        else:
            if random.random() < 0.08:  # Less frequent
                base_multiplier *= random.uniform(1.3, 1.8)
        
        # Clamp to node-specific limits
        if behavior_type == 'transport-dominant':
            base_multiplier = max(1.5, min(4.0, base_multiplier))  # Up to 4.0x
        else:
            base_multiplier = max(1.3, min(3.0, base_multiplier))  # Up to 3.0x
        
        return base_multiplier

    def _generate_urban_heated_temp(self, hour, day, is_rainy, node_profile):
        """Generate temperature with urban heat island effect and node-specific behavior."""
        month = day.month
        behavior_type = node_profile.get('behavior', 'mixed')
        
        # Urban Manila: hotter baseline
        if month == 3:
            base_temp = 27.5
            peak_temp = 32.5
        elif month == 4:
            base_temp = 28.5
            peak_temp = 34.5
        else:
            base_temp = 29.5
            peak_temp = 36.5
        
        if is_rainy:
            base_temp -= 2
            peak_temp -= 1.5
        
        # 🧬 NODE-SPECIFIC TEMPERATURE BEHAVIOR
        if behavior_type == 'transport-dominant':
            # NODE 3: Hotter midday spikes due to vehicle clustering
            if 1 <= hour < 5:
                temp = base_temp - 2 + random.gauss(0, 1.0)
            elif 5 <= hour < 7:
                temp = base_temp - 2 + (hour - 5) / 2 + random.gauss(0, 0.6)
            elif 7 <= hour < 12:
                progress = (hour - 7) / 5
                temp = base_temp + (peak_temp - base_temp) * 0.8 * progress + random.gauss(0, 0.8)
            elif 12 <= hour < 15:
                # EXTRA HOT: vehicle clustering effect
                temp = peak_temp + random.uniform(1.0, 2.5) + random.gauss(0, 1.2)
            elif 15 <= hour < 19:
                progress = (hour - 15) / 4
                temp = peak_temp - (peak_temp - base_temp) * 0.6 * progress + random.gauss(0, 0.8)
            elif 19 <= hour < 23:
                progress = (hour - 19) / 4
                temp = base_temp + 1.2 - (peak_temp - base_temp) * 0.35 * progress + random.gauss(0, 0.8)
            else:
                temp = base_temp + 0.8 + random.gauss(0, 0.7)
        else:
            # NODE 4: More stable heat curve (human shading + density dampening)
            if 1 <= hour < 5:
                temp = base_temp - 1.8 + random.gauss(0, 0.6)
            elif 5 <= hour < 7:
                temp = base_temp - 1.8 + (hour - 5) / 2.2 + random.gauss(0, 0.4)
            elif 7 <= hour < 12:
                progress = (hour - 7) / 5
                temp = base_temp + (peak_temp - base_temp) * 0.65 * progress + random.gauss(0, 0.5)
            elif 12 <= hour < 15:
                # Moderate heat: human shading effect
                temp = peak_temp - random.uniform(0.5, 1.5) + random.gauss(0, 0.7)
            elif 15 <= hour < 19:
                progress = (hour - 15) / 4
                temp = peak_temp - (peak_temp - base_temp) * 0.45 * progress + random.gauss(0, 0.5)
            elif 19 <= hour < 23:
                progress = (hour - 19) / 4
                temp = base_temp + 0.8 - (peak_temp - base_temp) * 0.25 * progress + random.gauss(0, 0.5)
            else:
                temp = base_temp + 0.5 + random.gauss(0, 0.5)
        
        return max(25.0, min(38.0, temp))

    def _generate_chaotic_humidity(self, hour, temperature, is_rainy, node_profile):
        """Generate humidity with more realism and node-specific behavior."""
        behavior_type = node_profile.get('behavior', 'mixed')
        
        if is_rainy:
            base_humidity = 85 + random.gauss(0, 3)
        elif 1 <= hour < 6:
            # High at night
            base_humidity = 80 + random.gauss(0, 3)
        elif 6 <= hour < 11:
            # Decreasing with heat
            base_humidity = 70 + random.gauss(0, 3)
        elif 11 <= hour < 15:
            # Low at peak heat
            base_humidity = 50 + random.gauss(0, 4)
        elif 15 <= hour < 19:
            # Rising as it cools
            base_humidity = 60 + random.gauss(0, 3)
        else:
            # Evening/night: rising
            base_humidity = 72 + random.gauss(0, 3)
        
        # 🧬 NODE-SPECIFIC HUMIDITY BEHAVIOR
        if behavior_type == 'transport-dominant':
            # NODE 3: More volatile (wind + exhaust mixing)
            base_humidity += random.gauss(0, 3.5)
        else:
            # NODE 4: Smoother, slightly higher baseline humidity (human density + market steam)
            base_humidity += random.gauss(0, 1.5)
            base_humidity += random.uniform(1.0, 2.5)  # Slightly higher baseline
        
        return max(40.0, min(95.0, base_humidity))

    def _generate_pressure_variation(self, hour):
        """Generate pressure with realistic variations."""
        # Daily pressure variation
        if 1 <= hour < 9:
            base_pressure = 1012.5 + random.gauss(0, 0.8)
        elif 9 <= hour < 15:
            base_pressure = 1013.0 + random.gauss(0, 1.0)
        else:
            base_pressure = 1012.8 + random.gauss(0, 0.9)
        
        return max(1004.0, min(1016.0, base_pressure))

    def _generate_gas_resistance(self, pm25, pm10):
        """Generate gas resistance inversely correlated with pollution."""
        # Strong inverse relationship with PM
        combined_pollution = pm25 * 0.7 + pm10 * 0.3
        base_resistance = 120 - (combined_pollution * 2.0)
        
        # Add noise
        gas = base_resistance + random.gauss(0, 5)
        
        return max(0.5, gas)

    def _generate_chaotic_health(self, is_prototyping, event_hour, hour):
        """Generate system health with chaos during prototyping."""
        if is_prototyping:
            # Much worse during prototyping
            pms_ok = random.random() < 0.85
            bme_ok = random.random() < 0.82
            
            # Worse during event
            if event_hour is not None and hour == event_hour:
                pms_ok = pms_ok and random.random() < 0.7
                bme_ok = bme_ok and random.random() < 0.7
        else:
            # Stable phase: mostly good
            pms_ok = random.random() < 0.97
            bme_ok = random.random() < 0.96
        
        pms_status = 'ok' if pms_ok else 'error'
        bme_status = 'ok' if bme_ok else 'error'
        
        if pms_ok and bme_ok:
            system_status = 'normal'
        elif pms_ok or bme_ok:
            system_status = 'degraded'
        else:
            system_status = 'critical'
        
        # Critical very rare
        if random.random() < 0.0005:
            system_status = 'critical'
        
        return system_status, pms_status, bme_status

    def _generate_urban_latency(self, system_status, is_prototyping, hour):
        """Generate latency with traffic-induced congestion."""
        if is_prototyping:
            base_latency = random.randint(80, 350)
        else:
            base_latency = random.randint(20, 150)
        
        # Rush hours: more congestion
        if hour in [7, 8, 9, 18, 19, 20]:
            base_latency *= random.uniform(1.3, 1.8)
        
        # Degraded system: higher latency
        if system_status == 'degraded':
            base_latency *= random.uniform(1.2, 1.5)
        elif system_status == 'critical':
            base_latency *= random.uniform(1.5, 2.5)
        
        return int(min(500, max(15, base_latency)))

    def _round_2dp(self, value):
        """Round to 2 decimal places."""
        return round(float(value), 2)

    @transaction.atomic
    def _insert_readings_batch(self, readings, batch_size=5000):
        """Insert readings in batches for performance."""
        total = len(readings)
        for i in range(0, total, batch_size):
            batch = readings[i:i + batch_size]
            SensorReading.objects.bulk_create(batch, batch_size=batch_size)
            progress = f"  [OK] Inserted {min(i + batch_size, total)}/{total} readings"
            self.stdout.write(progress)

    def _print_summary_stats(self, readings):
        """Print summary statistics with NODE PERSONALITY VALIDATION."""
        if not readings:
            self.stdout.write(self.style.WARNING('No readings generated'))
            return
        
        pm25_values = [r.pm2_5 for r in readings if r.pm2_5 is not None]
        pm10_values = [r.pm10 for r in readings if r.pm10 is not None]
        temps = [r.temperature for r in readings if r.temperature is not None]
        humidities = [r.humidity for r in readings if r.humidity is not None]
        
        if pm25_values:
            self.stdout.write(self.style.SUCCESS('\n' + '=' * 70))
            self.stdout.write(self.style.SUCCESS('SUMMARY STATISTICS & NODE PERSONALITY VALIDATION'))
            self.stdout.write(self.style.SUCCESS('=' * 70 + '\n'))
            
            self.stdout.write(f'Total readings inserted:    {len(readings):,}')
            self.stdout.write(f'Date range:                 {readings[0].timestamp.date()} to {readings[-1].timestamp.date()}')
            
            # Calculate average interval
            if len(readings) > 1:
                intervals = []
                for i in range(1, min(100, len(readings))):
                    delta = (readings[i].timestamp - readings[i-1].timestamp).total_seconds() / 60
                    intervals.append(delta)
                avg_interval = sum(intervals) / len(intervals) if intervals else 0
                self.stdout.write(f'Average posting interval:   {avg_interval:.1f} minutes')
            
            # Count status conditions
            degraded_count = sum(1 for r in readings if r.system_status == 'degraded')
            critical_count = sum(1 for r in readings if r.system_status == 'critical')
            error_count = sum(1 for r in readings if r.pms_status == 'error' or r.bme_status == 'error')
            
            self.stdout.write(f'\nDegraded events:            {degraded_count} ({degraded_count*100//len(readings)}%)')
            self.stdout.write(f'Critical events:            {critical_count} ({critical_count*100//len(readings)}%)')
            self.stdout.write(f'Sensor error events:        {error_count} ({error_count*100//len(readings)}%)')
            
            self.stdout.write(f'\n' + '-' * 70)
            self.stdout.write(f'PM2.5 STATISTICS:')
            self.stdout.write(f'-' * 70)
            self.stdout.write(f'  Min:  {min(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  Max:  {max(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  Mean: {sum(pm25_values)/len(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  StdDev (Volatility Index): {self._stddev(pm25_values):.2f}')
            
            # Calculate spike frequency
            spike_count = sum(1 for i in range(1, len(pm25_values)) 
                            if pm25_values[i] > pm25_values[i-1] * 1.3)
            spike_frequency = (spike_count / len(pm25_values)) * 100
            self.stdout.write(f'  Spike Frequency (30% jumps): {spike_frequency:.1f}%')
            
            # PM10 analysis
            if pm10_values:
                self.stdout.write(f'\n' + '-' * 70)
                self.stdout.write(f'PM10 STATISTICS:')
                self.stdout.write(f'-' * 70)
                self.stdout.write(f'  Min:  {min(pm10_values):.2f} µg/m³')
                self.stdout.write(f'  Max:  {max(pm10_values):.2f} µg/m³')
                self.stdout.write(f'  Mean: {sum(pm10_values)/len(pm10_values):.2f} µg/m³')
                
                # PM10/PM2.5 ratio analysis
                ratios = [pm10_values[i] / pm25_values[i] for i in range(len(pm25_values)) if pm25_values[i] > 0]
                if ratios:
                    self.stdout.write(f'  Avg PM10/PM2.5 Ratio: {sum(ratios)/len(ratios):.2f}')
                    self.stdout.write(f'  Max Ratio (dust events): {max(ratios):.2f}x')
            
            self.stdout.write(f'\n' + '-' * 70)
            self.stdout.write(f'TEMPERATURE & HUMIDITY:')
            self.stdout.write(f'-' * 70)
            self.stdout.write(f'Temperature range: {min(temps):.1f}°C - {max(temps):.1f}°C')
            if humidities:
                self.stdout.write(f'Humidity range: {min(humidities):.1f}% - {max(humidities):.1f}%')
            
            self.stdout.write(f'\n' + '-' * 70)
            self.stdout.write(f'DATA INTEGRITY VALIDATION:')
            self.stdout.write(f'-' * 70)
            
            # Check PM hierarchy
            pm_hierarchy_valid = True
            invalid_count = 0
            for i in range(len(pm25_values)):
                if not (pm25_values[i] <= pm10_values[i]):
                    pm_hierarchy_valid = False
                    invalid_count += 1
            
            if pm_hierarchy_valid:
                self.stdout.write(f'✓ PM1.0 <= PM2.5 <= PM10 ratio maintained: [OK]')
            else:
                self.stdout.write(f'✗ PM hierarchy violations: {invalid_count} ({invalid_count*100//len(pm25_values)}%)')
            
            # Check no identical consecutive PM patterns
            identical_count = 0
            for i in range(1, len(pm25_values)):
                if pm25_values[i] == pm25_values[i-1]:
                    identical_count += 1
            
            if identical_count < len(pm25_values) * 0.02:
                self.stdout.write(f'✓ No excessive identical PM readings: [OK] ({identical_count} duplicates)')
            else:
                self.stdout.write(f'⚠ High duplicate rate: {identical_count} ({identical_count*100//len(pm25_values)}%)')
            
            self.stdout.write(f'\n' + '=' * 70)
            self.stdout.write(self.style.SUCCESS('[SUCCESS] Data generation complete with personality differentiation!\n'))

    def _stddev(self, values):
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
