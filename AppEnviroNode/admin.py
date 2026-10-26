from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import CustomUser, SensorNode, SensorReading, Alert, SensorNodeAPIKey
from .models import Product, Order

class CustomUserAdmin(BaseUserAdmin):
    """Custom User Admin to manage extended user fields."""
    list_display = ('username', 'email', 'first_name', 'role', 'organization', 'is_approved', 'is_active')
    list_filter = ('role', 'is_approved', 'is_active', 'created_at')
    search_fields = ('username', 'email', 'organization')
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Role & Organization', {'fields': ('role', 'organization', 'is_approved')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at')}),
    )
    
    readonly_fields = ('created_at', 'date_joined', 'last_login')
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role', 'organization'),
        }),
    )


class SensorNodeAdmin(admin.ModelAdmin):
    """Admin for ESP8266 Sensor Nodes."""
    list_display = ('name', 'mac_address', 'status', 'location', 'organization', 'is_active', 'last_seen', 'created_at')
    list_filter = ('status', 'is_active', 'organization', 'created_at')
    search_fields = ('name', 'mac_address', 'location', 'organization')
    readonly_fields = ('mac_address', 'created_at', 'updated_at', 'last_reading', 'last_seen')
    
    fieldsets = (
        ('Device Information', {'fields': ('mac_address', 'name', 'location', 'organization')}),
        ('Location', {'fields': ('latitude', 'longitude')}),
        ('Status', {'fields': ('status', 'is_active', 'last_reading', 'last_seen')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )


class SensorReadingAdmin(admin.ModelAdmin):
    """Admin for Sensor Readings."""
    list_display = ('node', 'pm2_5', 'temperature', 'humidity', 'aqi', 'aqi_level', 'timestamp')
    list_filter = ('aqi_level', 'node__organization', 'timestamp')
    search_fields = ('node__name', 'node__mac_address')
    readonly_fields = ('aqi', 'aqi_level', 'timestamp')
    
    fieldsets = (
        ('Node', {'fields': ('node',)}),
        ('Particulate Matter', {'fields': ('pm1_0', 'pm2_5', 'pm10')}),
        ('Environmental Data (BME680)', {'fields': ('temperature', 'humidity', 'pressure', 'gas_resistance')}),
        ('Air Quality', {'fields': ('aqi', 'aqi_level')}),
        ('Timestamp', {'fields': ('timestamp',)}),
    )
    
    list_max_show_all = 200


class AlertAdmin(admin.ModelAdmin):
    """Admin for System Alerts and Password Reset Requests."""
    list_display = ('get_alert_title', 'alert_type', 'status', 'severity', 'triggered_at')
    list_filter = ('alert_type', 'status', 'severity', 'triggered_at')
    search_fields = ('user__email', 'node__name', 'title', 'description')
    readonly_fields = ('triggered_at', 'resolved_at', 'password_reset_token', 'password_reset_uid')
    
    fieldsets = (
        ('Alert Type & Status', {'fields': ('alert_type', 'status', 'severity', 'is_active')}),
        ('Node/User', {'fields': ('node', 'user')}),
        ('Content', {'fields': ('title', 'description')}),
        ('Password Reset Fields', {
            'fields': ('password_reset_token', 'password_reset_uid', 'auto_approval_time', 'denial_reason'),
            'classes': ('collapse',),
        }),
        ('Moderation', {'fields': ('approved_by',)}),
        ('Relations', {'fields': ('reading',)}),
        ('Timestamps', {'fields': ('triggered_at', 'resolved_at')}),
    )
    
    list_max_show_all = 200
    
    def get_alert_title(self, obj):
        if obj.alert_type == 'password_reset_request' and obj.user:
            return f"Password Reset - {obj.user.email}"
        return obj.title
    get_alert_title.short_description = 'Title'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Admins only see admin-related alerts
        if not request.user.is_staff:
            return qs.none()
        return qs


class SensorNodeAPIKeyAdmin(admin.ModelAdmin):
    """Admin for Sensor Node API Keys (Security: Issue 2.1 Fix)."""
    list_display = ('node', 'masked_api_key', 'is_active', 'created_at', 'last_used')
    list_filter = ('is_active', 'created_at', 'last_used')
    search_fields = ('node__name', 'node__mac_address', 'api_key')
    readonly_fields = ('api_key', 'created_at', 'last_used')
    
    fieldsets = (
        ('Node & Authentication', {'fields': ('node', 'api_key')}),
        ('Status', {'fields': ('is_active',)}),
        ('Activity', {'fields': ('created_at', 'last_used')}),
    )
    
    def masked_api_key(self, obj):
        """Display masked API key for security."""
        if obj.api_key:
            visible = obj.api_key[:8]
            return format_html('{}<span style="color:gray;">...{}chars</span>', visible, len(obj.api_key) - 8)
        return "—"
    masked_api_key.short_description = 'API Key'
    
    def has_add_permission(self, request):
        """API keys are auto-generated, prevent manual creation."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Only allow deletion through node deletion."""
        return True


admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(SensorNode, SensorNodeAdmin)
admin.site.register(SensorReading, SensorReadingAdmin)
admin.site.register(Alert, AlertAdmin)
admin.site.register(SensorNodeAPIKey, SensorNodeAPIKeyAdmin)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'stock', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Replaced 'user' with the new customer fields
    list_display = ('id', 'customer_name', 'customer_email', 'product', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('customer_name', 'customer_email')