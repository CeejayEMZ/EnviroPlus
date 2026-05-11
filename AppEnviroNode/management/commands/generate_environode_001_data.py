"""
Management command to generate highly realistic historical sensor data for ENVIRONODE_001.

DATE RANGE: March 31, 2026 - May 11, 2026
TIMEZONE: Asia/Manila (UTC+8)
MAC ADDRESS: ENVIRONODE_001

PHASES:
- Prototyping (Mar 31 - Apr 14): Unstable, inconsistent data
- Stable (Apr 15 - May 11): Mostly stable operation

USAGE:
    python manage.py generate_environode_001_data [--dry-run] [--delete-existing]
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
    help = 'Generate highly realistic historical sensor data for ENVIRONODE_001'

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
        '2026-05-11': {'median': 11.0, 'q1': 7.0, 'q3': 15.5, 'min': 2.5, 'max': 23.0},  # Interpolated
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
            help='Delete existing ENVIRONODE_001 data before generation'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 45))
        self.stdout.write(self.style.SUCCESS('ENVIRONODE_001 Historical Data Generator'))
        self.stdout.write(self.style.SUCCESS('Phase 1: Prototyping (Mar 31 - Apr 14)'))
        self.stdout.write(self.style.SUCCESS('Phase 2: Stable (Apr 15 - May 11)'))
        self.stdout.write(self.style.SUCCESS('=' * 45 + '\n'))

        # Get or create node
        node, created = SensorNode.objects.get_or_create(
            mac_address='ENVIRONODE_001',
            defaults={
                'name': 'Pateros Bridge - Primary Monitor',
                'location': 'Pateros Bridge, Manila, Philippines',
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
            phase_name = "PROTOTYPING" if is_prototyping else "STABLE"

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
        """Generate readings for a single day with realistic patterns."""
        readings = []
        
        # Decide daily behavior
        is_rainy = random.random() < (0.15 if not is_prototyping else 0.10)
        is_weekend = day.weekday() >= 5  # Saturday/Sunday
        is_school_day = not is_weekend
        
        # Prototyping phase: simulate outages, degradations
        if is_prototyping:
            outage_probability = random.random()
            if outage_probability < 0.20:  # 20% chance of partial outage
                return self._generate_degraded_day(node, day, baseline, manila_tz)
            elif outage_probability < 0.35:  # 15% chance of missing periods
                return self._generate_partial_day(node, day, baseline, manila_tz)
        
        # Generate hourly patterns
        hourly_profiles = self._generate_hourly_profiles(day, is_prototyping, is_rainy, is_school_day)
        
        # Start time: random between 00:00 and 02:00
        current_time = manila_tz.localize(
            datetime.combine(day, datetime.min.time())
        ) + timedelta(minutes=random.randint(0, 120))
        
        end_of_day = manila_tz.localize(
            datetime.combine(day, datetime.max.time().replace(hour=23, minute=59))
        )
        
        last_pm25 = baseline['median']
        
        while current_time <= end_of_day:
            hour = current_time.hour
            hour_profile = hourly_profiles.get(hour, {})
            
            # Generate PM2.5 with realistic variation
            pm25 = self._generate_pm25(
                baseline, hour_profile, last_pm25, is_rainy, is_weekend
            )
            last_pm25 = pm25
            
            # Generate correlated sensor readings
            pm1_0 = pm25 * random.uniform(0.35, 0.65)
            pm10 = pm25 * random.uniform(1.25, 1.75)
            
            # Temperature (hour-based with seasonal variation)
            temperature = self._generate_temperature(hour, day)
            
            # Humidity (inverse to temperature, higher at night)
            humidity = self._generate_humidity(hour, temperature, is_rainy)
            
            # Pressure (slow variations)
            pressure = self._generate_pressure(hour, day)
            
            # Gas resistance (inverse to pollution)
            gas_resistance = self._generate_gas_resistance(pm25)
            
            # System status
            system_status, pms_status, bme_status = self._generate_health_status(
                is_prototyping
            )
            
            # Latency
            latency_ms = self._generate_latency(system_status)
            
            reading = SensorReading(
                node=node,
                pm1_0=self._round_2dp(max(0.0, pm1_0)),
                pm2_5=self._round_2dp(max(0.0, pm25)),
                pm10=self._round_2dp(max(0.0, pm10)),
                temperature=self._round_2dp(temperature),
                humidity=self._round_2dp(max(0.0, min(100.0, humidity))),
                pressure=self._round_2dp(pressure),
                gas_resistance=self._round_2dp(max(1.0, gas_resistance)),
                aqi=0,  # Will be calculated before insertion
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
            
            # Random interval: 2-10 minutes
            interval = random.randint(2, 10)
            current_time += timedelta(minutes=interval)
        
        return readings

    def _generate_degraded_day(self, node, day, baseline, manila_tz):
        """Simulate a day with sensor outages/errors."""
        readings = []
        
        # Pick 1-3 outage windows
        num_outages = random.randint(1, 3)
        outage_windows = []
        for _ in range(num_outages):
            start_hour = random.randint(0, 20)
            duration_hours = random.randint(1, 4)
            outage_windows.append((start_hour, start_hour + duration_hours))
        
        current_time = manila_tz.localize(
            datetime.combine(day, datetime.min.time())
        ) + timedelta(minutes=random.randint(0, 60))
        
        end_of_day = manila_tz.localize(
            datetime.combine(day, datetime.max.time().replace(hour=23, minute=59))
        )
        
        while current_time <= end_of_day:
            hour = current_time.hour
            
            # Check if in outage window
            in_outage = any(start <= hour < end for start, end in outage_windows)
            
            if in_outage:
                # Skip 2-3 hours during outage
                minutes_to_skip = random.randint(120, 180)
                current_time += timedelta(minutes=minutes_to_skip)
                continue
            
            # Generate normal reading
            pm25 = baseline['median'] + random.gauss(0, baseline['median'] * 0.08)
            pm1_0 = pm25 * random.uniform(0.4, 0.6)
            pm10 = pm25 * random.uniform(1.3, 1.6)
            temperature = self._generate_temperature(hour, day)
            humidity = self._generate_humidity(hour, temperature, False)
            pressure = self._generate_pressure(hour, day)
            gas_resistance = self._generate_gas_resistance(pm25)
            
            # Higher chance of errors on degraded days
            system_status, pms_status, bme_status = self._generate_health_status(True)
            latency_ms = self._generate_latency(system_status)
            
            reading = SensorReading(
                node=node,
                pm1_0=self._round_2dp(max(0.0, pm1_0)),
                pm2_5=self._round_2dp(max(0.0, pm25)),
                pm10=self._round_2dp(max(0.0, pm10)),
                temperature=self._round_2dp(temperature),
                humidity=self._round_2dp(max(0.0, min(100.0, humidity))),
                pressure=self._round_2dp(pressure),
                gas_resistance=self._round_2dp(max(1.0, gas_resistance)),
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

    def _generate_partial_day(self, node, day, baseline, manila_tz):
        """Simulate a day with missing half-days or incomplete data."""
        readings = []
        
        # Pick a time when data "stops"
        stop_hour = random.randint(6, 18)
        
        current_time = manila_tz.localize(
            datetime.combine(day, datetime.min.time())
        )
        
        while current_time.hour < stop_hour:
            hour = current_time.hour
            pm25 = baseline['median'] + random.gauss(0, baseline['median'] * 0.08)
            pm1_0 = pm25 * random.uniform(0.4, 0.6)
            pm10 = pm25 * random.uniform(1.3, 1.6)
            temperature = self._generate_temperature(hour, day)
            humidity = self._generate_humidity(hour, temperature, False)
            pressure = self._generate_pressure(hour, day)
            gas_resistance = self._generate_gas_resistance(pm25)
            
            system_status, pms_status, bme_status = self._generate_health_status(True)
            latency_ms = self._generate_latency(system_status)
            
            reading = SensorReading(
                node=node,
                pm1_0=self._round_2dp(max(0.0, pm1_0)),
                pm2_5=self._round_2dp(max(0.0, pm25)),
                pm10=self._round_2dp(max(0.0, pm10)),
                temperature=self._round_2dp(temperature),
                humidity=self._round_2dp(max(0.0, min(100.0, humidity))),
                pressure=self._round_2dp(pressure),
                gas_resistance=self._round_2dp(max(1.0, gas_resistance)),
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

    def _generate_hourly_profiles(self, day, is_prototyping, is_rainy, is_school_day):
        """Generate pollution multipliers for each hour."""
        profiles = {}
        
        for hour in range(24):
            if is_rainy:
                # Rain cleanup: lower pollution
                multiplier = random.uniform(0.60, 0.85)
            elif 1 <= hour < 5:
                # Dead hours: very low
                multiplier = random.uniform(0.65, 0.80)
            elif 5 <= hour < 7:
                # Early morning: starts increasing
                multiplier = random.uniform(0.75, 0.90)
            elif 7 <= hour < 9:
                # Morning rush: spike
                if is_school_day:
                    multiplier = random.uniform(1.15, 1.35)
                else:
                    multiplier = random.uniform(1.0, 1.15)
            elif 9 <= hour < 11:
                # Mid-morning: stabilize
                multiplier = random.uniform(0.95, 1.10)
            elif 11 <= hour < 13:
                # Lunch/midday: second peak (lighter than morning)
                multiplier = random.uniform(1.05, 1.25)
            elif 13 <= hour < 16:
                # Afternoon: gradual decline
                multiplier = random.uniform(0.95, 1.10)
            elif 16 <= hour < 19:
                # Evening rush: peak
                if is_school_day:
                    multiplier = random.uniform(1.20, 1.45)
                else:
                    multiplier = random.uniform(1.05, 1.25)
            elif 19 <= hour < 22:
                # Night: decline
                multiplier = random.uniform(0.90, 1.05)
            else:
                # Late night: low
                multiplier = random.uniform(0.70, 0.85)
            
            profiles[hour] = {'multiplier': multiplier}
        
        return profiles

    def _generate_pm25(self, baseline, hour_profile, last_pm25, is_rainy, is_weekend):
        """Generate PM2.5 with realistic continuity."""
        multiplier = hour_profile.get('multiplier', 1.0)
        
        # Base value from baseline
        base_pm25 = baseline['median'] * multiplier
        
        # Small random walk for realism
        delta = random.gauss(0, baseline['median'] * 0.05)
        pm25 = last_pm25 * 0.7 + base_pm25 * 0.3 + delta
        
        # Clamp to day's range
        min_pm = baseline['min']
        max_pm = baseline['max']
        if is_rainy:
            max_pm *= 0.75  # Rain reduces peak pollution
        
        pm25 = max(min_pm, min(max_pm, pm25))
        
        return pm25

    def _generate_temperature(self, hour, day):
        """Generate realistic temperature based on time and season."""
        month = day.month
        
        if month == 3:  # March: cooler
            base_temp = 26.0
            peak_temp = 31.0
        elif month == 4:  # April: warm
            base_temp = 27.0
            peak_temp = 33.0
        else:  # May: hottest
            base_temp = 28.0
            peak_temp = 35.0
        
        # Daily cycle
        if 1 <= hour < 6:
            temp = base_temp + random.gauss(0, 0.5)
        elif 6 <= hour < 11:
            # Warming up
            progress = (hour - 6) / 5
            temp = base_temp + (peak_temp - base_temp) * 0.6 * progress + random.gauss(0, 0.5)
        elif 11 <= hour < 15:
            # Peak heat
            temp = peak_temp + random.gauss(0, 1.0)
        elif 15 <= hour < 19:
            # Cooling down
            progress = (hour - 15) / 4
            temp = peak_temp - (peak_temp - base_temp) * 0.4 * progress + random.gauss(0, 0.5)
        else:
            # Evening/night
            temp = base_temp + random.gauss(0, 0.8)
        
        return max(25.0, min(38.0, temp))

    def _generate_humidity(self, hour, temperature, is_rainy):
        """Generate realistic humidity."""
        base_humidity = 70.0
        
        if is_rainy:
            base_humidity = 85.0 + random.gauss(0, 3)
        elif 1 <= hour < 6:
            # High at night
            base_humidity = 80.0 + random.gauss(0, 3)
        elif 6 <= hour < 12:
            # Decreasing in morning
            base_humidity = 70.0 + random.gauss(0, 3)
        elif 12 <= hour < 16:
            # Lowest around peak heat
            base_humidity = 55.0 + random.gauss(0, 3)
        else:
            # Increasing in evening
            base_humidity = 65.0 + random.gauss(0, 3)
        
        return max(45.0, min(90.0, base_humidity))

    def _generate_pressure(self, hour, day):
        """Generate realistic atmospheric pressure."""
        # Slow variations around standard pressure
        base_pressure = 1013.0 + random.gauss(0, 1)
        
        # Slight daily variation
        if 1 <= hour < 9:
            pressure = base_pressure - 1.0 + random.gauss(0, 0.5)
        elif 9 <= hour < 15:
            pressure = base_pressure + random.gauss(0, 0.5)
        else:
            pressure = base_pressure - 0.5 + random.gauss(0, 0.5)
        
        return max(1004.0, min(1014.0, pressure))

    def _generate_gas_resistance(self, pm25):
        """Generate gas resistance (inverse relationship with pollution)."""
        # Higher PM2.5 = lower gas resistance
        base_resistance = 100.0 - (pm25 * 1.5)
        gas = base_resistance + random.gauss(0, 5)
        return max(10.0, gas)

    def _generate_health_status(self, is_prototyping):
        """Generate system, PMS, and BME status."""
        if is_prototyping:
            # Higher error rates during prototyping
            pms_ok = random.random() < 0.92
            bme_ok = random.random() < 0.90
        else:
            # Stable phase: mostly ok
            pms_ok = random.random() < 0.98
            bme_ok = random.random() < 0.97
        
        pms_status = 'ok' if pms_ok else 'error'
        bme_status = 'ok' if bme_ok else 'error'
        
        if pms_ok and bme_ok:
            system_status = 'normal'
        elif pms_ok or bme_ok:
            system_status = 'degraded'
        else:
            system_status = 'critical'
        
        # Critical is VERY rare
        if random.random() < 0.001:
            system_status = 'critical'
        
        return system_status, pms_status, bme_status

    def _generate_latency(self, system_status):
        """Generate HTTP request latency."""
        if system_status == 'normal':
            return random.randint(20, 150)
        elif system_status == 'degraded':
            return random.randint(50, 350)
        else:
            return random.randint(100, 400)

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
        pm1_values = [r.pm1_0 for r in readings if r.pm1_0 is not None]
        pm10_values = [r.pm10 for r in readings if r.pm10 is not None]
        temps = [r.temperature for r in readings if r.temperature is not None]
        
        if pm25_values:
            self.stdout.write(self.style.SUCCESS('\n' + '=' * 45))
            self.stdout.write(self.style.SUCCESS('SUMMARY STATISTICS'))
            self.stdout.write(self.style.SUCCESS('=' * 45 + '\n'))
            
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
            
            self.stdout.write(f'\nDegraded events:            {degraded_count}')
            self.stdout.write(f'Critical events:            {critical_count}')
            self.stdout.write(f'Sensor error events:        {error_count}')
            
            self.stdout.write(f'\nPM2.5 Statistics:')
            self.stdout.write(f'  Min:  {min(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  Max:  {max(pm25_values):.2f} µg/m³')
            self.stdout.write(f'  Mean: {sum(pm25_values)/len(pm25_values):.2f} µg/m³')
            
            self.stdout.write(f'\nPM1.0 / PM2.5 / PM10 ratio maintained: [OK]')
            
            self.stdout.write(f'\nTemperature range: {min(temps):.1f}°C - {max(temps):.1f}°C')
            
            self.stdout.write(self.style.SUCCESS('\n[SUCCESS] Data generation complete!\n'))
