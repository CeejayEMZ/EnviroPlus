from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
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
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.utils.crypto import get_random_string
from django.template.loader import render_to_string
from django.conf import settings
from django.views.decorators.cache import cache_page
from functools import wraps
from .ai import ask_enviro_ai, generate_ai_insights
import csv
import io
import logging
from datetime import timedelta, datetime
import base64
import hashlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
# from xhtml2pdf import pisa
from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
import json
import urllib.parse
from .forms import CustomAuthenticationForm, CustomUserCreationForm, PasswordResetRequestForm, SensorNodeForm
from .models import SensorNode, SensorReading, Alert, SystemLog, AdminActionLog
from .services import EmailService
from django.contrib.auth import get_user_model

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
    # ⚡ OPTIMIZATION: Skip large JSON injection - will fetch async via API
    # =========================================================================
    check_and_update_node_status()
    
    # Only count active/inactive, don't serialize full data
    active_count = SensorNode.objects.filter(status='active').count()
    inactive_count = SensorNode.objects.filter(status='inactive').count()
    total_node_count = SensorNode.objects.count()
    
    top_polluted_areas, cleanest_areas, top_area_count = build_top_area_rankings(limit=5)
    
    # ⚡ OPTIMIZATION: Limit rankings to 5 items each
    context = {
        'aggregate_data': aggregate_data,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),
        # ✅ REMOVED: active_nodes_json, inactive_nodes_json (fetched via API)
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
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            
            # ✅ FIX: Support both username and email login
            user = None
            
            # Try username first
            user = authenticate(request, username=username, password=password)
            
            # If username fails and input looks like email, try email login
            if user is None and '@' in username:
                try:
                    email_user = User.objects.get(email=username)
                    user = authenticate(request, username=email_user.username, password=password)
                except User.DoesNotExist:
                    pass
            
            if user is not None:
                # Check if user is active and approved
                if not user.is_active:
                    messages.error(request, 'Your account has been deactivated.')
                    return render(request, 'AppEnviroNode/auth/login.html', {'form': form})
                
                if not user.is_approved:
                    messages.error(request, 'Your account is pending admin approval.')
                    return render(request, 'AppEnviroNode/auth/login.html', {'form': form})
                
                # Log user in
                login(request, user)
                
                # Check if user must change password (first login)
                if user.must_change_password:
                    messages.info(request, 'Please set a new password for security.')
                    return redirect('app:force_password_change')
                
                messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                return redirect('app:client_dashboard')
            else:
                messages.error(request, 'Invalid username/email or password.')
        else:
            # Form validation failed - show errors
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, str(error))
                    else:
                        messages.error(request, f'{error}')
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
    """Dashboard with all sensor nodes, latest readings, analytics, and chart data."""
    from django.db.models.functions import TruncDay
    
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
    # SECTION 2: Generate 7-day chart data (reuse client_analytics logic)
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
    # SECTION 3: Analytics aggregations (same as client_analytics, last 7 days)
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
    # SECTION 5: Map data (reuse from client_map_view logic)
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
            readings_qs = readings_qs.filter(node__id=int(node_filter))
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
        'nodes': nodes_response,
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
    Receive sensor data from ESP8266 nodes.
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
            system_status=data.get('system_status', 'normal'),
            pms_status=data.get('pms_status', 'ok'),
            bme_status=data.get('bme_status', 'ok'),
            latency_ms=data.get('latency_ms'),
            timestamp=timezone.now(),
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
    
    Returns real-time chart and summary data for realtime.html template.
    Handles range, node, start_date, end_date filters from UI.
    """
    try:
        from django.db.models.functions import TruncHour, TruncDay
        
        now = timezone.now()
        
        # Parse filter parameters from template UI
        selected_range = request.GET.get('range', '24h').lower()
        node_param = request.GET.get('node', '').strip()
        start_date_str = request.GET.get('start_date', '').strip()
        end_date_str = request.GET.get('end_date', '').strip()
        
        # Determine time window
        if selected_range == 'custom' and start_date_str and end_date_str:
            try:
                time_start = datetime.strptime(start_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                time_end = datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                time_end = time_end.replace(hour=23, minute=59, second=59)
                range_label = f"{start_date_str} to {end_date_str}"
            except:
                time_start = now - timedelta(hours=24)
                time_end = now
                range_label = "Last 24 hours"
                selected_range = '24h'
        elif selected_range == '7d':
            time_start = now - timedelta(days=7)
            time_end = now
            range_label = "Last 7 days"
        elif selected_range == '30d':
            time_start = now - timedelta(days=30)
            time_end = now
            range_label = "Last 30 days"
        else:
            time_start = now - timedelta(hours=24)
            time_end = now
            range_label = "Last 24 hours"
            selected_range = '24h'
        
        # Parse node filter
        selected_node_id = None
        selected_location = None
        
        if node_param.startswith('node:'):
            try:
                selected_node_id = int(node_param.split(':')[1])
            except:
                pass
        elif node_param.startswith('location:'):
            selected_location = node_param.split(':', 1)[1]
        
        # Build readings queryset
        readings_qs = SensorReading.objects.filter(
            timestamp__gte=time_start,
            timestamp__lte=time_end
        ).select_related('node')
        
        if selected_node_id:
            readings_qs = readings_qs.filter(node_id=selected_node_id)
        elif selected_location:
            readings_qs = readings_qs.filter(node__location__iexact=selected_location)
        
        # Calculate aggregation strategy based on time range
        if selected_range == '24h':
            trunc_func = TruncHour
        elif selected_range == '7d':
            trunc_func = TruncDay
        else:
            trunc_func = TruncDay
        
        # Aggregate chart data
        chart_agg = readings_qs.annotate(
            period=trunc_func('timestamp')
        ).values('period').annotate(
            avg_aqi=Avg('aqi'),
            avg_pm2_5=Avg('pm2_5'),
            avg_pm10=Avg('pm10'),
            avg_temperature=Avg('temperature')
        ).order_by('period')
        
        chart_data = []
        for item in chart_agg:
            if item['period']:
                chart_data.append({
                    'period': item['period'].isoformat() if item['period'] else '',
                    'date': item['period'].strftime('%Y-%m-%d %H:%M') if item['period'] else '',
                    'avg_aqi': round(item['avg_aqi'], 1) if item['avg_aqi'] is not None else None,
                    'avg_pm2_5': round(item['avg_pm2_5'], 2) if item['avg_pm2_5'] is not None else None,
                    'avg_pm10': round(item['avg_pm10'], 2) if item['avg_pm10'] is not None else None,
                    'avg_temperature': round(item['avg_temperature'], 1) if item['avg_temperature'] is not None else None,
                })
        
        # Calculate summary metrics
        aqi_values = readings_qs.filter(aqi__isnull=False).values_list('aqi', flat=True)
        avg_aqi = round(sum(aqi_values) / len(aqi_values), 1) if aqi_values else None
        
        total_readings = readings_qs.count()
        
        # Get latest reading info
        latest_reading = readings_qs.filter(aqi__isnull=False).order_by('-timestamp').first()
        latest_aqi = latest_reading.aqi if latest_reading else None
        latest_node_name = latest_reading.node.name if latest_reading else 'Unknown'
        latest_node_location = latest_reading.node.location if latest_reading else 'Unknown'
        latest_timestamp = latest_reading.timestamp if latest_reading else None
        
        # Count active nodes
        active_nodes = SensorNode.objects.filter(is_active=True).count()
        
        summary = {
            'success': True,
            'avg_aqi': avg_aqi,
            'total_readings': total_readings,
            'active_nodes': active_nodes,
            'range_label': range_label,
            'latest_aqi': latest_aqi,
            'latest_node_name': latest_node_name,
            'latest_node_location': latest_node_location,
            'latest_timestamp': latest_timestamp.isoformat() if latest_timestamp else None,
        }
        
        return JsonResponse({
            'success': True,
            'summary': summary,
            'chart_data': chart_data,
        })
        
    except Exception as e:
        logger.error(f"API realtime data error: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to load',
            'summary': {
                'avg_aqi': None,
                'total_readings': 0,
                'active_nodes': 0,
                'range_label': '',
                'latest_aqi': None,
                'latest_node_name': 'Unknown',
                'latest_node_location': 'Unknown',
                'latest_timestamp': None,
            },
            'chart_data': [],
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


@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_users_invite(request):
    """Send invitation to new user (creates pending account)."""
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
    
    try:
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


@login_required(login_url='app:login')
@require_http_methods(["POST"])
def api_users_resend_invite(request, user_id):
    """Resend invitation email to pending user."""
    # ✅ ROLE-BASED ACCESS CONTROL
    if not request.user.is_admin_user():
        return JsonResponse({'status': 'error', 'message': 'Admin access required'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    
    if user.is_approved:
        return JsonResponse({'status': 'error', 'message': 'User is already approved'}, status=400)
    
    try:
        # Generate new activation token and link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        # Use FRONTEND_BASE_URL from settings for consistent email links
        activation_link = f"{settings.FRONTEND_BASE_URL}/activate/{uid}/{token}/"
        
        # ✅ SEND EMAIL USING EMAIL SERVICE with error handling
        email_result = EmailService.send_user_invite_email(user, activation_link)
        
        if not email_result['success']:
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
        return JsonResponse({'status': 'error', 'message': f'Failed to resend invitation: {str(e)}'}, status=500)


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
        
        if not password or len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters')
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
        
        messages.success(request, 'Account activated successfully! Welcome to EnviroNode.')
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
    User requests password reset.
    Creates Alert object for admin moderation.
    Auto-approves after 5 minutes if not manually reviewed.
    """
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            
            try:
                user = User.objects.get(email=email)
                
                # Generate password reset token and uid
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                
                # Build reset link
                reset_link = request.build_absolute_uri(f'/reset-password/{uid}/{token}/')
                
                # Create Alert for admin moderation
                alert = Alert.objects.create(
                    user=user,
                    alert_type='password_reset_request',
                    status='pending',
                    severity='info',
                    title=f'Password Reset Request - {user.email}',
                    description=f'User {user.email} requested password reset at {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}',
                    password_reset_token=token,
                    password_reset_uid=uid,
                    auto_approval_time=timezone.now() + timedelta(minutes=5),
                )
                
                # Log the action
                SystemLog.objects.create(
                    event_type='admin',
                    message=f'Password reset requested by user: {user.email}',
                    created_at=timezone.now(),
                )
                
                messages.success(request, 'Password reset request submitted. Check your email for instructions.')
                logger.info(f"Password reset request created for {user.email} (Alert ID: {alert.id})")
                
            except User.DoesNotExist:
                # Don't reveal if email exists (security)
                logger.info(f"Password reset request for non-existent email: {email}")
            except Exception as e:
                messages.error(request, f'Error processing request: {str(e)}')
                logger.error(f"[ERROR] Password reset request failed for {email}: {str(e)}")
        
        return render(request, 'AppEnviroNode/auth/forgot_password.html', {'form': form})
    
    # GET request - show form
    form = PasswordResetRequestForm()
    return render(request, 'AppEnviroNode/auth/forgot_password.html', {'form': form})


@require_http_methods(["GET", "POST"])
def reset_password(request, uidb64, token):
    """Reset user password using token from email."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return render(request, 'AppEnviroNode/auth/activation_invalid.html', {
            'message': 'Invalid password reset link'
        })
    
    # Check token validity
    if not default_token_generator.check_token(user, token):
        return render(request, 'AppEnviroNode/auth/activation_invalid.html', {
            'message': 'Password reset link has expired. Please request a new one.'
        })
    
    if request.method == 'POST':
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        if not password or len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters')
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
        user.save()
        
        # Log the action
        SystemLog.objects.create(
            event_type='auth',
            message=f'Password reset completed for user: {user.email}',
            node=None,
            reading=None,
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
        subject = 'EnviroNode - Password Reset Request (Admin Initiated)'
        html_message = render_to_string('AppEnviroNode/email/password_reset.html', {
            'user': user,
            'reset_link': reset_link,
            'domain': request.get_host(),
            'initiated_by_admin': True,
        })
        
        send_mail(
            subject,
            f'Click this link to reset your password: {reset_link}',
            'noreply@environode.local',
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

def parse_export_params(request):
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    selected_node = request.GET.get('node', 'all')
    today = timezone.localdate()

    if not date_from:
        date_from = (today - timedelta(days=14)).isoformat()
    if not date_to:
        date_to = today.isoformat()

    try:
        date_from_obj = datetime.fromisoformat(date_from).date()
    except (TypeError, ValueError):
        date_from_obj = today - timedelta(days=14)

    try:
        date_to_obj = datetime.fromisoformat(date_to).date()
    except (TypeError, ValueError):
        date_to_obj = today

    if date_to_obj < date_from_obj:
        date_to_obj = date_from_obj

    return date_from_obj, date_to_obj, selected_node

def build_chart_image(summary):
    labels = summary.get('trend_labels', [])
    values = [float(v) if v is not None else float('nan') for v in summary.get('trend_values', [])]

    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=100)
    x = list(range(len(labels)))
    ax.plot(x, values, marker='o', color='#1f77b4', linewidth=2)
    ax.fill_between(x, values, alpha=0.12, color='#1f77b4')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.set_ylabel('AQI')
    ax.set_title('AQI Trend')
    ax.grid(True, linestyle='--', alpha=0.4)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', bbox_inches='tight')
    plt.close(fig)
    buffer.seek(0)
    return buffer

def build_chart_explanation(summary):
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

    filename = f"environode-report-{date_from_obj.isoformat()}_to_{date_to_obj.isoformat()}.csv"
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

    return render(request, 'AppEnviroNode/admin/analytics_export.html', {
        'summary': summary,
        'chart_image': chart_image,
        'chart_explanation': chart_explanation,
        'node_name': node_name,
        'report_period': summary.get('report_period', ''),
        'generated_at': summary.get('generated_at', ''),
        'avg_aqi': summary.get('avg_aqi', 0),
        'peak_aqi': summary.get('peak_aqi', 0),
        'low_aqi': summary.get('peak_aqi', 0),
        'good_days': 0,
        'moderate_days': 0,
        'unhealthy_days': 0,
        'good_pct': 0,
        'moderate_pct': 0,
        'unhealthy_pct': 0,
        'most_affected_node': 'N/A',
    })

@login_required(login_url='app:login')
def export_report_pdf(request):
    date_from_obj, date_to_obj, selected_node, selected_location = parse_export_params(request)
    summary = build_report_summary(date_from_obj, date_to_obj, selected_node, selected_location)
    chart_image = base64.b64encode(build_chart_image(summary['summary']).getvalue()).decode('ascii')
    chart_explanation = build_chart_explanation(summary['summary'])
    
    node_name = 'All Nodes'
    
    if selected_node != 'all':
        node = SensorNode.objects.filter(pk=selected_node).first()
        node_name = node.name if node else node_name

    html_string = render_to_string('AppEnviroNode/admin/analytics_export.html', {
        'summary': summary,
        'chart_image': chart_image,
        'chart_explanation': chart_explanation,
        'node_name': node_name,
        'report_period': summary.get('report_period', ''),
        'generated_at': summary.get('generated_at', ''),
        'avg_aqi': summary.get('avg_aqi', 0),
        'peak_aqi': summary.get('peak_aqi', 0),
        'low_aqi': summary.get('peak_aqi', 0),
        'good_days': 0,
        'moderate_days': 0,
        'unhealthy_days': 0,
        'good_pct': 0,
        'moderate_pct': 0,
        'unhealthy_pct': 0,
        'most_affected_node': 'N/A',
        'pdf_export': True,
    })

    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)
    
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Environode-report-{date_from_obj.isoformat()}_to_{date_to_obj.isoformat()}.pdf"'
        )
        return response
    return HttpResponse('Error generating PDF')

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
    summary = build_report_summary(date_from_obj, date_to_obj, selected_node, selected_location)

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
        f'attachment; filename="Environode-report-{date_from_obj.isoformat()}_to_{date_to_obj.isoformat()}.xlsx"'
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
