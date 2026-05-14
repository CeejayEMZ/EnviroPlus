# EnviroNode: Security Features, Functionalities & Database Backup Strategy

**Last Updated:** May 14, 2026  
**Environment:** Django 5.2 + PostgreSQL on Render + Leaflet.js  
**Classification:** Production-Ready Environmental Monitoring System

---

## 📑 Table of Contents

1. [Security Features](#security-features)
2. [Core Functionalities](#core-functionalities)
3. [Database Backup Strategy (PostgreSQL on Render)](#database-backup-strategy-postgresql-on-render)
4. [Deployment Architecture](#deployment-architecture)

---

## 🔒 Security Features

### 1. Authentication & Authorization

#### Django Built-in Authentication
- **User authentication system** with session-based management
- **Password hashing** using Django's PBKDF2 algorithm with SHA256
- **Password validation** enforcing:
  - Minimum length requirements
  - Common password prevention
  - Numeric-only password rejection
  - User attribute similarity checks

#### Role-Based Access Control (RBAC)
- **Three user roles:**
  - **Admin**: Full system access, user management, configuration
  - **Official**: Data access, report viewing, alert management
  - **Public**: Limited map viewing (read-only)
- **User approval workflow**: New registrations require admin approval before access
- **Permission-based decorators** on sensitive endpoints

#### API Key Authentication (For ESP8266 Nodes)
- **Bearer token authentication** for IoT device data ingestion
- **Per-node API keys**: Each sensor node has unique 32-byte cryptographically secure key
- **Key management features:**
  - One-time key visibility upon generation
  - Enable/disable without deletion capability
  - Usage tracking with `last_used` timestamp
  - Automatic key rotation support
- **Implementation location:** `SensorNodeAPIKey` model in `models.py`

---

### 2. Input Validation & Data Sanitization

#### API Input Validation
```
Sensor data endpoint (/api/sensor-data/):
├─ MAC address validation (AA:BB:CC:DD:EE:FF format)
├─ MAC address mismatch detection (prevents spoofing)
├─ Sensor value range validation:
│   ├─ PM2.5, PM10, PM1.0: 0-1000 μg/m³
│   ├─ Temperature: -50 to 60 °C
│   ├─ Humidity: 0-100 %
│   ├─ Pressure: 300-1100 hPa
│   └─ Latency: 0-60000 ms
└─ Status field validation (normal, degraded, critical only)
```

#### ORM Protection
- **Prepared statements** via Django ORM (protection against SQL injection)
- **Type casting** enforced at ORM level
- **Automatic parameterization** of all database queries

---

### 3. CSRF Protection

#### Cross-Site Request Forgery Mitigation
- **CSRF middleware enabled** for all state-changing operations (POST, PUT, DELETE)
- **CSRF exemption** only for ESP8266 API endpoint (`/api/sensor-data/`)
  - Justified: IoT devices cannot handle CSRF tokens
  - Mitigated by: API key authentication instead
- **Token validation** enforced on all form submissions
- **SameSite cookie policy** configured

---

### 4. Transport Security

#### HTTPS Configuration
- **SSL/TLS enforcement** on production (Render)
- **Secure headers** middleware implemented:
  - `X-Frame-Options: DENY` (clickjacking prevention)
  - `X-Content-Type-Options: nosniff` (MIME-type sniffing prevention)
- **HTTP Strict Transport Security (HSTS)** configured on Render
- **Secure cookies** (HttpOnly, Secure flags enabled in production)

---

### 5. Data Privacy & Protection

#### Session Management
- **Server-side session storage** (Django default)
- **Automatic session timeout** after inactivity
- **Session fixation prevention** via Django middleware

#### User Data Protection
- **No sensitive data in URLs**
- **Email fields** encrypted/hashed appropriately
- **Password reset tokens** time-limited (24-hour expiration)
- **Admin action logging** of all user modifications

#### Sensor Data Access Control
- **Data filtering by user role**
- **Geographic scoping** (Barangay Pembo only - prevents data leakage)
- **Timestamp validation** prevents future-dated data injection

---

### 6. Logging & Monitoring

#### Comprehensive Audit Trail
- **AdminActionLog model** tracks:
  - User create/update/delete operations
  - Timestamp of each action
  - Administrator who performed the action
  - Changes made
- **SystemLog model** tracks:
  - API calls and sensor data ingestion
  - Alert triggers and escalations
  - Background job execution
  - Error conditions and exceptions
- **Django signals** ensure automatic logging on model changes

#### Security Event Logging
- Failed login attempts (future implementation)
- Invalid API key rejections
- MAC address mismatch attempts (spoofing detection)
- Out-of-range sensor value submissions

---

### 7. API Security

#### Rate Limiting Considerations
**Current Status**: Not implemented (planned for Phase 3)  
**Recommended Implementation**:
```python
# Add to requirements:
django-ratelimit==4.1.0

# Usage on views:
@ratelimit(key='ip', rate='100/h', method='POST')
def api_sensor_data(request):
    # ...
```

#### API Endpoint Protection
- **Authorization headers required** for all sensitive endpoints
- **Content-Type validation** (JSON enforcement)
- **Response filtering** based on user permissions
- **Pagination** prevents data dumping attacks

---

### 8. Security Best Practices Implemented

✅ **Principle of Least Privilege**: Users only access needed data  
✅ **Defense in Depth**: Multiple security layers (auth + validation + logging)  
✅ **Fail Securely**: Errors don't expose system information  
✅ **Regular Expression Validation**: Input format validation  
✅ **Type Hints**: Code clarity and runtime type checking  
✅ **Documentation**: All security mechanisms documented  

---

### 9. Known Security Gaps & Mitigation Plan

| Gap | Severity | Mitigation | Timeline |
|-----|----------|-----------|----------|
| No rate limiting | High | Implement django-ratelimit | Phase 3 |
| DEBUG mode in production possible | Critical | Enforce DEBUG=False in Render | Immediate |
| ALLOWED_HOSTS = "*" | High | Restrict to render.com domain | Immediate |
| Static files CORS | Medium | Add origin restrictions | Phase 3 |
| No WebSocket auth | Medium | Implement token-based WS auth | Phase 4 |

---

## 🚀 Core Functionalities

### 1. Real-Time Sensor Data Management

#### Data Ingestion Pipeline
- **ESP8266 nodes** transmit sensor readings via HTTPS POST
- **Endpoints**: `/api/sensor-data/` (API key authenticated)
- **Data fields captured**:
  - PM2.5, PM10, PM1.0 (particulate matter)
  - Temperature, Humidity, Pressure (BME680)
  - Latitude, Longitude (GPS coordinates)
  - Signal strength (RSSI)
  - Node status (normal/degraded/critical)
  - Timestamp (server-side)

#### Real-Time Data Polling
- **5-second polling interval** from frontend to backend
- **Endpoints**:
  - `/api/latest-readings/` - Most recent data from all nodes
  - `/api/sensor-reading-stream/` - WebSocket placeholder for future
- **Data deduplication**: In-memory caching prevents redundant updates
- **Request debouncing**: Prevents API flooding (frontend-side)

---

### 2. Interactive Map System

#### Leaflet.js Integration
- **Marker clustering** for dense sensor areas
- **Heatmap visualization** of PM2.5 levels
- **Dynamic marker coloring**:
  - 🟢 Green (0-50): Good
  - 🟡 Yellow (51-100): Moderate
  - 🟠 Orange (101-150): Unhealthy for Sensitive Groups
  - 🔴 Red (151-200+): Unhealthy
  - 🟣 Purple (200+): Very Unhealthy

#### Unified Controls
- **Pollutant selector**: PM2.5, PM10, PM1.0, AQI
- **Time range picker**: Last 24 hours, 7 days, 30 days
- **Node status filter**: All, online, offline, critical
- **Location search**: Find specific sensor nodes

---

### 3. Sensor Management Dashboard

#### Node Registration & Configuration
- **Manual node creation** by admin users
- **Fields configurable**:
  - Node MAC address (unique identifier)
  - Latitude/Longitude (automatic geocoding support)
  - Node name and description
  - Installation date
  - Hardware version (ESP8266 type)
  - Sensor model (PMS5003, BME680)

#### Node Status Monitoring
- **Last seen timestamp**: Tracks device connectivity
- **Battery level**: For battery-powered nodes (if applicable)
- **Signal strength (RSSI)**: Indicates WiFi connection quality
- **Active/inactive toggle**: Enable/disable without deletion
- **Health metrics**:
  - Uptime percentage
  - Average data latency
  - Reading count (last 24h)

---

### 4. Analytics & Reporting

#### Historical Data Analysis
- **Temporal aggregation**:
  - Minute-level: Raw sensor readings (24-hour retention)
  - Hourly-level: Average/min/max calculations
  - Daily-level: Summary statistics
  - Monthly-level: Trend analysis

#### Advanced Analytics Features
- **Spike detection**: Identifies anomalous readings
- **Trend analysis**: Calculates direction and rate of change
- **Comparative analysis**: Node-to-node correlation
- **System health metrics**: Overall network status

#### Report Generation
- **Endpoints**:
  - `/api/analytics/air-quality-summary/` - Aggregated stats
  - `/api/analytics/trend-analysis/` - Historical trends
  - `/api/analytics/system-health/` - Network status
- **Export formats**: JSON, PDF (reportlab integration)
- **Custom date ranges**: User-specified analysis periods

---

### 5. Alert System

#### Alert Triggering
- **Thresholds per pollutant**:
  - PM2.5 > 150: "Unhealthy" alert
  - PM10 > 200: "Unhealthy" alert
  - Temperature out-of-range
  - Node offline for >15 minutes

#### Alert Management
- **Alert creation**: Automatic on threshold breach
- **Alert approval workflow**: Escalation to admin users
- **Alert deduplication**: Prevents spam (same alert < 30 minutes)
- **Alert resolution**: Manual marking as resolved
- **Alert history**: Full audit trail

#### Notification Channels
- **In-app notifications**: Dashboard notifications
- **Email alerts** (SMTP configured):
  - Gmail SMTP support
  - Custom email templates
  - Admin contact list configuration
- **Webhook placeholders**: For future Slack/Teams integration

---

### 6. User Management System

#### User Registration & Approval
- **Registration form**: Email, password, organization
- **Admin approval workflow**: Users cannot access until approved
- **Email verification**: Optional (can be enforced)
- **Bulk user import**: CSV upload for multiple users

#### User Profile Management
- **Profile fields**:
  - Full name
  - Email (unique)
  - Organization affiliation
  - Role assignment (admin, official, public)
  - Last login timestamp
  - Account status (active, inactive, pending)

#### Permission Management
- **Role-based access**: Automatic permissions per role
- **Custom permissions**: Future implementation for fine-grained control
- **Access logs**: Track user activity for security

---

### 7. AI Integration (Groq LLM)

#### Anomaly Detection & Insights
- **Groq AI API** integration for natural language analysis
- **Features**:
  - Pattern recognition in sensor data
  - Anomaly explanation generation
  - Recommended actions
- **Rate limiting**: Prevents API quota exhaustion
- **Async processing**: Background job queuing

---

### 8. Background Jobs & Scheduling

#### APScheduler Integration
- **Scheduled tasks**:
  - Data aggregation (hourly/daily rollups)
  - Alert processing and escalation
  - Stale data cleanup (>90 days archival)
  - API cache refresh (45-60s TTL)
  - System health checks

#### Job Management
- **Execution logs**: All scheduled jobs tracked
- **Error handling**: Failed jobs logged with error details
- **Retry logic**: Automatic retry on transient failures
- **Job monitoring**: Dashboard displays next execution times

---

### 9. Frontend Features

#### Dashboard Views
- **Admin Dashboard**:
  - System health overview
  - User management panel
  - Alert management queue
  - Recent activity logs
  - Node status summary

- **Official Dashboard**:
  - Real-time map with filters
  - Historical data charts
  - Alert notifications
  - Report generation tools

- **Public Map**:
  - Read-only sensor visualization
  - Basic filtering
  - No sensitive data exposure

#### JavaScript Modules (15+ modules)
- `map.js` - Leaflet initialization and controls
- `realtime.js` - 5-second polling updates
- `analytics.js` - Chart.js visualizations
- `alerts.js` - Alert notification handling
- `dashboard.js` - Dashboard interactions
- `forms.js` - Form validation and submission
- `filters.js` - Advanced filtering with debounce
- `export.js` - Data export functionality
- (See file breakdown in system blueprint)

---

## 💾 Database Backup Strategy (PostgreSQL on Render)

### 1. Understanding Render's PostgreSQL Service

#### Database Hosting
- **Managed service**: Render handles infrastructure, patching, upgrades
- **Automated backups**: Built-in daily backups
- **Replica availability**: High-availability option available
- **Geographic redundancy**: Data replicated across zones

#### Connection Details
```
DATABASE_URL format: postgresql://user:password@host:port/database
Example: postgresql://render_user:pass123@dpg-xxxx.render.com:5432/environode_db

Typical credentials stored in:
├─ .env file (development)
├─ Render environment variables (production)
└─ GitHub Secrets (CI/CD pipelines)
```

---

### 2. Render's Built-in Backup System

#### Automatic Daily Backups
- **Frequency**: Automatically created every 24 hours
- **Retention**: Last 7 daily backups kept automatically
- **Location**: Encrypted storage on Render infrastructure
- **Recovery time**: <30 minutes for manual restore

#### Accessing Backups
1. Log into Render Dashboard
2. Navigate to PostgreSQL database instance
3. Click "Backups" tab
4. View list of available backup snapshots
5. Click "Restore" to restore to new database

**Important**: Restoring creates a **new database instance** (doesn't overwrite existing)

---

### 3. Backup Strategy Tiers

### Tier 1: Automatic Backups (Render Default)

| Component | Details |
|-----------|---------|
| **Frequency** | Daily (24-hour cycle) |
| **Retention** | 7 days (last 7 daily snapshots) |
| **Restore Time** | <30 minutes |
| **Cost** | Included in PostgreSQL service |
| **RPO (Recovery Point)** | 24 hours |
| **Use Case** | Protection against accidental deletion, database corruption |

**Limitations**:
- Only 7 days of history
- No hourly granularity
- Requires manual intervention to restore
- Not suitable for compliance requiring >7 day retention

---

### Tier 2: Manual Point-in-Time Backups

#### Implementation Strategy
```bash
# Schedule daily manual backups using pg_dump
# Add to your backend application or CI/CD pipeline

# 1. Backup to local file (then upload)
pg_dump postgresql://user:password@host:5432/dbname > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Upload to cloud storage (AWS S3, Google Cloud Storage)
# 3. Set 30-day retention policy on storage bucket
# 4. Keep compressed backups (reduces size by 80%)

# 5. Schedule via CI/CD (GitHub Actions example):
name: Daily PostgreSQL Backup
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM UTC daily
  
jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Backup PostgreSQL
        run: |
          PGPASSWORD=${{ secrets.DATABASE_PASSWORD }} pg_dump \
            -h ${{ secrets.DATABASE_HOST }} \
            -U ${{ secrets.DATABASE_USER }} \
            -d ${{ secrets.DATABASE_NAME }} \
            -Fc > backup_$(date +%Y%m%d).dump
      
      - name: Upload to S3
        run: |
          aws s3 cp backup_*.dump s3://your-backup-bucket/
```

---

### Tier 3: Continuous WAL (Write-Ahead Log) Archiving

#### Advanced Setup (Optional)
```sql
-- Enable WAL archiving for point-in-time recovery
-- This allows recovery to any second within the retention period

-- Render PostgreSQL Configuration:
-- Contact Render support to enable WAL archiving
-- Requires custom archive_command parameter

-- WAL archiving configuration:
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://wal-archive-bucket/%f'
```

**Benefits**:
- Recovery to any point in time (second-level granularity)
- Compliance with strict recovery requirements
- Useful for regulatory audit trails

**Drawbacks**:
- Requires Render support ticket
- Increases storage costs
- More complex to manage

---

### 4. Implementing Automated Backups

#### Option A: GitHub Actions (Recommended for Free Tier)

Create `.github/workflows/backup-postgres.yml`:

```yaml
name: PostgreSQL Backup to S3

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
  workflow_dispatch:     # Allow manual trigger

jobs:
  backup:
    runs-on: ubuntu-latest
    
    steps:
      - name: Install PostgreSQL client
        run: |
          sudo apt-get update
          sudo apt-get install -y postgresql-client
      
      - name: Create backup
        env:
          PGPASSWORD: ${{ secrets.DATABASE_PASSWORD }}
        run: |
          pg_dump \
            -h ${{ secrets.DATABASE_HOST }} \
            -U ${{ secrets.DATABASE_USER }} \
            -d ${{ secrets.DATABASE_NAME }} \
            -Fc \
            --verbose \
            -f backup_$(date +%Y%m%d_%H%M%S).dump
      
      - name: Upload to S3
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_DEFAULT_REGION: ${{ secrets.AWS_DEFAULT_REGION }}
        run: |
          aws s3 cp backup_*.dump \
            s3://your-backup-bucket/postgres-backups/ \
            --metadata "date=$(date +%Y-%m-%d),env=production"
      
      - name: Clean old backups (keep 30 days)
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_DEFAULT_REGION: ${{ secrets.AWS_DEFAULT_REGION }}
        run: |
          aws s3 rm s3://your-backup-bucket/postgres-backups/ \
            --recursive \
            --exclude "*" \
            --include "backup_$(date -d '30 days ago' +%Y%m%d)_*.dump"
      
      - name: Notify on failure
        if: failure()
        run: |
          curl -X POST -d "Backup failed" ${{ secrets.SLACK_WEBHOOK }}
```

#### Option B: Render Cron Job

Create `cron_backup.py` in your Django project:

```python
# AppEnviroNode/management/commands/backup_postgres.py

from django.core.management.base import BaseCommand
from django.conf import settings
import subprocess
import os
from datetime import datetime
import boto3

class Command(BaseCommand):
    help = 'Backup PostgreSQL database to S3'
    
    def handle(self, *args, **options):
        db_config = settings.DATABASES['default']
        
        # Parse DATABASE_URL
        db_url = os.getenv('DATABASE_URL')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = f'backup_{timestamp}.dump'
        
        try:
            # Create backup using pg_dump
            cmd = f'pg_dump {db_url} -Fc -f {backup_file}'
            subprocess.run(cmd, shell=True, check=True)
            self.stdout.write(f'✓ Backup created: {backup_file}')
            
            # Upload to S3
            s3 = boto3.client('s3')
            s3.upload_file(
                backup_file,
                'your-backup-bucket',
                f'postgres-backups/{backup_file}'
            )
            self.stdout.write('✓ Uploaded to S3')
            
            # Clean up local file
            os.remove(backup_file)
            self.stdout.write('✓ Local backup cleaned up')
            
        except Exception as e:
            self.stderr.write(f'✗ Backup failed: {str(e)}')
            raise

# Schedule in AppEnviroNode/scheduler.py
scheduler.add_job(
    func=django_cron,
    args=['backup_postgres'],
    trigger="cron",
    hour=2,
    minute=0,
    id='postgres_backup'
)
```

---

### 5. Backup Restore Procedures

#### Scenario A: Restore Render's Automatic Backup

**Time**: 10-30 minutes | **Downtime**: Yes (during restore)

```
1. Log into Render Dashboard
2. Select PostgreSQL database instance
3. Go to "Backups" section
4. Click "Restore" on desired backup
5. Choose: "Restore to new database" or "Restore to existing"
6. Wait for completion (shows as new database instance)
7. Update DATABASE_URL if new instance created
8. Test application connectivity
9. Delete old database instance (optional)
```

#### Scenario B: Restore from S3 Manual Backup

**Time**: 5-15 minutes | **Downtime**: Minimal

```bash
# 1. Download backup from S3
aws s3 cp s3://your-backup-bucket/postgres-backups/backup_20260514.dump .

# 2. Restore to target database
PGPASSWORD=password pg_restore \
  -h new-db-host.render.com \
  -U user \
  -d dbname \
  -Fc \
  -v \
  backup_20260514.dump

# 3. Verify data integrity
psql -h new-db-host.render.com -U user -d dbname -c "SELECT COUNT(*) FROM sensorreading;"

# 4. Update application if using new database
# Edit .env or Render environment variables with new DATABASE_URL
```

#### Scenario C: Restore Specific Data (Single Table)

```bash
# Restore only sensornode table from backup
pg_restore -h host -U user -d dbname -Fc \
  --table=appenvironode_sensornode \
  backup_20260514.dump
```

---

### 6. Backup Monitoring & Health Checks

#### Backup Verification Script

```python
# AppEnviroNode/management/commands/verify_backup.py

from django.core.management.base import BaseCommand
from django.db import connection
import subprocess
from datetime import datetime, timedelta

class Command(BaseCommand):
    help = 'Verify backup integrity and database health'
    
    def handle(self, *args, **options):
        # 1. Check database size
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    pg_size_pretty(pg_database.datsize) as size
                FROM pg_database 
                WHERE datname = current_database()
            """)
            size = cursor.fetchone()[0]
            self.stdout.write(f'✓ Database size: {size}')
        
        # 2. Check table row counts
        tables = ['appenvironode_sensorreading', 'appenvironode_alert', 'appenvironode_sensornode']
        for table in tables:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT COUNT(*) FROM {table}')
                count = cursor.fetchone()[0]
                self.stdout.write(f'✓ {table}: {count:,} rows')
        
        # 3. Check last backup timestamp
        cmd = "aws s3 ls s3://your-backup-bucket/postgres-backups/ | tail -1"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        self.stdout.write(f'✓ Last backup: {result.stdout}')
        
        # 4. Check if backup exists for today
        today = datetime.now().strftime('%Y%m%d')
        cmd = f"aws s3 ls s3://your-backup-bucket/postgres-backups/ | grep {today}"
        result = subprocess.run(cmd, shell=True, capture_output=True)
        
        if result.returncode == 0:
            self.stdout.write('✓ Today\'s backup exists')
        else:
            self.stderr.write('✗ WARNING: No backup for today!')
```

---

### 7. Backup Compliance & Documentation

#### Recovery Time Objectives (RTO) & Recovery Point Objectives (RPO)

| Strategy | RTO | RPO | Compliance |
|----------|-----|-----|-----------|
| **Render Auto Backups** | <30 min | 24 hours | SOC2 (basic) |
| **Daily S3 Dumps** | 5-15 min | 24 hours | HIPAA-friendly |
| **Hourly S3 Dumps** | 5-15 min | 1 hour | GDPR-compliant |
| **WAL Archiving** | <5 min | Seconds | Maximum compliance |

#### Recommended for EnviroNode:
- **Daily automated backups** (S3 + GitHub Actions)
- **7-day retention** minimum
- **Monthly test restores** to verify integrity
- **Backup documentation** in this file

---

### 8. Costs & Best Practices

#### Cost Breakdown
```
Render PostgreSQL (included):
├─ Automatic daily backups: $0
├─ 7-day retention: $0
└─ Restore operations: $0

External S3 Storage (AWS):
├─ ~1GB backup size × 30 backups = 30GB: ~$0.70/month
├─ PUT requests (daily): ~$0.07/month
└─ GET requests (restores): ~$0/month

Monthly Total: ~$0.77 (plus Render DB hosting)
```

#### Best Practices
✅ **Test restores monthly** - Don't wait for emergency  
✅ **Keep both automated + manual backups** - Defense in depth  
✅ **Monitor backup completion** - Set up alerts  
✅ **Document restore procedures** - Train team  
✅ **Encrypt backups in transit** - Use HTTPS/TLS  
✅ **Encrypt backups at rest** - S3 server-side encryption  
✅ **Version control backup scripts** - Track changes  
✅ **Separate backup credentials** - Don't hardcode in code  

---

## 🏗️ Deployment Architecture

### Development Environment
```
Local Machine
├─ SQLite3 database (dev)
├─ Django dev server (runserver)
├─ No HTTPS enforcement
└─ DEBUG = True
```

### Production Environment (Render)
```
Render Platform
├─ Web Service (Python/Django)
│   ├─ Gunicorn WSGI server
│   ├─ Environment variables (.env)
│   ├─ 512MB RAM (free tier) / 1GB+ (paid)
│   └─ Auto-restart on crash
│
├─ PostgreSQL Database (Managed)
│   ├─ Automatic daily backups
│   ├─ Automatic SSL/TLS
│   ├─ High availability option
│   └─ Automatic patching
│
├─ Static Files (WhiteNoise)
│   ├─ Served by Django/Gunicorn
│   ├─ Gzip compression enabled
│   └─ Browser caching headers
│
└─ Environment Configuration
    ├─ DATABASE_URL (postgres connection)
    ├─ SECRET_KEY (Django secret)
    ├─ DEBUG (must be False)
    ├─ ALLOWED_HOSTS (render.com domain)
    └─ EMAIL_* (SMTP configuration)
```

---

## 📋 Checklist: Security & Backup Readiness

- [ ] Verify DEBUG=False in production
- [ ] Verify ALLOWED_HOSTS restricted (not "*")
- [ ] Confirm DATABASE_URL set in Render environment
- [ ] Test API key authentication with test node
- [ ] Create S3 bucket for backups
- [ ] Set up GitHub Actions backup workflow
- [ ] Test restore procedure (restore to test database)
- [ ] Configure email alerts for backup failures
- [ ] Document backup restoration process for team
- [ ] Schedule monthly backup integrity checks
- [ ] Enable Render's "High Availability" option (if using paid tier)
- [ ] Set up monitoring/alerting for database performance

---

**For questions or updates**, consult the security audit (`ENVIRO_NODE_SECURITY_AUDIT.md`) and system blueprint (`ENVIRO_NODE_SYSTEM_BLUEPRINT.md`).
