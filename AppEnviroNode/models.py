from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta
import json
import secrets

class CustomUser(AbstractUser):
    """Extended User model with role and organization fields."""
    ROLE_CHOICES = (
        ('admin', 'Administrator'),
        ('official', 'Official'),
    )
    MAX_FAILED_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 5
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='official')
    organization = models.CharField(max_length=255, blank=True, null=True, help_text="Barangay or organization name")
    is_approved = models.BooleanField(default=False, help_text="Admin approval status")
    must_change_password = models.BooleanField(default=True, help_text="User must change password on first login")
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    def is_admin_user(self):
        return self.role == 'admin'

    def is_locked_out(self):
        if self.locked_until and timezone.now() < self.locked_until:
            return True
        if self.locked_until and timezone.now() >= self.locked_until:
            self.locked_until = None
            self.failed_login_attempts = 0
            self.save(update_fields=['locked_until', 'failed_login_attempts'])
        return False

    def record_failed_login(self):
        if self.is_locked_out():
            return True

        self.failed_login_attempts += 1
        if self.failed_login_attempts >= self.MAX_FAILED_LOGIN_ATTEMPTS:
            self.locked_until = timezone.now() + timedelta(minutes=self.LOCKOUT_DURATION_MINUTES)
            self.failed_login_attempts = 0
            self.save(update_fields=['failed_login_attempts', 'locked_until'])
            return True

        self.save(update_fields=['failed_login_attempts'])
        return False

    def reset_failed_logins(self):
        self.failed_login_attempts = 0
        self.locked_until = None
        self.save(update_fields=['failed_login_attempts', 'locked_until'])


class SensorNode(models.Model):
    """Represents an ESP8266 sensor node."""
    STATUS_CHOICES = (
        ('active', 'Active - Sending data regularly'),
        ('inactive', 'Inactive - Not sending data'),
        ('unregistered', 'Unregistered - Auto-created, needs configuration'),
        ('rogue', 'Rogue - Invalid or suspicious'),
    )
    
    mac_address = models.CharField(max_length=17, unique=True, help_text="MAC address of ESP8266")
    name = models.CharField(max_length=100, default="Unregistered Node", help_text="Node name/identifier")
    location = models.CharField(max_length=255, blank=True, null=True, help_text="Physical location (street address)")
    latitude = models.FloatField(null=True, blank=True, help_text="Latitude for map display")
    longitude = models.FloatField(null=True, blank=True, help_text="Longitude for map display")
    organization = models.CharField(max_length=255, default="EMBO", help_text="Organization using this node")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unregistered', help_text="Current node status")
    is_active = models.BooleanField(default=True, help_text="Node is actively sending data")
    last_reading = models.DateTimeField(null=True, blank=True, help_text="Last sensor reading timestamp")
    last_seen = models.DateTimeField(auto_now=True, help_text="Last time node was seen or updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-last_seen']
        verbose_name = 'Sensor Node'
        verbose_name_plural = 'Sensor Nodes'
        indexes = [
            models.Index(fields=['status', '-last_seen']),
            models.Index(fields=['-last_seen']),
            models.Index(fields=['mac_address']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.mac_address})"
    
    def get_status_color(self):
        """Return bootstrap color class for status."""
        colors = {
            'active': 'success',
            'inactive': 'warning',
            'unregistered': 'info',
            'rogue': 'danger',
        }
        return colors.get(self.status, 'secondary')
    
    def update_status(self):
        """Update status based on last_seen timestamp (5-minute threshold)."""
        if self.last_reading:
            time_since_reading = timezone.now() - self.last_reading
            if time_since_reading > timedelta(minutes=5):
                if self.status != 'inactive':
                    self.status = 'inactive'
                    self.save()
            elif self.status != 'active':
                self.status = 'active'
                self.save()
        return self.status


class SensorReading(models.Model):
    """Stores sensor data from ESP8266 nodes."""
    node = models.ForeignKey(SensorNode, on_delete=models.CASCADE, related_name='readings')
    
    # Particulate Matter
    pm1_0 = models.FloatField(null=True, blank=True, help_text="PM1.0 µg/m³")
    pm2_5 = models.FloatField(null=True, blank=True, help_text="PM2.5 µg/m³")
    pm10 = models.FloatField(null=True, blank=True, help_text="PM10 µg/m³")
    
    # BME680
    temperature = models.FloatField(null=True, blank=True, help_text="Temperature °C")
    humidity = models.FloatField(null=True, blank=True, help_text="Humidity %")
    pressure = models.FloatField(null=True, blank=True, help_text="Pressure hPa")
    gas_resistance = models.FloatField(null=True, blank=True, help_text="Gas resistance kΩ")
    
    # Calculated values
    aqi = models.IntegerField(null=True, blank=True, help_text="Air Quality Index (0-500)")
    aqi_level = models.CharField(
        max_length=20,
        choices=[
            ('good', 'Good'),
            ('moderate', 'Moderate'),
            ('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
            ('unhealthy', 'Unhealthy'),
            ('very_unhealthy', 'Very Unhealthy'),
            ('hazardous', 'Hazardous'),
        ],
        blank=True,
        null=True,
    )
    
    # Gas Quality Fields (computed from mq135_raw or BME680)
    gas_quality = models.CharField(
        max_length=20,
        choices=[
            ('normal', 'Normal'),
            ('good', 'Good'),
            ('moderate', 'Moderate'),
            ('poor', 'Poor'),
            ('critical', 'Critical'),
            ('unknown', 'Unknown'),
        ],
        default='normal',
        help_text="Computed gas quality from MQ135 sensor or BME680 gas resistance"
    )
    
    pollution_source = models.CharField(
        max_length=50,
        default='unknown',
        help_text="Inferred pollution source (e.g., traffic, industrial, biomass, unknown)"
    )
    
    gas_alert = models.BooleanField(
        default=False,
        null=True,
        help_text="Gas quality alert triggered (high pollution detected)"
    )
    
    # Raw MQ135 value from ESP8266 (for gas calculations)
    mq135_raw = models.IntegerField(
        null=True,
        blank=True,
        help_text="Raw MQ135 sensor value (0-1024) or -1 if unavailable"
    )
    
    # System Health & Sensor Status Fields (NEW)
    system_status = models.CharField(
        max_length=20,
        choices=[
            ('normal', 'Normal'),
            ('degraded', 'Degraded'),
            ('critical', 'Critical'),
        ],
        default='normal',
        help_text="Overall system health status from ESP8266"
    )
    
    pms_status = models.CharField(
        max_length=10,
        choices=[('ok', 'OK'), ('error', 'Error')],
        default='ok',
        help_text="PMS5003 sensor status (particulate matter)"
    )
    
    bme_status = models.CharField(
        max_length=10,
        choices=[('ok', 'OK'), ('error', 'Error')],
        default='ok',
        help_text="BME680 sensor status (temperature/humidity/pressure)"
    )
    
    latency_ms = models.IntegerField(null=True, blank=True, help_text="Request latency in milliseconds")
    
    is_anomaly = models.BooleanField(
        default=False,
        help_text="Marks reading as anomalous (e.g., sudden spike/drop)"
    )
    
    timestamp = models.DateTimeField(db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Sensor Reading'
        verbose_name_plural = 'Sensor Readings'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['node', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.node.name} - {self.timestamp}"
    
    def save(self, *args, **kwargs):
        """Calculate AQI and ensure gas fields have safe defaults."""
        if self.pm2_5 is not None:
            from .utils import calculate_aqi
            self.aqi, self.aqi_level = calculate_aqi(self.pm2_5)
        
        # Defensive: ensure gas fields never NULL (database constraint safety)
        if self.gas_quality is None:
            self.gas_quality = 'normal'
        if self.pollution_source is None:
            self.pollution_source = 'unknown'
        if self.gas_alert is None:
            self.gas_alert = False
            
        super().save(*args, **kwargs)


class Alert(models.Model):
    """Alert system for critical sensor readings and admin moderation tasks."""
    SEVERITY_CHOICES = (
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
        ('resolved', 'Resolved'),
    )
    
    ALERT_TYPE_CHOICES = (
        ('sensor_alert', 'Sensor Alert'),
        ('password_reset_request', 'Password Reset Request'),
    )
    
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('resolved', 'Resolved'),
    )
    
    node = models.ForeignKey(
        SensorNode,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alerts'
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alerts'
    )
    reading = models.ForeignKey(SensorReading, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts')
    
    # Core fields
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES, default='sensor_alert')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    title = models.CharField(max_length=255, help_text="Alert title")
    description = models.TextField(help_text="Alert description")
    is_active = models.BooleanField(default=True, help_text="Alert is still active/unresolved")
    
    # Password reset specific fields
    password_reset_token = models.CharField(max_length=255, null=True, blank=True)
    password_reset_uid = models.CharField(max_length=255, null=True, blank=True)
    auto_approval_time = models.DateTimeField(null=True, blank=True, help_text="Time when auto-approval will occur")
    approved_by = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_alerts')
    denial_reason = models.TextField(null=True, blank=True, help_text="Reason for denying the request")
    
    # Timestamps
    triggered_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-triggered_at']
        verbose_name = 'Alert'
        verbose_name_plural = 'Alerts'
        indexes = [
            models.Index(fields=['-triggered_at']),
            models.Index(fields=['node', '-triggered_at']),
            models.Index(fields=['alert_type', 'status']),
        ]
    
    def __str__(self):
        if self.alert_type == 'password_reset_request' and self.user:
            return f"Password Reset Request - {self.user.email} ({self.status})"
        elif self.node:
            return f"{self.node.name} - {self.title} ({self.severity})"
        else:
            return f"{self.title} ({self.severity})"
    
    def resolve(self):
        """Mark alert as resolved."""
        self.is_active = False
        self.resolved_at = timezone.now()
        self.severity = 'resolved'
        self.save()


class SystemLog(models.Model):
    """Unified system logging for all events (readings, warnings, device events, admin actions)."""
    EVENT_TYPE_CHOICES = (
        ('reading', 'Sensor Reading'),
        ('warning', 'Sensor Warning'),
        ('device_online', 'Device Online'),
        ('device_offline', 'Device Offline'),
        ('system', 'System Event'),
        ('admin', 'Admin Action'),
    )
    
    SEVERITY_CHOICES = (
        ('good', 'Good'),
        ('moderate', 'Moderate'),
        ('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
        ('unhealthy', 'Unhealthy'),
        ('very_unhealthy', 'Very Unhealthy'),
        ('hazardous', 'Hazardous'),
    )
    
    node = models.ForeignKey(SensorNode, on_delete=models.CASCADE, null=True, blank=True, related_name='system_logs')
    reading = models.ForeignKey(SensorReading, on_delete=models.SET_NULL, null=True, blank=True, related_name='logs')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, null=True, blank=True)
    message = models.TextField(help_text="Log message/description")
    value = models.IntegerField(null=True, blank=True, help_text="Optional numeric value (e.g., AQI, temperature)")
    sensor_type = models.CharField(
        max_length=20,
        choices=[
            ('pm2_5', 'PM2.5'),
            ('pm10', 'PM10'),
            ('pm1_0', 'PM1.0'),
            ('temperature', 'Temperature'),
            ('humidity', 'Humidity'),
            ('pressure', 'Pressure'),
            ('aqi', 'AQI'),
        ],
        null=True,
        blank=True,
        help_text="Type of sensor for reading log"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'System Log'
        verbose_name_plural = 'System Logs'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['node', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
            models.Index(fields=['severity', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_event_type_display()} - {self.created_at}"


class AdminActionLog(models.Model):
    """Track all admin/user actions for audit trail."""
    ACTION_CHOICES = (
        ('node_create', 'Node Created'),
        ('node_update', 'Node Updated'),
        ('node_delete', 'Node Deleted'),
        ('alert_threshold_update', 'Alert Threshold Updated'),
        ('user_created', 'User Created'),
        ('user_updated', 'User Updated'),
        ('user_deleted', 'User Deleted'),
        ('config_changed', 'Configuration Changed'),
        ('data_exported', 'Data Exported'),
        ('alert_resolved', 'Alert Resolved'),
    )
    
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_actions')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True)
    target_model = models.CharField(max_length=100, null=True, blank=True, help_text="Model affected (e.g., SensorNode)")
    target_id = models.IntegerField(null=True, blank=True, help_text="ID of affected object")
    description = models.TextField(help_text="Action description")
    details = models.JSONField(default=dict, blank=True, help_text="Additional JSON data")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Admin Action Log'
        verbose_name_plural = 'Admin Action Logs'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]
    
    def __str__(self):
        user_str = self.user.username if self.user else "System"
        return f"{user_str} - {self.get_action_display()}"


class SensorNodeAPIKey(models.Model):
    """API authentication tokens for ESP8266 sensor nodes (fixes security issue 2.1)."""
    node = models.OneToOneField(SensorNode, on_delete=models.CASCADE, related_name='api_key', help_text="Associated sensor node")
    api_key = models.CharField(max_length=50, unique=True, db_index=True, help_text="Unique API key for authentication")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True, help_text="Last time this key was used")
    is_active = models.BooleanField(default=True, help_text="API key is active")
    
    class Meta:
        verbose_name = 'Sensor Node API Key'
        verbose_name_plural = 'Sensor Node API Keys'
        indexes = [
            models.Index(fields=['api_key']),
            models.Index(fields=['node']),
        ]
    
    def save(self, *args, **kwargs):
        """Generate API key on creation."""
        if not self.api_key:
            self.api_key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"API Key for {self.node.name}"
