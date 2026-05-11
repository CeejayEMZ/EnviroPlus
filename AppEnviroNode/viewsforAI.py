from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import models
from django.db.models import Q, Max, Count, Avg, Min
from django.core.serializers.json import DjangoJSONEncoder
from django.core.paginator import Paginator
import csv
from datetime import timedelta, datetime
import json
import urllib.parse
from .forms import CustomAuthenticationForm, CustomUserCreationForm, PasswordResetRequestForm, SensorNodeForm
from .models import SensorNode, SensorReading, Alert, SystemLog, AdminActionLog
from django.contrib.auth import get_user_model
from .ai import ask_enviro_ai, generate_ai_insights


User = get_user_model()


# UTILITY FUNCTIONS
def get_latest_reading(node):
    return node.readings.order_by('-timestamp').first()

def check_and_update_node_status():
    """Check all nodes and update status to 'inactive' if no reading in 5 minutes."""
    threshold_time = timezone.now() - timedelta(minutes=5)
    
    # Find all active nodes that haven't sent data in 5+ minutes
    inactive_nodes = SensorNode.objects.filter(
        status='active',
        last_reading__lt=threshold_time
    )
    
    for node in inactive_nodes:
        node.status = 'inactive'
        node.save()
        print(f"[STATUS UPDATE] Node {node.name} marked as 'inactive'")
    
    return inactive_nodes.count()


def build_top_area_rankings(limit=5):
    nodes = SensorNode.objects.filter(readings__isnull=False).prefetch_related('readings').distinct()
    latest_nodes = []
    for node in nodes:
        latest = node.readings.order_by('-timestamp').first()
        if latest and latest.aqi is not None:
            latest_nodes.append((node, latest))

    latest_nodes.sort(key=lambda item: item[1].aqi, reverse=True)

    def serialize_entry(node, reading):
        return {
            'node_id': node.id,
            'name': node.name,
            'location': node.location or 'Unknown Area',
            'aqi': reading.aqi,
            'aqi_level': reading.get_aqi_level_display() if hasattr(reading, 'get_aqi_level_display') else getattr(reading, 'aqi_level', None),
            'updated_at': reading.timestamp.isoformat() if reading.timestamp else None,
        }

    top_polluted = [serialize_entry(node, reading) for node, reading in latest_nodes[:limit]]
    cleanest = [serialize_entry(node, reading) for node, reading in sorted(latest_nodes, key=lambda item: item[1].aqi)[:limit]]
    return top_polluted, cleanest, len(latest_nodes)

# PUBLIC PAGES (No authentication required)
def dashboard(request):
    from django.db.models.functions import TruncDay
    
    if request.user.is_authenticated:
        return redirect('app:client_dashboard')
    
    # =========================================================================
    # SECTION 1: Get all active sensor nodes with their latest readings
    # =========================================================================
    nodes = SensorNode.objects.filter(is_active=True).prefetch_related('readings').order_by('name')
    
    # Aggregate data (for node cards)
    aggregate_data = {
        'total_nodes': nodes.count(),
        'nodes': [],
        'latest_overall': None,
        'avg_aqi': 0,
        'avg_pm2_5': 0,
        'avg_temperature': 0,
    }
    
    total_aqi = 0
    total_pm2_5 = 0
    total_temp = 0
    valid_readings = 0
    
    for node in nodes:
        latest = node.readings.first()
        if latest:
            aggregate_data['nodes'].append({
                'node': node,
                'reading': latest,
            })
            
            if not aggregate_data['latest_overall'] or latest.timestamp > aggregate_data['latest_overall'].timestamp:
                aggregate_data['latest_overall'] = latest
            if latest.aqi is not None:
                total_aqi += latest.aqi
            if latest.pm2_5 is not None:
                total_pm2_5 += latest.pm2_5
            if latest.temperature is not None:
                total_temp += latest.temperature
            valid_readings += 1
    
    # Calculate averages
    if valid_readings > 0:
        aggregate_data['avg_aqi'] = round(total_aqi / valid_readings)
        aggregate_data['avg_pm2_5'] = round(total_pm2_5 / valid_readings, 2)
        aggregate_data['avg_temperature'] = round(total_temp / valid_readings, 1)
    
    # =========================================================================
    # SECTION 2: Generate 7-day chart data
    # =========================================================================
    today = timezone.now().date()
    start_date = today - timedelta(days=7)
    time_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    time_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    
    readings_qs = SensorReading.objects.filter(
        timestamp__gte=time_start,
        timestamp__lte=time_end
    ).select_related('node')
    
    # Chart data: daily aggregation for 7-day trend
    chart_data_raw = readings_qs.annotate(
        period=TruncDay('timestamp')
    ).values('period').annotate(
        avg_aqi=models.Avg('aqi'),
        avg_pm2_5=models.Avg('pm2_5'),
        avg_temperature=models.Avg('temperature'),
        count=models.Count('id')
    ).order_by('period')
    
    chart_data = [
        {
            'date': item['period'].strftime('%Y-%m-%d') if item['period'] else 'N/A',
            'avg_aqi': round(item['avg_aqi'], 1) if item['avg_aqi'] else 0,
            'avg_pm2_5': round(item['avg_pm2_5'], 2) if item['avg_pm2_5'] else None,
            'avg_temperature': round(item['avg_temperature'], 1) if item['avg_temperature'] else None,
            'count': item['count']
        }
        for item in chart_data_raw
    ]
    
    # =========================================================================
    # SECTION 3: Map data (active and inactive nodes)
    # =========================================================================
    check_and_update_node_status()
    
    all_nodes = SensorNode.objects.all().prefetch_related('readings')
    active_nodes_json = []
    inactive_nodes_json = []
    
    for node in all_nodes:
        latest_reading = node.readings.first()
        json_data = {
            'node': {
                'id': node.id,
                'name': node.name,
                'location': node.location,
                'latitude': float(node.latitude) if node.latitude else None,
                'longitude': float(node.longitude) if node.longitude else None,
                'mac_address': node.mac_address,
                'status': node.status,
            },
            'pollutants': {
                'pm25': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 else None,
                'pm10': float(latest_reading.pm10) if latest_reading and latest_reading.pm10 else None,
                'pm1_0': float(latest_reading.pm1_0) if latest_reading and latest_reading.pm1_0 else None,
                'aqi': latest_reading.aqi if latest_reading else None,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature else None,
                'humidity': float(latest_reading.humidity) if latest_reading and latest_reading.humidity else None,
            }
        }
        
        if node.status == 'active':
            active_nodes_json.append(json_data)
        else:
            inactive_nodes_json.append(json_data)
    
    top_polluted_areas, cleanest_areas, top_area_count = build_top_area_rankings(limit=5)
    context = {
        'aggregate_data': aggregate_data,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),
        'active_nodes_json': json.dumps(active_nodes_json, cls=DjangoJSONEncoder),
        'inactive_nodes_json': json.dumps(inactive_nodes_json, cls=DjangoJSONEncoder),
        'top_polluted_areas': top_polluted_areas,
        'cleanest_areas': cleanest_areas,
        'top_polluted_areas_json': json.dumps(top_polluted_areas, cls=DjangoJSONEncoder),
        'cleanest_areas_json': json.dumps(cleanest_areas, cls=DjangoJSONEncoder),
        'total_nodes': all_nodes.count(),
        'active_count': len(active_nodes_json),
        'inactive_count': len(inactive_nodes_json),
        'top_area_count': top_area_count,
    }
    return render(request, 'AppEnviroNode/main/dashboard.html', context)


def api_analytics_aqi_trend(request):
    """Return hourly AQI averages for the last 24 hours."""
    from django.db.models.functions import TruncHour

    now = timezone.now()
    start_time = now - timedelta(hours=24)
    start_hour = start_time.replace(minute=0, second=0, microsecond=0)

    readings_qs = SensorReading.objects.filter(
        timestamp__gte=start_hour,
        timestamp__lte=now,
        aqi__isnull=False
    )

    chart_data_raw = readings_qs.annotate(
        period=TruncHour('timestamp')
    ).values('period').annotate(
        avg_aqi=models.Avg('aqi'),
        count=models.Count('id')
    ).order_by('period')

    hourly_map = {
        item['period']: round(item['avg_aqi'], 1)
        for item in chart_data_raw
        if item['period'] is not None
    }

    labels = []
    values = []
    current = start_hour
    while current <= now:
        raw_label = current.strftime('%I:%M %p')
        label = raw_label.lstrip('0') if raw_label.startswith('0') else raw_label
        labels.append(label)
        values.append(hourly_map.get(current, None))
        current += timedelta(hours=1)

    return JsonResponse({
        'labels': labels,
        'aqi': values,
        'generated_at': now.isoformat(),
        'range_hours': 24
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_analytics_top_areas(request):
    """
    GET /api/analytics/top-areas/

    Returns the current top polluted and cleanest monitored areas based on the latest AQI reading per node.
    """
    try:
        top_polluted, cleanest, count = build_top_area_rankings(limit=5)
        return JsonResponse({
            'success': True,
            'top_polluted_areas': top_polluted,
            'cleanest_areas': cleanest,
            'count': count
        }, status=200)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def realtime(request):
    """Display real-time sensor data from latest readings."""
    filters = build_realtime_filters(request)
    nodes = SensorNode.objects.filter(is_active=True).order_by('name')
    readings_qs = build_realtime_queryset(filters)

    total_readings = readings_qs.count()
    active_nodes = nodes.count()
    avg_aqi = None

    if readings_qs.filter(aqi__isnull=False).exists():
        agg = readings_qs.aggregate(avg_aqi=Avg('aqi'))
        avg_aqi = round(agg['avg_aqi'], 1) if agg['avg_aqi'] is not None else None

    chart_data = build_realtime_chart_data(readings_qs, filters['selected_range'])
    recent_readings = readings_qs.order_by('-timestamp')[:10]

    context = {
        'nodes': nodes,
        'selected_range': filters['selected_range'],
        'selected_node': filters['selected_node'] or '',
        'selected_node_id': filters['selected_node_id'] or '',
        'start_date': filters['start_date'],
        'end_date': filters['end_date'],
        'range_label': filters['range_label'],
        'avg_aqi': avg_aqi,
        'total_readings': total_readings,
        'active_nodes': active_nodes,
        'chart_data_json': json.dumps(chart_data, cls=DjangoJSONEncoder),
        'recent_readings': recent_readings,
    }
    return render(request, 'AppEnviroNode/main/realtime.html', context)

def map_view(request):
    """Display sensor nodes on interactive map with WAQI-inspired controls."""
    nodes = SensorNode.objects.filter(is_active=True).prefetch_related('readings')
    
    # Serialize node data to JSON-safe format with full pollutant data
    nodes_json_safe = []
    for node in nodes:
        latest_reading = get_latest_reading(node)
        nodes_json_safe.append({
            'node': {
                'id': node.id,
                'name': node.name,
                'location': node.location,
                'latitude': float(node.latitude) if node.latitude else None,
                'longitude': float(node.longitude) if node.longitude else None,
                'mac_address': node.mac_address,
                'status': node.status,
            },
            'latest_reading': {
                'aqi': latest_reading.aqi if latest_reading else None,
                'aqi_level': latest_reading.aqi_level if latest_reading else None,
                'pm2_5': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 else None,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature else None,
                'timestamp': latest_reading.timestamp.isoformat() if latest_reading else None,
            },
            # Enhanced: Full pollutant data for WAQI-style control filtering
            'pollutants': {
                'pm25': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 is not None else 0,
                'pm10': float(latest_reading.pm10) if latest_reading and latest_reading.pm10 is not None else 0,
                'pm1_0': float(latest_reading.pm1_0) if latest_reading and latest_reading.pm1_0 is not None else 0,
                'aqi': latest_reading.aqi if latest_reading and latest_reading.aqi is not None else 0,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature is not None else 0,
                'humidity': float(latest_reading.humidity) if latest_reading and latest_reading.humidity is not None else 0,
                'pressure': float(latest_reading.pressure) if latest_reading and latest_reading.pressure is not None else 0,
                'gas_resistance': float(latest_reading.gas_resistance) if latest_reading and latest_reading.gas_resistance is not None else 0,
            }
        })
    
    context = {
        'nodes_json': json.dumps(nodes_json_safe, cls=DjangoJSONEncoder),
        'total_nodes': nodes.count(),
        'map_initialized': True,
    }
    return render(request, 'AppEnviroNode/main/map.html', context)

def history(request):
    """Display historical sensor data."""
    from django.core.paginator import Paginator
    
    readings = SensorReading.objects.select_related('node').order_by('-timestamp')
    paginator = Paginator(readings, 10)  
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    total_readings = readings.count()
    avg_aqi = None
    if readings.exists():
        aqi_values = [r.aqi for r in readings if r.aqi is not None]
        if aqi_values:
            avg_aqi = sum(aqi_values) // len(aqi_values)
    
    context = {
        'page_obj': page_obj,
        'total_readings': total_readings,
        'avg_aqi': avg_aqi,
    }
    return render(request, 'AppEnviroNode/main/history.html', context)

def alerts(request):
    """Display alerts and advisories."""
    from django.utils import timezone
    from datetime import timedelta
    
    # Get critical and warning alerts from last 24 hours
    time_threshold = timezone.now() - timedelta(hours=24)
    
    active_alerts = Alert.objects.filter(is_active=True).select_related('node', 'reading')
    recent_alerts = Alert.objects.filter(
        triggered_at__gte=time_threshold
    ).select_related('node', 'reading')
    
    # Count alerts by severity
    critical_count = active_alerts.filter(severity='critical').count()
    warning_count = active_alerts.filter(severity='warning').count()
    total_24h = recent_alerts.count()
    
    context = {
        'active_alerts': active_alerts[:10],  # Show latest 10
        'alert_history': recent_alerts[:20],  # Show latest 20
        'critical_count': critical_count,
        'warning_count': warning_count,
        'total_24h': total_24h,
    }
    return render(request, 'AppEnviroNode/main/alerts.html', context)

def health(request):
    """Display health advisory based on current AQI."""
    # Get latest reading to determine advisory
    latest_reading = SensorReading.objects.filter(node__is_active=True).first()
    
    context = {
        'latest_reading': latest_reading,
    }
    return render(request, 'AppEnviroNode/main/health.html', context)

def about(request):
    return render(request, 'AppEnviroNode/main/about.html')


# AUTHENTICATION VIEWS
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('app:client_dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('app:client_dashboard')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'AppEnviroNode/auth/login.html', {'form': form})


@require_http_methods(["GET", "POST"])
def signup_view(request):
    """Handle admin/official registration."""
    if request.user.is_authenticated:
        return redirect('app:client_dashboard')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_approved = False 
            user.save()
            
            messages.success(
                request,
                f'Account created successfully! Please wait for admin approval. You can log in once approved.'
            )
            return redirect('app:login')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'AppEnviroNode/auth/signup.html', {'form': form})


@require_http_methods(["POST"])
@login_required
def logout_view(request):
    """Handle user logout."""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('app:dashboard')


@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    """Handle password reset request."""
    if request.user.is_authenticated:
        return redirect('app:client_dashboard')
    
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data.get('email')
            user = User.objects.get(email=email)
            # TODO: Send password reset email
            messages.info(
                request,
                'If an account exists with this email, you will receive password reset instructions.'
            )
            return redirect('app:login')
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
    else:
        form = PasswordResetRequestForm()
    
    return render(request, 'AppEnviroNode/auth/forgot_password.html', {'form': form})

@login_required(login_url='app:login')
def client_dashboard(request):
    """
    Admin Dashboard — fully dynamic.
    Queries: SensorNode, SensorReading, Alert, CustomUser
    Blueprint rule: ALL aggregation in this view. Zero calculations in the template.
    """
    from django.db.models.functions import TruncDay

    # =========================================================================
    # SECTION 1: Get all active sensor nodes with their latest readings
    # =========================================================================
    nodes = SensorNode.objects.filter(is_active=True).prefetch_related('readings').order_by('name')

    aggregate_data = {
        'total_nodes': nodes.count(),
        'nodes': [],
        'latest_overall': None,
        'avg_aqi': 0,
        'avg_pm2_5': 0,
        'avg_temperature': 0,
    }

    total_aqi = 0
    total_pm2_5 = 0
    total_temp = 0
    valid_readings = 0

    for node in nodes:
        latest = node.readings.first()
        if latest:
            aggregate_data['nodes'].append({
                'node': node,
                'reading': latest,
            })
            if not aggregate_data['latest_overall'] or latest.timestamp > aggregate_data['latest_overall'].timestamp:
                aggregate_data['latest_overall'] = latest
            if latest.aqi is not None:
                total_aqi += latest.aqi
            if latest.pm2_5 is not None:
                total_pm2_5 += latest.pm2_5
            if latest.temperature is not None:
                total_temp += latest.temperature
            valid_readings += 1

    if valid_readings > 0:
        aggregate_data['avg_aqi'] = round(total_aqi / valid_readings)
        aggregate_data['avg_pm2_5'] = round(total_pm2_5 / valid_readings, 2)
        aggregate_data['avg_temperature'] = round(total_temp / valid_readings, 1)

    # =========================================================================
    # SECTION 2: Generate 7-day chart data
    # =========================================================================
    today = timezone.now().date()
    start_date = today - timedelta(days=7)
    time_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    time_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    readings_qs = SensorReading.objects.filter(
        timestamp__gte=time_start,
        timestamp__lte=time_end
    ).select_related('node')

    chart_data_raw = readings_qs.annotate(
        period=TruncDay('timestamp')
    ).values('period').annotate(
        avg_aqi=models.Avg('aqi'),
        avg_pm2_5=models.Avg('pm2_5'),
        avg_temperature=models.Avg('temperature'),
        count=models.Count('id')
    ).order_by('period')

    chart_data = [
        {
            'date': item['period'].strftime('%Y-%m-%d') if item['period'] else 'N/A',
            'avg_aqi': round(item['avg_aqi'], 1) if item['avg_aqi'] else 0,
            'avg_pm2_5': round(item['avg_pm2_5'], 2) if item['avg_pm2_5'] else None,
            'avg_temperature': round(item['avg_temperature'], 1) if item['avg_temperature'] else None,
            'count': item['count']
        }
        for item in chart_data_raw
    ]

    # =========================================================================
    # SECTION 3: Analytics aggregations (last 7 days)
    # =========================================================================
    total_readings = readings_qs.count()
    analytics = {
        'total_readings': total_readings,
        'avg_aqi': None,
        'min_aqi': None,
        'max_aqi': None,
        'avg_pm2_5': None,
        'avg_temperature': None,
    }

    if total_readings > 0:
        readings_with_aqi = readings_qs.filter(aqi__isnull=False)
        readings_with_pm = readings_qs.filter(pm2_5__isnull=False)
        readings_with_temp = readings_qs.filter(temperature__isnull=False)

        if readings_with_aqi.exists():
            agg_result = readings_with_aqi.aggregate(
                avg_val=models.Avg('aqi'),
                min_val=models.Min('aqi'),
                max_val=models.Max('aqi')
            )
            analytics['avg_aqi'] = round(agg_result['avg_val'], 1) if agg_result['avg_val'] else None
            analytics['min_aqi'] = agg_result['min_val']
            analytics['max_aqi'] = agg_result['max_val']

        if readings_with_pm.exists():
            pm_avg = readings_with_pm.aggregate(models.Avg('pm2_5'))['pm2_5__avg']
            analytics['avg_pm2_5'] = round(pm_avg, 2) if pm_avg else None

        if readings_with_temp.exists():
            temp_avg = readings_with_temp.aggregate(models.Avg('temperature'))['temperature__avg']
            analytics['avg_temperature'] = round(temp_avg, 1) if temp_avg else None

    # =========================================================================
    # SECTION 4: System health metrics
    # =========================================================================
    total_nodes = SensorNode.objects.count()
    active_nodes = SensorNode.objects.filter(is_active=True).count()
    latest_reading_obj = SensorReading.objects.order_by('-timestamp').first()
    latest_reading_time = latest_reading_obj.timestamp if latest_reading_obj else None

    system_health = {
        'total_nodes': total_nodes,
        'active_nodes': active_nodes,
        'inactive_nodes': total_nodes - active_nodes,
        'latest_reading_time': latest_reading_time,
        'data_freshness_minutes': int(
            (timezone.now() - latest_reading_time).total_seconds() / 60
        ) if latest_reading_time else None,
    }

    # =========================================================================
    # SECTION 5: Map data
    # =========================================================================
    check_and_update_node_status()

    all_nodes = SensorNode.objects.all().prefetch_related('readings')
    active_nodes_json = []
    inactive_nodes_json = []

    for node in all_nodes:
        latest_reading = node.readings.first()
        json_data = {
            'node': {
                'id': node.id,
                'name': node.name,
                'location': node.location,
                'latitude': float(node.latitude) if node.latitude else None,
                'longitude': float(node.longitude) if node.longitude else None,
                'mac_address': node.mac_address,
                'status': node.status,
            },
            'pollutants': {
                'pm25': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 else None,
                'pm10': float(latest_reading.pm10) if latest_reading and latest_reading.pm10 else None,
                'pm1_0': float(latest_reading.pm1_0) if latest_reading and latest_reading.pm1_0 else None,
                'aqi': latest_reading.aqi if latest_reading else None,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature else None,
                'humidity': float(latest_reading.humidity) if latest_reading and latest_reading.humidity else None,
            }
        }

        if node.status == 'active':
            active_nodes_json.append(json_data)
        else:
            inactive_nodes_json.append(json_data)

    # =========================================================================
    # SECTION 6: Alert severity counts (NEW)
    # Powers: primary incident card, secondary strip, alert summary card
    # =========================================================================
    active_alerts_qs = Alert.objects.filter(
        is_active=True
    ).select_related('node').order_by('-triggered_at')

    severity_counts = {
        'critical': active_alerts_qs.filter(severity='critical').count(),
        'warning':  active_alerts_qs.filter(severity='warning').count(),
        'info':     active_alerts_qs.filter(severity='info').count(),
    }

    # =========================================================================
    # SECTION 7: User statistics (NEW)
    # Powers: users card, secondary strip pending-approval pill
    # =========================================================================
    user_stats = {
        'total_users':      User.objects.count(),
        'pending_approval': User.objects.filter(is_approved=False).count(),
        'admin_count':      User.objects.filter(role='admin').count(),
        'official_count':   User.objects.filter(role='official').count(),
    }

    # =========================================================================
    # BUILD CONTEXT
    # =========================================================================
    context = {
        # Existing keys — unchanged
        'aggregate_data':      aggregate_data,
        'chart_data':          json.dumps(chart_data, cls=DjangoJSONEncoder),
        'analytics':           analytics,
        'system_health':       system_health,
        'active_nodes_json':   json.dumps(active_nodes_json, cls=DjangoJSONEncoder),
        'inactive_nodes_json': json.dumps(inactive_nodes_json, cls=DjangoJSONEncoder),
        'total_nodes':         all_nodes.count(),
        'active_count':        len(active_nodes_json),
        'inactive_count':      len(inactive_nodes_json),
        # New keys
        'active_alerts':       active_alerts_qs[:5],   # top 5 for incident card
        'severity_counts':     severity_counts,
        'user_stats':          user_stats,
    }
    return render(request, 'AppEnviroNode/admin/clientdashboard.html', context)

@login_required(login_url='app:login')
def client_analytics(request):
    """
    Dynamic analytics dashboard with filter support and time-based aggregation.
    
    BLUEPRINT COMPLIANCE:
    - All aggregation done in Django views (NO frontend calculations)
    - Data flows: SensorReading ORM → aggregation → context → template
    - Respects filter inputs (node, location, date range, time grouping)
    - Chart data pre-computed and injected as JSON
    
    Query Parameters:
    - node: Filter by SensorNode.id
    - location: Filter by SensorNode.location
    - start_date: YYYY-MM-DD format (default: 7 days ago)
    - end_date: YYYY-MM-DD format (default: today)
    - grouping: 'daily' | 'weekly' | 'monthly' (default: 'daily')
    """
    from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
    
    # ============================================================================
    # SECTION 1: Parse Filter Parameters
    # ============================================================================
    # Extract filters from GET request (user can change via form submit/dropdown)
    selected_node_id = request.GET.get('node', None)
    selected_location = request.GET.get('location', None)
    start_date_str = request.GET.get('start_date', None)
    end_date_str = request.GET.get('end_date', None)
    grouping = request.GET.get('grouping', 'daily')  # daily, weekly, monthly
    
    # Validate grouping parameter
    if grouping not in ['daily', 'weekly', 'monthly']:
        grouping = 'daily'
    
    # ============================================================================
    # SECTION 2: Build Date Range (Default: Last 7 days)
    # ============================================================================
    today = timezone.now().date()
    
    # Parse start_date from query parameter or default to 7 days ago
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today - timedelta(days=7)
    else:
        start_date = today - timedelta(days=7)
    
    # Parse end_date from query parameter or default to today
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today
    else:
        end_date = today
    
    # Ensure end_date is inclusive (set to end of day)
    time_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    time_end = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
    
    # ============================================================================
    # SECTION 3: Build Base QuerySet with Filters
    # ============================================================================
    readings_qs = SensorReading.objects.filter(
        timestamp__gte=time_start,
        timestamp__lte=time_end
    ).select_related('node')
    
    # Apply node filter (filter by specific SensorNode)
    if selected_node_id:
        try:
            readings_qs = readings_qs.filter(node_id=int(selected_node_id))
        except (ValueError, TypeError):
            pass  # Invalid node ID, ignore filter
    
    # Apply location filter (filter by SensorNode.location)
    if selected_location:
        readings_qs = readings_qs.filter(node__location=selected_location)
    
    # ============================================================================
    # SECTION 4: Compute Aggregate Statistics (ORM-based)
    # ============================================================================
    # Blueprint Rule: All calculations in backend, NOT frontend
    total_readings = readings_qs.count()
    
    # Initialize analytics dict with safe default values
    analytics = {
        'total_readings': total_readings,
        'avg_aqi': None,
        'min_aqi': None,
        'max_aqi': None,
        'avg_pm2_5': None,
        'avg_temperature': None,
        'date_range': f"{start_date} to {end_date}",
        'grouping': grouping,
        'median_aqi': None,  # TODO: Compute median
        'peak_time': None,   # TODO: Find peak time
        'std_dev_aqi': None, # TODO: Compute std dev
    }
    
    # Aggregate with null-safety filters
    if total_readings > 0:
        readings_with_aqi = readings_qs.filter(aqi__isnull=False)
        readings_with_pm = readings_qs.filter(pm2_5__isnull=False)
        readings_with_temp = readings_qs.filter(temperature__isnull=False)
        
        if readings_with_aqi.exists():
            agg_result = readings_with_aqi.aggregate(
                avg_val=models.Avg('aqi'),
                min_val=models.Min('aqi'),
                max_val=models.Max('aqi')
            )
            analytics['avg_aqi'] = round(agg_result['avg_val'], 1) if agg_result['avg_val'] else None
            analytics['min_aqi'] = agg_result['min_val']
            analytics['max_aqi'] = agg_result['max_val']
        
        if readings_with_pm.exists():
            pm_avg = readings_with_pm.aggregate(models.Avg('pm2_5'))['pm2_5__avg']
            analytics['avg_pm2_5'] = round(pm_avg, 2) if pm_avg else None
        
        if readings_with_temp.exists():
            temp_avg = readings_with_temp.aggregate(models.Avg('temperature'))['temperature__avg']
            analytics['avg_temperature'] = round(temp_avg, 1) if temp_avg else None
    
    # ============================================================================
    # SECTION 5: Generate Time-Series Chart Data
    # ============================================================================
    # Select appropriate truncation function based on grouping parameter
    # This allows frontend to display data at the right granularity
    if grouping == 'weekly':
        trunc_func = TruncWeek
        date_format = '%Y-W%V'  # Week format
    elif grouping == 'monthly':
        trunc_func = TruncMonth
        date_format = '%Y-%m'
    else:  # daily
        trunc_func = TruncDay
        date_format = '%Y-%m-%d'
    
    # Compute time-series aggregation: group readings by time period, calculate average AQI, PM2.5, and Temperature
    chart_data_raw = readings_qs.annotate(
        period=trunc_func('timestamp')
    ).values('period').annotate(
        avg_aqi=models.Avg('aqi'),
        avg_pm2_5=models.Avg('pm2_5'),
        avg_temperature=models.Avg('temperature'),
        count=models.Count('id')
    ).order_by('period')
    
    # Format chart data for JSON injection into frontend
    # Chart library (Chart.js) expects: [{date: "YYYY-MM-DD", avg_aqi: 75, avg_pm2_5: 45}, ...]
    chart_data = [
        {
            'date': item['period'].strftime(date_format) if item['period'] else 'N/A',
            'avg_aqi': round(item['avg_aqi'], 1) if item['avg_aqi'] else 0,
            'avg_pm2_5': round(item['avg_pm2_5'], 2) if item['avg_pm2_5'] else None,
            'avg_temperature': round(item['avg_temperature'], 1) if item['avg_temperature'] else None,
            'count': item['count']
        }
        for item in chart_data_raw
    ]
    
    # ============================================================================
    # SECTION 6: Get Available Filters (for dropdown lists)
    # ============================================================================
    # Populate node and location dropdowns for users to select from
    all_nodes = SensorNode.objects.filter(is_active=True).values('id', 'name').order_by('name')
    
    all_locations = SensorNode.objects.filter(
        is_active=True
    ).values_list('location', flat=True).distinct().order_by('location')
    
    # ============================================================================
    # SECTION 7: Network Health Metrics
    # ============================================================================
    # Dynamic System Insights (replaces static template text)
    total_nodes = SensorNode.objects.count()
    active_nodes = SensorNode.objects.filter(is_active=True).count()
    inactive_nodes = total_nodes - active_nodes
    
    # Get timestamp of most recent reading across all nodes
    latest_reading_obj = SensorReading.objects.order_by('-timestamp').first()
    latest_reading_time = latest_reading_obj.timestamp if latest_reading_obj else None
    
    system_health = {
        'total_nodes': total_nodes,
        'active_nodes': active_nodes,
        'inactive_nodes': inactive_nodes,
        'latest_reading_time': latest_reading_time,
        'data_freshness_minutes': int(
            (timezone.now() - latest_reading_time).total_seconds() / 60
        ) if latest_reading_time else None,
    }
    
    # ============================================================================
    # SECTION 7A: Build Node Comparison Data (for bar chart)
    # ============================================================================
    # Aggregate per-node statistics during selected period (useful for identifying hotspots)
    node_comparison_data = []
    
    for node in SensorNode.objects.filter(is_active=True).order_by('name'):
        node_readings = readings_qs.filter(node=node)
        
        if node_readings.count() > 0:
            node_aqi_readings = node_readings.filter(aqi__isnull=False)
            node_pm_readings = node_readings.filter(pm2_5__isnull=False)
            node_temp_readings = node_readings.filter(temperature__isnull=False)
            
            avg_aqi = node_aqi_readings.aggregate(models.Avg('aqi'))['aqi__avg'] if node_aqi_readings.exists() else None
            avg_pm25 = node_pm_readings.aggregate(models.Avg('pm2_5'))['pm2_5__avg'] if node_pm_readings.exists() else None
            avg_temp = node_temp_readings.aggregate(models.Avg('temperature'))['temperature__avg'] if node_temp_readings.exists() else None
            
            node_comparison_data.append({
                'node_name': node.name,
                'avg_aqi': round(avg_aqi, 1) if avg_aqi else None,
                'avg_pm2_5': round(avg_pm25, 2) if avg_pm25 else None,
                'avg_temperature': round(avg_temp, 1) if avg_temp else None,
            })
    
    # ============================================================================
    # SECTION 7B: Build Node Table Data (for status table)
    # ============================================================================
    # Get status and latest reading for each active node
    node_table_data = []
    
    for node in SensorNode.objects.filter(is_active=True).order_by('name'):
        latest_node_reading = node.readings.first()
        
        
        node_readings = readings_qs.filter(node=node)
        if node_readings.count() > 0:
            node_aqi_readings = node_readings.filter(aqi__isnull=False)
            avg_aqi = node_aqi_readings.aggregate(models.Avg('aqi'))['aqi__avg'] if node_aqi_readings.exists() else latest_node_reading.aqi if latest_node_reading else None
        else:
            avg_aqi = latest_node_reading.aqi if latest_node_reading else None
        
        node_table_data.append({
            'name': node.name,
            'location': node.location or 'Unknown',
            'avg_aqi': round(avg_aqi, 1) if avg_aqi else None,
            'is_active': node.status == 'active',
            'last_seen': latest_node_reading.timestamp if latest_node_reading else None,
        })
    
    # ============================================================================
    # SECTION 8: Build Context Dictionary
    # ============================================================================
    context = {
        'analytics': analytics,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),  # Safe for template injection
        'chart_data_list': chart_data,  # For direct iteration (optional)
        
        # Filter values (for form re-population)
        'selected_node_id': selected_node_id,
        'selected_location': selected_location,
        'start_date': start_date_str or start_date.isoformat(),
        'end_date': end_date_str or end_date.isoformat(),
        'selected_grouping': grouping,
        
        # Available options for dropdowns
        'all_nodes': all_nodes,
        'all_locations': all_locations,
        
        # Network health (for System Insights section)
        'system_health': system_health,
        
        # Node comparison and table data (for charts and tables)
        'node_comparison_data': json.dumps(node_comparison_data, cls=DjangoJSONEncoder),
        'node_table_data': node_table_data,
        
        # Advanced analytics (placeholder for future implementation)
        'median_aqi': analytics.get('avg_aqi'),  # TODO: Compute median in backend
        'peak_time': None,  # TODO: Find time with highest AQI
        'std_dev_aqi': None,  # TODO: Compute standard deviation
    }
    
    return render(request, 'AppEnviroNode/admin/clientanalytics.html', context)


@csrf_exempt
@require_http_methods(["GET"])
def api_analytics(request):
    """
    JSON API endpoint for analytics data (future-proof for async updates).
    
    BLUEPRINT COMPLIANCE:
    - Provides same aggregation logic as client_analytics
    - Supports same query parameters
    - Returns pure JSON (no HTML)
    - Ready for frontend fetch() calls or third-party integrations
    
    Query Parameters (same as client_analytics view):
    - node: Filter by SensorNode.id
    - location: Filter by SensorNode.location
    - start_date: YYYY-MM-DD format
    - end_date: YYYY-MM-DD format
    - grouping: 'daily' | 'weekly' | 'monthly'
    
    Response:
    {
      "success": true,
      "analytics": {...},
      "chart_data": [...],
      "system_health": {...}
    }
    """
    from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
    
    try:
        # Parse filters (reuse logic from client_analytics)
        selected_node_id = request.GET.get('node', None)
        selected_location = request.GET.get('location', None)
        start_date_str = request.GET.get('start_date', None)
        end_date_str = request.GET.get('end_date', None)
        grouping = request.GET.get('grouping', 'daily')
        
        if grouping not in ['daily', 'weekly', 'monthly']:
            grouping = 'daily'
        
        # Date range logic (same as client_analytics)
        today = timezone.now().date()
        
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                start_date = today - timedelta(days=7)
        else:
            start_date = today - timedelta(days=7)
        
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                end_date = today
        else:
            end_date = today
        
        time_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        time_end = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        
        # Build base queryset with filters (same as client_analytics)
        readings_qs = SensorReading.objects.filter(
            timestamp__gte=time_start,
            timestamp__lte=time_end
        ).select_related('node')
        
        if selected_node_id:
            try:
                readings_qs = readings_qs.filter(node_id=int(selected_node_id))
            except (ValueError, TypeError):
                pass
        
        if selected_location:
            readings_qs = readings_qs.filter(node__location=selected_location)
        
        # Compute aggregate statistics
        total_readings = readings_qs.count()
        analytics = {
            'total_readings': total_readings,
            'avg_aqi': None,
            'min_aqi': None,
            'max_aqi': None,
            'avg_pm2_5': None,
            'avg_temperature': None,
        }
        
        if total_readings > 0:
            readings_with_aqi = readings_qs.filter(aqi__isnull=False)
            readings_with_pm = readings_qs.filter(pm2_5__isnull=False)
            readings_with_temp = readings_qs.filter(temperature__isnull=False)
            
            if readings_with_aqi.exists():
                agg_result = readings_with_aqi.aggregate(
                    avg_val=models.Avg('aqi'),
                    min_val=models.Min('aqi'),
                    max_val=models.Max('aqi')
                )
                analytics['avg_aqi'] = round(agg_result['avg_val'], 1) if agg_result['avg_val'] else None
                analytics['min_aqi'] = agg_result['min_val']
                analytics['max_aqi'] = agg_result['max_val']
            
            if readings_with_pm.exists():
                pm_avg = readings_with_pm.aggregate(models.Avg('pm2_5'))['pm2_5__avg']
                analytics['avg_pm2_5'] = round(pm_avg, 2) if pm_avg else None
            
            if readings_with_temp.exists():
                temp_avg = readings_with_temp.aggregate(models.Avg('temperature'))['temperature__avg']
                analytics['avg_temperature'] = round(temp_avg, 1) if temp_avg else None
        
        # Chart data generation (same logic)
        if grouping == 'weekly':
            trunc_func = TruncWeek
        elif grouping == 'monthly':
            trunc_func = TruncMonth
        else:
            trunc_func = TruncDay
        
        chart_data_raw = readings_qs.annotate(
            period=trunc_func('timestamp')
        ).values('period').annotate(
            avg_aqi=models.Avg('aqi'),
            avg_pm2_5=models.Avg('pm2_5'),
            avg_temperature=models.Avg('temperature'),
            count=models.Count('id')
        ).order_by('period')
        
        chart_data = [
            {
                'date': item['period'].isoformat() if item['period'] else 'N/A',
                'avg_aqi': round(item['avg_aqi'], 1) if item['avg_aqi'] else 0,
                'avg_pm2_5': round(item['avg_pm2_5'], 2) if item['avg_pm2_5'] else None,
                'avg_temperature': round(item['avg_temperature'], 1) if item['avg_temperature'] else None,
                'count': item['count']
            }
            for item in chart_data_raw
        ]
        
        # System health
        total_nodes = SensorNode.objects.count()
        active_nodes = SensorNode.objects.filter(is_active=True).count()
        latest_reading_obj = SensorReading.objects.order_by('-timestamp').first()
        latest_reading_time = latest_reading_obj.timestamp if latest_reading_obj else None
        
        system_health = {
            'total_nodes': total_nodes,
            'active_nodes': active_nodes,
            'inactive_nodes': total_nodes - active_nodes,
            'latest_reading_time': latest_reading_time.isoformat() if latest_reading_time else None,
        }
        
        return JsonResponse({
            'success': True,
            'analytics': analytics,
            'chart_data': chart_data,
            'system_health': system_health,
            'filters': {
                'node': selected_node_id,
                'location': selected_location,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'grouping': grouping,
            }
        }, status=200)
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required(login_url='app:login')
def client_alerts(request):
    """Display active and resolved alerts from the Alert table."""
    # Get active alerts (most recent first)
    active_alerts = Alert.objects.filter(is_active=True).select_related('node', 'reading').order_by('-triggered_at')
    
    # Get resolved alerts (last 10)
    resolved_alerts = Alert.objects.filter(is_active=False).select_related('node', 'reading').order_by('-resolved_at')[:10]
    
    # Count by severity
    severity_counts = {
        'info': Alert.objects.filter(is_active=True, severity='info').count(),
        'warning': Alert.objects.filter(is_active=True, severity='warning').count(),
        'critical': Alert.objects.filter(is_active=True, severity='critical').count(),
    }
    
    context = {
        'active_alerts': active_alerts,
        'resolved_alerts': resolved_alerts,
        'severity_counts': severity_counts,
        'total_active': active_alerts.count(),
        'total_resolved': resolved_alerts.count(),
    }
    return render(request, 'AppEnviroNode/admin/clientalerts.html', context)

@login_required(login_url='app:login')
@login_required(login_url='app:login')
def client_devices(request):
    """Display all sensor devices/nodes - fully dynamic with CRUD support."""
    # Check and update node statuses before rendering
    check_and_update_node_status()
    
    nodes = SensorNode.objects.all().prefetch_related('readings').order_by('-last_seen')
    
    # Organize nodes by status for comprehensive view
    active_nodes = []
    inactive_nodes = []
    unregistered_nodes = []
    rogue_nodes = []
    
    for node in nodes:
        latest_reading = node.readings.first()
        
        # Calculate uptime if node has readings
        uptime_str = "N/A"
        if node.created_at:
            uptime_days = (timezone.now() - node.created_at).days
            uptime_str = f"{uptime_days} days" if uptime_days > 0 else "< 1 day"
        
        node_data = {
            'node': node,
            'latest_reading': latest_reading,
            'status_display': node.get_status_display() if hasattr(node, 'get_status_display') else node.status.title(),
            'status_color': node.get_status_color(),
            'uptime': uptime_str,
            'last_update': latest_reading.timestamp if latest_reading else node.last_seen,
        }
        
        if node.status == 'active':
            active_nodes.append(node_data)
        elif node.status == 'inactive':
            inactive_nodes.append(node_data)
        elif node.status == 'unregistered':
            unregistered_nodes.append(node_data)
        elif node.status == 'rogue':
            rogue_nodes.append(node_data)
    
    # Combine all nodes in display order: active, inactive, unregistered, rogue
    all_nodes_display = active_nodes + inactive_nodes + unregistered_nodes + rogue_nodes
    
    context = {
        'nodes': all_nodes_display,
        'active_nodes': active_nodes,
        'inactive_nodes': inactive_nodes,
        'unregistered_nodes': unregistered_nodes,
        'rogue_nodes': rogue_nodes,
        'total_nodes': nodes.count(),
        'active_count': len(active_nodes),
        'inactive_count': len(inactive_nodes),
        'unregistered_count': len(unregistered_nodes),
        'rogue_count': len(rogue_nodes),
    }
    return render(request, 'AppEnviroNode/admin/clientdevices.html', context)

@login_required(login_url='app:login')
def client_health(request):
    return render(request, 'AppEnviroNode/admin/clienthealth.html')

@login_required(login_url='app:login')
def client_map_view(request):
    """Display sensor nodes on interactive map for admins."""
    nodes = SensorNode.objects.filter(is_active=True).prefetch_related('readings')
    
    # Create separate lists for each status
    active_nodes = []
    inactive_nodes = []
    unregistered_nodes = []
    rogue_nodes = []
    
    for node in nodes:
        latest_reading = get_latest_reading(node)
        
        # Build the exact dictionary structure your JS needs
        node_data = {
            'node': {
                'id': node.id,
                'name': node.name,
                'location': node.location,
                'latitude': float(node.latitude) if node.latitude else None,
                'longitude': float(node.longitude) if node.longitude else None,
                'mac_address': node.mac_address,
                'status': node.status,
            },
            'latest_reading': {
                'aqi': latest_reading.aqi if latest_reading else None,
                'aqi_level': latest_reading.aqi_level if latest_reading else None,
                'pm2_5': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 else None,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature else None,
                'timestamp': latest_reading.timestamp.isoformat() if latest_reading else None,
            },
            'pollutants': {
                'pm25': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 is not None else 0,
                'pm10': float(latest_reading.pm10) if latest_reading and latest_reading.pm10 is not None else 0,
                'pm1_0': float(latest_reading.pm1_0) if latest_reading and latest_reading.pm1_0 is not None else 0,
                'aqi': latest_reading.aqi if latest_reading and latest_reading.aqi is not None else 0,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature is not None else 0,
                'humidity': float(latest_reading.humidity) if latest_reading and latest_reading.humidity is not None else 0,
            }
        }
        
        # Sort the node_data into the correct list based on its status
        if node.status == 'active':
            active_nodes.append(node_data)
        elif node.status == 'inactive':
            inactive_nodes.append(node_data)
        elif node.status == 'unregistered':
            unregistered_nodes.append(node_data)
        else:
            rogue_nodes.append(node_data)
    
    # Send the categorized lists to the template as JSON
    context = {
        'active_nodes_json': json.dumps(active_nodes, cls=DjangoJSONEncoder),
        'inactive_nodes_json': json.dumps(inactive_nodes, cls=DjangoJSONEncoder),
        'unregistered_nodes_json': json.dumps(unregistered_nodes, cls=DjangoJSONEncoder),
        'rogue_nodes_json': json.dumps(rogue_nodes, cls=DjangoJSONEncoder),
        'total_nodes': nodes.count(),
    }
    return render(request, 'AppEnviroNode/admin/clientmapview.html', context)

@login_required(login_url='app:login')
def node_create(request):
    """Create a new sensor node."""
    if request.method == 'POST':
        form = SensorNodeForm(request.POST)
        if form.is_valid():
            node = form.save()
            messages.success(request, f'Node "{node.name}" created successfully!')
            return redirect('app:client_map')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = SensorNodeForm()
    
    context = {'form': form, 'action': 'Create Node'}
    return render(request, 'AppEnviroNode/admin/node_form.html', context)


@login_required(login_url='app:login')
def node_edit(request, pk):
    """Edit an existing sensor node."""
    node = get_object_or_404(SensorNode, pk=pk)
    
    if request.method == 'POST':
        form = SensorNodeForm(request.POST, instance=node)
        if form.is_valid():
            form.save()
            messages.success(request, f'Node "{node.name}" updated successfully!')
            return redirect('app:client_map')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = SensorNodeForm(instance=node)
    
    context = {'form': form, 'node': node, 'action': 'Edit Node'}
    return render(request, 'AppEnviroNode/admin/node_form.html', context)


@login_required(login_url='app:login')
def node_delete(request, pk):
    """Delete a sensor node."""
    node = get_object_or_404(SensorNode, pk=pk)
    
    if request.method == 'POST':
        node_name = node.name
        node.delete()
        messages.success(request, f'Node "{node_name}" deleted successfully!')
        return redirect('app:client_map')
    
    context = {'node': node}
    return render(request, 'AppEnviroNode/admin/node_confirm_delete.html', context)

@login_required(login_url='app:login')
def client_realtime(request):
    """Display real-time sensor data from all active nodes."""
    # Get all active nodes with latest readings
    nodes = SensorNode.objects.filter(is_active=True, status='active').prefetch_related('readings')
    
    node_data = []
    for node in nodes:
        latest_reading = node.readings.first()
        if latest_reading:
            node_data.append({
                'node': node,
                'reading': latest_reading,
            })
    
    # Get latest overall reading for reference
    latest_overall = SensorReading.objects.filter(node__is_active=True, node__status='active').first()
    
    context = {
        'latest_update': latest_overall.timestamp if latest_overall else None,
        'node_data': node_data,
        'total_nodes': len(node_data),
    }
    return render(request, 'AppEnviroNode/admin/clientrealtime.html', context)

@login_required(login_url='app:login')
@login_required(login_url='app:login')
def client_settings(request):
    return render(request, 'AppEnviroNode/admin/clientsettings.html')

@login_required(login_url='app:login')
@login_required(login_url='app:login')
def client_history(request):
    """
    Enhanced history view with filtering, metrics calculation, and export capabilities.
    Shows unified logs from SystemLog (readings, warnings, device events, admin actions).
    Default shows last 30 days to ensure data is visible on first load.
    """
    # Get filter parameters
    event_type = request.GET.get('event_type', 'all')
    node_id = request.GET.get('node', 'all')
    date_range = request.GET.get('date_range', 'last30')  # Changed default from 'today' to 'last30'
    sensor_type = request.GET.get('sensor_type', 'all')
    severity = request.GET.get('severity', 'all')
    
    # Handle export request
    if request.GET.get('export') == 'csv':
        return export_history_csv(request, event_type, node_id, date_range, sensor_type, severity)
    
    # Build date filter
    now = timezone.now()
    if date_range == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_range == 'last7':
        start_date = now - timedelta(days=7)
    elif date_range == 'last30':
        start_date = now - timedelta(days=30)
    elif date_range == 'custom':
        try:
            custom_start = request.GET.get('start_date')
            if custom_start:
                start_date = timezone.datetime.strptime(custom_start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            else:
                start_date = now - timedelta(days=30)
        except:
            start_date = now - timedelta(days=30)
    else:
        start_date = now - timedelta(days=30)
    
    # Build queryset with filters
    logs_query = SystemLog.objects.select_related('node', 'reading').filter(created_at__gte=start_date).order_by('-created_at')
    
    if event_type != 'all':
        logs_query = logs_query.filter(event_type=event_type)
    
    if node_id != 'all':
        try:
            logs_query = logs_query.filter(node_id=int(node_id))
        except (ValueError, TypeError):
            pass
    
    if sensor_type != 'all':
        logs_query = logs_query.filter(sensor_type=sensor_type)
    
    if severity != 'all':
        logs_query = logs_query.filter(severity=severity)
    
    # Pagination
    paginator = Paginator(logs_query, 15)  # 15 items per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Calculate metrics for the selected date range (from full queryset, not just current page)
    metrics = calculate_history_metrics(logs_query)
    
    # Get all nodes for filter dropdown
    nodes = SensorNode.objects.filter(is_active=True).order_by('name')
    
    # Get unique event types for secondary filtering
    event_types = [
        ('reading', 'Sensor Reading'),
        ('warning', 'Sensor Warning'),
        ('device_online', 'Device Online'),
        ('device_offline', 'Device Offline'),
        ('system', 'System Event'),
        ('admin', 'Admin Action'),
    ]
    
    sensor_types = [
        ('pm2_5', 'PM2.5'),
        ('pm10', 'PM10'),
        ('pm1_0', 'PM1.0'),
        ('temperature', 'Temperature'),
        ('humidity', 'Humidity'),
        ('aqi', 'AQI'),
    ]
    
    severity_levels = [
        ('good', 'Good'),
        ('moderate', 'Moderate'),
        ('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
        ('unhealthy', 'Unhealthy'),
        ('hazardous', 'Hazardous'),
    ]
    
    context = {
        'page_obj': page_obj,
        'logs': page_obj.object_list,
        'metrics': metrics,
        'nodes': nodes,
        'event_types': event_types,
        'sensor_types': sensor_types,
        'severity_levels': severity_levels,
        'selected_event_type': event_type,
        'selected_node': node_id,
        'selected_date_range': date_range,
        'selected_sensor_type': sensor_type,
        'selected_severity': severity,
        'total_logs': logs_query.count(),
    }
    
    return render(request, 'AppEnviroNode/admin/clienthistory.html', context)


def calculate_history_metrics(logs_queryset):
    """
    Calculate aggregated metrics from SystemLog queryset.
    Returns dict with: total_events, normal_readings, warnings, system_events, highest_aqi, most_active_node
    """
    # Count by event type
    total_events = logs_queryset.count()
    normal_readings = logs_queryset.filter(event_type='reading', severity='good').count()
    warnings = logs_queryset.filter(
        Q(event_type='warning') | 
        Q(event_type='reading', severity__in=['moderate', 'unhealthy_sensitive', 'unhealthy', 'hazardous'])
    ).count()
    system_events = logs_queryset.filter(event_type__in=['device_online', 'device_offline', 'system', 'admin']).count()
    
    # Get highest AQI
    highest_aqi_log = logs_queryset.filter(event_type='reading', value__isnull=False).order_by('-value').first()
    highest_aqi = highest_aqi_log.value if highest_aqi_log else 0
    
    # Get most active node
    most_active = logs_queryset.values('node__name').annotate(count=Count('id')).order_by('-count').first()
    most_active_node = most_active['node__name'] if most_active else 'N/A'
    
    return {
        'total_events': total_events,
        'normal_readings': normal_readings,
        'warnings': warnings,
        'system_events': system_events,
        'highest_aqi': highest_aqi,
        'most_active_node': most_active_node,
    }


def export_history_csv(request, event_type, node_id, date_range, sensor_type, severity):
    """
    Export filtered history logs as CSV.
    """
    # Build the same filtered queryset as in client_history
    now = timezone.now()
    if date_range == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_range == 'last7':
        start_date = now - timedelta(days=7)
    elif date_range == 'last30':
        start_date = now - timedelta(days=30)
    else:
        start_date = now - timedelta(days=30)
    
    logs = SystemLog.objects.select_related('node', 'reading').filter(created_at__gte=start_date)
    
    if event_type != 'all':
        logs = logs.filter(event_type=event_type)
    if node_id != 'all':
        try:
            logs = logs.filter(node_id=int(node_id))
        except (ValueError, TypeError):
            pass
    if sensor_type != 'all':
        logs = logs.filter(sensor_type=sensor_type)
    if severity != 'all':
        logs = logs.filter(severity=severity)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="history_{now.strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'Event Type', 'Node', 'Severity', 'Sensor Type', 'Value', 'Message'])
    
    for log in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.get_event_type_display(),
            log.node.name if log.node else 'System',
            log.get_severity_display() if log.severity else 'N/A',
            log.get_sensor_type_display() if log.sensor_type else 'N/A',
            log.value or '',
            log.message,
        ])
    
    return response


@login_required(login_url='app:login')
def client_users(request):
    return render(request, 'AppEnviroNode/admin/clientusers.html')

@login_required(login_url='app:login')
def client_ai(request):
    return render(request, 'AppEnviroNode/admin/clientai.html')

@require_http_methods(["POST"])
def api_enviro_ai_chat(request):
    """
    POST /api/chat/
    """
    try:
        body = json.loads(request.body)
        user_message = body.get('message', '').strip()

        if not user_message:
            return JsonResponse({'success': False, 'reply': 'No message provided.'}, status=400)

        latest = SensorReading.objects.filter(
            node__is_active=True
        ).order_by('-timestamp').first()

        aqi       = latest.aqi if latest else None
        aqi_level = latest.get_aqi_level_display() if latest and latest.aqi_level else None

        reply = ask_enviro_ai(user_message, aqi, aqi_level)
        return JsonResponse({'success': True, 'reply': reply})

    except Exception as e:
        return JsonResponse({'success': False, 'reply': 'Something went wrong.'}, status=500)


@login_required(login_url='app:login')
@require_http_methods(["GET"])
def api_ai_insights(request):
    from .ai import generate_ai_insights

    total_nodes  = SensorNode.objects.count()
    active_nodes = SensorNode.objects.filter(status='active').count()
    time_threshold = timezone.now() - timedelta(days=7)
    readings = SensorReading.objects.filter(timestamp__gte=time_threshold)

    agg = readings.aggregate(
        avg_aqi=Avg('aqi'),
        max_aqi=Max('aqi'),
        min_aqi=Min('aqi'),
        avg_pm2_5=Avg('pm2_5'),
        avg_temp=Avg('temperature'),
    )

    sensor_summary = {
        'avg_aqi':        round(agg['avg_aqi'], 1)   if agg['avg_aqi']   else None,
        'max_aqi':        agg['max_aqi'],
        'min_aqi':        agg['min_aqi'],
        'avg_pm2_5':      round(agg['avg_pm2_5'], 2) if agg['avg_pm2_5'] else None,
        'avg_temp':       round(agg['avg_temp'], 1)  if agg['avg_temp']  else None,
        'total_readings': readings.count(),
        'active_nodes':   active_nodes,
        'inactive_nodes': total_nodes - active_nodes,
        'critical_alerts': Alert.objects.filter(
            is_active=True, severity='critical'
        ).count(),
    }

    insights = generate_ai_insights(sensor_summary)

    return JsonResponse({
        'success': True,
        'insights': insights,
        'sensor_summary': sensor_summary,
    })

# API ENDPOINTS for ESP8266 Sensor Integration
@csrf_exempt
@require_http_methods(["POST"])
def api_sensor_data(request):
    """
    Receive sensor data from ESP8266 nodes.
    Expected JSON: {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "pm1_0": 10.5,
        "pm2_5": 25.3,
        "pm10": 45.2,
        "temperature": 28.5,
        "humidity": 65.0,
        "pressure": 1013.25,
        "gas_resistance": 120.5
    }
    """
    try:
        # Decode request body to string if it's bytes
        if isinstance(request.body, bytes):
            body_str = request.body.decode('utf-8')
        else:
            body_str = request.body
        
        # Log incoming request for debugging
        print(f"[API DEBUG] Incoming request body: {body_str}")
        
        # Parse JSON
        data = json.loads(body_str)
        print(f"[API DEBUG] Parsed data: {data}")
        
        mac_address = data.get('mac_address')
        
        if not mac_address:
            print("[API ERROR] MAC address missing")
            return JsonResponse({'success': False, 'message': 'MAC address is required'}, status=400)
        
        print(f"[API DEBUG] Processing MAC: {mac_address}")
        
        # Get or create sensor node with proper status handling
        node, created = SensorNode.objects.get_or_create(
            mac_address=mac_address,
            defaults={
                'name': f"Unregistered Node",
                'status': 'unregistered',
                'organization': data.get('organization', 'EMBO'),
                'location': data.get('location', 'Unknown'),
            }
        )
        print(f"[API DEBUG] Node {'created' if created else 'found'}: {node.name}")
        
        # Update node status to active (receiving data)
        if node.status != 'active':
            node.status = 'active'
            print(f"[API DEBUG] Node status updated to 'active'")
        
        # Create sensor reading
        reading = SensorReading.objects.create(
            node=node,
            pm1_0=data.get('pm1_0'),
            pm2_5=data.get('pm2_5'),
            pm10=data.get('pm10'),
            temperature=data.get('temperature'),
            humidity=data.get('humidity'),
            pressure=data.get('pressure'),
            gas_resistance=data.get('gas_resistance'),
        )
        print(f"[API DEBUG] Reading created: {reading.id}, AQI: {reading.aqi}")
        
        # Update node's last_reading and last_seen timestamps
        node.last_reading = timezone.now()
        node.last_seen = timezone.now()
        node.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Reading recorded successfully',
            'reading_id': reading.id,
            'node_status': node.status,
            'aqi': reading.aqi,
            'aqi_level': reading.aqi_level,
        }, status=201)
        
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON: {str(e)}"
        print(f"[API ERROR] {error_msg}")
        return JsonResponse({'success': False, 'message': error_msg}, status=400)
    
    except ValueError as e:
        error_msg = f"Value error: {str(e)}"
        print(f"[API ERROR] {error_msg}")
        return JsonResponse({'success': False, 'message': error_msg}, status=400)
    
    except Exception as e:
        error_msg = f"Server error: {str(e)}"
        print(f"[API ERROR] {error_msg}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': error_msg}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_sensor_latest(request):
    """
    API endpoint to get the absolute latest reading and node details (used for sparklines).
    """
    node_id = request.GET.get('node_id')
    if not node_id:
        return JsonResponse({'success': False, 'error': 'Node ID required'})
        
    try:
        node = SensorNode.objects.get(id=node_id)
        latest = node.readings.first()
        
        # Get 6h trend for sparkline
        six_hours_ago = timezone.now() - timedelta(hours=6)
        recent_readings = node.readings.filter(
            timestamp__gte=six_hours_ago
        ).order_by('timestamp')
        
        sparkline_data = []
        for i, reading in enumerate(recent_readings):
            sparkline_data.append({
                'label': f'{reading.timestamp.hour}h',
               
                'value': reading.aqi or 0  
            })
        
        # Get 24h peak
        day_ago = timezone.now() - timedelta(hours=24)
        day_readings = node.readings.filter(timestamp__gte=day_ago)
        peak_aqi = day_readings.aggregate(Max('aqi'))['aqi__max'] or 0
        
        return JsonResponse({
            'success': True,
            'id': node.id,
            'name': node.name,
            'location': node.location,
            'status': node.status,
            'aqi_current': round(latest.aqi or 0, 1) if latest else 0, 
            'pm2_5': round(latest.pm2_5 or 0, 1) if latest else 0,
            'pm10': round(latest.pm10 or 0, 1) if latest else 0,
            'temperature': round(latest.temperature or 0, 1) if latest else 0,
            'humidity': round(latest.humidity or 0, 1) if latest else 0,
            'peak_24h': round(peak_aqi, 1),
            'sparkline_data': sparkline_data,
            'last_reading_time': latest.timestamp.isoformat() if latest else None,
        })
    except SensorNode.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Node not found'})

@csrf_exempt
@require_http_methods(["GET"])
def api_sensor_node_history(request, node_id):
    """
    Get historical sensor data for a specific node (last 24 hours).
    API endpoint - accessible without authentication.
    """
    try:
        node = SensorNode.objects.get(id=node_id)
        
        # Get readings from last 24 hours
        time_threshold = timezone.now() - timedelta(hours=24)
        readings = node.readings.filter(timestamp__gte=time_threshold)
        
        data = {
            'node_id': node.id,
            'name': node.name,
            'mac_address': node.mac_address,
            'location': node.location,
            'readings': []
        }
        
        for reading in readings:
            data['readings'].append({
                'id': reading.id,
                'pm1_0': reading.pm1_0,
                'pm2_5': reading.pm2_5,
                'pm10': reading.pm10,
                'temperature': reading.temperature,
                'humidity': reading.humidity,
                'pressure': reading.pressure,
                'gas_resistance': reading.gas_resistance,
                'aqi': reading.aqi,
                'aqi_level': reading.aqi_level,
                'timestamp': reading.timestamp.isoformat(),
            })
        
        return JsonResponse({'success': True, 'data': data, 'count': len(data['readings'])}, status=200)
        
    except SensorNode.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Node not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================================
# ANALYTICS API ENDPOINTS (For Dynamic Dashboard)
# ============================================================================
# New endpoints to support enviro-analytics.js dynamic dashboard
# These endpoints provide data in JSON format for AJAX/fetch() calls
# Uses existing models without schema changes

@csrf_exempt
@require_http_methods(["GET"])
def api_analytics_overview(request):
    """
    GET /api/analytics/overview/
    
    Returns current aggregate analytics data:
    - Current AQI value
    - Pollutant composition percentages
    - Individual pollutant values
    - Risk distribution percentages
    
    Query Parameters:
    - timeframe: '24h', '7d', '30d' (default: '7d')
    - node_id: Specific node ID or 'all' (default: 'all')
    """
    try:
        timeframe = request.GET.get('timeframe', '7d')
        node_id = request.GET.get('node_id', 'all')
        
        # Determine time window
        time_map = {'24h': 1, '7d': 7, '30d': 30}
        days = time_map.get(timeframe, 7)
        time_threshold = timezone.now() - timedelta(days=days)
        
        # Build queryset
        readings_qs = SensorReading.objects.filter(
            timestamp__gte=time_threshold,
            aqi__isnull=False,
            pm2_5__isnull=False
        ).select_related('node')
        
        if node_id != 'all':
            try:
                readings_qs = readings_qs.filter(node_id=int(node_id))
            except (ValueError, TypeError):
                pass
        
        # Aggregate metrics
        agg = readings_qs.aggregate(
            aqi_avg=Avg('aqi'),
            aqi_max=Max('aqi'),
            aqi_min=Min('aqi'),
            pm25_avg=Avg('pm2_5'),
            pm10_avg=Avg('pm10'),
            temp_avg=Avg('temperature'),
            gas_res_avg=Avg('gas_resistance'),
        )
        
        current_aqi = agg['aqi_avg'] or 75
        
        # Composition: estimate from PM2.5 and PM10
        pm25_val = agg['pm25_avg'] or 25
        pm10_val = agg['pm10_avg'] or 40
        total_pm = pm25_val + pm10_val
        
        pm25_pct = int((pm25_val / total_pm * 100)) if total_pm > 0 else 50
        pm10_pct = int((pm10_val / total_pm * 100)) if total_pm > 0 else 30
        other_pct = 100 - pm25_pct - pm10_pct
        
        # Risk distribution (based on AQI thresholds)
        total = readings_qs.count()
        risk_stable = readings_qs.filter(aqi__lte=50).count()
        risk_elevated = readings_qs.filter(aqi__gt=50, aqi__lte=150).count()
        risk_critical = readings_qs.filter(aqi__gt=150).count()
        
        stable_pct = int((risk_stable / total * 100)) if total > 0 else 60
        elevated_pct = int((risk_elevated / total * 100)) if total > 0 else 25
        critical_pct = 100 - stable_pct - elevated_pct
        
        return JsonResponse({
            'success': True,
            'aqi_current': round(current_aqi, 1),
            'aqi_max': round(agg['aqi_max'] or 0, 1),
            'aqi_min': round(agg['aqi_min'] or 0, 1),
            'composition': {
                'pm25': pm25_pct,
                'pm10': pm10_pct,
                'other': other_pct
            },
            'pm2_5': round(pm25_val, 1),
            'pm10': round(pm10_val, 1),
            'gas_resistance': round(agg['gas_res_avg'] or 0, 1),
            'temperature': round(agg['temp_avg'] or 28, 1),
            'risk_stable': stable_pct,
            'risk_elevated': elevated_pct,
            'risk_critical': critical_pct,
            'timeframe': timeframe,
            'data_points': readings_qs.count()
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_list(request):
    """
    GET /api/nodes/
    
    Returns list of all sensor nodes with latest data
    """
    try:
        nodes = SensorNode.objects.filter(
            status__in=['active', 'inactive', 'warning', 'rogue']
        ).order_by('name')
        
        nodes_data = []
        for node in nodes:
            latest = node.readings.order_by('-timestamp').first()
            
            trend_direction = 'stable'
            if latest and len(nodes_data) > 0:
                prev_aqi = nodes_data[-1].get('aqi_current', latest.aqi or 0)
                curr_aqi = latest.aqi or 0
                if curr_aqi > prev_aqi:
                    trend_direction = 'up'
                elif curr_aqi < prev_aqi:
                    trend_direction = 'down'
            
            nodes_data.append({
                'id': node.id,
                'name': node.name,
                'mac_address': node.mac_address,
                'location': node.location,
                'status': node.status,
                'aqi_current': round(latest.aqi or 0, 1) if latest else 0,
                'pm2_5': round(latest.pm2_5 or 0, 1) if latest else 0,
                'pm10': round(latest.pm10 or 0, 1) if latest else 0,
                'temperature': round(latest.temperature or 0, 1) if latest else 0,
                'last_seen': latest.timestamp.isoformat() if latest else None,
                'trend_direction': trend_direction
            })
        
        return JsonResponse({
            'success': True,
            'count': len(nodes_data),
            'results': nodes_data
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_node_detail(request, node_id):
    """
    GET /api/nodes/<node_id>/detail/
    
    Returns detailed data for a specific node:
    - Current readings
    - 24-hour sparkline data
    - Peak values
    - Status
    """
    try:
        node = SensorNode.objects.get(id=node_id)
        latest = node.readings.order_by('-timestamp').first()
        
        # Get last 6 hours for sparkline (hourly averages)
        six_hours_ago = timezone.now() - timedelta(hours=6)
        recent_readings = node.readings.filter(
            timestamp__gte=six_hours_ago
        ).order_by('timestamp')
        
        sparkline_data = []
        for i, reading in enumerate(recent_readings):
            sparkline_data.append({
                'label': f'{reading.timestamp.hour}h',
                'value': reading.aqi or 0
            })
        
        # Get 24h peak
        day_ago = timezone.now() - timedelta(hours=24)
        day_readings = node.readings.filter(timestamp__gte=day_ago)
        peak_aqi = day_readings.aggregate(Max('aqi'))['aqi__max'] or 0
        
        return JsonResponse({
            'success': True,
            'id': node.id,
            'name': node.name,
            'location': node.location,
            'status': node.status,
            'aqi_current': round(latest.aqi or 0, 1) if latest else 0,
            'pm2_5': round(latest.pm2_5 or 0, 1) if latest else 0,
            'pm10': round(latest.pm10 or 0, 1) if latest else 0,
            'temperature': round(latest.temperature or 0, 1) if latest else 0,
            'humidity': round(latest.humidity or 0, 1) if latest else 0,
            'peak_24h': round(peak_aqi, 1),
            'sparkline_data': sparkline_data,
            'last_reading_time': latest.timestamp.isoformat() if latest else None
        }, status=200)
        
    except SensorNode.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Node not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_analytics_trends(request):
    """
    GET /api/analytics/trends/
    
    Returns time-series trend data for charts
    
    Query Parameters:
    - timeframe: '24h', '7d', '30d' (default: '7d')
    - metric: 'aqi', 'pm25', 'pm10', 'temp' (default: 'aqi')
    - node_id: Specific node ID or 'all' (default: 'all')
    """
    try:
        timeframe = request.GET.get('timeframe', '7d')
        metric = request.GET.get('metric', 'aqi')
        node_id = request.GET.get('node_id', 'all')
        
        # Determine time window
        time_map = {'24h': 1, '7d': 7, '30d': 30}
        days = time_map.get(timeframe, 7)
        time_threshold = timezone.now() - timedelta(days=days)
        
        # Build queryset
        readings_qs = SensorReading.objects.filter(
            timestamp__gte=time_threshold
        ).select_related('node').order_by('timestamp')
        
        if node_id != 'all':
            try:
                readings_qs = readings_qs.filter(node_id=int(node_id))
            except (ValueError, TypeError):
                pass
        
        # Aggregate by day if more than 24h
        if days > 1:
            from django.db.models.functions import TruncDay
            readings_qs = readings_qs.annotate(
                day=TruncDay('timestamp')
            ).values('day').annotate(
                avg_val=Avg(metric if metric != 'aqi' else 'aqi'),
                avg_pm25=Avg('pm2_5'),
                avg_pm10=Avg('pm10'),
                avg_temp=Avg('temperature')
            ).order_by('day')
            
            datapoints = []
            metric_map = {'aqi': 'avg_val', 'pm25': 'avg_pm25', 'pm10': 'avg_pm10', 'temp': 'avg_temp'}
            metric_key = metric_map.get(metric, 'avg_val')
            
            for item in readings_qs:
                datapoints.append({
                    'date': item['day'].strftime('%b %d'),
                    'label': item['day'].strftime('%b %d'),
                    'value': round(item[metric_key] or 0, 1)
                })
        else:
            # Hourly for 24h
            datapoints = []
            for reading in readings_qs:
                metric_val = {
                    'aqi': reading.aqi,
                    'pm25': reading.pm2_5,
                    'pm10': reading.pm10,
                    'temp': reading.temperature
                }.get(metric, reading.aqi)
                datapoints.append({
                    'date': reading.timestamp.strftime('%H:%M'),
                    'label': reading.timestamp.strftime('%H:%M'),
                    'value': round(metric_val or 0, 1)
                })
        
        return JsonResponse({
            'success': True,
            'metric': metric,
            'timeframe': timeframe,
            'datapoints': datapoints,
            'count': len(datapoints)
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_analytics_system_health(request):
    """
    GET /api/analytics/system-health/
    
    Returns system health metrics:
    - Network uptime
    - Latency
    - Data quality
    - Anomaly count
    """
    try:
        # Calculate uptime (active nodes / total nodes)
        total_nodes = SensorNode.objects.exclude(status='unregistered').count()
        active_nodes = SensorNode.objects.filter(status='active').count()
        uptime = (active_nodes / total_nodes * 100) if total_nodes > 0 else 0
        
        # Calculate data freshness (minutes since last reading)
        latest_reading = SensorReading.objects.order_by('-timestamp').first()
        if latest_reading:
            time_diff = (timezone.now() - latest_reading.timestamp).total_seconds() / 60
            freshness = max(0, 60 - int(time_diff))  # Minutes fresh (max 60)
        else:
            freshness = 0
        
        # Simulate latency (would come from actual measurements)
        latency = 1.2
        
        # Count anomalies (readings with extreme values)
        anomalies = SensorReading.objects.filter(
            Q(aqi__gt=300) | Q(pm2_5__gt=200) | Q(temperature__gt=50)
        ).count()
        
        return JsonResponse({
            'success': True,
            'uptime': round(uptime, 1),
            'latency': latency,
            'anomalies': anomalies,
            'data_freshness_minutes': int(freshness),
            'active_nodes': active_nodes,
            'total_nodes': total_nodes
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def parse_realtime_filters(request):
    selected_node_id = None
    node_param = request.GET.get('node')
    if node_param:
        try:
            selected_node_id = int(node_param)
        except (TypeError, ValueError):
            selected_node_id = None

    selected_range = request.GET.get('range', '24h').lower()
    if selected_range not in ['24h', '7d', '30d', 'custom']:
        selected_range = '24h'

    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    now = timezone.now()

    if selected_range == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            time_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
            time_end = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        except ValueError:
            selected_range = '7d'
            time_end = now
            time_start = now - timedelta(days=7)
            start_date_str = time_start.date().isoformat()
            end_date_str = time_end.date().isoformat()
    elif selected_range == '7d':
        time_end = now
        time_start = now - timedelta(days=7)
        start_date_str = time_start.date().isoformat()
        end_date_str = time_end.date().isoformat()
    elif selected_range == '30d':
        time_end = now
        time_start = now - timedelta(days=30)
        start_date_str = time_start.date().isoformat()
        end_date_str = time_end.date().isoformat()
    else:
        time_end = now
        time_start = now - timedelta(hours=24)
        start_date_str = time_start.date().isoformat()
        end_date_str = time_end.date().isoformat()

    if selected_range == 'custom' and start_date_str and end_date_str:
        range_label = f"{start_date_str} to {end_date_str}"
    elif selected_range == '7d':
        range_label = 'Last 7 days'
    elif selected_range == '30d':
        range_label = 'Last 30 days'
    else:
        range_label = 'Last 24 hours'

    return {
        'selected_node_id': selected_node_id,
        'selected_range': selected_range,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'time_start': time_start,
        'time_end': time_end,
        'range_label': range_label,
    }


def build_realtime_filters(request):
    selected_node = request.GET.get('node', '').strip()
    selected_node_id = None
    selected_location = None

    if selected_node.startswith('node:'):
        try:
            selected_node_id = int(selected_node.split(':', 1)[1])
        except (TypeError, ValueError):
            selected_node_id = None
    elif selected_node.startswith('location:'):
        selected_location = urllib.parse.unquote_plus(selected_node.split(':', 1)[1])

    selected_range = request.GET.get('range', '24h').lower()
    if selected_range not in ['24h', '7d', '30d', 'custom']:
        selected_range = '24h'

    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    now = timezone.now()

    if selected_range == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            time_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
            time_end = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        except ValueError:
            selected_range = '7d'
            time_end = now
            time_start = now - timedelta(days=7)
            start_date_str = time_start.date().isoformat()
            end_date_str = time_end.date().isoformat()
    elif selected_range == '7d':
        time_end = now
        time_start = now - timedelta(days=7)
        start_date_str = time_start.date().isoformat()
        end_date_str = time_end.date().isoformat()
    elif selected_range == '30d':
        time_end = now
        time_start = now - timedelta(days=30)
        start_date_str = time_start.date().isoformat()
        end_date_str = time_end.date().isoformat()
    else:
        time_end = now
        time_start = now - timedelta(hours=24)
        start_date_str = time_start.date().isoformat()
        end_date_str = time_end.date().isoformat()

    if selected_range == 'custom' and start_date_str and end_date_str:
        range_label = f"{start_date_str} to {end_date_str}"
    elif selected_range == '7d':
        range_label = 'Last 7 days'
    elif selected_range == '30d':
        range_label = 'Last 30 days'
    else:
        range_label = 'Last 24 hours'

    return {
        'selected_node': selected_node,
        'selected_node_id': selected_node_id,
        'selected_location': selected_location,
        'selected_range': selected_range,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'time_start': time_start,
        'time_end': time_end,
        'range_label': range_label,
    }


def build_realtime_queryset(filters):
    readings_qs = SensorReading.objects.select_related('node').filter(
        timestamp__gte=filters['time_start'],
        timestamp__lte=filters['time_end']
    )
    if filters['selected_node_id']:
        readings_qs = readings_qs.filter(node_id=filters['selected_node_id'])
    elif filters.get('selected_location'):
        location = filters['selected_location']
        if location.lower() == 'unknown':
            readings_qs = readings_qs.filter(models.Q(node__location__isnull=True) | models.Q(node__location__exact=''))
        else:
            readings_qs = readings_qs.filter(node__location=location)
    return readings_qs


def build_realtime_chart_data(readings_qs, selected_range):
    from django.db.models.functions import TruncDay, TruncHour

    if selected_range == '24h':
        trunc_func = TruncHour
    else:
        trunc_func = TruncDay

    chart_data_raw = readings_qs.annotate(
        period=trunc_func('timestamp')
    ).values('period').annotate(
        avg_aqi=Avg('aqi'),
        avg_pm2_5=Avg('pm2_5'),
        avg_pm10=Avg('pm10'),
        avg_temperature=Avg('temperature')
    ).order_by('period')

    return [
        {
            'period': item['period'].isoformat() if item['period'] else '',
            'avg_aqi': round(item['avg_aqi'], 1) if item['avg_aqi'] is not None else None,
            'avg_pm2_5': round(item['avg_pm2_5'], 2) if item['avg_pm2_5'] is not None else None,
            'avg_pm10': round(item['avg_pm10'], 2) if item['avg_pm10'] is not None else None,
            'avg_temperature': round(item['avg_temperature'], 1) if item['avg_temperature'] is not None else None,
        }
        for item in chart_data_raw
    ]



def api_realtime_data(request):
    """
    API endpoint for real-time sensor data.
    """
    latest_readings = []
    nodes = SensorNode.objects.filter(is_active=True).prefetch_related('readings')
    
    for node in nodes:
        reading = node.readings.first()
        if reading:
            latest_readings.append({
                'node_id': node.id,
                'name': node.name,
                'location': node.location,
                'aqi': reading.aqi,
                'pm2_5': reading.pm2_5,
                'pm10': reading.pm10,
                'temperature': reading.temperature,
                'humidity': reading.humidity,
                'timestamp': reading.timestamp.isoformat()
            })
            
    return JsonResponse({'status': 'success', 'data': latest_readings})


@require_http_methods(["GET"])
def api_daily_forecast(request):
    """Return a simple 4-day forecast container from recent sensor data."""
    from django.utils import timezone
    from datetime import timedelta

    now = timezone.now()
    earliest = now - timedelta(days=4)

    readings_qs = SensorReading.objects.filter(
        timestamp__gte=earliest,
        timestamp__lte=now,
        aqi__isnull=False
    ).select_related('node').order_by('-timestamp')

    day_groups = {}
    segments = [
        ('morning', 5, 12, 'Morning', 'forecast-morning'),
        ('afternoon', 12, 17, 'Afternoon', 'forecast-afternoon'),
        ('evening', 17, 23, 'Evening', 'forecast-evening'),
    ]

    for reading in readings_qs:
        local_date = reading.timestamp.astimezone(timezone.get_current_timezone()).date()
        if local_date not in day_groups:
            day_groups[local_date] = {
                'date': local_date,
                'segments': {key: [] for key, *_ in segments},
                'summary': {
                    'aqi': [],
                    'pm2_5': [],
                    'temperature': []
                }
            }

        hour = reading.timestamp.astimezone(timezone.get_current_timezone()).hour
        for key, start, end, label, css_class in segments:
            if start <= hour < end:
                day_groups[local_date]['segments'][key].append(reading)
                break

        if reading.aqi is not None:
            day_groups[local_date]['summary']['aqi'].append(reading.aqi)
        if reading.pm2_5 is not None:
            day_groups[local_date]['summary']['pm2_5'].append(reading.pm2_5)
        if reading.temperature is not None:
            day_groups[local_date]['summary']['temperature'].append(reading.temperature)

    forecast = []
    sorted_days = sorted(day_groups.keys(), reverse=True)[:4]
    for day in sorted_days:
        group = day_groups[day]
        daily_segments = []
        for key, start, end, label, css_class in segments:
            readings = group['segments'][key]
            avg_aqi = round(sum([r.aqi for r in readings]) / len(readings), 0) if readings else None
            avg_pm2_5 = round(sum([r.pm2_5 for r in readings if r.pm2_5 is not None]) / len([r for r in readings if r.pm2_5 is not None]), 1) if readings and any(r.pm2_5 is not None for r in readings) else None
            avg_temp = round(sum([r.temperature for r in readings if r.temperature is not None]) / len([r for r in readings if r.temperature is not None]), 0) if readings and any(r.temperature is not None for r in readings) else None

            daily_segments.append({
                'period': label,
                'aqi': avg_aqi,
                'pm2_5': avg_pm2_5,
                'temperature': avg_temp,
                'css_class': css_class
            })

        summary = {
            'avg_aqi': round(sum(group['summary']['aqi']) / len(group['summary']['aqi']), 0) if group['summary']['aqi'] else None,
            'avg_pm2_5': round(sum(group['summary']['pm2_5']) / len(group['summary']['pm2_5']), 1) if group['summary']['pm2_5'] else None,
            'avg_temperature': round(sum(group['summary']['temperature']) / len(group['summary']['temperature']), 0) if group['summary']['temperature'] else None,
        }

        forecast.append({
            'day_label': day.strftime('%A'),
            'day_subtitle': day.strftime('%b %d, %Y'),
            'segments': daily_segments,
            'summary': summary
        })

    if not forecast:
        sample_days = []
        for days_back, label in [(4, 'Thursday'), (3, 'Friday'), (2, 'Saturday'), (1, 'Sunday')]:
            sample_days.append({
                'day_label': label,
                'day_subtitle': (now - timedelta(days=days_back)).strftime('%b %d, %Y'),
                'segments': [
                    {'period': 'Morning', 'aqi': 67, 'pm2_5': 38, 'temperature': 26, 'css_class': 'forecast-morning'},
                    {'period': 'Afternoon', 'aqi': 95, 'pm2_5': 46, 'temperature': 30, 'css_class': 'forecast-afternoon'},
                    {'period': 'Evening', 'aqi': 112, 'pm2_5': 46, 'temperature': 27, 'css_class': 'forecast-evening'},
                ],
                'summary': {'avg_aqi': 91, 'avg_pm2_5': 43, 'avg_temperature': 28}
            })
        forecast = sample_days

    return JsonResponse({
        'success': True,
        'forecast': forecast
    })