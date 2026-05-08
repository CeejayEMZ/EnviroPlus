# EnviroNode Realtime Dashboard - Deployment & Testing Guide

**Deployment Date:** May 8, 2026  
**Version:** 2.0 (Production)

---

## 📋 PRE-DEPLOYMENT CHECKLIST

- [ ] Backup database (`db.sqlite3`)
- [ ] Backup current `views.py` and `realtime.html`
- [ ] Review changes in `REALTIME_REFACTORING_SUMMARY.md`
- [ ] Ensure 3+ days of sensor readings exist in database
- [ ] Test in development environment first
- [ ] Clear browser cache before testing

---

## 🚀 DEPLOYMENT STEPS

### Step 1: Update Python Files

```bash
# Verify files were updated
git diff AppEnviroNode/views.py
git diff AppEnviroNode/utils.py
```

**Updated:**
- ✅ `AppEnviroNode/views.py` - New api_realtime_data() and api_daily_forecast()
- ✅ `AppEnviroNode/utils.py` - Added forecast utilities
- ✅ `AppEnviroNode/templates/AppEnviroNode/main/realtime.html` - Enhanced JS

### Step 2: Verify Django Settings

```python
# MainEnviroNode/settings.py - ensure cache is configured
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'TIMEOUT': 300,
    }
}

# If you want to use Redis (optional but recommended for production):
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'TIMEOUT': 300,
    }
}
```

### Step 3: Run Tests

```bash
# Run Django tests
python manage.py test

# Run custom validation script (after server is running)
python test_realtime_api.py
```

### Step 4: Collect Static Files (if on production)

```bash
python manage.py collectstatic --noinput
```

### Step 5: Restart Django Server

```bash
# Development
python manage.py runserver

# Production (gunicorn example)
gunicorn MainEnviroNode.wsgi:application --bind 0.0.0.0:8000
```

---

## 🧪 TESTING PROCEDURE

### Test 1: API Endpoint Response Validation

**URL:** `http://localhost:8000/api/realtime-data/`

**Expected Response:**
```json
{
  "success": true,
  "summary": {
    "avg_aqi": 75.5,
    "latest_aqi": 82.0,
    "latest_node_name": "Market Avenue",
    "latest_node_location": "Market District",
    "total_readings": 450,
    "active_nodes": 8,
    "range_label": "Last 7 days"
  },
  "chart_data": [...],
  "location_label": "Location: Market District"
}
```

**Test Steps:**
1. Open browser Developer Tools (F12)
2. Go to Network tab
3. Visit realtime dashboard
4. Look for `api/realtime-data/` request
5. Verify response contains all required fields
6. Check `location_label` is NOT hardcoded "Signal Village"

### Test 2: Forecast API Response

**URL:** `http://localhost:8000/api/daily-forecast/`

**Expected Behavior:**
- Returns 7-day forecast if 3+ days of data exist
- If insufficient data: returns error message "Insufficient historical data"
- Never shows hardcoded/sample forecast data

**Test Steps:**
1. Open browser console
2. Fetch forecast:
   ```javascript
   fetch('/api/daily-forecast/').then(r => r.json()).then(d => console.log(d))
   ```
3. Verify `is_predicted: true` for future dates
4. Verify `is_predicted: false` for past dates
5. Check confidence scores (0-1)

### Test 3: Realtime Polling

**Test Steps:**
1. Open realtime dashboard: `/realtime/`
2. Open Network tab (F12)
3. Watch for `api/realtime-data/` requests every 15 seconds
4. Change filters (node, date range)
5. Verify AQI badge updates
6. Verify location name updates dynamically
7. Hide the tab → polling should stop
8. Show the tab again → polling should resume

**Verify Polling State:**
```javascript
// In browser console:
console.log(isPolling)  // should be true
console.log(pollingInterval)  // should be non-null
```

### Test 4: Chart Rendering

**Test Steps:**
1. Load realtime dashboard
2. Verify 3 charts render:
   - AQI Trend (line chart)
   - PM2.5 / PM10 (bar chart)
   - Temperature (line chart)
3. Change time range (24h, 7d, 30d)
4. Verify charts update without full page reload
5. Custom date range should work
6. Check mobile responsive (resize browser)

### Test 5: Forecast Card Rendering

**Test Steps:**
1. Scroll to "7-Day Forecast" section
2. Verify 7 cards render
3. Look for "Today" badge on current day
4. Check for "*" indicator on predicted days
5. Verify AQI color coding matches badges:
   - Good: Green
   - Moderate: Yellow
   - Unhealthy: Orange
   - etc.
6. Verify PM2.5 values displayed
7. Refresh forecast button should work

### Test 6: Error Handling

**Simulate Error:**
```javascript
// In browser console, break the API temporarily
window.apiRealtimeDataUrl = '/api/broken/'

// Then trigger reload
loadRealtimeData()

// Should show error gracefully, not crash UI
```

**Expected:**
- Error logged to console
- UI remains functional
- Polling continues after error
- Next successful fetch resumes normal operation

### Test 7: Filter Integration

**Test Filter Changes:**
1. Select specific node → verify location updates
2. Select location group → verify location label updates
3. Select "All Nodes" → verify "Location: All Nodes"
4. Custom date range → verify label shows dates
5. Each change should trigger data refresh
6. Charts and summary should update

### Test 8: Performance Check

**In Browser DevTools:**
1. Open Performance tab
2. Start recording
3. Trigger filter change
4. Stop recording
5. **Targets:**
   - API fetch: < 500ms
   - Chart update: < 200ms
   - DOM update: < 100ms
   - Memory: Should not grow > 50MB over 5 minutes of polling

### Test 9: Mobile Responsiveness

**Test on Mobile (or resize browser):**
1. Realtime filters should stack vertically
2. Charts should resize
3. Forecast cards should be horizontal scrollable
4. Live monitoring bar should be readable
5. All buttons should be tap-able (min 44px)

---

## 🐛 TROUBLESHOOTING

### Issue: "No forecast data available"
**Cause:** Less than 3 days of sensor readings  
**Solution:** 
- Check database has data: `SELECT COUNT(*) FROM AppEnviroNode_sensorreading;`
- If empty, run: `python manage.py generate_historical_data --days=14`

### Issue: Location shows "Unknown Location"
**Cause:** Sensor nodes don't have location field set  
**Solution:**
- Admin panel → Sensor Nodes
- Edit each node and set "location" field
- Restart dashboard

### Issue: Polling not starting
**Cause:** JavaScript error preventing initialization  
**Solution:**
- Check browser console for errors
- Verify realtime.html compiled correctly
- Ensure Chart.js is loaded
- Clear browser cache

### Issue: Charts showing old data
**Cause:** Cache not invalidating  
**Solution:**
```python
# Django shell
from django.views.decorators.cache import cache_clear
cache.clear()
```

### Issue: "Location: Signal Village" still showing
**Cause:** Old code still in production  
**Solution:**
- Verify `realtime.html` was updated
- Clear browser cache (Ctrl+Shift+Del)
- Hard refresh (Ctrl+F5)

### Issue: API returns 500 error
**Cause:** Query error or missing field  
**Solution:**
```python
# Check Django logs for full error
tail -f logs/django.log

# Or temporarily enable debug
DEBUG = True  # in settings.py
```

---

## ✅ VALIDATION CHECKLIST

After deployment, verify:

- [ ] Realtime dashboard loads without errors
- [ ] API response includes `location_label` field
- [ ] Location name is NOT "Signal Village" (hardcoded)
- [ ] Live monitoring badge updates every ~15 seconds
- [ ] Forecast shows real data (not sample/fake)
- [ ] Charts render correctly
- [ ] Filters work (node, date, location)
- [ ] Custom date range validation works
- [ ] Mobile view is responsive
- [ ] Console has no JS errors
- [ ] Performance is acceptable (< 500ms API calls)

---

## 📊 MONITORING

### Key Metrics to Watch

**API Performance:**
```bash
# Check average response time
curl -w "Time: %{time_total}s\n" http://localhost:8000/api/realtime-data/
```

**Database Queries:**
```python
# Django Debug Toolbar (if installed)
# Shows query count and execution time
```

**Caching Effectiveness:**
```python
# Monitor cache hits/misses
from django.core.cache import cache
print(cache.get('forecast_cache'))
```

---

## 🔄 ROLLBACK PLAN

If issues occur:

1. **Quick Rollback:**
   ```bash
   git revert HEAD
   python manage.py runserver
   ```

2. **Full Rollback:**
   ```bash
   git checkout HEAD~1 AppEnviroNode/views.py
   git checkout HEAD~1 AppEnviroNode/utils.py
   git checkout HEAD~1 AppEnviroNode/templates/AppEnviroNode/main/realtime.html
   python manage.py runserver
   ```

3. **Restore Database Backup:**
   ```bash
   cp db.sqlite3.backup db.sqlite3
   python manage.py migrate
   ```

---

## 📝 DOCUMENTATION

For detailed technical information, see:
- **Main Summary:** `REALTIME_REFACTORING_SUMMARY.md`
- **API Details:** View docstrings in `AppEnviroNode/views.py`
- **Utility Functions:** View `AppEnviroNode/utils.py`

---

## 🎉 SUCCESS INDICATORS

Your deployment is successful when:

✅ **User Experience:**
- Dashboard loads quickly (< 1s)
- Live AQI badge updates every 15 seconds
- Location name shows actual node location (not "Signal Village")
- Forecast shows real predictions (no hardcoded data)

✅ **Technical:**
- No console errors
- API calls complete in < 500ms
- Database queries optimized (< 5 queries per request)
- Memory usage stable over time

✅ **Data Quality:**
- Forecast confidence shows real scores (0-1)
- Predicted days marked with "*"
- Charts match actual data trends

---

## 📞 SUPPORT

If you encounter issues:

1. **Check Logs:**
   ```bash
   tail -f logs/django.log
   cat logs/error.log
   ```

2. **Run Validation:**
   ```bash
   python test_realtime_api.py
   ```

3. **Test Manually:**
   ```javascript
   // In browser console
   fetch('/api/realtime-data/').then(r => r.json()).then(d => console.log(d))
   ```

4. **Debug Polling:**
   ```javascript
   // Check polling status
   console.log('Is polling:', isPolling)
   console.log('Last fetch:', lastFetchTime)
   console.log('Abort controller:', currentAbortController)
   ```

---

**Deployment Complete! 🚀**

Monitor the system for 24-48 hours to ensure stability.
