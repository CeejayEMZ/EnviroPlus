from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import models
from django.db.models import Q, Max, Count, Avg, Min
from django.core.serializers.json import DjangoJSONEncoder
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.utils.crypto import get_random_string
from django.template.loader import render_to_string
from django.conf import settings
from django.views.decorators.cache import cache_page
from functools import wraps
from .forms import ProductForm
import requests
from requests.auth import HTTPBasicAuth
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Sum, Q

# File processing and standard libraries
import csv
import io
import logging
import base64
import hashlib
import json
import urllib.parse
import re
from datetime import timedelta, datetime

# --- SYSTEM AUDIT LOG SIGNALS ---
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

# External packages
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

# Local app imports
from .ai import ask_enviro_ai, generate_ai_insights
from .forms import CustomAuthenticationForm, CustomUserCreationForm, PasswordResetRequestForm, SensorNodeForm
from .models import HardwareRequest, SensorNode, SensorReading, Alert, SystemLog, AdminActionLog, Product, Order
from .services import EmailService

def validate_password_strength(password):
    """
    Checks if a password meets strict security requirements:
    - Minimum 12 characters
    - At least 1 uppercase letter
    - At least 1 number
    - At least 1 special character
    """
    if not password or len(password) < 12:
        return False, 'Password must be at least 12 characters long.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number.'
    if not re.search(r'[^a-zA-Z0-9]', password):
        return False, 'Password must contain at least one special character.'
    
    return True, ''

logger = logging.getLogger(__name__)
User = get_user_model()

# ============================================================================
# OPTIMIZATION: Simple in-memory caching decorator (30-60 seconds)
# ============================================================================
_api_cache = {}

def cache_api_response(ttl_seconds=45):
    """Decorator to cache API responses by request parameters."""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Build cache key from function name and query params
            cache_key = f"{func.__name__}_{hashlib.md5(request.GET.urlencode().encode()).hexdigest()}"
            
            # Check cache
            cached = _api_cache.get(cache_key)
            if cached:
                expiry, response = cached
                if timezone.now().timestamp() < expiry:
                    return response
                else:
                    del _api_cache[cache_key]
            
            # Execute view and cache result
            response = func(request, *args, **kwargs)
            _api_cache[cache_key] = (timezone.now().timestamp() + ttl_seconds, response)
            return response
        return wrapper
    return decorator


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('app:login')
        if request.user.role != 'admin':
            messages.error(request, 'Access denied. Administrator privileges required.')
            return redirect('app:client_dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


# ============================================================================
# OPTIMIZATION: Adaptive aggregation strategy
# ============================================================================
def get_aggregation_strategy(days_span):
    """
    Determine aggregation based on date range:
    - 24h → minute aggregation (up to 60 points)
    - 7d → hourly aggregation (up to 168 points)
    - 30d → daily aggregation (30 points)
    - custom → auto-select based on range size
    """
    if days_span <= 1:
        return 'minute'  # 24h
    elif days_span <= 7:
        return 'hour'    # 7d
    else:
        return 'day'     # 30d+

def format_time_ago(dt):
    """Format datetime as relative time string."""
    if not dt:
        return 'Never'
    now = timezone.now()
    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    else:
        return f"{int(seconds // 86400)}d ago"

def aggregate_readings(readings_qs, strategy, metric_field):
    """Aggregate sensor readings based on strategy."""
    from django.db.models.functions import TruncMinute, TruncHour, TruncDay
    
    if strategy == 'minute':
        trunc_func = TruncMinute
        grouping_fmt = '%H:%M'
    elif strategy == 'hour':
        trunc_func = TruncHour
        grouping_fmt = '%b %d %H:%M'
    else:  # day
        trunc_func = TruncDay
        grouping_fmt = '%b %d'
    
    aggregated = readings_qs.annotate(
        period=trunc_func('timestamp')
    ).values('period').annotate(
        avg_val=Avg(metric_field)
    ).order_by('period')
    
    return aggregated, trunc_func, grouping_fmt

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
    latest_per_node = SensorReading.objects.filter(node=models.OuterRef('pk')).order_by('-timestamp')
    nodes = SensorNode.objects.annotate(
        latest_aqi=models.Subquery(latest_per_node.values('aqi')[:1]),
        latest_aqi_level=models.Subquery(latest_per_node.values('aqi_level')[:1]),
        latest_timestamp=models.Subquery(latest_per_node.values('timestamp')[:1])
    ).filter(latest_aqi__isnull=False)

    def serialize_entry(node):
        return {
            'node_id': node.id,
            'name': node.name,
            'location': node.location or 'Unknown Area',
            'aqi': node.latest_aqi,
            'aqi_level': node.latest_aqi_level,
            'aqi_level_display': node.latest_aqi_level.replace('_', ' ').title() if node.latest_aqi_level else None,
            'updated_at': node.latest_timestamp.isoformat() if node.latest_timestamp else None,
        }

    top_polluted = [serialize_entry(node) for node in nodes.order_by('-latest_aqi')[:limit]]
    cleanest = [serialize_entry(node) for node in nodes.order_by('latest_aqi')[:limit]]
    return top_polluted, cleanest, nodes.count()

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
        'avg_pm10': 0,
        'avg_pm1_0': 0,
        'avg_temperature': 0,
        'avg_humidity': 0,
        'avg_pressure': 0,
        'avg_gas_resistance': 0,
        'avg_aqi_level': None,
        'avg_aqi_level_display': 'Moderate',
    }
    
    total_aqi = total_pm2_5 = total_pm10 = total_pm1_0 = 0.0
    total_temp = total_humidity = total_pressure = total_gas = 0.0
    count_aqi = count_pm2_5 = count_pm10 = count_pm1_0 = 0
    count_temp = count_humidity = count_pressure = count_gas = 0
    
    for node in nodes:
        latest = node.readings.order_by('-timestamp').first()
        if latest:
            aggregate_data['nodes'].append({
                'node': node,
                'reading': latest,
            })
            
            if not aggregate_data['latest_overall'] or latest.timestamp > aggregate_data['latest_overall'].timestamp:
                aggregate_data['latest_overall'] = latest
            if latest.aqi is not None:
                total_aqi += latest.aqi
                count_aqi += 1
            if latest.pm2_5 is not None:
                total_pm2_5 += latest.pm2_5
                count_pm2_5 += 1
            if latest.pm10 is not None:
                total_pm10 += latest.pm10
                count_pm10 += 1
            if latest.pm1_0 is not None:
                total_pm1_0 += latest.pm1_0
                count_pm1_0 += 1
            if latest.temperature is not None:
                total_temp += latest.temperature
                count_temp += 1
            if latest.humidity is not None:
                total_humidity += latest.humidity
                count_humidity += 1
            if latest.pressure is not None:
                total_pressure += latest.pressure
                count_pressure += 1
            if latest.gas_resistance is not None:
                total_gas += latest.gas_resistance
                count_gas += 1
    
    # Calculate averages
    if count_aqi > 0:
        aggregate_data['avg_aqi'] = round(total_aqi / count_aqi)
        aggregate_data['avg_aqi_level'] = get_aqi_category_label(aggregate_data['avg_aqi'])
        aggregate_data['avg_aqi_level_display'] = aggregate_data['avg_aqi_level']
    if count_pm2_5 > 0:
        aggregate_data['avg_pm2_5'] = round(total_pm2_5 / count_pm2_5, 2)
    if count_pm10 > 0:
        aggregate_data['avg_pm10'] = round(total_pm10 / count_pm10, 2)
    if count_pm1_0 > 0:
        aggregate_data['avg_pm1_0'] = round(total_pm1_0 / count_pm1_0, 2)
    if count_temp > 0:
        aggregate_data['avg_temperature'] = round(total_temp / count_temp, 1)
    if count_humidity > 0:
        aggregate_data['avg_humidity'] = round(total_humidity / count_humidity, 1)
    if count_pressure > 0:
        aggregate_data['avg_pressure'] = round(total_pressure / count_pressure, 1)
    if count_gas > 0:
        aggregate_data['avg_gas_resistance'] = round(total_gas / count_gas, 1)
    
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
        latest_reading = node.readings.order_by('-timestamp').first()
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
                'pm25': float(latest_reading.pm2_5) if latest_reading and latest_reading.pm2_5 is not None else None,
                'pm10': float(latest_reading.pm10) if latest_reading and latest_reading.pm10 is not None else None,
                'pm1_0': float(latest_reading.pm1_0) if latest_reading and latest_reading.pm1_0 is not None else None,
                'aqi': latest_reading.aqi if latest_reading and latest_reading.aqi is not None else None,
                'temperature': float(latest_reading.temperature) if latest_reading and latest_reading.temperature is not None else None,
                'humidity': float(latest_reading.humidity) if latest_reading and latest_reading.humidity is not None else None,
                'pressure': float(latest_reading.pressure) if latest_reading and latest_reading.pressure is not None else None,
                'gas_resistance': float(latest_reading.gas_resistance) if latest_reading and latest_reading.gas_resistance is not None else None,
                'aqi_level': latest_reading.aqi_level if latest_reading else None,
            }
        }

        if node.status == 'active':
            active_nodes_json.append(json_data)
        else:
            inactive_nodes_json.append(json_data)

    active_count = len(active_nodes_json)
    inactive_count = len(inactive_nodes_json)
    total_node_count = all_nodes.count()

    top_polluted_areas, cleanest_areas, top_area_count = build_top_area_rankings(limit=5)

    # ⚡ OPTIMIZATION: Limit rankings to 5 items each
    context = {
        'aggregate_data': aggregate_data,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),
        'active_nodes_json': json.dumps(active_nodes_json, cls=DjangoJSONEncoder),
        'inactive_nodes_json': json.dumps(inactive_nodes_json, cls=DjangoJSONEncoder),
        'top_polluted_areas': top_polluted_areas,
        'cleanest_areas': cleanest_areas,
        'top_polluted_areas_json': json.dumps(top_polluted_areas, cls=DjangoJSONEncoder),
        'cleanest_areas_json': json.dumps(cleanest_areas, cls=DjangoJSONEncoder),
        'total_nodes': total_node_count,
        'active_count': active_count,
        'inactive_count': inactive_count,
        'top_area_count': top_area_count,
    }
    return render(request, 'AppEnviroNode/main/dashboard.html', context)


@cache_api_response(ttl_seconds=60)  # OPTIMIZATION: Cache for 60s
@csrf_exempt
@require_http_methods(["GET"])
def api_analytics_aqi_trend(request):
    """Return hourly AQI averages for the last 24 hours.
    
    OPTIMIZATION: Cached response to prevent repeated heavy aggregations.
    Time window is fixed at 24 hours - query is consistent and cacheable.
    """
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


@cache_api_response(ttl_seconds=60)  # OPTIMIZATION: Cache for 60s
@csrf_exempt
@require_http_methods(["GET"])
def api_analytics_top_areas(request):
    """
    GET /api/analytics/top-areas/

    Returns the current top polluted and cleanest monitored areas based on the latest AQI reading per node.
    OPTIMIZATION: Cached to avoid repeated area ranking computations.
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


@csrf_exempt
@require_http_methods(["GET"])
def api_dashboard_nodes(request):
    """
    ⚡ OPTIMIZATION: Lightweight API endpoint for dashboard map initialization
    
    GET /api/dashboard/nodes/
    Query params:
      - limit: max nodes to return (default 100, max 150)
      - status: 'active', 'inactive', or 'all' (default: 'all')
    
    Returns minimal node data for efficient map rendering without full page reload.
    Avoids large JSON injection into templates.
    """
    try:
        # Parse query parameters
        limit = int(request.GET.get('limit', 100))
        limit = min(limit, 150)  # Cap at 150 to prevent abuse
        status_filter = request.GET.get('status', 'all')
        
        latest_per_node = SensorReading.objects.filter(node=models.OuterRef('pk')).order_by('-timestamp')
        query = SensorNode.objects.annotate(
            latest_aqi=models.Subquery(latest_per_node.values('aqi')[:1]),
            latest_pm2_5=models.Subquery(latest_per_node.values('pm2_5')[:1]),
            latest_pm10=models.Subquery(latest_per_node.values('pm10')[:1]),
            latest_pm1_0=models.Subquery(latest_per_node.values('pm1_0')[:1]),
            latest_temperature=models.Subquery(latest_per_node.values('temperature')[:1]),
            latest_humidity=models.Subquery(latest_per_node.values('humidity')[:1]),
            latest_pressure=models.Subquery(latest_per_node.values('pressure')[:1]),
            latest_gas_resistance=models.Subquery(latest_per_node.values('gas_resistance')[:1]),
            latest_timestamp=models.Subquery(latest_per_node.values('timestamp')[:1])
        ).only(
            'id', 'name', 'location', 'latitude', 'longitude', 'mac_address', 'status'
        )
        
        if status_filter == 'active':
            query = query.filter(status='active')
        elif status_filter == 'inactive':
            query = query.filter(status='inactive')
        
        nodes = query[:limit]
        
        nodes_data = []
        for node in nodes:
            nodes_data.append({
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
                    'pm25': float(node.latest_pm2_5) if node.latest_pm2_5 is not None else None,
                    'pm10': float(node.latest_pm10) if node.latest_pm10 is not None else None,
                    'pm1_0': float(node.latest_pm1_0) if node.latest_pm1_0 is not None else None,
                    'aqi': node.latest_aqi if node.latest_aqi is not None else None,
                    'temperature': float(node.latest_temperature) if node.latest_temperature is not None else None,
                    'humidity': float(node.latest_humidity) if node.latest_humidity is not None else None,
                }
            })
        
        return JsonResponse({
            'success': True,
            'nodes': nodes_data,
            'count': len(nodes_data),
            'limit': limit,
            'timestamp': timezone.now().isoformat()
        }, status=200)
    except Exception as e:
        logger.error(f"Dashboard nodes API error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@cache_api_response(ttl_seconds=30)  # OPTIMIZATION: Lightweight endpoint cached for 30s
@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_light(request):
    """
    ⚡ OPTIMIZATION: Ultra-lightweight node endpoint for map rendering
    
    GET /api/nodes/light/
    Returns ONLY: id, name, location, coordinates, AQI, status
    Reduced payload by 70-90% compared to full endpoint.
    Perfect for initial map render and polling updates.
    
    Query params:
      - limit: max nodes (default 100, max 200)
      - status: 'active' | 'inactive' | 'all' (default: 'all')
    
    Response size: ~60 bytes per node vs ~200+ bytes with full pollutants.
    """
    try:
        limit = int(request.GET.get('limit', 100))
        limit = min(limit, 200)
        status_filter = request.GET.get('status', 'all')
        
        # Single optimized query with minimal fields
        latest_per_node = SensorReading.objects.filter(
            node=models.OuterRef('pk')
        ).order_by('-timestamp')
        
        query = SensorNode.objects.filter(is_active=True).annotate(
            latest_aqi=models.Subquery(latest_per_node.values('aqi')[:1]),
            latest_timestamp=models.Subquery(latest_per_node.values('timestamp')[:1])
        ).values_list(
            'id', 'name', 'location', 'latitude', 'longitude', 'status',
            'latest_aqi', 'latest_timestamp'
        )
        
        if status_filter != 'all':
            query = query.filter(status=status_filter)
        
        query = query[:limit]
        
        # Minimal response - ~60 bytes per node
        nodes_data = [
            {
                'id': row[0],
                'name': row[1],
                'location': row[2] or 'Unknown',
                'lat': float(row[3]) if row[3] else None,
                'lng': float(row[4]) if row[4] else None,
                'status': row[5],
                'aqi': row[6]  # Only essential field
            }
            for row in query if row[3] and row[4]  # Only include nodes with coordinates
        ]
        
        return JsonResponse({
            'nodes': nodes_data,
            'count': len(nodes_data),
            'cached': True
        }, status=200)
    except Exception as e:
        logger.error(f"Nodes light API error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


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
    """Display sensor nodes on interactive map with WAQI-inspired controls.
    
    OPTIMIZATION: Uses single optimized query with annotated subqueries to fetch
    ONLY latest reading data per node, avoiding N+1 queries and prefetch overhead.
    """
    # Build subquery to fetch latest reading fields efficiently
    latest_reading = SensorReading.objects.filter(
        node=models.OuterRef('pk')
    ).order_by('-timestamp')
    
    # Annotate nodes with latest reading fields directly from DB
    nodes_data = SensorNode.objects.filter(
        is_active=True,
        latitude__isnull=False,  # Skip nodes with no coordinates
        longitude__isnull=False
    ).annotate(
        # Fetch only required fields from latest reading
        latest_aqi=models.Subquery(latest_reading.values('aqi')[:1]),
        latest_aqi_level=models.Subquery(latest_reading.values('aqi_level')[:1]),
        latest_pm25=models.Subquery(latest_reading.values('pm2_5')[:1]),
        latest_pm10=models.Subquery(latest_reading.values('pm10')[:1]),
        latest_pm1_0=models.Subquery(latest_reading.values('pm1_0')[:1]),
        latest_temperature=models.Subquery(latest_reading.values('temperature')[:1]),
        latest_humidity=models.Subquery(latest_reading.values('humidity')[:1]),
        latest_pressure=models.Subquery(latest_reading.values('pressure')[:1]),
        latest_gas_resistance=models.Subquery(latest_reading.values('gas_resistance')[:1]),
        latest_timestamp=models.Subquery(latest_reading.values('timestamp')[:1]),
    ).values(
        'id', 'name', 'location', 'latitude', 'longitude', 'mac_address', 'status',
        'latest_aqi', 'latest_aqi_level', 'latest_pm25', 'latest_pm10', 'latest_pm1_0',
        'latest_temperature', 'latest_humidity', 'latest_pressure', 'latest_gas_resistance',
        'latest_timestamp'
    )
    
    # Serialize directly from annotated values (no ORM object creation overhead)
    nodes_json_safe = []
    for node_data in nodes_data:
        nodes_json_safe.append({
            'node': {
                'id': node_data['id'],
                'name': node_data['name'],
                'location': node_data['location'] or 'Unknown',
                'latitude': float(node_data['latitude']) if node_data['latitude'] else None,
                'longitude': float(node_data['longitude']) if node_data['longitude'] else None,
                'mac_address': node_data['mac_address'],
                'status': node_data['status'],
            },
            'latest_reading': {
                'aqi': node_data['latest_aqi'],
                'aqi_level': node_data['latest_aqi_level'],
                'pm2_5': float(node_data['latest_pm25']) if node_data['latest_pm25'] is not None else None,
                'temperature': float(node_data['latest_temperature']) if node_data['latest_temperature'] is not None else None,
                'timestamp': node_data['latest_timestamp'].isoformat() if node_data['latest_timestamp'] else None,
            },
            'pollutants': {
                'pm25': float(node_data['latest_pm25']) if node_data['latest_pm25'] is not None else None,
                'pm10': float(node_data['latest_pm10']) if node_data['latest_pm10'] is not None else None,
                'pm1_0': float(node_data['latest_pm1_0']) if node_data['latest_pm1_0'] is not None else None,
                'aqi': node_data['latest_aqi'],
                'temperature': float(node_data['latest_temperature']) if node_data['latest_temperature'] is not None else None,
                'humidity': float(node_data['latest_humidity']) if node_data['latest_humidity'] is not None else None,
                'pressure': float(node_data['latest_pressure']) if node_data['latest_pressure'] is not None else None,
                'gas_resistance': float(node_data['latest_gas_resistance']) if node_data['latest_gas_resistance'] is not None else None,
            }
        })
    
    context = {
        'nodes_json': json.dumps(nodes_json_safe, cls=DjangoJSONEncoder),
        'total_nodes': len(nodes_json_safe),
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
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('app:client_dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        username = request.POST.get('username', '').strip()

        if username:
            candidate = None
            try:
                candidate = User.objects.get(username=username)
            except User.DoesNotExist:
                if '@' in username:
                    try:
                        candidate = User.objects.get(email=username)
                    except User.DoesNotExist:
                        candidate = None

            if candidate and candidate.is_locked_out():
                messages.error(
                    request,
                    f'Too many failed attempts. Please try again later. Your account is locked until {candidate.locked_until.strftime("%Y-%m-%d %H:%M %p")}.',
                )
                return render(request, 'AppEnviroNode/auth/login.html', {'form': form})

        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')

            user = None
            user = authenticate(request, username=username, password=password)

            if user is None and '@' in username:
                try:
                    email_user = User.objects.get(email=username)
                    user = authenticate(request, username=email_user.username, password=password)
                except User.DoesNotExist:
                    pass

            if user is not None:
                if user.is_locked_out():
                    messages.error(request, 'Too many failed login attempts. Please try again later.')
                    return render(request, 'AppEnviroNode/auth/login.html', {'form': form})

                if not user.is_active:
                    messages.error(request, 'Your account has been deactivated.')
                    return render(request, 'AppEnviroNode/auth/login.html', {'form': form})

                if not user.is_approved:
                    messages.error(request, 'Your account is pending admin approval.')
                    return render(request, 'AppEnviroNode/auth/login.html', {'form': form})

                user.reset_failed_logins()
                login(request, user)

                if user.must_change_password:
                    messages.info(request, 'Please set a new password for security.')
                    return redirect('app:force_password_change')

                messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                return redirect('app:client_dashboard')

            # if credentials are wrong, but the username exists, count the failed attempt
            target_user = None
            try:
                target_user = User.objects.get(username=username)
            except User.DoesNotExist:
                if '@' in username:
                    try:
                        target_user = User.objects.get(email=username)
                    except User.DoesNotExist:
                        target_user = None

            if target_user is not None:
                locked = target_user.record_failed_login()
                if locked:
                    messages.error(
                        request,
                        f'Too many failed login attempts. Please try again later. Account locked until {target_user.locked_until.strftime("%Y-%m-%d %H:%M %p")}.',
                    )
                else:
                    remaining = target_user.MAX_FAILED_LOGIN_ATTEMPTS - target_user.failed_login_attempts
                    messages.error(request, f'Invalid username/email or password. {remaining} attempt(s) remaining before lockout.')
            else:
                messages.error(request, 'Invalid username/email or password.')
        else:
            target_user = None
            try:
                target_user = User.objects.get(username=username)
            except User.DoesNotExist:
                if '@' in username:
                    try:
                        target_user = User.objects.get(email=username)
                    except User.DoesNotExist:
                        target_user = None

            if target_user is not None:
                if target_user.is_locked_out():
                    messages.error(
                        request,
                        f'Too many failed attempts. Please try again later. Your account is locked until {target_user.locked_until.strftime("%Y-%m-%d %H:%M %p")}.',
                    )
                else:
                    locked = target_user.record_failed_login()
                    if locked:
                        messages.error(
                            request,
                            f'Too many failed login attempts. Please try again later. Account locked until {target_user.locked_until.strftime("%Y-%m-%d %H:%M %p")}.',
                        )
                    else:
                        remaining = target_user.MAX_FAILED_LOGIN_ATTEMPTS - target_user.failed_login_attempts
                        messages.error(request, f'Invalid username/email or password. {remaining} attempt(s) remaining before lockout.')
            else:
                # Add this fallback for accounts that don't exist
                messages.error(request, 'Invalid username/email or password.')
                
    # === MAKE SURE THESE FINAL LINES ARE INDENTED EXACTLY LIKE THIS ===
    else:
        # This handles the initial GET request to load the empty form
        form = CustomAuthenticationForm()

    # This MUST be the last line of the function, aligned with the 'if request.method'
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
    """Dashboard with all sensor nodes, latest readings, analytics, and chart data."""
    from django.db.models.functions import TruncDay
    from django.db.models import Sum
    
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
    # SECTION 3: Analytics aggregations
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
    # SECTION 6: Transactions & Orders Summary (Updated with Most Bought Item)
    # =========================================================================
    from django.db.models import Sum
    from .models import Order, HardwareRequest

    total_orders_count = Order.objects.count()
    total_revenue = Order.objects.filter(
        status__in=['paid', 'shipped', 'received']
    ).aggregate(Sum('total_price'))['total_price__sum'] or 0.00
    pending_requests_count = HardwareRequest.objects.filter(is_processed=False).count()
    
    # FIXED: Safely exclude deleted products so it never displays "None"
    most_bought = Order.objects.exclude(product__isnull=True).values('product__name').annotate(
        total_qty=Sum('quantity')
    ).order_by('-total_qty').first()
    
    most_bought_name = most_bought['product__name'] if most_bought else "No active orders"
    most_bought_qty = most_bought['total_qty'] if most_bought else 0
    
    context = {
        'aggregate_data': aggregate_data,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),
        'analytics': analytics,
        'system_health': system_health,
        'active_nodes_json': json.dumps(active_nodes_json, cls=DjangoJSONEncoder),
        'inactive_nodes_json': json.dumps(inactive_nodes_json, cls=DjangoJSONEncoder),
        'total_nodes': all_nodes.count(),
        'active_count': len(active_nodes_json),
        'inactive_count': len(inactive_nodes_json),
        'total_orders_count': total_orders_count,
        'total_revenue': total_revenue,
        'pending_requests_count': pending_requests_count,
        'most_bought_name': most_bought_name,
        'most_bought_qty': most_bought_qty,
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
    # SECTION 5: Generate Time-Series Chart Data (OPTIMIZED)
    # ============================================================================
    # ⚡ OPTIMIZATION: Use adaptive aggregation based on date range
    chart_date_range = (end_date - start_date).days
    aggregation_strategy = get_aggregation_strategy(chart_date_range)
    
    # Use appropriate time grouping function
    if aggregation_strategy == 'minute':
        from django.db.models.functions import TruncMinute
        trunc_func = TruncMinute
        date_format = '%H:%M'
    elif aggregation_strategy == 'hour':
        from django.db.models.functions import TruncHour
        trunc_func = TruncHour
        date_format = '%b %d %H:%M'
    else:  # day
        from django.db.models.functions import TruncDay
        trunc_func = TruncDay
        date_format = '%Y-%m-%d'
    
    # Compute time-series aggregation
    chart_data_raw = readings_qs.annotate(
        period=trunc_func('timestamp')
    ).values('period').annotate(
        avg_aqi=models.Avg('aqi'),
        avg_pm2_5=models.Avg('pm2_5'),
        avg_temperature=models.Avg('temperature'),
        count=models.Count('id')
    ).order_by('period')

    # Format chart data for JSON injection into frontend
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
@admin_required
def client_alerts(request):
    # ── Filters ──────────────────────────────────────────────
    search_query = request.GET.get('search', '').strip()
    severity_filter = request.GET.get('severity', 'all')
    status_filter = request.GET.get('status', 'active')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    # ── Base queryset ─────────────────────────────────────────
    alerts_qs = Alert.objects.select_related('node', 'reading').order_by('-triggered_at')
    # Status filter
    if status_filter == 'active':
        alerts_qs = alerts_qs.filter(is_active=True)
    elif status_filter == 'resolved':
        alerts_qs = alerts_qs.filter(is_active=False)
    # 'all' = no filter
    # Severity filter
    if severity_filter != 'all':
        alerts_qs = alerts_qs.filter(severity=severity_filter)
    # Search filter
    if search_query:
        alerts_qs = alerts_qs.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(node__name__icontains=search_query)
        )
    # Date range filter
    if date_from:
        try:
            alerts_qs = alerts_qs.filter(
                triggered_at__gte=timezone.make_aware(
                    datetime.strptime(date_from, '%Y-%m-%d')
                )
            )
        except ValueError:
            pass
    if date_to:
        try:
            alerts_qs = alerts_qs.filter(
                triggered_at__lte=timezone.make_aware(
                    datetime.strptime(date_to, '%Y-%m-%d').replace(
                        hour=23, minute=59, second=59
                    )
                )
            )
        except ValueError:
            pass
    # ── Pagination ────────────────────────────────────────────
    paginator = Paginator(alerts_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    # ── Severity counts (unfiltered active) ───────────────────
    severity_counts = {
        'info':     Alert.objects.filter(is_active=True, severity='info').count(),
        'warning':  Alert.objects.filter(is_active=True, severity='warning').count(),
        'critical': Alert.objects.filter(is_active=True, severity='critical').count(),
    }
    context = {
        'page_obj': page_obj,
        'alerts': page_obj.object_list,
        'severity_counts': severity_counts,
        'total_active': Alert.objects.filter(is_active=True).count(),
        'total_resolved': Alert.objects.filter(is_active=False).count(),
        # Filter state (for form repopulation)
        'search_query': search_query,
        'selected_severity': severity_filter,
        'selected_status': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'total_results': paginator.count,
    }
    return render(request, 'AppEnviroNode/admin/clientalerts.html', context)

@login_required(login_url='app:login')
def client_devices(request):
    if not request.user.is_admin_user():
        messages.error(request, 'You do not have permission to access device management.')
        return redirect('app:client_dashboard')
    check_and_update_node_status()
    nodes = SensorNode.objects.all().prefetch_related('readings').order_by('-last_seen')
    active_nodes = []
    inactive_nodes = []
    unregistered_nodes = []
    rogue_nodes = []
    for node in nodes:
        latest_reading = node.readings.first()
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
@require_http_methods(["GET"])
def api_node_readings(request, node_id):
    """GET /api/nodes/<node_id>/readings/ — paginated readings for a node."""
    try:
        node = get_object_or_404(SensorNode, id=node_id)
        page = int(request.GET.get('page', 1))
        per_page = 10
        readings_qs = node.readings.order_by('-timestamp')
        paginator = Paginator(readings_qs, per_page)
        page_obj = paginator.get_page(page)
        data = []
        for r in page_obj:
            data.append({
                'id': r.id,
                'timestamp': r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'aqi': r.aqi,
                'aqi_level': r.aqi_level,
                'pm1_0': r.pm1_0,
                'pm2_5': r.pm2_5,
                'pm10': r.pm10,
                'temperature': r.temperature,
                'humidity': r.humidity,
                'pressure': r.pressure,
            })
        return JsonResponse({
            'success': True,
            'node_name': node.name,
            'readings': data,
            'page': page,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_node_reading_delete(request, reading_id):
    """POST /api/readings/<reading_id>/delete/ — delete a single reading."""
    if not request.user.is_admin_user():
        return JsonResponse({'success': False, 'error': 'Admin only'}, status=403)
    try:
        reading = get_object_or_404(SensorReading, id=reading_id)
        reading.delete()
        return JsonResponse({'success': True, 'message': 'Reading deleted.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required(login_url='app:login')
@require_http_methods(["GET"])
def api_node_readings_export(request, node_id):
    """GET /api/nodes/<node_id>/readings/export/ — export all readings as CSV."""
    if not request.user.is_admin_user():
        return JsonResponse({'success': False, 'error': 'Admin only'}, status=403)
    try:
        node = get_object_or_404(SensorNode, id=node_id)
        readings = node.readings.order_by('-timestamp')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{node.name}_readings.csv"'
        writer = csv.writer(response)
        writer.writerow(['Timestamp', 'AQI', 'AQI Level', 'PM1.0', 'PM2.5', 'PM10', 'Temperature', 'Humidity', 'Pressure'])
        for r in readings:
            writer.writerow([
                r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                r.aqi, r.aqi_level,
                r.pm1_0, r.pm2_5, r.pm10,
                r.temperature, r.humidity, r.pressure,
            ])
        return response
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required(login_url='app:login')
def client_health(request):
    return render(request, 'AppEnviroNode/admin/clienthealth.html')

# ============================================================================
# OPTIMIZATION: Map View API Endpoints (Viewport & Performance)
# ============================================================================

@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_live(request):
    """
    GET /api/nodes/live/
    
    Returns latest readings grouped by status for map initialization.
    OPTIMIZATION: Single query with annotated subqueries, minimal serialization overhead.
    Limited to 200 total nodes. Only latest reading per node.
    """
    try:
        # Single subquery to fetch only latest reading fields
        latest_reading = SensorReading.objects.filter(
            node=models.OuterRef('pk')
        ).order_by('-timestamp')
        
        # Fetch all active nodes with latest readings in a single query
        nodes_queryset = SensorNode.objects.filter(is_active=True).annotate(
            latest_aqi=models.Subquery(latest_reading.values('aqi')[:1]),
            latest_pm25=models.Subquery(latest_reading.values('pm2_5')[:1]),
            latest_pm10=models.Subquery(latest_reading.values('pm10')[:1]),
            latest_pm1_0=models.Subquery(latest_reading.values('pm1_0')[:1]),
            latest_temp=models.Subquery(latest_reading.values('temperature')[:1]),
            latest_humidity=models.Subquery(latest_reading.values('humidity')[:1]),
            latest_timestamp=models.Subquery(latest_reading.values('timestamp')[:1]),
        ).order_by('-latest_timestamp').values(
            'id', 'name', 'location', 'latitude', 'longitude', 'status', 'mac_address',
            'latest_aqi', 'latest_pm25', 'latest_pm10', 'latest_pm1_0', 'latest_temp', 
            'latest_humidity', 'latest_timestamp'
        )[:200]  # Limit at query level for efficiency
        
        # Group by status in single Python pass
        grouped = {'active': [], 'inactive': [], 'unregistered': [], 'rogue': []}
        
        for node in nodes_queryset:
            status = node['status'] or 'unregistered'
            
            # Build minimal node data structure
            node_data = {
                'node': {
                    'id': node['id'],
                    'name': node['name'],
                    'location': node['location'] or 'Unknown',
                    'latitude': float(node['latitude']) if node['latitude'] else None,
                    'longitude': float(node['longitude']) if node['longitude'] else None,
                    'mac_address': node['mac_address'],
                    'status': status,
                },
                'latest_reading': {
                    'aqi': node['latest_aqi'],
                    'timestamp': node['latest_timestamp'].isoformat() if node['latest_timestamp'] else None,
                },
                'pollutants': {
                    'aqi': node['latest_aqi'],
                    'pm25': float(node['latest_pm25']) if node['latest_pm25'] is not None else None,
                    'pm10': float(node['latest_pm10']) if node['latest_pm10'] is not None else None,
                    'pm1_0': float(node['latest_pm1_0']) if node['latest_pm1_0'] is not None else None,
                    'temperature': float(node['latest_temp']) if node['latest_temp'] is not None else None,
                    'humidity': float(node['latest_humidity']) if node['latest_humidity'] is not None else None,
                }
            }
            
            if status in grouped:
                grouped[status].append(node_data)
        
        return JsonResponse({
            'active': grouped['active'],
            'inactive': grouped['inactive'],
            'unregistered': grouped['unregistered'],
            'rogue': grouped['rogue']
        }, status=200)
    except Exception as e:
        logger.error(f'[API NODES LIVE] Error: {str(e)}')
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_viewport(request):
    """
    GET /api/nodes/viewport/
    
    Returns nodes within a bounding box (viewport) for efficient map rendering.
    
    Query Parameters:
    - bbox: Bounding box in "south,west,north,east" format (from Leaflet)
    - timeframe: 'live' or '24h' (default: 'live')
    """
    try:
        # Parse bbox parameter: format is "south,west,north,east"
        bbox_str = request.GET.get('bbox', '')
        timeframe = request.GET.get('timeframe', 'live')
        
        if not bbox_str:
            return JsonResponse({'error': 'Missing bbox parameter'}, status=400)
        
        try:
            parts = bbox_str.split(',')
            if len(parts) != 4:
                raise ValueError('Invalid bbox format')
            south, west, north, east = map(float, parts)
        except (ValueError, IndexError):
            return JsonResponse({'error': 'Invalid bbox format. Expected: south,west,north,east'}, status=400)
        
        # Query nodes within bounding box
        latest_reading = SensorReading.objects.filter(
            node=models.OuterRef('pk')
        ).order_by('-timestamp')
        
        nodes_queryset = SensorNode.objects.filter(
            is_active=True,
            latitude__gte=south,
            latitude__lte=north,
            longitude__gte=west,
            longitude__lte=east
        ).annotate(
            latest_aqi=models.Subquery(latest_reading.values('aqi')[:1]),
            latest_pm25=models.Subquery(latest_reading.values('pm2_5')[:1]),
            latest_pm10=models.Subquery(latest_reading.values('pm10')[:1]),
            latest_pm1_0=models.Subquery(latest_reading.values('pm1_0')[:1]),
            latest_temp=models.Subquery(latest_reading.values('temperature')[:1]),
            latest_humidity=models.Subquery(latest_reading.values('humidity')[:1]),
            latest_timestamp=models.Subquery(latest_reading.values('timestamp')[:1]),
        ).order_by('-latest_timestamp').values(
            'id', 'name', 'location', 'latitude', 'longitude', 'status', 'mac_address',
            'latest_aqi', 'latest_pm25', 'latest_pm10', 'latest_pm1_0', 'latest_temp', 
            'latest_humidity', 'latest_timestamp'
        )[:200]
        
        # Group by status
        grouped = {'active': [], 'inactive': [], 'unregistered': [], 'rogue': []}
        
        for node in nodes_queryset:
            status = node['status'] or 'unregistered'
            
            node_data = {
                'node': {
                    'id': node['id'],
                    'name': node['name'],
                    'location': node['location'] or 'Unknown',
                    'latitude': float(node['latitude']) if node['latitude'] else None,
                    'longitude': float(node['longitude']) if node['longitude'] else None,
                    'mac_address': node['mac_address'],
                    'status': status,
                },
                'latest_reading': {
                    'aqi': node['latest_aqi'],
                    'timestamp': node['latest_timestamp'].isoformat() if node['latest_timestamp'] else None,
                },
                'pollutants': {
                    'aqi': node['latest_aqi'],
                    'pm25': float(node['latest_pm25']) if node['latest_pm25'] is not None else None,
                    'pm10': float(node['latest_pm10']) if node['latest_pm10'] is not None else None,
                    'pm1_0': float(node['latest_pm1_0']) if node['latest_pm1_0'] is not None else None,
                    'temperature': float(node['latest_temp']) if node['latest_temp'] is not None else None,
                    'humidity': float(node['latest_humidity']) if node['latest_humidity'] is not None else None,
                }
            }
            
            if status in grouped:
                grouped[status].append(node_data)
        
        return JsonResponse({
            'active': grouped['active'],
            'inactive': grouped['inactive'],
            'unregistered': grouped['unregistered'],
            'rogue': grouped['rogue']
        }, status=200)
    except Exception as e:
        logger.error(f'[API NODES VIEWPORT] Error: {str(e)}')
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_24h(request):
    """
    GET /api/nodes/24h/
    
    Returns latest readings from last 24h grouped by status.
    Same structure as live endpoint for consistency.
    """
    try:
        now = timezone.now()
        start_24h = now - timedelta(hours=24)
        
        # Latest reading in last 24h per node
        latest_reading = SensorReading.objects.filter(
            node=models.OuterRef('pk'),
            timestamp__gte=start_24h
        ).order_by('-timestamp')
        
        nodes = SensorNode.objects.filter(is_active=True).annotate(
            latest_aqi=models.Subquery(latest_reading.values('aqi')[:1]),
            latest_pm25=models.Subquery(latest_reading.values('pm2_5')[:1]),
            latest_pm10=models.Subquery(latest_reading.values('pm10')[:1]),
            latest_temp=models.Subquery(latest_reading.values('temperature')[:1]),
            latest_humidity=models.Subquery(latest_reading.values('humidity')[:1]),
            latest_timestamp=models.Subquery(latest_reading.values('timestamp')[:1]),
        ).values(
            'id', 'name', 'location', 'latitude', 'longitude', 'status', 'mac_address',
            'latest_aqi', 'latest_pm25', 'latest_pm10', 'latest_temp', 'latest_humidity', 'latest_timestamp'
        )  # FIX: Include ALL nodes in 24h window, even offline ones
        
        grouped = {'active': [], 'inactive': [], 'unregistered': [], 'rogue': []}
        total_count = 0
        max_nodes = 200
        
        for node in nodes.order_by('-latest_timestamp'):
            if total_count >= max_nodes:
                break
            
            status = node['status'] or 'unregistered'
            
            # NEW: Get AQI history (last 24 readings for chart)
            aqi_history = list(
                SensorReading.objects.filter(
                    node_id=node['id'],
                    timestamp__gte=start_24h
                ).order_by('timestamp').values_list('aqi', flat=True)[:24]
            )
            
            # FIX: Handle NULL readings for offline nodes
            node_data = {
                'node': {
                    'id': node['id'],
                    'name': node['name'],
                    'location': node['location'] or 'Unknown',
                    'latitude': float(node['latitude']) if node['latitude'] else None,
                    'longitude': float(node['longitude']) if node['longitude'] else None,
                    'mac_address': node['mac_address'],
                    'status': status,
                },
                'latest_reading': {
                    'aqi': node['latest_aqi'] if node['latest_aqi'] is not None else None,
                    'timestamp': node['latest_timestamp'].isoformat() if node['latest_timestamp'] else None,
                    'battery': None,
                    'rssi': None,
                },
                'pollutants': {
                    'aqi': node['latest_aqi'] if node['latest_aqi'] is not None else None,
                    'pm25': float(node['latest_pm25']) if node['latest_pm25'] is not None else None,
                    'pm10': float(node['latest_pm10']) if node['latest_pm10'] is not None else None,
                    'temperature': float(node['latest_temp']) if node['latest_temp'] is not None else None,
                    'humidity': float(node['latest_humidity']) if node['latest_humidity'] is not None else None,
                },
                'aqi_history': [int(val) if val is not None else 0 for val in aqi_history]
            }
            
            if status in grouped:
                grouped[status].append(node_data)
                total_count += 1
        
        logger.debug(f'[API NODES 24H] Returned {total_count} total nodes')
        return JsonResponse({
            'active': grouped['active'],
            'inactive': grouped['inactive'],
            'unregistered': grouped['unregistered'],
            'rogue': grouped['rogue']
        }, status=200)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required(login_url='app:login')
def client_map_view(request):
    """Display sensor nodes on interactive map for admins."""
    # OPTIMIZATION: Don't serialize all nodes in template - fetch via API instead
    # Only pass status counts for UI display
    total_nodes = SensorNode.objects.filter(is_active=True).count()
    active_count = SensorNode.objects.filter(status='active').count()
    inactive_count = SensorNode.objects.filter(status='inactive').count()
    unregistered_count = SensorNode.objects.filter(status='unregistered').count()
    rogue_count = SensorNode.objects.filter(status='rogue').count()
    
    context = {
        # OPTIMIZATION: Pass empty arrays - JS will fetch live data via /api/nodes/live/
        'active_nodes_json': json.dumps([], cls=DjangoJSONEncoder),
        'inactive_nodes_json': json.dumps([], cls=DjangoJSONEncoder),
        'unregistered_nodes_json': json.dumps([], cls=DjangoJSONEncoder),
        'rogue_nodes_json': json.dumps([], cls=DjangoJSONEncoder),
        'total_nodes': total_nodes,
        'active_count': active_count,
        'inactive_count': inactive_count,
        'unregistered_count': unregistered_count,
        'rogue_count': rogue_count,
    }
    return render(request, 'AppEnviroNode/admin/clientmapview.html', context)

@login_required(login_url='app:login')
def node_create(request):
    """Create a new sensor node."""
    # Enforce admin-only access
    if not request.user.is_admin_user():
        messages.error(request, 'You do not have permission to create nodes.')
        return redirect('app:client_dashboard')
    
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
    # Enforce admin-only access
    if not request.user.is_admin_user():
        messages.error(request, 'You do not have permission to edit nodes.')
        return redirect('app:client_dashboard')
    
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
    # Enforce admin-only access
    if not request.user.is_admin_user():
        messages.error(request, 'You do not have permission to delete nodes.')
        return redirect('app:client_dashboard')
    
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
    import json
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db.models.functions import TruncMinute
    from django.db.models import Avg

    now = timezone.now()
    time_start = now - timedelta(minutes=15)

    # Get all active nodes with their latest readings
    all_nodes = SensorNode.objects.filter(is_active=True).prefetch_related('readings')

    # Build nodes list for initial data
    nodes_list = []
    active_count = 0
    total_aqi = []

    for node in all_nodes:
        latest = node.readings.first()
        if latest:
            node_aqi = latest.aqi
            if node_aqi is not None:
                total_aqi.append(node_aqi)

            # Calculate status based on timestamp freshness
            if latest.timestamp:
                seconds_since = (now - latest.timestamp).total_seconds()
                status = 'disconnected' if seconds_since >= 300 else 'active'
            else:
                status = 'disconnected'

            node_item = {
                'node_id': node.id,
                'name': node.name,
                'zone': getattr(node, 'zone', None) or node.location or 'Unknown',
                'location': node.location or '',
                'status': status,
                'aqi': node_aqi,
                'latest_aqi': node_aqi,
                'pm2_5': latest.pm2_5,
                'pm10': latest.pm10,
                'temperature': latest.temperature,
                'humidity': latest.humidity,
                'co2': getattr(latest, 'co2', None),
                'timestamp': int(latest.timestamp.timestamp()) if latest.timestamp else None,
                'last_seen': latest.timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest.timestamp else None,
            }
            nodes_list.append(node_item)

            if node.status == 'active':
                active_count += 1

    # Get readings for feed events
    readings_qs = SensorReading.objects.filter(
        timestamp__gte=time_start,
        timestamp__lte=now
    ).select_related('node').order_by('-timestamp')[:10]

    feed_events = []
    for reading in readings_qs:
        if reading.aqi is not None:
            severity = 'critical' if reading.aqi > 150 else 'warning' if reading.aqi > 100 else 'info'
            feed_events.append({
                'node_id': reading.node_id,
                'title': f'AQI reading: {reading.aqi}',
                'description': f'{reading.node.name} reported AQI {reading.aqi}',
                'severity': severity,
                'tag_label': severity.upper(),
                'tag_class': f'crealtime-tag-{severity}',
                'bg_class': 'crealtime-bg-green' if severity == 'info' else 'crealtime-bg-yellow' if severity == 'warning' else 'crealtime-bg-red',
                'icon': '✓' if severity == 'info' else '⚠' if severity == 'warning' else '🚨',
                'timestamp': int(reading.timestamp.timestamp()) if reading.timestamp else None,
                'timestamp_unix': int(reading.timestamp.timestamp()) if reading.timestamp else None,
            })

    # Generate alerts
    alert_entries = []
    for node in nodes_list:
        if node['status'] != 'active':
            alert_entries.append({
                'node_name': node['name'],
                'title': f'Node Offline: {node["name"]}',
                'description': f'Node has not reported data recently',
                'severity': 'critical',
            })
        elif node['aqi'] is not None and node['aqi'] > 100:
            alert_entries.append({
                'node_name': node['name'],
                'title': f'High AQI Alert: {node["name"]}',
                'description': f'AQI level {node["aqi"]} exceeds safe threshold',
                'severity': 'warning' if node['aqi'] <= 150 else 'critical',
            })

    # Calculate chart values
    chart_values = []
    if total_aqi:
        # Get aggregated chart data
        chart_agg = SensorReading.objects.filter(
            timestamp__gte=time_start,
            timestamp__lte=now,
            aqi__isnull=False
        ).annotate(
            period=TruncMinute('timestamp')
        ).values('period').annotate(
            avg_aqi=Avg('aqi')
        ).order_by('period')[:30]

        chart_values = [round(item['avg_aqi'], 1) for item in chart_agg if item['avg_aqi'] is not None]

    # Build system info
    avg_aqi = round(sum(total_aqi) / len(total_aqi), 1) if total_aqi else None

    # Get zones (using location field since zone doesn't exist)
    zones = list(all_nodes.exclude(location__isnull=True).exclude(location='').values_list('location', flat=True).distinct())

    # Build realtime payload for initial data
    realtime_payload = {
        'nodes': nodes_list,
        'feed_events': feed_events,
        'alert_entries': alert_entries,
        'system': {
            'active_count': active_count,
            'total_nodes': all_nodes.count(),
            'avg_aqi': avg_aqi,
        },
        'chart_values': chart_values,
        'zones': zones,
    }

    # Also provide API-compatible format for polling
    realtime_payload.update({
        'data': nodes_list,
        'feed': feed_events,
        'alerts': alert_entries,
        'active_nodes': active_count,
        'total_nodes': all_nodes.count(),
        'live_aqi': avg_aqi,
    })

    context = {
        'latest_update': now,
        'node_data': nodes_list,
        'total_nodes': len(nodes_list),
        'realtime_payload_json': json.dumps(realtime_payload, cls=DjangoJSONEncoder),
    }
    return render(request, 'AppEnviroNode/admin/clientrealtime.html', context)

@login_required(login_url='app:login')
def api_client_reports(request):
    """
    Return optimized report JSON with rolling date windows per report_type.
    
    Parameters:
    - report_type: '24hrs', 'Weekly', 'Monthly', or 'Custom'
    - date_from, date_to: Custom dates (only used if report_type='Custom')
    - node: Node ID filter (optional, 'all' = no filter)
    - location: Location filter (optional, 'all' = no filter)
    """
    from datetime import datetime
    from django.db.models.functions import TruncDay, TruncHour, TruncMinute

    # === ROLLING DATE WINDOW COMPUTATION ===
    report_type = request.GET.get('report_type', '24hrs').strip()
    node_id = request.GET.get('node', 'all').strip()
    
    now = timezone.now()
    
    # Compute time range based on report_type
    if report_type == '24hrs':
        time_start = now - timedelta(hours=24)
        time_end = now
        agg_strategy = 'hour'
        display_fmt = '%b %d %H:00'
        total_days = 1
    elif report_type == 'Weekly':
        time_start = now - timedelta(days=7)
        time_end = now
        agg_strategy = 'hour'
        display_fmt = '%b %d %H:00'
        total_days = 7
    elif report_type == 'Monthly':
        time_start = now - timedelta(days=30)
        time_end = now
        agg_strategy = 'day'
        display_fmt = '%b %d'
        total_days = 30
    else:  # Custom
        date_format = '%Y-%m-%d'
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        
        try:
            date_from_dt = datetime.strptime(date_from, date_format).date() if date_from else (now.date() - timedelta(days=6))
            date_to_dt = datetime.strptime(date_to, date_format).date() if date_to else now.date()
        except (ValueError, TypeError):
            date_from_dt = now.date() - timedelta(days=6)
            date_to_dt = now.date()
        
        if date_from_dt > date_to_dt:
            date_from_dt, date_to_dt = date_to_dt - timedelta(days=6), date_to_dt
        
        time_start = timezone.make_aware(datetime.combine(date_from_dt, datetime.min.time()))
        time_end = timezone.make_aware(datetime.combine(date_to_dt, datetime.max.time()))
        total_days = (date_to_dt - date_from_dt).days + 1
        agg_strategy = get_aggregation_strategy(total_days)
        display_fmt = '%b %d' if agg_strategy == 'day' else ('%b %d %H:00' if agg_strategy == 'hour' else '%H:%M')
        report_type = 'Custom'
    
    # === OPTIMIZED QUERY WITH AGGREGATION ===
    readings_qs = SensorReading.objects.filter(
        timestamp__date__gte=date_from,
        timestamp__date__lte=date_to,
        node__is_active=True
    ).select_related('node')
    
    if node_id and node_id != 'all':
        try:
            readings_qs = readings_qs.filter(node__id=int(node_id))
        except (ValueError, TypeError):
            pass
    
    # Get active nodes list (compact)
    nodes_qs = SensorNode.objects.filter(is_active=True, status='active').values_list('id', 'name', 'location')
    nodes = [
        {
            'id': node_id,
            'label': f"{name} ({location or 'Unknown Area'})"
        }
        for node_id, name, location in nodes_qs
    ]
    
    total_nodes = len(nodes)
    nodes_online = total_nodes
    
    # === AGGREGATED METRICS (single efficient query) ===
    agg = readings_qs.aggregate(
        avg_aqi=Avg('aqi'),
        max_aqi=Max('aqi'),
        min_aqi=Min('aqi')
    )

    avg_aqi = round(agg['avg_aqi'], 1) if agg['avg_aqi'] is not None else 0
    peak_aqi = agg['max_aqi'] or 0
    low_aqi = agg['min_aqi'] or 0

    peak_reading = readings_qs.filter(aqi=peak_aqi).only('aqi', 'aqi_level', 'timestamp').first() if peak_aqi else None
    low_reading = readings_qs.filter(aqi=low_aqi).only('aqi', 'aqi_level', 'timestamp').first() if low_aqi else None

    good_days = readings_qs.filter(aqi_level='good').values('timestamp__date').distinct().count()
    moderate_days = readings_qs.filter(aqi_level='moderate').values('timestamp__date').distinct().count()
    unhealthy_days = readings_qs.filter(aqi_level__in=['unhealthy', 'unhealthy_sensitive']).values('timestamp__date').distinct().count()

    good_pct = round((good_days / total_days) * 100, 1) if total_days else 0
    moderate_pct = round((moderate_days / total_days) * 100, 1) if total_days else 0
    unhealthy_pct = round((unhealthy_days / total_days) * 100, 1) if total_days else 0
    
    # === MOST AFFECTED NODE (optimized) ===
    most_affected_qs = readings_qs.values('node__id', 'node__name', 'node__location').annotate(
        avg_node_aqi=Avg('aqi')
    ).order_by('-avg_node_aqi').first()

    most_affected_node = {
        'name': most_affected_qs['node__name'],
        'location': most_affected_qs['node__location'] or 'Unknown Area'
    } if most_affected_qs else None

    strategy = get_aggregation_strategy(total_days)
    trend_labels = []
    trend_values = []

    if strategy == 'day':
        trunc_func = TruncDay
        date_fmt = '%b %d'
    elif strategy == 'hour':
        trunc_func = TruncHour
        date_fmt = '%b %d %H:00'
    else:
        trunc_func = TruncMinute
        date_fmt = '%H:%M'

    trend_data = readings_qs.annotate(
        period=trunc_func('timestamp')
    ).values('period').annotate(
        avg_val=Avg('aqi')
    ).order_by('period')

    for item in trend_data[:90]:
        if item['period']:
            trend_labels.append(item['period'].strftime(date_fmt))
            trend_values.append(round(item['avg_val'], 1) if item['avg_val'] else 0)

    report_type = 'Custom'
    if total_days == 7:
        report_type = 'Weekly'
    elif total_days == 15:
        report_type = 'Bi-Weekly'
    elif total_days in (30, 31):
        report_type = 'Monthly'

    response_data = {
        'nodes': [],
        'avg_aqi': avg_aqi,
        'peak_aqi': peak_aqi,
        'peak_level': peak_reading.aqi_level if peak_reading else None,
        'peak_date': peak_reading.timestamp.strftime('%Y-%m-%d') if peak_reading else None,
        'low_aqi': low_aqi,
        'low_level': low_reading.aqi_level if low_reading else None,
        'low_date': low_reading.timestamp.strftime('%Y-%m-%d') if low_reading else None,
        'most_affected_node': most_affected_node,
        'good_days': good_days,
        'moderate_days': moderate_days,
        'unhealthy_days': unhealthy_days,
        'good_pct': good_pct,
        'moderate_pct': moderate_pct,
        'unhealthy_pct': unhealthy_pct,
        'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M'),
        'uptime_pct': 100,
        'nodes_online': nodes_online,
        'total_nodes': total_nodes,
        'report_type': report_type,
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'report_period': f"{date_from.strftime('%b %d')} - {date_to.strftime('%b %d, %Y')}",
        'trend_labels': trend_labels,
        'trend_values': trend_values,
        'insights': [
            'Air quality appears stable across the selected period.',
            'Monitor peak days for any rapid AQI changes.'
        ],
        'actions': [
            'Review nodes with the highest average AQI.',
            'Check sensor maintenance schedules for outlier days.'
        ],
        'distribution_note': 'AQI distribution reflects the most recent readings for the chosen period.',
        'total_days': total_days,
    }

    return JsonResponse(response_data)

@login_required(login_url='app:login')
def client_settings(request):
    return render(request, 'AppEnviroNode/admin/clientsettings.html')

def _audit_filtered_queryset(request):
    """
    Shared database filtering for the History page and both
    report formats. Search runs before pagination.
    """
    params = request.GET
    logs = SystemLog.objects.select_related('node').all()

    event_type = params.get('event_type', 'all')
    node_id = params.get('node', 'all')
    sensor_type = params.get('sensor_type', 'all')
    severity = params.get('severity', 'all')
    date_range = params.get('date_range', 'all')
    search_query = params.get('q', '').strip()[:120]

    now = timezone.now()

    # Date filters
    if date_range == 'today':
        start = timezone.localtime(now).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        logs = logs.filter(created_at__gte=start)

    elif date_range == 'last7':
        logs = logs.filter(
            created_at__gte=now - timedelta(days=7)
        )

    elif date_range == 'last30':
        logs = logs.filter(
            created_at__gte=now - timedelta(days=30)
        )

    elif date_range == 'custom':
        for parameter, lookup, clock in (
            ('start_date', 'gte', datetime.min.time()),
            ('end_date', 'lte', datetime.max.time()),
        ):
            value = params.get(parameter, '')

            if not value:
                continue

            try:
                day = datetime.strptime(
                    value, '%Y-%m-%d'
                ).date()

                boundary = timezone.make_aware(
                    datetime.combine(day, clock),
                    timezone.get_current_timezone(),
                )

                logs = logs.filter(
                    **{f'created_at__{lookup}': boundary}
                )

            except ValueError:
                pass

    # Existing dropdown filters
    if event_type != 'all':
        logs = logs.filter(event_type=event_type)

    if node_id != 'all':
        try:
            logs = logs.filter(node_id=int(node_id))
        except (TypeError, ValueError):
            pass

    if sensor_type != 'all':
        logs = logs.filter(sensor_type=sensor_type)

    if severity != 'all':
        logs = logs.filter(severity=severity)

    # Search the entire stored audit history.
    if search_query:
        search = (
            Q(message__icontains=search_query)
            | Q(node__name__icontains=search_query)
            | Q(node__location__icontains=search_query)
            | Q(node__mac_address__icontains=search_query)
            | Q(event_type__icontains=search_query)
            | Q(severity__icontains=search_query)
            | Q(sensor_type__icontains=search_query)
        )

        # Search human-readable labels, such as
        # "Device Offline" or "Moderate".
        term = search_query.casefold()

        for field_name in (
            'event_type', 'severity', 'sensor_type'
        ):
            field = SystemLog._meta.get_field(field_name)

            for value, label in field.flatchoices:
                if term in str(label).casefold():
                    search |= Q(**{field_name: value})

        # Existing custom order events.
        if term in 'store orders' or 'store orders' in term:
            search |= Q(event_type='order')

        # Numeric log ID or reading value.
        numeric_term = search_query.lstrip('#')

        if (
            numeric_term.isascii()
            and numeric_term.isdigit()
            and len(numeric_term) <= 15
        ):
            numeric_value = int(numeric_term)

            search |= (
                Q(pk=numeric_value)
                | Q(value=numeric_value)
            )

        logs = logs.filter(search)

    return logs.order_by('-created_at', '-pk')

@login_required(login_url='app:login')
def client_history(request):
    """
    Admin History:
    - Global log search
    - Existing filters
    - Summary metrics
    - Pagination
    - CSV / Excel reports
    """
    if not SystemLog.objects.exists():
        SystemLog.objects.create(
            event_type='system',
            severity='good',
            message=(
                'System Audit Logger successfully initialized. '
                'Tracking is now active.'
            ),
        )

    event_type = request.GET.get('event_type', 'all')
    node_id = request.GET.get('node', 'all')
    date_range = request.GET.get('date_range', 'all')
    sensor_type = request.GET.get('sensor_type', 'all')
    severity = request.GET.get('severity', 'all')
    search_query = request.GET.get('q', '').strip()[:120]

    # Export the same filtered records shown in History.
    if request.GET.get('export') == 'csv':
        return export_history_csv(
            request, event_type, node_id,
            date_range, sensor_type, severity
        )

    if request.GET.get('export') == 'excel':
        return export_history_excel(
            request, event_type, node_id,
            date_range, sensor_type, severity
        )

    logs_query = _audit_filtered_queryset(request)

    # Pagination happens after filtering and searching.
    paginator = Paginator(logs_query, 15)
    page_obj = paginator.get_page(
        request.GET.get('page', 1)
    )

    event_types = [
        ('reading', 'Sensor Reading'),
        ('warning', 'Sensor Warning'),
        ('device_online', 'Device Online'),
        ('device_offline', 'Device Offline'),
        ('system', 'System Event'),
        ('admin', 'Admin Action'),
        ('order', 'Store Orders'),
    ]

    sensor_types = [
        ('pm2_5', 'PM2.5'),
        ('pm10', 'PM10'),
        ('pm1_0', 'PM1.0'),
        ('temperature', 'Temperature'),
        ('humidity', 'Humidity'),
        ('pressure', 'Pressure'),
        ('aqi', 'AQI'),
    ]

    severity_levels = [
        ('good', 'Good'),
        ('moderate', 'Moderate'),
        ('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
        ('unhealthy', 'Unhealthy'),
        ('very_unhealthy', 'Very Unhealthy'),
        ('hazardous', 'Hazardous'),
    ]

    context = {
        'page_obj': page_obj,
        'logs': page_obj.object_list,

        'metrics': calculate_history_metrics(logs_query),

        'nodes': SensorNode.objects.filter(
            is_active=True
        ).order_by('name'),

        'event_types': event_types,
        'sensor_types': sensor_types,
        'severity_levels': severity_levels,

        'selected_event_type': event_type,
        'selected_node': node_id,
        'selected_date_range': date_range,
        'selected_sensor_type': sensor_type,
        'selected_severity': severity,

        'search_query': search_query,
        'total_logs': paginator.count,
    }

    return render(
        request,
        'AppEnviroNode/admin/clienthistory.html',
        context
    )



def calculate_history_metrics(logs_queryset):
    """
    Calculate audit metrics using the current search and filters.
    """
    total_events = logs_queryset.count()

    normal_readings = logs_queryset.filter(
        event_type='reading',
        severity='good'
    ).count()

    warnings = logs_queryset.filter(
        Q(event_type='warning')
        | Q(
            event_type='reading',
            severity__in=[
                'moderate',
                'unhealthy_sensitive',
                'unhealthy',
                'very_unhealthy',
                'hazardous',
            ]
        )
    ).count()

    system_events = logs_queryset.filter(
        event_type__in=[
            'device_online',
            'device_offline',
            'system',
            'admin'
        ]
    ).count()

    highest_log = logs_queryset.filter(
        event_type='reading',
        value__isnull=False
    ).order_by('-value').first()

    most_active = logs_queryset.filter(
        node__isnull=False
    ).values('node__name').annotate(
        count=Count('id')
    ).order_by('-count').first()

    return {
        'total_events': total_events,
        'normal_readings': normal_readings,
        'warnings': warnings,
        'system_events': system_events,

        'highest_aqi': (
            highest_log.value if highest_log else 0
        ),

        'most_active_node': (
            most_active['node__name']
            if most_active else 'N/A'
        ),
    }


def export_history_csv(
    request,
    event_type,
    node_id,
    date_range,
    sensor_type,
    severity
):
    """
    Export all matching audit logs to CSV.
    Search and filter parameters are applied together.
    """
    logs = _audit_filtered_queryset(request)
    now = timezone.now()

    response = HttpResponse(content_type='text/csv')

    response['Content-Disposition'] = (
        f'attachment; filename="EnviroPlus_Audit_Log_'
        f'{now:%Y%m%d_%H%M%S}.csv"'
    )

    writer = csv.writer(response)

    writer.writerow([
        'Timestamp',
        'Event Type',
        'Node Name',
        'Location',
        'MAC Address',
        'Severity',
        'Sensor Type',
        'Value',
        'Message',
    ])

    for log in logs.iterator(chunk_size=500):
        node = log.node

        writer.writerow([
            timezone.localtime(
                log.created_at
            ).strftime('%Y-%m-%d %H:%M:%S'),

            log.get_event_type_display(),

            node.name if node else 'System',
            node.location if node else 'N/A',
            node.mac_address if node else 'N/A',

            (
                log.get_severity_display()
                if log.severity else 'N/A'
            ),

            (
                log.get_sensor_type_display()
                if log.sensor_type else 'N/A'
            ),

            log.value if log.value is not None else 'N/A',
            log.message,
        ])

    return response


@login_required(login_url='app:login')
def client_users(request):
    # Enforce admin-only access
    if not request.user.is_admin_user():
        messages.error(request, 'You do not have permission to access user management.')
        return redirect('app:client_dashboard')
    
    return render(request, 'AppEnviroNode/admin/clientusers.html')

@login_required(login_url='app:login')
def client_ai(request):
    return render(request, 'AppEnviroNode/admin/clientai.html')


# API ENDPOINTS for ESP8266 Sensor Integration
@csrf_exempt
@require_http_methods(["POST"])
def api_sensor_data(request):
    """
    Receive sensor data from ESP8266 nodes with API key authentication.
    
    ✅ SECURITY FIX: Implements API key authentication (Issue 2.1)
    
    Header: Authorization: Bearer <API_KEY>
    Expected JSON: {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "pm1_0": 10.5,
        "pm2_5": 25.3,
        "pm10": 45.2,
        "temperature": 28.5,
        "humidity": 65.0,
        "pressure": 1013.25,
        "gas_resistance": 120.5,
        "system_status": "normal",
        "pms_status": "ok",
        "bme_status": "ok",
        "latency_ms": 79
    }
    """
    try:
        # ✅ AUTHENTICATION CHECK (Fix for Issue 2.1: No API Authentication)
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return JsonResponse({
                'success': False,
                'message': 'Missing or invalid Authorization header. Use: Authorization: Bearer <API_KEY>'
            }, status=401)
        
        api_key = auth_header.replace('Bearer ', '').strip()
        
        # Verify API key exists and is active
        try:
            from .models import SensorNodeAPIKey
            api_key_obj = SensorNodeAPIKey.objects.select_related('node').get(
                api_key=api_key,
                is_active=True
            )
            authenticated_node = api_key_obj.node
            
            # Update last_used timestamp
            api_key_obj.last_used = timezone.now()
            api_key_obj.save(update_fields=['last_used'])
            
        except SensorNodeAPIKey.DoesNotExist:
            logger.warning(f"Invalid or inactive API key used: {api_key[:8]}...")
            return JsonResponse({
                'success': False,
                'message': 'Invalid or inactive API key'
            }, status=401)
        
        # ✅ INPUT VALIDATION (Fix for Issue 4.4: Minimal Input Validation)
        if isinstance(request.body, bytes):
            body_str = request.body.decode('utf-8')
        else:
            body_str = request.body
        
        data = json.loads(body_str)
        mac_address = data.get('mac_address', '').strip()
        
        # Validate MAC address format (accepts both standard MAC and custom identifiers like ENVIROPLUS_XXX)
        import re
        # Match either: AA:BB:CC:DD:EE:FF or custom identifiers like ENVIROPLUS_001
        if not re.match(r'^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$|^[A-Za-z0-9_-]+$', mac_address):
            return JsonResponse({
                'success': False,
                'message': 'Invalid MAC address format. Expected: AA:BB:CC:DD:EE:FF or custom identifier like ENVIROPLUS_001'
            }, status=400)
        
        # ✅ VERIFY MAC ADDRESS MATCHES REGISTERED NODE (prevents spoofing)
        if mac_address != authenticated_node.mac_address:
            logger.warning(f"MAC mismatch for API key {api_key[:8]}...: Expected {authenticated_node.mac_address}, got {mac_address}")
            return JsonResponse({
                'success': False,
                'message': 'MAC address does not match registered node'
            }, status=403)
        
        # ✅ VALIDATE SENSOR VALUE RANGES (Fix for Issue 4.4)
        def validate_sensor_value(value, min_val, max_val, name):
            if value is None:
                return None
            try:
                val = float(value)
                if not min_val <= val <= max_val:
                    raise ValueError(f"{name} out of range: {val}")
                return val
            except (ValueError, TypeError):
                raise ValueError(f"{name} invalid value: {value}")
        
        try:
            pm1_0 = validate_sensor_value(data.get('pm1_0'), 0, 1000, "PM1.0")
            pm2_5 = validate_sensor_value(data.get('pm2_5'), 0, 1000, "PM2.5")
            pm10 = validate_sensor_value(data.get('pm10'), 0, 1000, "PM10")
            temperature = validate_sensor_value(data.get('temperature'), -50, 60, "Temperature")
            humidity = validate_sensor_value(data.get('humidity'), 0, 100, "Humidity")
            pressure = validate_sensor_value(data.get('pressure'), 300, 1100, "Pressure")
            gas_resistance = validate_sensor_value(data.get('gas_resistance'), 0, 1000000, "Gas Resistance")
            latency_ms = validate_sensor_value(data.get('latency_ms'), 0, 60000, "Latency")
            
            # 🔧 DEFENSIVE: Validate MQ135 raw value with fallback
            mq135_raw = data.get('mq135_raw')
            if mq135_raw is None:
                mq135_raw = -1
            else:
                try:
                    mq135_raw = int(mq135_raw)
                    # Clamp to valid range (0-1024) or mark as unavailable (-1)
                    if mq135_raw < -1:
                        mq135_raw = -1
                    elif mq135_raw > 1024:
                        mq135_raw = 1024
                except (ValueError, TypeError):
                    logger.warning(f"Invalid mq135_raw value: {data.get('mq135_raw')}, using fallback -1")
                    mq135_raw = -1
            
            logger.debug(f"[API] Incoming sensor data: pm2_5={pm2_5}, mq135_raw={mq135_raw}, gas_resistance={gas_resistance}")
            
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=400)
        
        # Validate status fields
        valid_statuses = ['normal', 'degraded', 'critical']
        valid_sensor_statuses = ['ok', 'error']
        
        system_status = data.get('system_status', 'normal')
        if system_status not in valid_statuses:
            system_status = 'normal'
        
        pms_status = data.get('pms_status', 'ok')
        if pms_status not in valid_sensor_statuses:
            pms_status = 'ok'
        
        bme_status = data.get('bme_status', 'ok')
        if bme_status not in valid_sensor_statuses:
            bme_status = 'ok'
        
        # 🔧 CALCULATE GAS QUALITY FIELDS (never leave null)
        from .utils import calculate_gas_quality, infer_pollution_source, calculate_aqi
        
        gas_quality_level, gas_source, gas_alert_flag = calculate_gas_quality(
            mq135_raw=mq135_raw if mq135_raw >= 0 else None,
            gas_resistance=gas_resistance
        )
        
        # Infer pollution source from multiple factors
        if pm2_5 is not None:
            aqi_level, _ = calculate_aqi(pm2_5)  # Get AQI level from PM2.5
        else:
            aqi_level = None
        
        pollution_source = infer_pollution_source(
            aqi_level=aqi_level,
            gas_quality=gas_quality_level,
            pm2_5=pm2_5,
            pm10=pm10,
            temperature=temperature,
            humidity=humidity
        )
        
        logger.debug(f"[API] Computed gas fields: quality={gas_quality_level}, source={pollution_source}, alert={gas_alert_flag}")
        
        # Node is already verified by API key, update status to active
        if authenticated_node.status != 'active':
            authenticated_node.status = 'active'
        
        # Create sensor reading with ALL fields including gas fields (NEVER NULL)
        reading = SensorReading.objects.create(
            node=authenticated_node,
            pm1_0=pm1_0,
            pm2_5=pm2_5,
            pm10=pm10,
            temperature=temperature,
            humidity=humidity,
            pressure=pressure,
            gas_resistance=gas_resistance,
            mq135_raw=mq135_raw if mq135_raw >= 0 else None,  # Store raw value for debugging
            gas_quality=gas_quality_level,  # ✅ ALWAYS SET - never null
            pollution_source=pollution_source,  # ✅ ALWAYS SET - never null
            gas_alert=gas_alert_flag,  # ✅ ALWAYS SET - never null
            system_status=system_status,
            pms_status=pms_status,
            bme_status=bme_status,
            latency_ms=latency_ms,
            timestamp=timezone.now(),
        )
        
        # Update node's last_reading timestamp
        authenticated_node.last_reading = timezone.now()
        authenticated_node.last_seen = timezone.now()
        authenticated_node.save()
        
        logger.info(
            f"Reading recorded: node={authenticated_node.name}, reading_id={reading.id}, "
            f"aqi={reading.aqi}, gas_quality={reading.gas_quality}, gas_alert={reading.gas_alert}"
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Reading recorded successfully',
            'reading_id': reading.id,
            'node_id': authenticated_node.id,
            'node_status': authenticated_node.status,
            'aqi': reading.aqi,
            'aqi_level': reading.aqi_level,
            'gas_quality': reading.gas_quality,
            'gas_alert': reading.gas_alert,
            'pollution_source': reading.pollution_source,
        }, status=201)
        
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON: {str(e)}"
        logger.error(error_msg)
        return JsonResponse({'success': False, 'message': error_msg}, status=400)
    
    except Exception as e:
        error_msg = f"Server error: {str(e)}"
        logger.error(error_msg, exc_info=True)
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
                'id': reading.id,  # Add reading ID for CRUD operations
                'reading_id': reading.id,  # Alias for API calls
                'timestamp': reading.timestamp.isoformat(),
                'label': f'{reading.timestamp.hour}h',
                'aqi': reading.aqi or 0,
                'pm2_5': reading.pm2_5 or 0,
                'pm10': reading.pm10 or 0,
                'temperature': reading.temperature or 0,
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

def parse_analytics_date_window(request):
    timeframe = request.GET.get('timeframe', '7d')
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    time_map = {'24h': 1, '7d': 7, '30d': 30}
    days = time_map.get(timeframe, 7)
    now = timezone.now()
    time_threshold = now - timedelta(days=days)
    time_end = now

    if timeframe == 'custom' and start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            if end_dt < start_dt:
                start_dt, end_dt = end_dt, start_dt
            time_threshold = timezone.make_aware(datetime.combine(start_dt, datetime.min.time()))
            time_end = timezone.make_aware(datetime.combine(end_dt, datetime.max.time()))
            days = (end_dt - start_dt).days + 1
        except (ValueError, TypeError):
            time_threshold = now - timedelta(days=days)
            time_end = now

    return timeframe, time_threshold, time_end, days


def apply_analytics_filters(readings_qs, request):
    node_id = request.GET.get('node_id', 'all')
    location = request.GET.get('location', 'all')

    if node_id != 'all':
        try:
            readings_qs = readings_qs.filter(node_id=int(node_id))
        except (ValueError, TypeError):
            pass

    if location and location != 'all':
        if location.lower() == 'unknown':
            readings_qs = readings_qs.filter(models.Q(node__location__isnull=True) | models.Q(node__location__exact=''))
        else:
            readings_qs = readings_qs.filter(node__location__iexact=location)

    return readings_qs


@csrf_exempt
@require_http_methods(["GET"])
@csrf_exempt
@require_http_methods(["GET"])
@cache_api_response(ttl_seconds=45)
def api_analytics_overview(request):
    """
    GET /api/analytics/overview/
    
    OPTIMIZED: Returns current aggregate analytics (cached 45s)
    - Only queries necessary fields
    - Limits aggregations to essential metrics
    
    Query Parameters:
    - timeframe: '24h', '7d', '30d' (default: '7d')
    - node_id: Specific node ID or 'all' (default: 'all')
    """
    try:
        timeframe, time_threshold, time_end, days = parse_analytics_date_window(request)

        # ⚡ OPTIMIZATION: Only fetch and aggregate essential fields
        readings_qs = SensorReading.objects.filter(
            timestamp__gte=time_threshold,
            timestamp__lte=time_end
        ).only('aqi', 'pm2_5', 'pm10', 'temperature', 'gas_resistance')
        
        readings_qs = apply_analytics_filters(readings_qs, request)
        
        # Single aggregation query (all at once)
        agg = readings_qs.aggregate(
            aqi_avg=Avg('aqi'),
            aqi_max=Max('aqi'),
            aqi_min=Min('aqi'),
            pm25_avg=Avg('pm2_5'),
            pm10_avg=Avg('pm10'),
            temp_avg=Avg('temperature'),
            gas_res_avg=Avg('gas_resistance')
        )
        
        current_aqi = agg['aqi_avg'] or 75
        pm25_val = agg['pm25_avg'] or 25
        pm10_val = agg['pm10_avg'] or 40
        total_pm = pm25_val + pm10_val
        
        pm25_pct = int((pm25_val / total_pm * 100)) if total_pm > 0 else 50
        pm10_pct = int((pm10_val / total_pm * 100)) if total_pm > 0 else 30
        other_pct = 100 - pm25_pct - pm10_pct
        
        # ⚡ OPTIMIZATION: Single risk query with annotate instead of multiple filters
        total = readings_qs.count()
        risk_counts = readings_qs.aggregate(
            stable=Count('id', filter=Q(aqi__lte=50)),
            elevated=Count('id', filter=Q(aqi__gt=50, aqi__lte=150)),
            critical=Count('id', filter=Q(aqi__gt=150))
        )
        
        stable_pct = int((risk_counts['stable'] / total * 100)) if total > 0 else 60
        elevated_pct = int((risk_counts['elevated'] / total * 100)) if total > 0 else 25
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
            'temperature': round(agg['temp_avg'] or 28, 1),
            'gas_resistance': round(agg['gas_res_avg'] or 0, 1),
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
    GET /api/nodes/<node_id>/detail/?timeframe=7d
    
    Returns detailed data for a specific node respecting timeframe filter:
    - Current readings
    - Sparkline data for selected timeframe (24h, 7d, 30d, custom)
    - Peak values within timeframe
    - Status
    """
    try:
        node = SensorNode.objects.get(id=node_id)
        latest = node.readings.order_by('-timestamp').first()
        
        # FIXED: Parse timeframe parameter to determine data range
        timeframe = request.GET.get('timeframe', '24h')
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')
        
        now = timezone.now()
        cutoff_time = now
        
        if timeframe == '24h':
            cutoff_time = now - timedelta(hours=24)
        elif timeframe == '7d':
            cutoff_time = now - timedelta(days=7)
        elif timeframe == '30d':
            cutoff_time = now - timedelta(days=30)
        elif timeframe == 'custom' and start_date_str:
            try:
                # Parse ISO format datetime string
                if 'T' in start_date_str:
                    start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
                else:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                cutoff_time = timezone.make_aware(start_date) if not timezone.is_aware(start_date) else start_date
            except Exception as e:
                print(f'[Analytics API] Error parsing custom date: {e}')
                cutoff_time = now - timedelta(hours=24)  # Fallback
        else:
            cutoff_time = now - timedelta(hours=24)  # Default fallback
        
        # Get sparkline data for selected timeframe
        recent_readings = node.readings.filter(
            timestamp__gte=cutoff_time
        ).order_by('timestamp')
        
        sparkline_data = []
        for i, reading in enumerate(recent_readings):
            sparkline_data.append({
                'id': reading.id,  # Add reading ID for CRUD operations
                'reading_id': reading.id,  # Alias for API calls
                'timestamp': reading.timestamp.isoformat(),
                'aqi': reading.aqi or 0,
                'pm2_5': reading.pm2_5 or 0,
                'pm10': reading.pm10 or 0,
                'temperature': reading.temperature or 0,
                'value': reading.aqi or 0,
                'label': f'{reading.timestamp.hour}h'
            })
        
        # Get peak within selected timeframe (not always 24h)
        peak_readings = node.readings.filter(timestamp__gte=cutoff_time)
        peak_aqi = peak_readings.aggregate(Max('aqi'))['aqi__max'] or 0
        
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
@csrf_exempt
@require_http_methods(["GET"])
@cache_api_response(ttl_seconds=45)
def api_analytics_trends(request):
    """
    GET /api/analytics/trends/
    
    OPTIMIZED: Returns aggregated time-series trend data
    - Adaptive aggregation based on timeframe (minute/hour/day)
    - Limited datapoints for efficient rendering
    - Cached for 45 seconds
    
    Query Parameters:
    - timeframe: '24h', '7d', '30d' (default: '7d')
    - metric: 'aqi', 'pm25', 'pm10', 'temp' (default: 'aqi')
    - node_id: Specific node ID or 'all' (default: 'all')
    """
    try:
        timeframe = request.GET.get('timeframe', '7d')
        metric = request.GET.get('metric', 'aqi')
        metric_field_map = {
            'aqi': 'aqi',
            'pm25': 'pm2_5',
            'pm10': 'pm10',
            'temp': 'temperature'
        }
        metric_field = metric_field_map.get(metric, 'aqi')
        timeframe, time_threshold, time_end, days = parse_analytics_date_window(request)

        # ⚡ OPTIMIZATION: Determine aggregation strategy based on timeframe
        strategy = get_aggregation_strategy(days)

        # Build queryset with minimal fields
        readings_qs = SensorReading.objects.filter(
            timestamp__gte=time_threshold,
            timestamp__lte=time_end,
            **{f'{metric_field}__isnull': False}
        ).select_related('node').only('timestamp', metric_field, 'node_id')
        
        readings_qs = apply_analytics_filters(readings_qs, request)
        
        # ⚡ OPTIMIZATION: Use aggregation strategy instead of raw readings
        aggregated, trunc_func, grouping_fmt = aggregate_readings(readings_qs, strategy, metric_field)
        
        datapoints = []
        for item in aggregated:
            period = item['period']
            if period is None:
                continue
            
            datapoints.append({
                'date': period.strftime(grouping_fmt) if hasattr(period, 'strftime') else str(period),
                'label': period.strftime(grouping_fmt) if hasattr(period, 'strftime') else str(period),
                'timestamp': period.isoformat() if hasattr(period, 'isoformat') else str(period),
                'value': round(item['avg_val'] or 0, 1)
            })

        # ⚡ OPTIMIZATION: Cap datapoints to max reasonable for frontend rendering
        max_points = {'minute': 60, 'hour': 168, 'day': 90}.get(strategy, 60)
        if len(datapoints) > max_points:
            # Further downsample if needed
            step = len(datapoints) // max_points + 1
            datapoints = datapoints[::step]

        return JsonResponse({
            'success': True,
            'metric': metric,
            'timeframe': timeframe,
            'aggregation': strategy,
            'datapoints': datapoints,
            'count': len(datapoints)
        }, status=200)
        
    except Exception as e:
        logger.error(f'Analytics trends error: {e}')
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


# ============================================================================
# SPIKE MANAGEMENT API ENDPOINTS
# ============================================================================

@csrf_exempt
@require_http_methods(["DELETE"])
@login_required(login_url='app:login')
def api_spike_delete(request):
    """Delete a spike reading (actually deletes the SensorReading record)"""
    try:
        reading_id = request.GET.get('reading_id')
        if not reading_id:
            return JsonResponse({'success': False, 'error': 'reading_id required'}, status=400)
        
        reading = get_object_or_404(SensorReading, id=reading_id)
        node_id = reading.node.id
        reading.delete()
        
        # Log the action
        AdminActionLog.objects.create(
            user=request.user,
            action='DELETE_SPIKE',
            details=f'Deleted spike reading {reading_id} (AQI: {reading.aqi}) from node {node_id}',
            severity='info'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Spike reading deleted successfully',
            'deleted_id': reading_id
        }, status=200)
    
    except SensorReading.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Reading not found'}, status=404)
    except Exception as e:
        logger.error(f'[Spike API] Delete failed: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@login_required(login_url='app:login')
def api_spike_flag(request):
    """Flag a spike reading as anomalous (for review/analysis)"""
    try:
        reading_id = request.GET.get('reading_id')
        action = request.GET.get('action', 'flag')  # 'flag', 'unflag'
        
        if not reading_id:
            return JsonResponse({'success': False, 'error': 'reading_id required'}, status=400)
        
        reading = get_object_or_404(SensorReading, id=reading_id)
        
        # Add custom field to flag anomalies (if extended in future)
        # For now, log the action
        AdminActionLog.objects.create(
            user=request.user,
            action=f'{action.upper()}_SPIKE',
            details=f'{action.capitalize()} spike reading {reading_id} (AQI: {reading.aqi}) from node {reading.node.id}',
            severity='info'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Spike {action} completed',
            'reading_id': reading_id,
            'action': action
        }, status=200)
    
    except SensorReading.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Reading not found'}, status=404)
    except Exception as e:
        logger.error(f'[Spike API] Flag failed: {str(e)}')
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
    GET /api/realtime-data/

    Dual-mode endpoint supporting both:
    1. Public realtime.html: range, node, start_date, end_date params
    2. Admin clientrealtime.js: filter, zone, time_range params
    """
    try:
        now = timezone.now()
        
        # Detect mode by checking for 'range' parameter (public) vs 'filter' (admin)
        is_public_realtime = 'range' in request.GET
        
        if is_public_realtime:
            # PUBLIC REALTIME.HTML MODE - supports filtering by range and node
            filters = build_realtime_filters(request)
            readings_qs = build_realtime_queryset(filters)
            
            # Calculate stats
            total_readings = readings_qs.count()
            active_nodes = SensorNode.objects.filter(is_active=True).count()
            avg_aqi = None
            latest_node_name = 'Unknown'
            latest_node_location = 'Unknown'
            latest_timestamp = None
            
            if readings_qs.filter(aqi__isnull=False).exists():
                agg = readings_qs.aggregate(avg_aqi=Avg('aqi'))
                avg_aqi = round(agg['avg_aqi'], 1) if agg['avg_aqi'] is not None else None
                
                # Get latest reading for live monitoring
                latest_reading = readings_qs.select_related('node').order_by('-timestamp').first()
                if latest_reading:
                    latest_node_name = latest_reading.node.name
                    latest_node_location = latest_reading.node.location or 'Unknown'
                    latest_timestamp = latest_reading.timestamp.isoformat()
            
            chart_data = build_realtime_chart_data(readings_qs, filters['selected_range'])
            
            return JsonResponse({
                'success': True,
                'summary': {
                    'avg_aqi': avg_aqi,
                    'latest_aqi': avg_aqi,
                    'latest_node_name': latest_node_name,
                    'latest_node_location': latest_node_location,
                    'latest_timestamp': latest_timestamp,
                    'total_readings': total_readings,
                    'active_nodes': active_nodes,
                    'range_label': filters['range_label'],
                },
                'chart_data': chart_data,
            })

        else:
            # ADMIN CLIENTREALTIME.JS MODE - fast 1/5/15 minute monitoring
            current_filter = request.GET.get('filter', 'all').lower()
            current_zone = request.GET.get('zone', 'all').lower()
            time_range = request.GET.get('time_range', '15m').lower()

            if time_range == '1m':
                time_start = now - timedelta(minutes=1)
            elif time_range == '5m':
                time_start = now - timedelta(minutes=5)
            else:
                time_start = now - timedelta(minutes=15)

            all_nodes = SensorNode.objects.filter(is_active=True)
            zones = list(all_nodes.exclude(location__isnull=True).exclude(location='').values_list('location', flat=True).distinct())

            readings_qs = SensorReading.objects.filter(
                timestamp__gte=time_start,
                timestamp__lte=now
            ).select_related('node')

            node_data = []
            active_nodes_count = 0
            total_aqi_values = []

            for node in all_nodes:
                latest = readings_qs.filter(node=node).order_by('-timestamp').first()
                if latest:
                    node_aqi = latest.aqi
                    if node_aqi is not None:
                        total_aqi_values.append(node_aqi)

                    node_item = {
                        'node_id': node.id,
                        'name': node.name,
                        'zone': getattr(node, 'zone', None) or node.location or 'Unknown',
                        'location': node.location or '',
                        'status': node.status or 'inactive',
                        'aqi': node_aqi,
                        'latest_aqi': node_aqi,
                        'pm2_5': latest.pm2_5,
                        'pm10': latest.pm10,
                        'temperature': latest.temperature,
                        'humidity': latest.humidity,
                        'co2': getattr(latest, 'co2', None),
                        'co2_level': getattr(latest, 'co2_level', None),
                        'timestamp': int(latest.timestamp.timestamp()) if latest.timestamp else None,
                        'last_seen': latest.timestamp.strftime('%Y-%m-%d %H:%M:%S') if latest.timestamp else None,
                        'battery': getattr(node, 'battery_level', None),
                        'battery_level': getattr(node, 'battery_level', None),
                        'signal_strength': getattr(node, 'signal_strength', None),
                        'rssi': getattr(node, 'rssi', None),
                        'uptime': getattr(node, 'uptime', None),
                        'uptime_seconds': getattr(node, 'uptime_seconds', None),
                    }
                    if node.status == 'active':
                        active_nodes_count += 1
                    node_data.append(node_item)

            filtered_data = node_data
            if current_filter == 'online':
                filtered_data = [n for n in filtered_data if n['status'] == 'active']
            elif current_filter == 'alerts':
                filtered_data = [n for n in filtered_data if n['status'] != 'active' or (n['aqi'] is not None and n['aqi'] > 65)]

            if current_zone != 'all':
                filtered_data = [n for n in filtered_data if n['zone'].lower() == current_zone]

            live_aqi = round(sum(total_aqi_values) / len(total_aqi_values), 1) if total_aqi_values else None

            chart_values = []
            if readings_qs.exists():
                from django.db.models.functions import TruncMinute
                chart_agg = readings_qs.filter(aqi__isnull=False).annotate(
                    period=TruncMinute('timestamp')
                ).values('period').annotate(
                    avg_aqi=Avg('aqi')
                ).order_by('period')[:30]
                chart_values = [round(item['avg_aqi'], 1) for item in chart_agg if item['avg_aqi'] is not None]

            feed = []
            recent_readings = readings_qs.order_by('-timestamp')[:10]
            for reading in recent_readings:
                if reading.aqi is not None:
                    severity = 'critical' if reading.aqi > 150 else 'warning' if reading.aqi > 100 else 'info'
                    feed.append({
                        'node_id': reading.node_id,
                        'title': f'AQI reading: {reading.aqi}',
                        'description': f'{reading.node.name} reported AQI {reading.aqi}',
                        'severity': severity,
                        'tag_label': severity.upper(),
                        'tag_class': f'crealtime-tag-{severity}',
                        'bg_class': 'crealtime-bg-green' if severity == 'info' else 'crealtime-bg-yellow' if severity == 'warning' else 'crealtime-bg-red',
                        'icon': '✓' if severity == 'info' else '⚠' if severity == 'warning' else '🚨',
                        'timestamp': int(reading.timestamp.timestamp()) if reading.timestamp else None,
                        'timestamp_unix': int(reading.timestamp.timestamp()) if reading.timestamp else None,
                    })

            alerts = []
            for node in node_data:
                if node['status'] != 'active':
                    alerts.append({
                        'node_name': node['name'],
                        'title': f'Node Offline: {node["name"]}',
                        'description': f'Node has not reported data recently',
                        'severity': 'critical',
                    })
                elif node['aqi'] is not None and node['aqi'] > 100:
                    alerts.append({
                        'node_name': node['name'],
                        'title': f'High AQI Alert: {node["name"]}',
                        'description': f'AQI level {node["aqi"]} exceeds safe threshold',
                        'severity': 'warning' if node['aqi'] <= 150 else 'critical',
                    })

            return JsonResponse({
                'status': 'success',
                'data': filtered_data,
                'feed': feed,
                'alerts': alerts,
                'chart_values': chart_values,
                'active_nodes': active_nodes_count,
                'total_nodes': all_nodes.count(),
                'live_aqi': live_aqi,
                'zones': zones,
            })

    except Exception as e:
        logger.error(f"API realtime data error: {e}", exc_info=True)
        is_public = 'range' in request.GET
        if is_public:
            return JsonResponse({
                'success': False,
                'error': str(e),
                'summary': {},
                'chart_data': [],
            }, status=500)
        else:
            return JsonResponse({
                'status': 'error',
                'error': str(e),
                'data': [],
                'feed': [],
                'alerts': [],
                'chart_values': [],
                'active_nodes': 0,
                'total_nodes': 0,
                'live_aqi': None,
                'zones': [],
            }, status=500)


@require_http_methods(["GET"])
@cache_page(300)
def api_daily_forecast(request):
    try:
        from .utils import predict_next_day_aqi, get_aqi_category
        
        now = timezone.now()
        today = now.astimezone(timezone.get_current_timezone()).date()
        
        readings = SensorReading.objects.filter(
            timestamp__gte=now - timedelta(days=30),
            timestamp__lte=now,
            aqi__isnull=False
        ).select_related('node').only(
            'aqi', 'pm2_5', 'temperature', 'timestamp'
        ).order_by('timestamp')
        
        daily_groups = {}
        for reading in readings:
            if not reading.timestamp:
                continue
            try:
                reading_date = reading.timestamp.astimezone(timezone.get_current_timezone()).date()
            except (TypeError, AttributeError):
                continue
            
            if reading_date not in daily_groups:
                daily_groups[reading_date] = {
                    'aqi_values': [],
                    'pm2_5_values': [],
                    'temp_values': [],
                    'count': 0
                }
            
            if reading.aqi is not None:
                daily_groups[reading_date]['aqi_values'].append(reading.aqi)
            if reading.pm2_5 is not None:
                daily_groups[reading_date]['pm2_5_values'].append(reading.pm2_5)
            if reading.temperature is not None:
                daily_groups[reading_date]['temp_values'].append(reading.temperature)
            daily_groups[reading_date]['count'] += 1
        
        daily_aggregates = []
        sorted_dates = sorted(daily_groups.keys())
        
        for date in sorted_dates:
            group = daily_groups[date]
            daily_aggregates.append({
                'date': date,
                'aqi_values': group['aqi_values'],
                'pm2_5_values': group['pm2_5_values'],
                'temp_values': group['temp_values'],
                'avg_aqi': round(sum(group['aqi_values']) / len(group['aqi_values']), 1) if group['aqi_values'] else None,
                'avg_pm2_5': round(sum(group['pm2_5_values']) / len(group['pm2_5_values']), 1) if group['pm2_5_values'] else None,
                'avg_temperature': round(sum(group['temp_values']) / len(group['temp_values']), 1) if group['temp_values'] else None,
            })
        
        if len(daily_aggregates) == 0:
            return JsonResponse({
                'success': True,
                'forecast': [],
                'message': 'No data available',
                'generated_at': now.isoformat(),
                'confidence_level': 'low'
            }, status=200)
        
        recent_aqi_all = [d['avg_aqi'] for d in daily_aggregates if d['avg_aqi'] is not None]
        recent_pm2_5_all = [d['avg_pm2_5'] for d in daily_aggregates if d['avg_pm2_5'] is not None]
        recent_temp_all = [d['avg_temperature'] for d in daily_aggregates if d['avg_temperature'] is not None]
        
        forecast_list = []
        
        history_start = today - timedelta(days=6)
        
        for i in range(-6, 4):
            forecast_date = today + timedelta(days=i)
            is_current = (forecast_date == today)
            is_predicted = (forecast_date > today)
            is_historical = (forecast_date < today)
            
            actual_data = next((d for d in daily_aggregates if d['date'] == forecast_date), None)
            
            if actual_data:
                aqi_level = get_aqi_category(actual_data['avg_aqi']) if actual_data['avg_aqi'] else 'unknown'
                forecast_list.append({
                    'date': forecast_date.isoformat(),
                    'day_label': forecast_date.strftime('%A')[:3],
                    'day_subtitle': forecast_date.strftime('%b %d, %Y'),
                    'avg_aqi': actual_data['avg_aqi'],
                    'aqi_level': aqi_level,
                    'avg_pm2_5': actual_data['avg_pm2_5'],
                    'avg_temperature': actual_data['avg_temperature'],
                    'confidence': 1.0,
                    'trend': 'stable',
                    'is_predicted': False,
                    'is_current': is_current,
                    'is_historical': is_historical,
                    'data_points': len(actual_data['aqi_values'])
                })
            elif is_predicted:
                if recent_aqi_all:
                    prediction = predict_next_day_aqi(
                        [(i, aqi) for i, aqi in enumerate(recent_aqi_all[-7:])],
                        confidence_threshold=0.5
                    )
                    predicted_aqi = prediction.get('predicted_aqi') if prediction else None
                    predicted_confidence = prediction.get('confidence', 0.5) if prediction else 0.5
                    predicted_trend = prediction.get('trend', 'stable') if prediction else 'stable'
                else:
                    predicted_aqi = None
                    predicted_confidence = 0.0
                    predicted_trend = 'stable'
                
                if predicted_aqi is not None:
                    forecast_list.append({
                        'date': forecast_date.isoformat(),
                        'day_label': forecast_date.strftime('%A')[:3],
                        'day_subtitle': forecast_date.strftime('%b %d, %Y'),
                        'avg_aqi': predicted_aqi,
                        'aqi_level': get_aqi_category(predicted_aqi),
                        'avg_pm2_5': sum(recent_pm2_5_all) / len(recent_pm2_5_all) if recent_pm2_5_all else None,
                        'avg_temperature': sum(recent_temp_all) / len(recent_temp_all) if recent_temp_all else None,
                        'confidence': predicted_confidence,
                        'trend': predicted_trend,
                        'is_predicted': True,
                        'is_current': False,
                        'is_historical': False,
                        'data_points': 0
                    })
        
        overall_confidence = 'high' if len(daily_aggregates) >= 14 else ('medium' if len(daily_aggregates) >= 7 else 'low')
        
        return JsonResponse({
            'success': True,
            'forecast': forecast_list[-7:] if len(forecast_list) > 7 else forecast_list,
            'generated_at': now.isoformat(),
            'confidence_level': overall_confidence,
            'data_coverage_days': len(daily_aggregates),
            'history_span_days': (sorted_dates[-1] - sorted_dates[0]).days if len(sorted_dates) > 1 else 0
        }, status=200)
        
    except Exception as e:
        logger.error(f'Forecast error: {str(e)[:200]}', exc_info=True)
        return JsonResponse({
            'success': True,
            'forecast': [],
            'generated_at': timezone.now().isoformat(),
            'confidence_level': 'low'
        }, status=200)


# ============================================================================
# USER MANAGEMENT API ENDPOINTS
# ============================================================================

@csrf_exempt
@require_http_methods(["GET"])
def api_auth_me(request):
    """Get current authenticated user info."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
    
    return JsonResponse({
        'id': request.user.id,
        'username': request.user.username,
        'email': request.user.email,
        'role': request.user.role,
        'is_admin': request.user.is_admin_user(),
    })


@login_required(login_url='app:login')
@require_http_methods(["GET"])
def api_users(request):
    """List all users with server-side filtering and pagination."""
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    # Get query parameters
    search = request.GET.get('search', '').strip()
    role_filter = request.GET.get('role', 'all')
    status_filter = request.GET.get('status', 'all')
    page = request.GET.get('page', 1)
    limit = request.GET.get('limit', 10)
    
    try:
        limit = int(limit)
        if limit < 1 or limit > 100:
            limit = 10
    except (ValueError, TypeError):
        limit = 10
    
    # Start with base queryset
    users_qs = User.objects.all().order_by('-created_at')
    
    # Apply search filter
    if search:
        users_qs = users_qs.filter(
            Q(username__icontains=search) | 
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    
    # Apply role filter
    if role_filter and role_filter != 'all':
        users_qs = users_qs.filter(role=role_filter)
    
    # Apply status filter
    if status_filter and status_filter != 'all':
        if status_filter == 'active':
            users_qs = users_qs.filter(is_active=True, is_approved=True)
        elif status_filter == 'pending':
            users_qs = users_qs.filter(is_approved=False)
        elif status_filter == 'disabled':
            users_qs = users_qs.filter(is_active=False)
    
    # Paginate with configurable limit
    paginator = Paginator(users_qs, limit)
    page_obj = paginator.get_page(page)
    
    # Serialize users
    users_data = []
    for user in page_obj:
        users_data.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'role': user.role,
            'organization': user.organization or '',
            'is_active': user.is_active,
            'is_approved': user.is_approved,
            'must_change_password': user.must_change_password,
            'status': 'active' if (user.is_active and user.is_approved) else ('pending' if not user.is_approved else 'disabled'),
            'created_at': user.created_at.isoformat() if hasattr(user, 'created_at') else user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
        })
    
    return JsonResponse({
        'status': 'success',
        'data': users_data,
        'pagination': {
            'total': paginator.count,
            'page': int(page),
            'pages': paginator.num_pages,
            'per_page': limit,
        }
    })


@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_users_create(request):
    """Create a new user manually."""
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    try:
        import json
        data = json.loads(request.body)
    except:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    role = data.get('role', 'official')
    password = data.get('password', '').strip()
    
    if not all([name, email, password]):
        return JsonResponse({'status': 'error', 'message': 'Missing required fields'}, status=400)
    
    # ✅ FRONTEND VALIDATION: Check if email exists
    if User.objects.filter(email=email).exists():
        return JsonResponse({'status': 'error', 'message': 'Email already registered'}, status=400)
    
    try:
        username = data.get('username', '').strip()
        first_name = data.get('first_name', 'Placeholder')
        last_name = data.get('last_name', 'Placeholder')

        if not username:
            return JsonResponse({'status': 'error', 'message': 'Username is required'}, status=400)

            # Check if username already exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({'status': 'error', 'message': 'Username is already taken'}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_approved=True, 
            is_active=True,
            must_change_password=True, 
        )
        
        # ✅ AUDIT LOGGING
        AdminActionLog.objects.create(
            user=request.user,
            action='user_created',
            target_model='CustomUser',
            target_id=user.id,
            description=f"Manually created user {user.email} with role {role}"
        )
        
        # ✅ ALERT SYSTEM: Log user creation event
        Alert.objects.create(
            node=None,
            severity='info',
            title='User Created',
            description=f'User {user.email} ({user.get_role_display()}) was created by {request.user.email}',
            is_active=True
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'User created successfully',
            'data': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'full_name': f"{user.first_name} {user.last_name}".strip(),
            }
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_users_invite(request):
    """Send invitation to new user (creates pending account)."""
    try:
        # ✅ ROLE-BASED ACCESS CONTROL
        if not request.user.is_admin_user():
            return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
        
        try:
            import json
            data = json.loads(request.body)
        except:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        
        # ✅ NEW: Extract explicit fields instead of just 'name'
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        first_name = data.get('first_name', 'Placeholder').strip()
        last_name = data.get('last_name', 'Placeholder').strip()
        role = data.get('role', 'official')
        
        # ✅ FIX: Require username instead of name
        if not all([email, username]):
            return JsonResponse({'status': 'error', 'message': 'Missing required fields'}, status=400)
        
        # ✅ FRONTEND VALIDATION: Check if email exists
        if User.objects.filter(email=email).exists():
            return JsonResponse({'status': 'error', 'message': 'Email already registered'}, status=400)
            
        # ✅ NEW VALIDATION: Check if username exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({'status': 'error', 'message': 'Username is already taken'}, status=400)
        
        # Validate email configuration before creating user
        smtp_user = getattr(settings, 'EMAIL_HOST_USER', '').strip()
        smtp_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '').strip()
        
        if not smtp_user or not smtp_pass:
            error_msg = "⚠️ Email service not configured: Missing BREVO SMTP credentials in environment"
            logger.error(error_msg)
            return JsonResponse({
                'status': 'error',
                'message': 'Email service temporarily unavailable. Contact administrator.'
            }, status=503)
        
        # Create pending user with secure temporary password
        temp_password = get_random_string(12)  # Secure random password
        
        # ✅ FIX: Pass exact username, first_name, and last_name straight into creation
        user = User.objects.create_user(
            username=username,
            email=email,
            password=temp_password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_approved=False,  # Pending approval via email
            is_active=False,  # Not yet active
            must_change_password=True,  # Must set password on activation
        )
        
        # Generate activation token and link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        # Use FRONTEND_BASE_URL from settings for consistent email links across all contexts
        activation_link = f"{settings.FRONTEND_BASE_URL}/activate/{uid}/{token}/"
        
        # ✅ SEND EMAIL USING EMAIL SERVICE with error handling
        email_result = EmailService.send_user_invite_email(user, activation_link)
        
        if not email_result['success']:
            # Email failed, but user was created. Log this and return error.
            logger.error(f"Email send failed for new user {user.id}: {email_result.get('error', 'Unknown error')}")
            user.delete()
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to send invitation email: {email_result.get("error", "Unknown error")}'
            }, status=500)
        
        # ✅ AUDIT LOGGING
        AdminActionLog.objects.create(
            user=request.user,
            action='user_created',
            target_model='CustomUser',
            target_id=user.id,
            description=f"Sent invitation to {user.email} with role {role}"
        )
        
        # ✅ ALERT SYSTEM: Log user invite event
        Alert.objects.create(
            node=None,
            severity='info',
            title='User Invited',
            description=f'Invitation sent to {user.email} ({user.get_role_display()}) by {request.user.email}',
            is_active=True
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Invitation sent successfully',
            'data': {
                'id': user.id,
                'email': user.email,
                'status': 'pending',
            }
        })
    except Exception as e:
        error_msg = f"Unexpected error in user_invite: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"ERROR: {error_msg}", file=sys.stderr)
        return JsonResponse({
            'status': 'error',
            'message': 'An unexpected error occurred. Please try again.'
        }, status=500)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required(login_url='app:login')
@require_http_methods(["PUT"])
def api_users_update(request, user_id):
    """Update user information."""
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    
    try:
        import json
        data = json.loads(request.body)
    except:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    
    # Track changes for audit
    changes = []
    
    # Update fields
    if 'first_name' in data and data['first_name'] != user.first_name:
        changes.append(f"first_name: {user.first_name} → {data['first_name']}")
        user.first_name = data['first_name']
    if 'last_name' in data and data['last_name'] != user.last_name:
        changes.append(f"last_name: {user.last_name} → {data['last_name']}")
        user.last_name = data['last_name']
    if 'email' in data and data['email'] != user.email:
        changes.append(f"email: {user.email} → {data['email']}")
        user.email = data['email']
    if 'role' in data and data['role'] != user.role:
        changes.append(f"role: {user.role} → {data['role']}")
        user.role = data['role']
    if 'organization' in data and data['organization'] != user.organization:
        changes.append(f"organization: {user.organization} → {data['organization']}")
        user.organization = data['organization']
    
    # ✅ ALERT SYSTEM: Log user update event if changes made
    if changes:
        Alert.objects.create(
            node=None,
            severity='info',
            title='User Updated',
            description=f'User {user.email} updated by {request.user.email}. Changes: {" | ".join(changes)}',
            is_active=True
        )
    
    return JsonResponse({
        'status': 'success',
        'message': 'User updated successfully',
        'data': {
            'id': user.id,
            'email': user.email,
        }
    })


@login_required(login_url='app:login')
@require_http_methods(["PATCH"])
def api_users_toggle(request, user_id):
    """Toggle user active status."""
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    
    try:
        import json
        data = json.loads(request.body)
    except:
        data = {}
    
    # Store old status for audit
    old_status = user.is_active
    
    # Toggle is_active or set explicitly
    if 'is_active' in data:
        user.is_active = data['is_active']
    else:
        user.is_active = not user.is_active
    
    user.save()
    
    action_desc = "Enabled" if user.is_active else "Disabled"
    
    # ✅ AUDIT LOGGING
    AdminActionLog.objects.create(
        user=request.user,
        action='user_updated',
        target_model='CustomUser',
        target_id=user.id,
        description=f"{action_desc} user {user.email}"
    )
    
    # ✅ ALERT SYSTEM: Log status change
    Alert.objects.create(
        node=None,
        severity='warning' if not user.is_active else 'info',
        title=f'User {action_desc}',
        description=f'User {user.email} was {action_desc.lower()} by {request.user.email}',
        is_active=True
    )
    
    return JsonResponse({
        'status': 'success',
        'message': f'User {action_desc.lower()} successfully',
        'data': {
            'id': user.id,
            'is_active': user.is_active,
        }
    })


@login_required(login_url='app:login')
@require_http_methods(["DELETE"])
def api_users_delete(request, user_id):
    """Delete a user permanently."""
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    user_email = user.email
    
    # ✅ AUDIT LOGGING
    AdminActionLog.objects.create(
        user=request.user,
        action='user_deleted',
        target_model='CustomUser',
        target_id=user.id,
        description=f"Deleted user {user_email}"
    )
    
    # ✅ ALERT SYSTEM: Log user deletion
    Alert.objects.create(
        node=None,
        severity='critical',
        title='User Deleted',
        description=f'User {user_email} was permanently deleted by {request.user.email}',
        is_active=True
    )
    
    user.delete()
    
    return JsonResponse({
        'status': 'success',
        'message': 'User deleted successfully'
    })


@csrf_exempt
@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_users_resend_invite(request, user_id):
    """Resend invitation email to pending user."""
    try:
        # ✅ ROLE-BASED ACCESS CONTROL
        if not request.user.is_admin_user():
            return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
        
        user = get_object_or_404(User, id=user_id)
        
        if user.is_approved:
            return JsonResponse({'status': 'error', 'message': 'User is already approved'}, status=400)
        
        # Validate email configuration before attempting to send
        smtp_user = getattr(settings, 'EMAIL_HOST_USER', '').strip()
        smtp_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '').strip()
        
        if not smtp_user or not smtp_pass:
            error_msg = "⚠️ Email service not configured: Missing BREVO SMTP credentials in environment"
            logger.error(f"{error_msg} (EMAIL_HOST_USER: {bool(smtp_user)}, EMAIL_HOST_PASSWORD: {bool(smtp_pass)})")
            return JsonResponse({
                'status': 'error',
                'message': 'Email service temporarily unavailable. Contact administrator.'
            }, status=503)
        
        # Generate new activation token and link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        # Use FRONTEND_BASE_URL from settings for consistent email links
        activation_link = f"{settings.FRONTEND_BASE_URL}/activate/{uid}/{token}/"
        
        # ✅ SEND EMAIL USING EMAIL SERVICE with error handling
        email_result = EmailService.send_user_invite_email(user, activation_link)
        
        if not email_result['success']:
            logger.error(f"Email send failed for user {user.id}: {email_result.get('error', 'Unknown error')}")
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to send invitation email: {email_result.get("error", "Unknown error")}'
            }, status=500)
        
        # ✅ AUDIT LOGGING
        AdminActionLog.objects.create(
            user=request.user,
            action='user_updated',
            target_model='CustomUser',
            target_id=user.id,
            description=f"Resent invitation to {user.email}"
        )
        
        # ✅ ALERT SYSTEM: Log resend invite event
        Alert.objects.create(
            node=None,
            severity='info',
            title='Invitation Resent',
            description=f'Invitation resent to {user.email} by {request.user.email}',
            is_active=True
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Invitation resent successfully'
        })
    except Exception as e:
        error_msg = f"Unexpected error in resend_invite: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"ERROR: {error_msg}", file=sys.stderr)
        return JsonResponse({
            'status': 'error',
            'message': 'An unexpected error occurred. Please try again.'
        }, status=500)


@login_required(login_url='app:login')
@require_http_methods(["GET"])
def api_users_invite_link(request, user_id):
    """
    Get invite link for a pending user.
    Used when user wants to copy the invite link without re-sending email.
    """
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    
    if user.is_approved:
        return JsonResponse({'status': 'error', 'message': 'User is already approved'}, status=400)
    
    try:
        # Generate activation token and link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        # Use FRONTEND_BASE_URL from settings for consistent email links
        activation_link = f"{settings.FRONTEND_BASE_URL}/activate/{uid}/{token}/"
        
        return JsonResponse({
            'status': 'success',
            'link': activation_link,
            'invite_link': activation_link,  # Backward compatibility
            'message': 'Invite link copied to clipboard'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Failed to generate link: {str(e)}'}, status=500)


# ============================================================================
# EMAIL & ACTIVATION SYSTEM
# ============================================================================

def activate_user(request, uidb64, token):
    """Activate user account and set password."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return render(request, 'AppEnviroNode/auth/activation_invalid.html', {
            'message': 'Invalid activation link'
        })
    
    # Check token validity
    if not default_token_generator.check_token(user, token):
        return render(request, 'AppEnviroNode/auth/activation_invalid.html', {
            'message': 'Activation link has expired'
        })
    
    if request.method == 'POST':
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        # 1. NEW STRICT VALIDATION
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            messages.error(request, error_msg)
            return render(request, 'AppEnviroNode/auth/activation.html', {
                'uidb64': uidb64,
                'token': token,
                'user': user,
            })
        
        if password != password_confirm:
            messages.error(request, 'Passwords do not match')
            return render(request, 'AppEnviroNode/auth/activation.html', {
                'uidb64': uidb64,
                'token': token,
                'user': user,
            })
        
        # Set password and activate account
        user.set_password(password)
        user.is_active = True
        user.is_approved = True
        user.must_change_password = False  # User just set password, no need to force change
        user.save()
        
        # Auto-login user after activation
        login(request, user)
        
        messages.success(request, 'Account activated successfully! Welcome to EnviroPlus.')
        return redirect('app:client_dashboard')
    
    return render(request, 'AppEnviroNode/auth/activation.html', {
        'uidb64': uidb64,
        'token': token,
        'user': user,
    })


# ============================================================================
# PASSWORD MANAGEMENT
# ============================================================================

@login_required(login_url='app:login')
@require_http_methods(["GET", "POST"])
def force_password_change(request):
    """Force user to change password on first login."""
    user = request.user
    
    if not user.must_change_password:
        return redirect('app:client_dashboard')
    
    if request.method == 'POST':
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        current_password = request.POST.get('current_password')
        
        # For newly created/invited users, current_password is optional
        # For users changing password after creation, current_password should match
        if current_password:
            # Validate current password if provided
            if not user.check_password(current_password):
                messages.error(request, 'Current password is incorrect')
                return render(request, 'AppEnviroNode/auth/force_password_change.html', {
                    'require_current_password': True
                })
        
        # Validate new password
        if not password or len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters')
            return render(request, 'AppEnviroNode/auth/force_password_change.html', {
                'require_current_password': bool(current_password)
            })
        
        if password != password_confirm:
            messages.error(request, 'Passwords do not match')
            return render(request, 'AppEnviroNode/auth/force_password_change.html', {
                'require_current_password': bool(current_password)
            })
        
        if current_password and password == current_password:
            messages.error(request, 'New password must be different from current password')
            return render(request, 'AppEnviroNode/auth/force_password_change.html', {
                'require_current_password': True
            })
        
        # Set new password
        user.set_password(password)
        user.must_change_password = False
        user.save()
        
        # Re-login with new password
        login(request, user)
        
        messages.success(request, 'Password changed successfully!')
        return redirect('app:client_dashboard')
    
    # For new users, don't require current password
    return render(request, 'AppEnviroNode/auth/force_password_change.html', {
        'require_current_password': False
    })


@login_required(login_url='app:login')
@require_http_methods(["GET", "POST"])
def change_password(request):
    """Allow user to change their password anytime."""
    user = request.user
    
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        # Validate current password
        if not user.check_password(current_password):
            messages.error(request, 'Current password is incorrect')
            return render(request, 'AppEnviroNode/auth/change_password.html')
        
        # Validate new password
        if not new_password or len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters')
            return render(request, 'AppEnviroNode/auth/change_password.html')
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'AppEnviroNode/auth/change_password.html')
        
        if new_password == current_password:
            messages.error(request, 'New password must be different from current password')
            return render(request, 'AppEnviroNode/auth/change_password.html')
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        # Re-login with new password
        login(request, user)
        
        messages.success(request, 'Password changed successfully!')
        return redirect('app:client_dashboard')
    
    return render(request, 'AppEnviroNode/auth/change_password.html')


@require_http_methods(["GET", "POST"])
def forgot_password_request(request):
    """
    Handles self-service password reset requests by immediately
    dispatching a secure reset link to the user's email.
    """
    if request.user.is_authenticated:
        return redirect('app:client_dashboard')

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            
            try:
                user = User.objects.get(email__iexact=email)
                
                # 1. Generate one-time secure reset token & UID
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                
                # 2. Build the full reset URL
                base_url = getattr(settings, 'FRONTEND_BASE_URL', request.build_absolute_uri('/')[:-1])
                reset_link = f"{base_url}/reset-password/{uid}/{token}/"
                
                # 3. Immediately send the email via EmailService
                email_result = EmailService.send_password_reset_email(user, reset_link)
                
                if not email_result.get('success', False):
                    logger.error(f"Failed to send password reset to {user.email}: {email_result.get('error')}")
                
                # 4. Log alert for audit trail
                Alert.objects.create(
                    user=user,
                    alert_type='password_reset_request',
                    status='approved',
                    severity='info',
                    title=f'Password Reset - {user.email}',
                    description=f'Password reset email dispatched to {user.email}',
                    password_reset_token=token,
                    password_reset_uid=uid,
                    is_active=False
                )
                
                SystemLog.objects.create(
                    event_type='admin',
                    message=f'Password reset email sent to user: {user.email}',
                    created_at=timezone.now(),
                )
                
            except User.DoesNotExist:
                # Silently fail to prevent email enumeration
                logger.info(f"Password reset attempted for non-existent email: {email}")
            except Exception as e:
                logger.error(f"Unexpected error in forgot_password_request: {str(e)}", exc_info=True)
            
            # Always show the generic success message to prevent user enumeration
            messages.success(request, 'If an account exists with that email address, password reset instructions have been sent.')
            return redirect('app:login')
    else:
        form = PasswordResetRequestForm()
    
    return render(request, 'AppEnviroNode/auth/forgot_password.html', {'form': form})


@require_http_methods(["GET", "POST"])
def reset_password(request, uidb64, token):
    """Reset user password using token from email."""
    try:
        # Decode the user ID from the URL
        uid = force_str(urlsafe_base64_decode(uidb64))
        print(f"[DEBUG] Decoded UID from URL: {uid}")
        
        # Fetch the user
        user = User.objects.get(pk=uid)
        print(f"[DEBUG] Successfully found user: {user.email}")
        
    except Exception as e:
        # If it fails here, the URL was mangled or the user was deleted
        print(f"[DEBUG] CRITICAL FAILURE: Could not decode UID or find user. Error: {e}")
        return render(request, 'AppEnviroNode/auth/activation_invalid.html', {
            'message': 'Invalid password reset link'
        })
    
    # Check token validity
    if not default_token_generator.check_token(user, token):
        # If it fails here, the token expired or was invalidated
        print(f"[DEBUG] CRITICAL FAILURE: Token check failed for {user.email}. Token might be expired or already used.")
        return render(request, 'AppEnviroNode/auth/activation_invalid.html', {
            'message': 'Password reset link has expired. Please request a new one.'
        })
    
    if request.method == 'POST':
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        # 1. NEW STRICT VALIDATION
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            messages.error(request, error_msg)
            return render(request, 'AppEnviroNode/auth/reset_password.html', {
                'uidb64': uidb64,
                'token': token,
                'user': user,
            })
        
        if password != password_confirm:
            messages.error(request, 'Passwords do not match')
            return render(request, 'AppEnviroNode/auth/reset_password.html', {
                'uidb64': uidb64,
                'token': token,
                'user': user,
            })
        
        # Set new password
        user.set_password(password)
        user.must_change_password = False
        
        # Reset failed attempts & unlock account
        if hasattr(user, 'reset_failed_logins'):
            user.reset_failed_logins()
        else:
            user.failed_login_attempts = 0
            user.locked_until = None
        user.save()
        
        # Resolve pending alerts for this user's password reset
        Alert.objects.filter(
            user=user,
            alert_type='password_reset_request',
            status='pending'
        ).update(status='resolved', is_active=False, resolved_at=timezone.now())
        
        # Log the action
        SystemLog.objects.create(
            event_type='auth',
            message=f'Password reset completed for user: {user.email}',
            created_at=timezone.now(),
        )
        
        messages.success(request, 'Password reset successfully! You can now log in with your new password.')
        return redirect('app:login')
    
    return render(request, 'AppEnviroNode/auth/reset_password.html', {
        'uidb64': uidb64,
        'token': token,
        'user': user,
    })


# ============================================================================
# ADMIN PASSWORD RESET ENDPOINTS
# ============================================================================

@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_users_reset_password(request, user_id):
    """Admin endpoint: Reset user password and send reset link."""
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    try:
        user = get_object_or_404(User, id=user_id)
        
        # Generate password reset token
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        reset_link = request.build_absolute_uri(f'/reset-password/{uid}/{token}/')
        
        # Mark user to change password on next login
        user.must_change_password = True
        user.save()
        
        # Send password reset email using HTML template
        subject = 'EnviroPlus - Password Reset Request (Admin Initiated)'
        html_message = render_to_string('AppEnviroNode/email/password_reset.html', {
            'user': user,
            'reset_link': reset_link,
            'domain': request.get_host(),
            'initiated_by_admin': True,
        })
        
        send_mail(
            subject,
            f'Click this link to reset your password: {reset_link}',
            'EnviroPLUS Admin <noreply@enviroplus.local>', 
            [user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        # Log action
        AdminActionLog.objects.create(
            user=request.user,
            action='password_reset',
            target_model='CustomUser',
            target_id=user.id,
            description=f"Password reset initiated for user: {user.email}"
        )
        
        # Also create SystemLog for audit trail
        SystemLog.objects.create(
            event_type='admin',
            message=f'Admin {request.user.email} initiated password reset for {user.email}',
            node=None,
            reading=None,
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Password reset email sent successfully'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


    # ============================================================================
# PASSWORD RESET ADMIN MODERATION VIEWS
# ============================================================================

@login_required(login_url='app:login')
@require_http_methods(["GET", "POST"])
def admin_password_reset_requests(request):
    """
    Admin view to see all pending password reset requests.
    Only admins can access this.
    """
    if not request.user.is_staff:
        messages.error(request, 'Access denied. Admin only.')
        return redirect('app:client_dashboard')
    
    # Get all pending password reset alerts
    alerts = Alert.objects.filter(
        alert_type='password_reset_request',
        status='pending'
    ).select_related('user').order_by('-triggered_at')
    
    # Pagination
    paginator = Paginator(alerts, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'alerts': page_obj.object_list,
    }
    
    return render(request, 'AppEnviroNode/admin/admin_password_reset_requests.html', context)


@login_required(login_url='app:login')
@require_http_methods(["POST"])
def admin_approve_password_reset(request, alert_id):
    """
    Admin approves a password reset request.
    Sends the reset email immediately.
    """
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
    
    try:
        alert = get_object_or_404(Alert, id=alert_id, alert_type='password_reset_request')
        user = alert.user
        
        if alert.status != 'pending':
            return JsonResponse({'status': 'error', 'message': 'Alert is not pending'})
        
        # Build reset link
        reset_link = request.build_absolute_uri(f'/reset-password/{alert.password_reset_uid}/{alert.password_reset_token}/')
        
        # Send password reset email using the same method as scheduler
        result = EmailService.send_password_reset_email(user, reset_link)
        
        if result['success']:
            # Update alert
            alert.status = 'approved'
            alert.approved_by = request.user
            alert.is_active = False
            alert.save()
            
            # Log action
            SystemLog.objects.create(
                event_type='admin',
                message=f'Admin {request.user.email} approved password reset for {user.email} (Alert ID: {alert.id})',
            )
            
            AdminActionLog.objects.create(
                admin=request.user,
                action_type='password_reset_approved',
                target_id=user.id,
                description=f'Approved password reset for {user.email}'
            )
            
            messages.success(request, f'Password reset approved and email sent to {user.email}')
            logger.info(f"Admin {request.user.email} approved password reset for {user.email}")
            
            return JsonResponse({'status': 'success', 'message': 'Password reset approved'})
        else:
            messages.error(request, f'Approved but failed to send email: {result["error"]}')
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to send email: {result["error"]}'
            }, status=500)
    
    except Exception as e:
        logger.error(f"Error approving password reset: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required(login_url='app:login')
@require_http_methods(["POST"])
def admin_deny_password_reset(request, alert_id):
    """
    Admin denies a password reset request.
    Sends denial email with optional reason.
    """
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
    
    try:
        alert = get_object_or_404(Alert, id=alert_id, alert_type='password_reset_request')
        user = alert.user
        reason = request.POST.get('reason', '')
        
        if alert.status != 'pending':
            return JsonResponse({'status': 'error', 'message': 'Alert is not pending'})
        
        # Send denial email
        result = EmailService.send_password_reset_denied_email(user, reason)
        
        if result['success']:
            # Update alert
            alert.status = 'denied'
            alert.approved_by = request.user
            alert.denial_reason = reason
            alert.is_active = False
            alert.save()
            
            # Log action
            SystemLog.objects.create(
                event_type='admin',
                message=f'Admin {request.user.email} denied password reset for {user.email} (Alert ID: {alert.id}). Reason: {reason}',
            )
            
            AdminActionLog.objects.create(
                admin=request.user,
                action_type='password_reset_denied',
                target_id=user.id,
                description=f'Denied password reset for {user.email}. Reason: {reason}'
            )
            
            messages.success(request, f'Password reset denied. Notification sent to {user.email}')
            logger.info(f"Admin {request.user.email} denied password reset for {user.email}")
            
            return JsonResponse({'status': 'success', 'message': 'Password reset denied'})
        else:
            messages.error(request, f'Failed to send denial email: {result["error"]}')
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to send email: {result["error"]}'
            }, status=500)
    
    except Exception as e:
        logger.error(f"Error denying password reset: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def get_aqi_category_label(aqi):
    if aqi is None:
        return 'Unknown'
    if aqi <= 50:
        return 'Good'
    if aqi <= 100:
        return 'Moderate'
    if aqi <= 150:
        return 'Unhealthy Sensitive'
    if aqi <= 200:
        return 'Unhealthy'
    if aqi <= 300:
        return 'Very Unhealthy'
    return 'Hazardous'

def get_report_readings(start_date, end_date, selected_node='all', selected_location='all'):
    start_at = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end_at = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

    readings = SensorReading.objects.filter(
        timestamp__gte=start_at,
        timestamp__lte=end_at,
        node__is_active=True
    ).select_related('node').only(
        'timestamp', 'aqi', 'pm1_0', 'pm2_5', 'pm10', 'temperature', 'humidity',
        'node__name', 'node__location'
    ).order_by('timestamp')

    if selected_node and selected_node != 'all':
        readings = readings.filter(node__id=selected_node)
    
    if selected_location and selected_location != 'all':
        readings = readings.filter(node__location__iexact=selected_location.strip())

    return readings

    peak_date = summary.get('peak_date')
    peak_aqi = summary.get('peak_aqi', 0)
    avg_aqi = summary.get('avg_aqi', 0)
    values = [v for v in summary.get('trend_values', []) if v is not None]
    if not values:
        return 'No AQI trend data is available for this reporting period.'

    first_value = values[0]
    last_value = values[-1]
    change = last_value - first_value
    if abs(change) <= 10:
        trend_desc = 'The trend remains fairly stable over the selected range.'
    elif change > 0:
        trend_desc = 'The AQI trend gradually increases toward the end of the period.'
    else:
        trend_desc = 'The AQI trend declines toward the end of the period.'

    spike_desc = 'A minor spike is present.'
    if peak_aqi >= 200:
        spike_desc = 'A significant hazard-level spike is present.'
    elif peak_aqi >= 150:
        spike_desc = 'A strong unhealthy spike is present.'
    elif peak_aqi >= 100:
        spike_desc = 'A noticeable moderate spike is present.'

    return (
        f"{peak_date or 'The report period'} shows a peak AQI of {peak_aqi}, "
        f"with an average AQI of {avg_aqi}. {spike_desc} {trend_desc}"
    )

@login_required(login_url='app:login')
def export_report_csv(request):
    date_from_obj, date_to_obj, selected_node, selected_location = parse_export_params(request)
    readings = get_report_readings(date_from_obj, date_to_obj, selected_node, selected_location)

    filename = f"enviroplus-report-{date_from_obj.isoformat()}_to_{date_to_obj.isoformat()}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Timestamp', 'Node Name', 'Location', 'AQI', 'PM1.0', 'PM2.5', 'PM10', 'Temperature', 'Humidity'
    ])

    for reading in readings:
        writer.writerow([
            reading.timestamp.strftime('%Y-%m-%d %H:%M:%S') if reading.timestamp else '',
            reading.node.name if reading.node else '',
            reading.node.location if reading.node else '',
            reading.aqi if reading.aqi is not None else '',
            f"{reading.pm1_0:.2f}" if reading.pm1_0 is not None else '',
            f"{reading.pm2_5:.2f}" if reading.pm2_5 is not None else '',
            f"{reading.pm10:.2f}" if reading.pm10 is not None else '',
            f"{reading.temperature:.1f}" if reading.temperature is not None else '',
            f"{reading.humidity:.1f}" if reading.humidity is not None else ''
        ])
    return response

@login_required(login_url='app:login')
def export_report_print(request):
    date_from_obj, date_to_obj, selected_node, selected_location = parse_export_params(request)
    summary = build_report_summary(date_from_obj, date_to_obj, selected_node, selected_location)
    chart_image = base64.b64encode(build_chart_image(summary['summary']).getvalue()).decode('ascii')
    chart_explanation = build_chart_explanation(summary['summary'])
    
    node_name = 'All Nodes'
    if selected_node != 'all':
        node = SensorNode.objects.filter(pk=selected_node).first()
        node_name = node.name if node else node_name

    # Compute category breakdown from actual summary data
    daily = summary['summary']
    good_days       = sum(1 for d in daily if d['avg_aqi'] <= 50)
    moderate_days   = sum(1 for d in daily if 50 < d['avg_aqi'] <= 100)
    unhealthy_days  = sum(1 for d in daily if d['avg_aqi'] > 100)
    total_days      = len(daily) or 1
    good_pct        = round(good_days / total_days * 100)
    moderate_pct    = round(moderate_days / total_days * 100)
    unhealthy_pct   = round(unhealthy_days / total_days * 100)

    # Most affected node (highest avg AQI reading in period)
    start_at = timezone.make_aware(datetime.combine(date_from_obj, datetime.min.time()))
    end_at   = timezone.make_aware(datetime.combine(date_to_obj, datetime.max.time()))
    worst = (SensorReading.objects
             .filter(timestamp__range=[start_at, end_at], aqi__isnull=False)
             .values('node__name')
             .annotate(avg=Avg('aqi'))
             .order_by('-avg')
             .first())
    most_affected_node = worst['node__name'] if worst else 'N/A'

    return render(request, 'AppEnviroNode/admin/analytics_export.html', {
        'summary':            summary,
        'chart_image':        chart_image,
        'chart_explanation':  chart_explanation,
        'node_name':          node_name,
        'report_period':      summary.get('report_period', ''),
        'generated_at':       summary.get('generated_at', ''),
        'avg_aqi':            summary.get('avg_aqi', 0),
        'peak_aqi':           summary.get('peak_aqi', 0),
        'low_aqi':            min((d['avg_aqi'] for d in daily), default=0),
        'good_days':          good_days,
        'moderate_days':      moderate_days,
        'unhealthy_days':     unhealthy_days,
        'good_pct':           good_pct,
        'moderate_pct':       moderate_pct,
        'unhealthy_pct':      unhealthy_pct,
        'most_affected_node': most_affected_node,
    })

@login_required(login_url='app:login')
def export_report_pdf(request):
    if not pisa:
        return HttpResponse('Error: xhtml2pdf is not installed. PDF export is unavailable.', status=503)
    
    date_from_obj, date_to_obj, selected_node, selected_location = parse_export_params(request)
    summary = build_report_summary(date_from_obj, date_to_obj, selected_node, selected_location)
    chart_image = base64.b64encode(build_chart_image(summary['summary']).getvalue()).decode('ascii')
    chart_explanation = build_chart_explanation(summary['summary'])

    node_name = 'All Nodes'
    if selected_node != 'all':
        node = SensorNode.objects.filter(pk=selected_node).first()
        node_name = node.name if node else node_name

    # Compute category breakdown from actual summary data
    daily = summary['summary']
    good_days       = sum(1 for d in daily if d['avg_aqi'] <= 50)
    moderate_days   = sum(1 for d in daily if 50 < d['avg_aqi'] <= 100)
    unhealthy_days  = sum(1 for d in daily if d['avg_aqi'] > 100)
    total_days      = len(daily) or 1
    good_pct        = round(good_days / total_days * 100)
    moderate_pct    = round(moderate_days / total_days * 100)
    unhealthy_pct   = round(unhealthy_days / total_days * 100)

    # Most affected node (highest avg AQI reading in period)
    start_at = timezone.make_aware(datetime.combine(date_from_obj, datetime.min.time()))
    end_at   = timezone.make_aware(datetime.combine(date_to_obj, datetime.max.time()))
    worst = (SensorReading.objects
             .filter(timestamp__range=[start_at, end_at], aqi__isnull=False)
             .values('node__name')
             .annotate(avg=Avg('aqi'))
             .order_by('-avg')
             .first())
    most_affected_node = worst['node__name'] if worst else 'N/A'

    html_string = render_to_string('AppEnviroNode/admin/analytics_export.html', {
        'summary':            summary,
        'chart_image':        chart_image,
        'chart_explanation':  chart_explanation,
        'node_name':          node_name,
        'report_period':      summary.get('report_period', ''),
        'generated_at':       summary.get('generated_at', ''),
        'avg_aqi':            summary.get('avg_aqi', 0),
        'peak_aqi':           summary.get('peak_aqi', 0),
        'low_aqi':            min((d['avg_aqi'] for d in daily), default=0),
        'good_days':          good_days,
        'moderate_days':      moderate_days,
        'unhealthy_days':     unhealthy_days,
        'good_pct':           good_pct,
        'moderate_pct':       moderate_pct,
        'unhealthy_pct':      unhealthy_pct,
        'most_affected_node': most_affected_node,
        'pdf_export':         True,
    })

    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)

    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="EnviroPlus-report-{date_from_obj.isoformat()}_to_{date_to_obj.isoformat()}.pdf"'
        )
        return response
    return HttpResponse('Error generating PDF — check that xhtml2pdf is installed.')

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

def parse_export_params(request):
    """Parse export parameters, handling report_type, dates, node, and location filters."""
    report_type = request.GET.get('report_type', '24hrs').strip()
    selected_node = request.GET.get('node', 'all')
    selected_location = request.GET.get('location', 'all')
    
    now = timezone.now()
    
    # Compute date range based on report_type (return as date objects for compatibility)
    if report_type == '24hrs':
        date_from_obj = (now - timedelta(hours=24)).date()
        date_to_obj = now.date()
    elif report_type == 'Weekly':
        date_from_obj = (now - timedelta(days=7)).date()
        date_to_obj = now.date()
    elif report_type == 'Monthly':
        date_from_obj = (now - timedelta(days=30)).date()
        date_to_obj = now.date()
    else:  # Custom
        date_from = request.GET.get('date_from', '')
        date_to = request.GET.get('date_to', '')
        
        if date_from and date_to:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                date_from_obj = (now - timedelta(days=30)).date()
                date_to_obj = now.date()
        else:
            date_from_obj = (now - timedelta(days=30)).date()
            date_to_obj = now.date()
        
    return date_from_obj, date_to_obj, selected_node, selected_location

def build_report_summary(date_from_obj, date_to_obj, selected_node, selected_location='all'):
    from django.db.models.functions import TruncDay

    start_at = timezone.make_aware(datetime.combine(date_from_obj, datetime.min.time()))
    end_at = timezone.make_aware(datetime.combine(date_to_obj, datetime.max.time()))

    readings_qs = SensorReading.objects.filter(
        timestamp__range=[start_at, end_at]
    ).select_related('node').only(
        'aqi', 'pm2_5', 'temperature', 'timestamp', 'node__name', 'node__location'
    )

    if selected_node != 'all':
        try:
            readings_qs = readings_qs.filter(node_id=int(selected_node))
        except (ValueError, TypeError):
            pass
    
    if selected_location != 'all':
        readings_qs = readings_qs.filter(node__location__iexact=selected_location.strip())

    daily_data = readings_qs.annotate(
        day=TruncDay('timestamp')
    ).values('day').annotate(
        avg_aqi=Avg('aqi'),
        avg_pm25=Avg('pm2_5'),
        avg_temp=Avg('temperature'),
        count=Count('id')
    ).order_by('day')

    summary = []
    for item in daily_data:
        avg_aqi = item['avg_aqi'] or 0
        if avg_aqi <= 50: category = 'Good'
        elif avg_aqi <= 100: category = 'Moderate'
        elif avg_aqi <= 150: category = 'Unhealthy for Sensitive Groups'
        elif avg_aqi <= 200: category = 'Unhealthy'
        elif avg_aqi <= 300: category = 'Very Unhealthy'
        else: category = 'Hazardous'

        summary.append({
            'date': item['day'].date() if item['day'] else date_from_obj,
            'avg_aqi': round(avg_aqi, 1),
            'avg_pm25': round(item['avg_pm25'], 2) if item['avg_pm25'] else 0,
            'avg_temp': round(item['avg_temp'], 1) if item['avg_temp'] else 0,
            'category': category,
            'readings_count': item['count']
        })

    total_days = (date_to_obj - date_from_obj).days + 1
    trend_labels = []
    trend_values = []

    for item in summary:
        trend_labels.append(item['date'].strftime('%b %d'))
        trend_values.append(item['avg_aqi'])

    return {
        'summary': summary,
        'date_from': date_from_obj,
        'date_to': date_to_obj,
        'trend_labels': trend_labels,
        'trend_values': trend_values,
        'avg_aqi': round(sum(item['avg_aqi'] for item in summary) / len(summary), 1) if summary else 0,
        'peak_aqi': max((item['avg_aqi'] for item in summary), default=0),
        'peak_date': summary[-1]['date'].isoformat() if summary else date_to_obj.isoformat(),
        'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M'),
        'report_period': f"{date_from_obj.strftime('%b %d')} - {date_to_obj.strftime('%b %d, %Y')}",
        'total_days': total_days,
    }

def build_chart_image(summary):
    dates = [s['date'] for s in summary]
    aqi_values = [s['avg_aqi'] for s in summary]
    
    plt.figure(figsize=(10, 5))
    plt.plot(dates, aqi_values, marker='o', linestyle='-', color='#3b82f6')
    plt.title('Average Daily AQI Trend')
    plt.xlabel('Date')
    plt.ylabel('AQI')
    plt.xticks(rotation=45, ha='right')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()
    return buffer

def build_chart_explanation(summary):
    if not summary:
        return "No data available for the selected period."
    
    avg_aqi = sum(s['avg_aqi'] for s in summary) / len(summary)
    max_aqi = max(s['avg_aqi'] for s in summary)
    
    explanation = f"Over the selected period, the average AQI was {round(avg_aqi, 1)}. "
    if avg_aqi <= 50:
        explanation += "This indicates generally good air quality. "
    elif avg_aqi <= 100:
        explanation += "This indicates moderate air quality, acceptable for most people. "
    else:
        explanation += "This indicates concerning air quality levels. "
        
    explanation += f"The highest recorded daily average was {max_aqi}."
    return explanation

@login_required(login_url='app:login')
def export_report_excel(request):
    date_from_obj, date_to_obj, selected_node, selected_location = parse_export_params(request)
    report_data = build_report_summary(date_from_obj, date_to_obj, selected_node, selected_location)
    summary = report_data['summary']

    wb = Workbook()
    ws = wb.active
    ws.title = "Air Quality Report"

    headers = ['Date', 'Average AQI', 'Average PM2.5', 'Average Temperature (°C)', 'Category']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for row_num, data in enumerate(summary, 2):
        ws.cell(row=row_num, column=1, value=data['date'])
        ws.cell(row=row_num, column=2, value=data['avg_aqi'])
        ws.cell(row=row_num, column=3, value=data['avg_pm25'])
        ws.cell(row=row_num, column=4, value=data['avg_temp'])
        ws.cell(row=row_num, column=5, value=data['category'])

    for col_num in range(1, 6):
        ws.column_dimensions[get_column_letter(col_num)].width = 20

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = (
        f'attachment; filename="EnviroPlus-report-{date_from_obj.isoformat()}_to_{date_to_obj.isoformat()}.xlsx"'
    )
    return response

# ============================================================================
# NOTIFICATION API ENDPOINTS
# ============================================================================

@csrf_exempt
@require_http_methods(["GET"])
def api_notifications_unread(request):
    """Get unread notification count for the current user."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'unread_count': 0}, status=200)
    
    try:
        unread_count = Alert.objects.filter(
            is_active=True,
            severity__in=['warning', 'critical']
        ).count()
        
        return JsonResponse({
            'success': True,
            'unread_count': unread_count
        }, status=200)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='app:login')
def api_notifications_list(request):
    """Get list of notifications for the current user."""
    try:
        alerts = Alert.objects.filter(
            is_active=True
        ).select_related('node', 'reading').order_by('-triggered_at')[:50]
        
        notifications = []
        for alert in alerts:
            # Determine category based on title and description
            title_lower = alert.title.lower() if alert.title else ''
            desc_lower = alert.description.lower() if alert.description else ''
            
            if 'user' in title_lower or 'admin' in title_lower or 'permission' in title_lower or 'login' in title_lower or 'logout' in title_lower:
                category = 'admin'
            elif 'sensor' in title_lower or 'node' in title_lower or 'device' in title_lower or 'hardware' in title_lower or 'esp' in title_lower:
                category = 'hardware'
            else:
                category = 'software'
            
            category_display = {
                'admin': 'Admin Alerts',
                'hardware': 'Hardware Alerts',
                'software': 'Software Alerts'
            }.get(category, 'General')
            
            notifications.append({
                'id': alert.id,
                'title': alert.title,
                'description': alert.description,
                'severity': alert.severity,
                'category': category,
                'category_display': category_display,
                'created_at': alert.triggered_at.isoformat(),
                'read': not alert.is_active,
                'node_name': alert.node.name if alert.node else 'System'
            })
        
        return JsonResponse({
            'success': True,
            'notifications': notifications,
            'count': len(notifications)
        }, status=200)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@login_required(login_url='app:login')
def api_notification_mark_read(request, notification_id):
    """Mark a notification as read (resolve the alert)."""
    try:
        alert = get_object_or_404(Alert, id=notification_id)
        if alert.is_active:
            alert.is_active = False
            alert.resolved_at = timezone.now()
            alert.save()
        
        return JsonResponse({'success': True, 'message': 'Notification marked as read'}, status=200)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@login_required(login_url='app:login')
def api_notifications_mark_all_read(request):
    """Mark all notifications as read."""
    try:
        updated = Alert.objects.filter(is_active=True).update(
            is_active=False,
            resolved_at=timezone.now()
        )
        return JsonResponse({
            'success': True,
            'message': f'{updated} notifications marked as read'
        }, status=200)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_http_methods(["GET"])
@cache_page(300)
def api_daily_forecast(request):
    try:
        from .utils import predict_next_day_aqi, get_aqi_category
        
        now = timezone.now()
        today = now.astimezone(timezone.get_current_timezone()).date()
        
        readings = SensorReading.objects.filter(
            timestamp__gte=now - timedelta(days=30),
            timestamp__lte=now,
            aqi__isnull=False
        ).select_related('node').order_by('timestamp')
        
        daily_groups = {}
        for reading in readings:
            if not reading.timestamp:
                continue
            try:
                reading_date = reading.timestamp.astimezone(timezone.get_current_timezone()).date()
            except (TypeError, AttributeError):
                continue
            
            if reading_date not in daily_groups:
                daily_groups[reading_date] = {'aqi': [], 'pm2_5': [], 'temperature': []}
            
            if reading.aqi is not None:
                daily_groups[reading_date]['aqi'].append(reading.aqi)
            if reading.pm2_5 is not None:
                daily_groups[reading_date]['pm2_5'].append(reading.pm2_5)
            if reading.temperature is not None:
                daily_groups[reading_date]['temperature'].append(reading.temperature)
        
        if not daily_groups:
            return JsonResponse({
                'success': True,
                'forecast': [],
                'generated_at': now.isoformat(),
                'confidence_level': 'low'
            }, status=200)
        
        daily_agg = []
        for date in sorted(daily_groups.keys()):
            group = daily_groups[date]
            daily_agg.append({
                'date': date,
                'avg_aqi': round(sum(group['aqi']) / len(group['aqi']), 1) if group['aqi'] else None,
                'avg_pm2_5': round(sum(group['pm2_5']) / len(group['pm2_5']), 1) if group['pm2_5'] else None,
                'avg_temperature': round(sum(group['temperature']) / len(group['temperature']), 1) if group['temperature'] else None,
                'count': len(group['aqi'])
            })
        
        def predict_with_trend(values_list, days_ahead=1):
            if not values_list or len(values_list) < 2:
                return round(values_list[0], 1) if values_list else 75
            
            recent_vals = values_list[-7:]
            n = len(recent_vals)
            x_vals = list(range(n))
            mean_x = sum(x_vals) / n
            mean_y = sum(recent_vals) / n
            
            numerator = sum((x_vals[i] - mean_x) * (recent_vals[i] - mean_y) for i in range(n))
            denominator = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
            
            slope = (numerator / denominator) if denominator > 0 else 0
            intercept = mean_y - slope * mean_x
            
            predicted = intercept + slope * (n + days_ahead - 1)
            predicted = max(0, min(500, predicted))
            
            return round(predicted, 1)
        
        avg_aqi_vals = [d['avg_aqi'] for d in daily_agg if d['avg_aqi'] is not None]
        avg_pm2_5_vals = [d['avg_pm2_5'] for d in daily_agg if d['avg_pm2_5'] is not None]
        avg_temp_vals = [d['avg_temperature'] for d in daily_agg if d['avg_temperature'] is not None]
        
        forecast_list = []
        
        for i in range(-4, 3):
            forecast_date = today + timedelta(days=i)
            is_current = (forecast_date == today)
            is_predicted = (forecast_date > today)
            is_historical = (forecast_date < today)
            
            actual_data = next((d for d in daily_agg if d['date'] == forecast_date), None)
            
            if actual_data:
                forecast_list.append({
                    'date': forecast_date.isoformat(),
                    'avg_aqi': actual_data['avg_aqi'],
                    'avg_pm2_5': actual_data['avg_pm2_5'],
                    'avg_temperature': actual_data['avg_temperature'],
                    'is_current': is_current,
                    'is_predicted': False,
                    'is_historical': is_historical,
                })
            elif is_predicted:
                if avg_aqi_vals:
                    days_ahead = (forecast_date - today).days
                    pred_aqi = predict_with_trend(avg_aqi_vals, days_ahead)
                    pred_pm = predict_with_trend(avg_pm2_5_vals, days_ahead) if avg_pm2_5_vals else (round(sum(avg_pm2_5_vals) / len(avg_pm2_5_vals), 1) if avg_pm2_5_vals else 0)
                    pred_temp = predict_with_trend(avg_temp_vals, days_ahead) if avg_temp_vals else (round(sum(avg_temp_vals) / len(avg_temp_vals), 1) if avg_temp_vals else 20)
                    
                    forecast_list.append({
                        'date': forecast_date.isoformat(),
                        'avg_aqi': pred_aqi,
                        'avg_pm2_5': pred_pm,
                        'avg_temperature': pred_temp,
                        'is_current': False,
                        'is_predicted': True,
                        'is_historical': False,
                    })
        
        confidence = 'high' if len(daily_agg) >= 14 else ('medium' if len(daily_agg) >= 7 else 'low')
        
        return JsonResponse({
            'success': True,
            'forecast': forecast_list,
            'generated_at': now.isoformat(),
            'confidence_level': confidence,
        }, status=200)
        
    except Exception as e:
        logger.error(f'Forecast error: {str(e)[:200]}', exc_info=True)
        return JsonResponse({
            'success': True,
            'forecast': [],
            'generated_at': timezone.now().isoformat(),
            'confidence_level': 'low'
        }, status=200)
    
@csrf_exempt
@require_http_methods(["GET"])
def api_closest_node(request):
    """
    GET /api/closest-node/?lat=14.5&lng=121.0
    Returns the closest active sensor node's latest reading
    based on user's coordinates (Haversine distance).
    Falls back to area average if no coords provided.
    """
    import math

    def haversine(lat1, lng1, lat2, lng2):
        """Calculate distance in km between two coordinates."""
        R = 6371  # Earth radius in km
        d_lat = math.radians(lat2 - lat1)
        d_lng = math.radians(lng2 - lng1)
        a = (math.sin(d_lat / 2) ** 2 +
             math.cos(math.radians(lat1)) *
             math.cos(math.radians(lat2)) *
             math.sin(d_lng / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    try:
        lat = request.GET.get('lat')
        lng = request.GET.get('lng')

        # ── Get all active nodes with their latest reading ──
        nodes = SensorNode.objects.filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False,
        ).prefetch_related('readings')

        # ── Build area average as fallback ──
        all_readings = SensorReading.objects.filter(
            node__is_active=True
        ).order_by('-timestamp')[:50]

        avg_aqi   = None
        avg_pm25  = None
        avg_temp  = None
        avg_hum   = None
        avg_pm10  = None
        avg_pm1   = None
        avg_pres  = None
        avg_gas   = None

        valid = [r for r in all_readings if r.aqi is not None]
        if valid:
            avg_aqi  = round(sum(r.aqi for r in valid) / len(valid))
            avg_pm25 = round(sum(r.pm2_5 for r in valid if r.pm2_5) / len(valid), 2)
            avg_temp = round(sum(r.temperature for r in valid if r.temperature) / len(valid), 1)
            avg_hum  = round(sum(r.humidity for r in valid if r.humidity) / len(valid), 1)
            avg_pm10 = round(sum(r.pm10 for r in valid if r.pm10) / len(valid), 2)
            avg_pm1  = round(sum(r.pm1_0 for r in valid if r.pm1_0) / len(valid), 2)
            avg_pres = round(sum(r.pressure for r in valid if r.pressure) / len(valid), 1)
            avg_gas  = round(sum(r.gas_resistance for r in valid if r.gas_resistance) / len(valid), 1)

        area_average = {
            'source':       'area_average',
            'node_name':    'Barangay Pembo',
            'location':     'Average across all nodes',
            'distance_km':  None,
            'aqi':          avg_aqi,
            'aqi_level':    valid[0].aqi_level if valid else None,
            'pm2_5':        avg_pm25,
            'pm10':         avg_pm10,
            'pm1_0':        avg_pm1,
            'temperature':  avg_temp,
            'humidity':     avg_hum,
            'pressure':     avg_pres,
            'gas_resistance': avg_gas,
            'timestamp':    valid[0].timestamp.isoformat() if valid else None,
        }

        # ── If no coordinates, return area average ──
        if not lat or not lng:
            return JsonResponse({'success': True, 'data': area_average})

        user_lat = float(lat)
        user_lng = float(lng)

        # ── Find closest node ──
        closest_node   = None
        closest_reading = None
        min_distance   = float('inf')

        for node in nodes:
            latest = node.readings.order_by('-timestamp').first()
            if not latest:
                continue
            dist = haversine(user_lat, user_lng,
                             float(node.latitude), float(node.longitude))
            if dist < min_distance:
                min_distance    = dist
                closest_node    = node
                closest_reading = latest

        # ── If no node found, return area average ──
        if not closest_node or not closest_reading:
            return JsonResponse({'success': True, 'data': area_average})

        # ── Return closest node data ──
        return JsonResponse({
            'success': True,
            'data': {
                'source':        'closest_node',
                'node_name':     closest_node.name,
                'location':      closest_node.location or 'Unknown',
                'distance_km':   round(min_distance, 2),
                'aqi':           closest_reading.aqi,
                'aqi_level':     closest_reading.aqi_level,
                'pm2_5':         float(closest_reading.pm2_5)         if closest_reading.pm2_5         else None,
                'pm10':          float(closest_reading.pm10)          if closest_reading.pm10          else None,
                'pm1_0':         float(closest_reading.pm1_0)         if closest_reading.pm1_0         else None,
                'temperature':   float(closest_reading.temperature)   if closest_reading.temperature   else None,
                'humidity':      float(closest_reading.humidity)       if closest_reading.humidity       else None,
                'pressure':      float(closest_reading.pressure)       if closest_reading.pressure       else None,
                'gas_resistance':float(closest_reading.gas_resistance) if closest_reading.gas_resistance else None,
                'timestamp':     closest_reading.timestamp.isoformat() if closest_reading.timestamp else None,
            }
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    

def shop_view(request):
    if request.method == 'POST' and 'customer_email' in request.POST:
        customer_name = request.POST.get('customer_name')
        customer_email = request.POST.get('customer_email')
        notes = request.POST.get('notes')
        
        HardwareRequest.objects.create(
            customer_name=customer_name, 
            customer_email=customer_email, 
            notes=notes
        )
        messages.success(request, "Your hardware request has been submitted successfully.")
        return redirect('app:shop')

    products = Product.objects.filter(is_active=True)
    return render(request, 'AppEnviroNode/shop/store.html', {'products': products})

@login_required
def hardware_inventory_view(request):
    products = Product.objects.all().order_by('-id')
    pending_requests = HardwareRequest.objects.filter(is_processed=False).order_by('-created_at')
    
    # --- Python Parser: Cleanly separate the request data ---
    for req in pending_requests:
        req.parsed_qty = 1
        req.parsed_address = "No address provided."
        req.parsed_notes = req.notes or ""
        req.detected_product_id = ""
        
        import re
        qty_match = re.search(r'Requested Quantity:\s*(\d+)', req.parsed_notes, re.IGNORECASE)
        if qty_match:
            req.parsed_qty = int(qty_match.group(1))
            req.parsed_notes = req.parsed_notes.replace(qty_match.group(0), '')
            
        addr_match = re.search(r'Shipping Address:\s*([\s\S]+)', req.parsed_notes, re.IGNORECASE)
        if addr_match:
            req.parsed_address = addr_match.group(1).strip()
            req.parsed_notes = re.sub(r'Shipping Address:\s*[\s\S]+', '', req.parsed_notes, flags=re.IGNORECASE)
            
        prod_match = re.search(r'Requesting build for\s+([^.\n]+)', req.parsed_notes, re.IGNORECASE)
        if prod_match:
            prod_name = prod_match.group(1).strip().lower()
            for p in products:
                if prod_name in p.name.lower():
                    req.detected_product_id = p.id
                    break
        
        req.parsed_notes = req.parsed_notes.strip()
        if not req.parsed_notes:
            req.parsed_notes = "No additional configuration notes provided."

    # --- Handle Form Submissions ---
    if request.method == 'POST':
        # 1. Handle "Process Requested Order" Modal
        if 'product_id' in request.POST:
            customer_name = request.POST.get('customer_name')
            customer_email = request.POST.get('customer_email')
            product_id = request.POST.get('product_id')
            quantity = int(request.POST.get('quantity', 1))
            
            if not product_id:
                messages.error(request, 'Please select a hardware configuration from the dropdown.')
                return redirect('app:hardware_inventory')
                
            product = get_object_or_404(Product, id=product_id)
            total_price = product.price * quantity
            
            req = HardwareRequest.objects.filter(customer_email=customer_email, is_processed=False).first()
            shipping_address = "Manual Request"
            if req and req.notes:
                addr_match = re.search(r'Shipping Address:\s*([\s\S]+)', req.notes, re.IGNORECASE)
                if addr_match:
                    shipping_address = addr_match.group(1).strip()
            
            if product.stock >= quantity:
                product.stock -= quantity
                product.save()

            new_order = Order.objects.create(
                customer_name=customer_name,
                customer_email=customer_email,
                contact_number="Provided via Request",
                shipping_address=shipping_address,
                product=product,
                quantity=quantity,
                total_price=total_price,
                status='pending',
            )
            
            try:
                PAYMONGO_SECRET_KEY = settings.PAYMONGO_SECRET_KEY
                pm_url = "https://api.paymongo.com/v1/links"
                pm_payload = {
                    "data": {
                        "attributes": {
                            "amount": int(total_price * 100), 
                            "description": f"EnviroPlus Manual Order: {product.name} (Qty: {quantity})",
                            "remarks": f"EnviroPlus Order ID: {new_order.id}" 
                        }
                    }
                }
                pm_headers = {"accept": "application/json", "content-type": "application/json"}
                response = requests.post(pm_url, json=pm_payload, headers=pm_headers, auth=(PAYMONGO_SECRET_KEY, ''), timeout=10)
                
                if response.status_code == 200:
                    checkout_data = response.json()
                    payment_url = checkout_data['data']['attributes']['checkout_url']
                    
                    brevo_url = "https://api.brevo.com/v3/smtp/email"
                    brevo_payload = {
                        "sender": {"name": "EnviroPlus Admin", "email": "enviroplusnode@gmail.com"}, 
                        "to": [{"email": customer_email, "name": customer_name}],
                        "subject": "Your EnviroPlus Order is Ready for Payment",
                        "htmlContent": f"""
                        <html>
                        <body>
                            <h2>Hello {customer_name},</h2>
                            <p>Your requested order for <strong>{quantity}x {product.name}</strong> has been processed by our team!</p>
                            <p>Total Amount: <strong>PHP {total_price}</strong></p>
                            <br>
                            <p>Please click the secure link below to proceed with your payment via GCash, Maya, or Card:</p>
                            <a href="{payment_url}" style="padding: 12px 24px; background-color: #ea580c; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Proceed to Payment</a>
                        </body>
                        </html>
                        """
                    }
                    brevo_headers = {"accept": "application/json", "content-type": "application/json", "api-key": getattr(settings, 'BREVO_API_KEY', '')}

                    try:
                        brevo_response = requests.post(brevo_url, json=brevo_payload, headers=brevo_headers, timeout=10)
                        if brevo_response.status_code in [201, 200]:
                            messages.success(request, f'Order created and payment link emailed via Brevo to {customer_name}.')
                        else:
                            messages.warning(request, f'Order created, but email failed. Send them this link manually: {payment_url}')
                    except Exception:
                        messages.warning(request, f'Order created, but email failed. Send them this link manually: {payment_url}')

                    if req:
                        req.is_processed = True
                        req.save()

                    # --- AUDIT LOG FOR ORDER PROCESSING ---
                    admin_name = request.user.get_full_name() or request.user.username
                    SystemLog.objects.create(
                        event_type='order',
                        severity='good',
                        message=f"Admin {admin_name} processed hardware request for {customer_name} ({quantity}x {product.name}).",
                        created_at=timezone.now()
                    )

                else:
                    new_order.delete()
                    messages.error(request, 'Failed to generate PayMongo checkout link.')

            except Exception:
                new_order.delete()
                messages.error(request, 'Connection to the payment gateway timed out.')

            return redirect('app:hardware_inventory')

        # 2. Handle "Register New U-Node" Admin Form
        else:
            form = ProductForm(request.POST, request.FILES)
            if form.is_valid():
                new_product = form.save()
                
                # --- AUDIT LOG FOR NEW HARDWARE ---
                admin_name = request.user.get_full_name() or request.user.username
                SystemLog.objects.create(
                    event_type='admin',
                    severity='good',
                    message=f"Admin {admin_name} added new hardware to the store: {new_product.name} (Stock: {new_product.stock}).",
                    created_at=timezone.now()
                )
                
                messages.success(request, 'New U-Node hardware added to the deployment store!')
                return redirect('app:hardware_inventory')
    else:
        form = ProductForm()
        
    return render(request, 'AppEnviroNode/admin/hardware_inventory.html', {
        'products': products,
        'pending_requests': pending_requests,
        'form': form
    })

@login_required
@require_http_methods(["POST"])
def hardware_delete_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_name = product.name
    product.delete()
    
    # --- AUDIT LOG CREATION ---
    admin_name = request.user.get_full_name() or request.user.username
    SystemLog.objects.create(
        event_type='admin',
        severity='moderate',  # Using 'moderate' gives it a yellow warning tint in the history table
        message=f"Admin {admin_name} deleted hardware from the store: {product_name}.",
        created_at=timezone.now()
    )
    
    messages.success(request, f'Hardware "{product_name}" has been removed.')
    return redirect('app:hardware_inventory')


@csrf_exempt
def paymongo_webhook(request):
    if request.method == 'POST':
        try:
            # Parse the hidden data sent by PayMongo
            payload = json.loads(request.body)
            event_type = payload.get('data', {}).get('attributes', {}).get('type')
            
            # Check if the event is a successful link payment
            if event_type == 'link.payment.paid':
                # Extract the remarks we sent earlier to identify the specific order
                remarks = payload['data']['attributes']['data']['attributes']['remarks']
                
                if remarks and "EnviroPlus Order ID:" in remarks:
                    order_id = int(remarks.split(":")[-1].strip())
                    
                    # Update the database
                    order = Order.objects.get(id=order_id)
                    order.status = 'Paid'
                    order.save()
                    
                    # You can trigger your Brevo email receipt function here later[cite: 8]
                    
        except Exception as e:
            print(f"Webhook error: {e}")
            return HttpResponse(status=400)
            
        # Tell PayMongo we received the message successfully
        return HttpResponse(status=200)
        
    return HttpResponse(status=405)

def dummy_checkout(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == 'POST':
        # 1. Force the backend to capture exactly what is inside the frontend text boxes
        customer_name = request.POST.get('customer_name')
        customer_email = request.POST.get('customer_email')
        contact_number = request.POST.get('contact_number')
        shipping_address = request.POST.get('shipping_address')
        
        quantity = int(request.POST.get('quantity', 1))
        total_price = product.price * quantity

        # Deduct stock conditionally
        if product.stock >= quantity:
            product.stock -= quantity
            product.save()

        # 2. Save the exact inputs to the database
        order = Order.objects.create(
            customer_name=customer_name,
            customer_email=customer_email,
            contact_number=contact_number,
            shipping_address=shipping_address,
            product=product,
            quantity=quantity,
            total_price=total_price,
            status='pending' 
        )

        # --- AUDIT LOG CREATION ---
        SystemLog.objects.create(
            event_type='order',
            severity='good',
            message=f"Storefront Checkout: {customer_name} purchased {quantity}x {product.name}.",
            created_at=timezone.now()
        )

        # 3. Call PayMongo Checkout Sessions API (Redirect Auto-Update Method)
        url = "https://api.paymongo.com/v1/checkout_sessions"
        
        success_url = request.build_absolute_uri(f'/payment-success/{order.id}/')
        cancel_url = request.build_absolute_uri('/shop/')
        
        payload = {
            "data": {
                "attributes": {
                    "billing": {
                        "name": customer_name,
                        "email": customer_email,
                        "phone": contact_number
                    },
                    "send_email_receipt": True,
                    "show_description": True,
                    "show_line_items": True,
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "description": f"EnviroPlus U-Node - {product.name}",
                    "line_items": [
                        {
                            "currency": "PHP",
                            "amount": int(product.price * 100), 
                            "name": product.name,
                            "quantity": quantity
                        }
                    ],
                    "payment_method_types": ["gcash", "paymaya", "card"]
                }
            }
        }
        
        headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }

        PAYMONGO_SECRET_KEY = settings.PAYMONGO_SECRET_KEY

        response = requests.post(
            url, json=payload, headers=headers, auth=(PAYMONGO_SECRET_KEY, '')
        )
        
        if response.status_code == 200:
            data = response.json()
            checkout_url = data['data']['attributes']['checkout_url']
            return redirect(checkout_url)
        else:
            print("PayMongo Error:", response.text)
            product.stock += quantity
            product.save()
            order.delete()
            messages.error(request, "Payment gateway is currently unavailable. Please try again.")
            return redirect('app:checkout', product_id=product.id)

    return render(request, 'AppEnviroNode/shop/checkout.html', {'product': product})

@login_required
def hardware_orders(request):
    if request.user.role != 'admin':
        messages.error(request, "Access restricted to administrators.")
        return redirect('app:client_dashboard')

    # Base queryset, ordered by newest first
    order_list = Order.objects.all().order_by('-created_at')

    # 1. Search Functionality
    search_query = request.GET.get('q', '')
    if search_query:
        order_list = order_list.filter(
            Q(customer_name__icontains=search_query) | 
            Q(customer_email__icontains=search_query) |
            Q(contact_number__icontains=search_query)
        )

    # --- REPORT EXPORT LOGIC WITH MODAL FILTERS ---
    export_format = request.GET.get('export_format')
    if export_format in ['csv', 'excel']:
        export_qs = order_list
        
        # Apply Status Filter
        export_status = request.GET.get('export_status', 'all')
        if export_status != 'all':
            export_qs = export_qs.filter(status=export_status)
            
        # Apply Date Range Filter
        start_date = request.GET.get('export_start_date')
        end_date = request.GET.get('export_end_date')
        
        if start_date:
            try:
                s_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                export_qs = export_qs.filter(created_at__gte=s_date)
            except ValueError:
                pass
                
        if end_date:
            try:
                e_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, tzinfo=timezone.utc)
                export_qs = export_qs.filter(created_at__lte=e_date)
            except ValueError:
                pass

        if export_format == 'csv':
            return export_orders_csv(export_qs)
        elif export_format == 'excel':
            return export_orders_excel(export_qs)

    # 2. Detailed Analytics Calculations
    total_orders_count = order_list.count()
    
    total_revenue = order_list.filter(
        status__in=['paid', 'shipped', 'received']
    ).aggregate(Sum('total_price'))['total_price__sum'] or 0.00

    total_units_sold = order_list.aggregate(Sum('quantity'))['quantity__sum'] or 0
    pending_orders_count = order_list.filter(status='pending').count()
    pending_requests_count = HardwareRequest.objects.filter(is_processed=False).count()
    
    most_bought = Order.objects.exclude(product__isnull=True).values('product__name').annotate(
        total_qty=Sum('quantity')
    ).order_by('-total_qty').first()
    
    most_bought_name = most_bought['product__name'] if most_bought else "No active orders"
    most_bought_qty = most_bought['total_qty'] if most_bought else 0

    # 3. Pagination (5 items per page)
    paginator = Paginator(order_list, 5)
    page_number = request.GET.get('page')
    orders = paginator.get_page(page_number)

    context = {
        'orders': orders,
        'total_orders_count': total_orders_count,
        'total_revenue': total_revenue,
        'total_units_sold': total_units_sold,
        'pending_orders_count': pending_orders_count,
        'pending_requests_count': pending_requests_count,
        'most_bought_name': most_bought_name,
        'most_bought_qty': most_bought_qty,
        'search_query': search_query,
    }
    
    return render(request, 'AppEnviroNode/shop/orders.html', context)

def export_orders_csv(queryset):
    """Generates a CSV report of the filtered orders."""
    now = timezone.now()
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="EnviroPlus_Orders_{now.strftime("%Y%m%d_%H%M")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Order ID', 'Customer Name', 'Email', 'Contact Number', 'Shipping Address', 'Product', 'Quantity', 'Total Price', 'Status', 'Date Ordered'])
    
    for order in queryset:
        product_name = order.product.name if order.product else 'Deleted Product'
        writer.writerow([
            f"#{order.id}",
            order.customer_name,
            order.customer_email,
            order.contact_number,
            order.shipping_address,
            product_name,
            order.quantity,
            order.total_price,
            order.get_status_display() if hasattr(order, 'get_status_display') else order.status.title(),
            order.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    return response


def export_orders_excel(queryset):
    """Generates a formatted Excel report of the filtered orders with fixed column widths."""
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl import Workbook
    import io
    
    now = timezone.now()
    wb = Workbook()
    ws = wb.active
    ws.title = "Hardware Orders"
    
    # Stylized Headers
    headers = ['Order ID', 'Customer Name', 'Email', 'Contact Number', 'Shipping Address', 'Product', 'Quantity', 'Total Price', 'Status', 'Date Ordered']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        cell.alignment = Alignment(horizontal='center', vertical='center')
    
    # Populate Rows
    for row_num, order in enumerate(queryset, 2):
        product_name = order.product.name if order.product else 'Deleted Product'
        ws.cell(row=row_num, column=1, value=f"#{order.id}")
        ws.cell(row=row_num, column=2, value=order.customer_name)
        ws.cell(row=row_num, column=3, value=order.customer_email)
        ws.cell(row=row_num, column=4, value=order.contact_number)
        ws.cell(row=row_num, column=5, value=order.shipping_address)
        ws.cell(row=row_num, column=6, value=product_name)
        ws.cell(row=row_num, column=7, value=order.quantity)
        ws.cell(row=row_num, column=8, value=float(order.total_price))
        ws.cell(row=row_num, column=9, value=order.get_status_display() if hasattr(order, 'get_status_display') else order.status.title())
        ws.cell(row=row_num, column=10, value=order.created_at.strftime('%Y-%m-%d %H:%M:%S'))
    
    # Explicitly set column widths to prevent '####'
    widths = [12, 22, 28, 18, 40, 25, 10, 15, 15, 22]
    for col_num, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col_num)].width = width
        
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="EnviroPlus_Orders_{now.strftime("%Y%m%d_%H%M")}.xlsx"'
    return response

@login_required
@require_POST
def update_order_status(request, order_id):
    if request.user.role != 'admin':
        messages.error(request, "Unauthorized action.")
        return redirect('app:client_dashboard')
    
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    
    # Validate that the submitted status is actually one of our choices
    valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
    if new_status in valid_statuses:
        order.status = new_status
        order.save()
        messages.success(request, f"Order #{order.id} marked as {order.get_status_display()}.")
    else:
        messages.error(request, "Invalid status update.")
        
    return redirect('app:hardware_orders') # Adjust prefix if needed based on your urls.py

def request_build_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    
    if request.method == 'POST':
        customer_name = request.POST.get('customer_name')
        customer_email = request.POST.get('customer_email')
        notes = request.POST.get('notes')
        
        # Save to the HardwareRequest database for the Admin to see
        HardwareRequest.objects.create(
            customer_name=customer_name, 
            customer_email=customer_email, 
            notes=notes
        )
        
        # --- AUDIT LOG CREATION ---
        SystemLog.objects.create(
            event_type='order',
            severity='moderate',
            message=f"New Hardware Request submitted by {customer_name} for review.",
            created_at=timezone.now()
        )
        
        messages.success(request, "Your hardware request has been sent! Our team will review it and email you the payment link when ready.")
        return redirect('app:shop')

    return render(request, 'AppEnviroNode/shop/request_order.html', {'product': product})

def payment_success(request, order_id):
    """Catches the user after PayMongo redirects them back, and auto-updates the order."""
    order = get_object_or_404(Order, id=order_id)
    
    # Auto-update to Paid
    if order.status != 'paid':
        order.status = 'paid'
        order.save()
        
    return redirect('app:shop')

@login_required
def process_request_view(request, request_id):
    hw_request = get_object_or_404(HardwareRequest, id=request_id)
    products = Product.objects.all().order_by('-id')

    # 1. Parse Data Safely via Python
    parsed_qty = 1
    parsed_notes = hw_request.notes or ""
    detected_product_id = None

    qty_match = re.search(r'Requested Quantity:\s*(\d+)', parsed_notes, re.IGNORECASE)
    if qty_match:
        parsed_qty = int(qty_match.group(1))

    prod_match = re.search(r'Requesting build for\s+([^.\n]+)', parsed_notes, re.IGNORECASE)
    if prod_match:
        prod_name = prod_match.group(1).strip().lower()
        for p in products:
            if prod_name in p.name.lower():
                detected_product_id = p.id
                break

    # 2. Handle the Form Submission (Create Order, PayMongo, Brevo)
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        quantity = int(request.POST.get('quantity', 1))

        if not product_id:
            messages.error(request, 'Please select a hardware configuration.')
            return redirect('app:process_request', request_id=request_id)

        product = get_object_or_404(Product, id=product_id)
        total_price = product.price * quantity

        # Extract address to save to the actual order
        shipping_address = "Manual Request"
        addr_match = re.search(r'Shipping Address:\s*([\s\S]+)', parsed_notes, re.IGNORECASE)
        if addr_match:
            shipping_address = addr_match.group(1).strip()

        if product.stock >= quantity:
            product.stock -= quantity
            product.save()

        new_order = Order.objects.create(
            customer_name=hw_request.customer_name,
            customer_email=hw_request.customer_email,
            contact_number="Provided via Request",
            shipping_address=shipping_address,
            product=product,
            quantity=quantity,
            total_price=total_price,
            status='pending',
        )

        try:
            # --- PAYMONGO CHECKOUT SESSIONS API ---
            url = "https://api.paymongo.com/v1/checkout_sessions"
            success_url = request.build_absolute_uri(f'/payment-success/{new_order.id}/')
            cancel_url = request.build_absolute_uri('/shop/')
            
            payload = {
                "data": {
                    "attributes": {
                        "billing": {
                            "name": hw_request.customer_name,
                            "email": hw_request.customer_email,
                        },
                        "send_email_receipt": True,
                        "show_description": True,
                        "show_line_items": True,
                        "success_url": success_url,
                        "cancel_url": cancel_url,
                        "description": f"EnviroPlus Manual Order: {product.name}",
                        "line_items": [
                            {
                                "currency": "PHP",
                                "amount": int(product.price * 100),
                                "name": product.name,
                                "quantity": quantity
                            }
                        ],
                        "payment_method_types": ["gcash", "paymaya", "card"]
                    }
                }
            }

            headers = {
                "accept": "application/json",
                "content-type": "application/json"
            }

            PAYMONGO_SECRET_KEY = settings.PAYMONGO_SECRET_KEY
            
            response = requests.post(
                url, json=payload, headers=headers, auth=HTTPBasicAuth(PAYMONGO_SECRET_KEY, ''), timeout=10
            )
            
            if response.status_code == 200:
                checkout_data = response.json()
                payment_url = checkout_data['data']['attributes']['checkout_url']
                
                # --- BREVO EMAIL INTEGRATION ---
                brevo_url = "https://api.brevo.com/v3/smtp/email"
                brevo_payload = {
                    "sender": {"name": "EnviroPlus Admin", "email": "enviroplusnode@gmail.com"}, 
                    "to": [{"email": hw_request.customer_email, "name": hw_request.customer_name}],
                    "subject": "Your EnviroPlus Order is Ready for Payment",
                    "htmlContent": f"""
                    <html>
                    <body>
                        <h2>Hello {hw_request.customer_name},</h2>
                        <p>Your requested order for <strong>{quantity}x {product.name}</strong> has been processed!</p>
                        <p>Total Amount: <strong>PHP {total_price}</strong></p>
                        <br>
                        <p>Please click the secure link below to proceed with your payment:</p>
                        <a href="{payment_url}" style="padding: 12px 24px; background-color: #ea580c; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Proceed to Payment</a>
                    </body>
                    </html>
                    """
                }
                brevo_headers = {"accept": "application/json", "content-type": "application/json", "api-key": getattr(settings, 'BREVO_API_KEY', '')}

                requests.post(brevo_url, json=brevo_payload, headers=brevo_headers, timeout=10)
                messages.success(request, f'Order created and payment link emailed to {hw_request.customer_name}.')

                hw_request.is_processed = True
                hw_request.save()

                # --- AUDIT LOG CREATION ---
                admin_name = request.user.get_full_name() or request.user.username
                SystemLog.objects.create(
                    event_type='admin',
                    severity='good',
                    message=f"Admin {admin_name} processed hardware request for {hw_request.customer_name} ({quantity}x {product.name}).",
                    created_at=timezone.now()
                )

            else:
                new_order.delete()
                print("PayMongo Error:", response.text)
                messages.error(request, 'Failed to generate PayMongo checkout link.')

        except Exception as e:
            new_order.delete()
            print("Error:", str(e))
            messages.error(request, 'Payment gateway connection failed.')

        return redirect('app:hardware_inventory')

    return render(request, 'AppEnviroNode/admin/process_request.html', {
        'req': hw_request,
        'products': products,
        'parsed_qty': parsed_qty,
        'detected_product_id': detected_product_id
    })

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    SystemLog.objects.create(
        event_type='system',
        severity='good',
        message=f"User '{user.username}' successfully logged into the system.",
        created_at=timezone.now()
    )

@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get('username', 'Unknown')
    SystemLog.objects.create(
        event_type='system',
        severity='unhealthy',
        message=f"SECURITY: Failed login attempt for username '{username}'.",
        created_at=timezone.now()
    )

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if user:
        SystemLog.objects.create(
            event_type='system',
            severity='good',
            message=f"User '{user.username}' logged out.",
            created_at=timezone.now()
        )

@login_required(login_url='app:login')
def export_history_excel(
    request,
    event_type,
    node_id,
    date_range,
    sensor_type,
    severity
):
    """
    Export all matching audit logs to a styled Excel workbook.
    Keeps the existing report columns and readable column widths.
    """
    from openpyxl.styles import Font, PatternFill

    logs = _audit_filtered_queryset(request)

    wb = Workbook()
    ws = wb.active

    ws.title = 'System Audit History'

    headers = [
        'Timestamp',
        'Event Type',
        'Node Name',
        'Location',
        'MAC Address',
        'Severity',
        'Sensor Type',
        'Value',
        'Message',
    ]

    for column, name in enumerate(headers, 1):
        cell = ws.cell(
            row=1,
            column=column,
            value=name
        )

        cell.font = Font(
            bold=True,
            color='FFFFFF'
        )

        cell.fill = PatternFill(
            start_color='0F172A',
            end_color='0F172A',
            fill_type='solid'
        )

        cell.alignment = Alignment(
            horizontal='center',
            vertical='center'
        )

    for row_number, log in enumerate(
        logs.iterator(chunk_size=500),
        2
    ):
        node = log.node

        values = [
            timezone.localtime(
                log.created_at
            ).strftime('%Y-%m-%d %H:%M:%S'),

            log.get_event_type_display(),

            node.name if node else 'System',
            node.location if node else 'N/A',
            node.mac_address if node else 'N/A',

            (
                log.get_severity_display()
                if log.severity else 'N/A'
            ),

            (
                log.get_sensor_type_display()
                if log.sensor_type else 'N/A'
            ),

            str(log.value) if log.value is not None else 'N/A',
            log.message,
        ]

        for column, value in enumerate(values, 1):
            ws.cell(
                row=row_number,
                column=column,
                value=value
            )

    for column, width in enumerate(
        [22, 18, 20, 25, 20, 15, 15, 12, 80],
        1
    ):
        ws.column_dimensions[
            get_column_letter(column)
        ].width = width

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions

    buffer = io.BytesIO()
    wb.save(buffer)

    response = HttpResponse(
        buffer.getvalue(),
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        f'attachment; filename="EnviroPlus_Audit_Log_'
        f'{timezone.now():%Y%m%d_%H%M%S}.xlsx"'
    )

    return response