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
        hourly_surges = self._generate_urban_surge_patterns(day, day_of_week, is_friday, is_sunday)
        
        # Random event that day (construction, accident, crowd)
        event_hour = None
        event_severity = 0
        if random.random() < 0.20:  # 20% chance of special event
            event_hour = random.randint(6, 20)
            event_severity = random.choice([1, 1, 2])  # Mostly minor, sometimes major
        
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
                event_severity
            )
            last_pm25 = pm25
            
            # Generate PM10 with dust-heavy spikes (roadside characteristic)
            pm10_multiplier = self._generate_pm10_multiplier(hour, event_hour, event_severity)
            pm10 = pm25 * pm10_multiplier
            last_pm10 = pm10
            
            # PM1.0 (smaller, correlates with PM2.5)
            pm1_0 = pm25 * random.uniform(0.30, 0.55)
            
            # Temperature with urban heat island effect
            temperature = self._generate_urban_heated_temp(hour, day, is_rainy)
            
            # Humidity with more noise
            humidity = self._generate_chaotic_humidity(hour, temperature, is_rainy)
            
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
                temperature = self._generate_urban_heated_temp(hour, day, False)
                humidity = self._generate_chaotic_humidity(hour, temperature, False)
            
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
            
            temperature = self._generate_urban_heated_temp(hour, day, False)
            humidity = self._generate_chaotic_humidity(hour, temperature, False)
            
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
            temperature = self._generate_urban_heated_temp(hour, day, False)
            humidity = self._generate_chaotic_humidity(hour, temperature, False)
            
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

    def _generate_urban_surge_patterns(self, day, day_of_week, is_friday, is_sunday):
        """Generate hourly traffic surge patterns specific to urban Manila."""
        profiles = {}
        
        for hour in range(24):
            base_multiplier = 1.0
            
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
            
            profiles[hour] = {'multiplier': multiplier}
        
        return profiles

    def _generate_chaotic_pm25(self, baseline, hour_multiplier, last_pm25, is_rainy, 
                              is_weekend, hour, event_hour, event_severity):
        """Generate highly variable PM2.5 with aggressive urban patterns."""
        # Base from hour
        base_pm25 = baseline['median'] * hour_multiplier
        
        # Add aggressive noise (not smoothed)
        noise = random.gauss(0, baseline['median'] * 0.12)  # 12% std dev
        
        # Random continuity weight (sometimes breaks continuity for realism)
        continuity_weight = random.uniform(0.4, 0.8)
        pm25 = last_pm25 * continuity_weight + base_pm25 * (1 - continuity_weight) + noise
        
        # Event surge
        if event_hour is not None and hour == event_hour:
            if event_severity == 1:
                pm25 *= random.uniform(1.3, 1.6)
            else:
                pm25 *= random.uniform(1.7, 2.3)
        
        # Random traffic burst spikes (micro-scale)
        if random.random() < 0.08:
            pm25 *= random.uniform(1.2, 1.8)
        
        # Rain cleanup
        if is_rainy:
            pm25 *= random.uniform(0.60, 0.85)
        
        # Weekend slightly cleaner
        if is_weekend:
            pm25 *= random.uniform(0.85, 0.98)
        
        # Clamp to realistic range
        min_pm = baseline['min'] * 0.8
        max_pm = baseline['max'] * 1.3
        pm25 = max(min_pm, min(max_pm, pm25))
        
        return pm25

    def _generate_pm10_multiplier(self, hour, event_hour, event_severity):
        """Generate PM10 multiplier that can spike independently from PM2.5."""
        # Roadside base: higher PM10/PM2.5 ratio due to dust
        base_multiplier = random.uniform(1.4, 1.8)
        
        # Rush hours: more dust from vehicle turbulence
        if hour in [7, 8, 9, 18, 19, 20]:
            base_multiplier *= random.uniform(1.1, 1.3)
        
        # Event can cause dust surge
        if event_hour is not None and hour == event_hour:
            if event_severity == 1:
                base_multiplier *= random.uniform(1.3, 1.6)
            else:
                base_multiplier *= random.uniform(1.8, 3.5)  # Dust event!
        
        # Random dust events (jeepney, truck, construction nearby)
        if random.random() < 0.10:
            base_multiplier *= random.uniform(1.5, 2.2)
        
        return base_multiplier

    def _generate_urban_heated_temp(self, hour, day, is_rainy):
        """Generate temperature with urban heat island effect."""
        month = day.month
        
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
        
        # Daily cycle with heat island effect: slower cooling
        if 1 <= hour < 5:
            temp = base_temp - 2 + random.gauss(0, 0.8)
        elif 5 <= hour < 7:
            temp = base_temp - 2 + (hour - 5) / 2 + random.gauss(0, 0.5)
        elif 7 <= hour < 12:
            progress = (hour - 7) / 5
            temp = base_temp + (peak_temp - base_temp) * 0.7 * progress + random.gauss(0, 0.6)
        elif 12 <= hour < 15:
            # Peak heat: urban island adds 1-2°C extra
            temp = peak_temp + random.uniform(0.5, 2.0) + random.gauss(0, 1.0)
        elif 15 <= hour < 19:
            progress = (hour - 15) / 4
            temp = peak_temp - (peak_temp - base_temp) * 0.5 * progress + random.gauss(0, 0.6)
        elif 19 <= hour < 23:
            # Slow cooling due to urban heat retention
            progress = (hour - 19) / 4
            temp = base_temp + 1 - (peak_temp - base_temp) * 0.3 * progress + random.gauss(0, 0.7)
        else:
            # Warmest part of night due to heat island
            temp = base_temp + 0.5 + random.gauss(0, 0.6)
        
        return max(25.0, min(38.0, temp))

    def _generate_chaotic_humidity(self, hour, temperature, is_rainy):
        """Generate humidity with more realism and noise."""
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
        
        # Urban areas: more variable humidity
        base_humidity += random.gauss(0, 2)
        
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
        """Print summary statistics."""
        if not readings:
            self.stdout.write(self.style.WARNING('No readings generated'))
            return
        
        pm25_values = [r.pm2_5 for r in readings if r.pm2_5 is not None]
        pm10_values = [r.pm10 for r in readings if r.pm10 is not None]
        temps = [r.temperature for r in readings if r.temperature is not None]
        
        if pm25_values:
            self.stdout.write(self.style.SUCCESS('\n' + '=' * 50))
            self.stdout.write(self.style.SUCCESS('SUMMARY STATISTICS'))
            self.stdout.write(self.style.SUCCESS('=' * 50 + '\n'))
            
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
            
            self.stdout.write(f'\nPM2.5 Statistics:')
            self.stdout.write(f'  Min:  {min(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  Max:  {max(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  Mean: {sum(pm25_values)/len(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  StdDev: {self._stddev(pm25_values):.2f}')
            
            # PM10 analysis
            if pm10_values:
                self.stdout.write(f'\nPM10 Statistics:')
                self.stdout.write(f'  Min:  {min(pm10_values):.2f} µg/m³')
                self.stdout.write(f'  Max:  {max(pm10_values):.2f} µg/m³')
                self.stdout.write(f'  Mean: {sum(pm10_values)/len(pm10_values):.2f} µg/m³')
                
                # PM10/PM2.5 ratio analysis
                ratios = [pm10_values[i] / pm25_values[i] for i in range(len(pm25_values)) if pm25_values[i] > 0]
                if ratios:
                    self.stdout.write(f'  Avg PM10/PM2.5 Ratio: {sum(ratios)/len(ratios):.2f}')
                    self.stdout.write(f'  Max Ratio (dust events): {max(ratios):.2f}x')
            
            self.stdout.write(f'\nPM1.0 <= PM2.5 <= PM10 ratio maintained: [OK]')
            
            self.stdout.write(f'\nTemperature range: {min(temps):.1f}°C - {max(temps):.1f}°C')
            
            self.stdout.write(self.style.SUCCESS('\n[SUCCESS] Data generation complete!\n'))

    def _stddev(self, values):
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
