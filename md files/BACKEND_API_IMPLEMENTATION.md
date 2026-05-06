# Backend API Implementation Guide

## Quick Reference: Required Endpoints for Map System

> **Status:** All 3 endpoints are critical for the map system to function at production level.

---

## Endpoint 1: `/api/nodes/live/`

**Purpose:** Fetch current sensor readings grouped by node status  
**HTTP Method:** GET  
**Authentication:** None (CSRF exempt)  
**Query Parameters:** None

### Response Format:
```json
{
  "active": [
    {
      "id": 1,
      "name": "Node_A",
      "status": "active",
      "location": "Makati CBD",
      "latitude": 14.5631,
      "longitude": 121.0192,
      "latest_reading": {
        "timestamp": "2026-05-04T12:30:45Z",
        "battery": 85,
        "rssi": -65
      },
      "pollutants": {
        "aqi": 45,
        "pm25": 12.5,
        "pm10": 35.2,
        "temperature": 28.5,
        "humidity": 72
      },
      "aqi_history": [40, 42, 45, 44, 46, 43, 41, 39, ...]
    }
  ],
  "inactive": [],
  "rogue": [],
  "unregistered": []
}
```

### Frontend Expectations:
- ✅ Maximum 200 nodes total (harder limit enforced by frontend)
- ✅ Only LATEST reading per node
- ✅ Grouped by status: "active" | "inactive" | "rogue" | "unregistered"
- ✅ Coordinates as floats (not strings)
- ✅ Timestamp in ISO 8601 format

### Implementation Tips:
```python
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_live(request):
    """Get current sensor readings grouped by status."""
    nodes_data = {
        "active": [],
        "inactive": [],
        "rogue": [],
        "unregistered": []
    }
    
    # Query all active nodes
    nodes = SensorNode.objects.filter(is_active=True).select_related(
        'readings'
    ).order_by('name')[:200]
    
    for node in nodes:
        # Get latest reading
        latest = node.readings.order_by('-timestamp').first()
        
        if not latest:
            continue  # Skip nodes with no readings
        
        node_dict = {
            "id": node.id,
            "name": node.name,
            "status": node.status,  # 'active', 'inactive', 'rogue', 'unregistered'
            "location": node.location,
            "latitude": float(node.latitude) if node.latitude else None,
            "longitude": float(node.longitude) if node.longitude else None,
            "latest_reading": {
                "timestamp": latest.timestamp.isoformat(),
                "battery": latest.battery,
                "rssi": latest.rssi
            },
            "pollutants": {
                "aqi": latest.aqi,
                "pm25": latest.pm2_5,
                "pm10": latest.pm10,
                "temperature": latest.temperature,
                "humidity": latest.humidity
            },
            "aqi_history": []  # Optional: see below
        }
        
        # Categorize by status
        status = node.status or 'unregistered'
        if status in nodes_data:
            nodes_data[status].append(node_dict)
    
    return JsonResponse(nodes_data)
```

---

## Endpoint 2: `/api/nodes/24h/`

**Purpose:** Fetch 24-hour averaged readings  
**HTTP Method:** GET  
**Authentication:** None  
**Query Parameters:** None

### Response Format:
Same as `/api/nodes/live/` but with 24-hour averages

### Implementation Tips:
```python
from django.db.models import Avg
from datetime import timedelta
from django.utils import timezone

@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_24h(request):
    """Get 24-hour averaged sensor readings grouped by status."""
    now = timezone.now()
    start_time = now - timedelta(hours=24)
    
    nodes_data = {
        "active": [],
        "inactive": [],
        "rogue": [],
        "unregistered": []
    }
    
    nodes = SensorNode.objects.filter(is_active=True).order_by('name')[:200]
    
    for node in nodes:
        # Get 24-hour average readings
        readings_24h = node.readings.filter(
            timestamp__gte=start_time,
            timestamp__lte=now
        )
        
        if not readings_24h.exists():
            continue
        
        # Calculate averages
        avg_data = readings_24h.aggregate(
            avg_aqi=Avg('aqi'),
            avg_pm25=Avg('pm2_5'),
            avg_pm10=Avg('pm10'),
            avg_temp=Avg('temperature'),
            avg_humidity=Avg('humidity')
        )
        
        latest = readings_24h.order_by('-timestamp').first()
        
        node_dict = {
            "id": node.id,
            "name": node.name,
            "status": node.status,
            "location": node.location,
            "latitude": float(node.latitude) if node.latitude else None,
            "longitude": float(node.longitude) if node.longitude else None,
            "latest_reading": {
                "timestamp": latest.timestamp.isoformat(),
                "battery": latest.battery,
                "rssi": latest.rssi
            },
            "pollutants": {
                "aqi": round(avg_data['avg_aqi'], 1) if avg_data['avg_aqi'] else 0,
                "pm25": round(avg_data['avg_pm25'], 2) if avg_data['avg_pm25'] else 0,
                "pm10": round(avg_data['avg_pm10'], 2) if avg_data['avg_pm10'] else 0,
                "temperature": round(avg_data['avg_temp'], 1) if avg_data['avg_temp'] else 0,
                "humidity": round(avg_data['avg_humidity'], 1) if avg_data['avg_humidity'] else 0
            },
            "aqi_history": []
        }
        
        status = node.status or 'unregistered'
        if status in nodes_data:
            nodes_data[status].append(node_dict)
    
    return JsonResponse(nodes_data)
```

---

## Endpoint 3: `/api/nodes/viewport/` ⭐ NEW

**Purpose:** Fetch nodes within geographic viewport (major performance optimization)  
**HTTP Method:** GET  
**Authentication:** None  
**Query Parameters:**
- `bbox` (REQUIRED): "south,west,north,east" bounding box
- `timeframe` (OPTIONAL): "live" (default) or "24h"

### Example Usage:
```
GET /api/nodes/viewport/?bbox=14.56,121.01,14.57,121.03&timeframe=live
```

### Response Format:
Same as `/api/nodes/live/` but filtered by bounding box

### Implementation:
```python
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

@csrf_exempt
@require_http_methods(["GET"])
def api_nodes_viewport(request):
    """Get nodes within geographic bounds (viewport-based fetching)."""
    
    # Get bounding box from query params
    bbox_str = request.GET.get('bbox', '')
    if not bbox_str:
        return JsonResponse({
            "error": "bbox parameter required (format: south,west,north,east)"
        }, status=400)
    
    try:
        south, west, north, east = map(float, bbox_str.split(','))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid bbox format"}, status=400)
    
    # Validate bounds
    if not (-90 <= south <= north <= 90 and -180 <= west <= east <= 180):
        return JsonResponse({"error": "Invalid coordinates"}, status=400)
    
    timeframe = request.GET.get('timeframe', 'live')
    
    # Query nodes within viewport
    nodes = SensorNode.objects.filter(
        is_active=True,
        latitude__gte=south,
        latitude__lte=north,
        longitude__gte=west,
        longitude__lte=east
    ).select_related('readings').order_by('name')[:200]
    
    nodes_data = {
        "active": [],
        "inactive": [],
        "rogue": [],
        "unregistered": []
    }
    
    for node in nodes:
        latest = node.readings.order_by('-timestamp').first()
        
        if not latest:
            continue
        
        node_dict = {
            "id": node.id,
            "name": node.name,
            "status": node.status,
            "location": node.location,
            "latitude": float(node.latitude),
            "longitude": float(node.longitude),
            "latest_reading": {
                "timestamp": latest.timestamp.isoformat(),
                "battery": latest.battery,
                "rssi": latest.rssi
            },
            "pollutants": {
                "aqi": latest.aqi,
                "pm25": latest.pm2_5,
                "pm10": latest.pm10,
                "temperature": latest.temperature,
                "humidity": latest.humidity
            },
            "aqi_history": []
        }
        
        status = node.status or 'unregistered'
        if status in nodes_data:
            nodes_data[status].append(node_dict)
    
    return JsonResponse(nodes_data)
```

### URL Registration:
```python
# AppEnviroNode/urls.py
from django.urls import path
from . import views

app_name = 'app'

urlpatterns = [
    # ... existing patterns ...
    
    # Map API endpoints
    path('api/nodes/live/', views.api_nodes_live, name='api_nodes_live'),
    path('api/nodes/24h/', views.api_nodes_24h, name='api_nodes_24h'),
    path('api/nodes/viewport/', views.api_nodes_viewport, name='api_nodes_viewport'),
]
```

---

## Performance Optimization: Optional AQI History

The frontend will only use the **last 24 points** of `aqi_history`. You can optimize by:

1. **Don't send it at all** (cleanest option):
   ```python
   "aqi_history": []  # Empty array
   ```

2. **Send only last 24 points**:
   ```python
   # Get hourly averages for last 24 hours
   from django.db.models.functions import TruncHour
   
   hourly_readings = node.readings.filter(
       timestamp__gte=start_time
   ).annotate(
       hour=TruncHour('timestamp')
   ).values('hour').annotate(
       avg_aqi=Avg('aqi')
   ).order_by('hour')[:24]
   
   node_dict['aqi_history'] = [
       r['avg_aqi'] for r in hourly_readings
   ]
   ```

---

## Testing Endpoints

```bash
# Test live endpoint
curl "http://localhost:8000/api/nodes/live/"

# Test 24h endpoint
curl "http://localhost:8000/api/nodes/24h/"

# Test viewport endpoint with bounding box
curl "http://localhost:8000/api/nodes/viewport/?bbox=14.56,121.01,14.57,121.03&timeframe=live"
```

---

## Error Handling

All endpoints should return standardized error responses:

```json
{
  "error": "Descriptive error message",
  "status": 400,
  "details": "Optional additional context"
}
```

Common scenarios:
- ❌ Invalid bbox format → 400
- ❌ Missing required parameter → 400
- ❌ No nodes found → 200 (with empty arrays)
- ❌ Database error → 500

---

## Database Query Optimization

For large datasets, add database indexes:

```python
class SensorNode(models.Model):
    # ... existing fields ...
    
    class Meta:
        indexes = [
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['is_active', 'status']),
        ]

class SensorReading(models.Model):
    # ... existing fields ...
    
    class Meta:
        indexes = [
            models.Index(fields=['node', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]
```

---

## Frontend Integration Test

Once endpoints are deployed, test in browser console:

```javascript
// Check live endpoint
fetch('/api/nodes/live/')
  .then(r => r.json())
  .then(data => console.log('Live nodes:', data))

// Check viewport endpoint
fetch('/api/nodes/viewport/?bbox=14.56,121.01,14.57,121.03')
  .then(r => r.json())
  .then(data => console.log('Viewport nodes:', data))

// Verify deduplication is working
// Should see no duplicate IDs in console
```

---

## Monitoring & Alerting

Recommended metrics to track:
- API response time: Should be <500ms for live/24h, <300ms for viewport
- Error rate: Should be <1%
- Node count per request: Should vary 0-200 depending on viewport
- Fetch frequency: Should see only 1 request per 300ms (due to debouncing)

---

**Last Updated:** May 4, 2026  
**Status:** Ready for Implementation
