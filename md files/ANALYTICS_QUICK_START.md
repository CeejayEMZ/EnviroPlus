# 🚀 Analytics System - Quick Start Guide

**For:** Admins using the EnviroNode analytics dashboard  
**Last Updated:** April 15, 2026  
**Status:** Production Ready

---

## 📍 WHERE TO ACCESS

**URL:** `http://localhost:8000/dashboard/analytics/`

or in production: `https://your-domain.com/dashboard/analytics/`

---

## 🎯 QUICK START (3 STEPS)

### Step 1: Open Analytics
Navigate to `/dashboard/analytics/` in your admin panel.

### Step 2: Apply Filters
1. **Filter by Node:** Select a specific sensor node from the dropdown
2. **Filter by Location:** Select a location (Pembo North, Pembo Central, etc.)
3. **Select Time Period:** Click the calendar icon to pick custom dates
4. **Choose Grouping:** Click Daily, Weekly, or Monthly for chart granularity

### Step 3: Review Dashboard
- **Metric Cards:** See average AQI, PM2.5, temperature
- **Line Chart:** Visual trend over selected time period
- **System Insights:** Network health and data freshness

---

## 📊 METRIC CARDS EXPLAINED

### Average AQI
- **What:** Mean Air Quality Index across selected period
- **Range:** Shown in "Range: MIN-MAX" box
- **Color:** Green (Good) to Red (Hazardous)
- **Use:** Assess overall air quality

### Avg PM2.5
- **What:** Mean particulate matter (PM2.5) in µg/m³
- **Health Impact:** Color-coded category below number
- **Use:** Identify pollution concentration

### Avg Temperature
- **What:** Mean temperature in Celsius
- **Time Period:** Reflects currently selected grouping (Daily/Weekly/Monthly)
- **Use:** Correlate with air quality patterns

### Total Readings
- **What:** Count of sensor measurements
- **Freshness:** Shows "Successfully logged" status
- **Use:** Assess data completeness

---

## 📈 CHART INTERPRETATION

### Line Chart
- **X-axis:** Time (Day/Week/Month based on grouping)
- **Y-axis:** AQI score (0-500)
- **Line:** Average AQI trend
- **Shaded Area:** Visual indicator under the line

### Identifying Patterns
- **Spikes:** High pollution periods
- **Dips:** Good air quality periods
- **Flat Line:** Stable conditions

### Example
```
If you see spikes on weekdays but dips on weekends
→ Indicates traffic-related pollution patterns
```

---

## 🎛️ FILTER REFERENCE

### Filter 1: Node
- **What:** Select readings from one specific sensor
- **Options:** List of active nodes (from database)
- **Default:** All nodes
- **Use:** Analyze individual sensor performance

### Filter 2: Location
- **What:** Group data by geographic area
- **Options:** All unique locations in database
- **Default:** All locations
- **Use:** Compare pollution between areas

### Filter 3: Date Range
- **What:** Custom start and end dates
- **Format:** YYYY-MM-DD (e.g., 2026-04-15)
- **Default:** Last 7 days
- **Use:** Analyze specific time periods

### Filter 4: Time Grouping
- **Daily:** One data point per calendar day
- **Weekly:** One data point per week
- **Monthly:** One data point per month
- **Use:** Adjust chart detail level

---

## 🔄 COMMON WORKFLOWS

### Workflow 1: Check Specific Location Health
```
1. Open analytics
2. Select Location: "Pembo North"
3. Select Grouping: "Daily"
4. Review last 7 days
→ See if that location has bad air quality
```

### Workflow 2: Compare Two Sensors
```
1. Note the average AQI for Node 1 (e.g., 75)
2. Change filter to Node 2
3. Note the average AQI (e.g., 45)
→ Node 1's area has worse air quality
```

### Workflow 3: Analyze Weekly Trend
```
1. Select Grouping: "Weekly"
2. Set date range to last 30 days
3. Look at chart line
→ Identify weekly patterns (e.g., weekday vs weekend)
```

### Workflow 4: Check Data Freshness
```
1. Look at "System Insights" section
2. Check "Data Freshness" indicator
→ If > 10 minutes old, nodes may be offline
→ If < 2 minutes old, data is fresh
```

---

## ⚠️ WHAT THE WARNINGS MEAN

### "No Active Nodes Detected"
- **Cause:** All nodes are offline
- **Action:** Check if ESP8266 devices are powered on and connected

### "Data is slightly stale" (5-10 minutes)
- **Cause:** Nodes haven't sent readings recently
- **Action:** Check internet connection, node battery status

### "No data available"
- **Cause:** No readings for selected period/filter
- **Action:** Expand date range or remove filters

### Yellow/Orange AQI
- **Cause:** Moderate to unhealthy air quality
- **Action:** May warrant public advisory or emergency alert

---

## 📱 USING ON MOBILE

The analytics dashboard is **fully responsive**:
- Metric cards stack vertically
- Chart scales to screen width
- Filters remain accessible
- Touch-friendly buttons

**Tip:** Rotate to landscape for better chart view

---

## 🔍 ADVANCED TIPS

### Tip 1: Identify Problem Areas
```
1. Set Location filter to different areas
2. Compare Average AQI values
3. The highest AQI = worst pollution
```

### Tip 2: Detect Sensor Malfunction
```
If one node shows:
- Constant values (never changes)
- No data spikes during high pollution times
→ Sensor may be faulty
→ Consider recalibration or replacement
```

### Tip 3: Export Data for Report
```
1. Click "Download Report" button (feature coming soon)
2. File downloads as CSV with all data
3. Open in Excel to create presentations
```

### Tip 4: Track Seasonal Changes
```
1. Set Grouping: "Monthly"
2. Set date range: Last 12 months
3. Compare monthly averages
→ Identify seasonal pollution patterns
```

---

## 🆘 TROUBLESHOOTING

### Q: Chart not showing
**A:** Wait a moment for page to load. If still nothing, check browser console for errors.

### Q: Filters not working
**A:** Filters auto-apply on change. If no results, try:
- Removing filters (click "All Nodes")
- Expanding date range
- Refreshing page

### Q: "No active nodes" message
**A:** One of:
- No sensors running (power off)
- WiFi disconnected
- Django server not receiving data
- Check `/api/sensor-latest/` endpoint manually

### Q: Numbers seem wrong
**A:** Remember:
- Metrics are AVERAGES (not latest reading)
- Null values ignored (only valid data used)
- Time zones may vary
- Check data freshness indicator

---

## 📞 SUPPORT

**Documentation:**
- Full system docs: [ENVIRO_NODE_SYSTEM_BLUEPRINT.md](./ENVIRO_NODE_SYSTEM_BLUEPRINT.md)
- Implementation details: [ANALYTICS_IMPLEMENTATION_SUMMARY.md](./ANALYTICS_IMPLEMENTATION_SUMMARY.md)
- Changelog: [CHANGELOG.md](./CHANGELOG.md)

**API Access (Developers):**
```
GET /api/analytics/
?node=1&location=Pembo&start_date=2026-04-01&end_date=2026-04-15&grouping=weekly
```

---

## 📋 KEYBOARD SHORTCUTS

| Key | Action |
|-----|--------|
| `Ctrl+Shift+A` | Jump to analytics (if implemented) |
| `Tab` | Navigate between filters |
| `Enter` | Submit date picker |
| `Esc` | Close date picker modal |

---

## ✅ VERIFICATION CHECKLIST

After first use, verify:
- [ ] Filters dropdown populated with real nodes
- [ ] Chart displays data points
- [ ] Metric cards show numbers (not "—")
- [ ] System health shows correct node count
- [ ] Data freshness timer works
- [ ] Date picker opens/closes correctly
- [ ] Time grouping buttons work

---

**Status:** ✅ Ready to Use  
**Last Verified:** April 15, 2026
