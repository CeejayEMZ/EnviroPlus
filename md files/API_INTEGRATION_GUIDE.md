# EnviroNode API Integration Guide

**Version**: 1.1.0  
**Endpoint**: `POST /api/sensor-data/`  
**Authentication**: None (CSRF exempt for IoT devices)

---

## 📋 Request Format

### Minimal Request (Backward Compatible)

**Old Format - Still Works**:
```bash
curl -X POST http://localhost:8000/api/sensor-data/ \
  -H "Content-Type: application/json" \
  -d '{
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "pm2_5": 25.3,
    "temperature": 28.5
  }'
```

### Complete Request (With New Features)

**New Format - Recommended**:
```bash
curl -X POST http://localhost:8000/api/sensor-data/ \
  -H "Content-Type: application/json" \
  -d '{
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
    "latency_ms": 150
  }'
```

---

## 📤 Response Format

### Success Response (201)

```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 2969,
  "node_status": "active",
  "aqi": 79,
  "aqi_level": "moderate",
  "system_status": "normal",
  "is_anomaly": false,
  "validation_issues": []
}
```

### Error Response (400/500)

```json
{
  "success": false,
  "message": "Invalid JSON: Expecting value: line 1 column 1"
}
```

---

## 📊 Field Reference

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `mac_address` | string | MAC address of ESP8266 | `"AA:BB:CC:DD:EE:FF"` |

### Optional Sensor Fields

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `pm1_0` | float | 0-500 µg/m³ | PM1.0 particulate matter |
| `pm2_5` | float | 0-500 µg/m³ | PM2.5 particulate matter |
| `pm10` | float | 0-600 µg/m³ | PM10 particulate matter |
| `temperature` | float | -10 to 60°C | Temperature from BME680 |
| `humidity` | float | 0-100% | Humidity from BME680 |
| `pressure` | float | Any | Pressure in hPa |
| `gas_resistance` | float | Any | Gas resistance in kΩ |

### NEW: System Health Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `system_status` | string | `normal`, `degraded`, `critical` | Overall ESP8266 health |
| `pms_status` | string | `ok`, `error` | PMS5003 sensor status |
| `bme_status` | string | `ok`, `error` | BME680 sensor status |
| `latency_ms` | integer | 0-10000 | Request latency in ms |

---

## 🔍 Example Scenarios

### Example 1: Normal Operation

**Request**:
```json
{
  "mac_address": "DE:AD:BE:EF:00:01",
  "pm1_0": 8.2,
  "pm2_5": 22.5,
  "pm10": 38.9,
  "temperature": 27.3,
  "humidity": 62.5,
  "pressure": 1013.5,
  "gas_resistance": 150.2,
  "system_status": "normal",
  "pms_status": "ok",
  "bme_status": "ok",
  "latency_ms": 120
}
```

**Response** (201):
```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 3042,
  "node_status": "active",
  "aqi": 71,
  "aqi_level": "moderate",
  "system_status": "normal",
  "is_anomaly": false,
  "validation_issues": []
}
```

**Database Impact**:
- ✅ SensorReading created
- ✅ AQI calculated
- ✅ Node set to active
- ✅ SystemLog: normal reading event

---

### Example 2: PMS Sensor Error

**Request**:
```json
{
  "mac_address": "DE:AD:BE:EF:00:02",
  "pm2_5": 0,
  "temperature": 28.1,
  "humidity": 65.0,
  "pms_status": "error",
  "bme_status": "ok",
  "system_status": "normal"
}
```

**Response** (201):
```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 3043,
  "node_status": "active",
  "aqi": null,
  "aqi_level": null,
  "system_status": "normal",
  "is_anomaly": false,
  "validation_issues": [
    "PMS5003 sensor error: PM values marked unreliable"
  ]
}
```

**Database Impact**:
- ✅ SensorReading created
- 🚨 Alert: "Sensor Failure: PMS5003"
- 🚨 SystemLog: sensor_failure event
- ⚠️ PM values not trusted (validation failed)

---

### Example 3: Critical System Status

**Request**:
```json
{
  "mac_address": "DE:AD:BE:EF:00:03",
  "system_status": "critical"
}
```

**Response** (201):
```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 3044,
  "node_status": "inactive",
  "aqi": null,
  "aqi_level": null,
  "system_status": "critical",
  "is_anomaly": false,
  "validation_issues": [
    "System critical: sensor data not trusted"
  ]
}
```

**Database Impact**:
- ✅ SensorReading created but marked untrusted
- 🚨 Node set to INACTIVE
- 🚨 Alert: "Critical System Failure"
- 🚨 SystemLog: system critical event (severity=hazardous)

---

### Example 4: Anomalous Reading (Spike)

**Scenario**: Previous reading was 30 µg/m³, current is 95 µg/m³ (spike of 65)

**Request**:
```json
{
  "mac_address": "DE:AD:BE:EF:00:04",
  "pm2_5": 95.0,
  "temperature": 28.5,
  "system_status": "normal",
  "pms_status": "ok",
  "bme_status": "ok"
}
```

**Response** (201):
```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 3045,
  "node_status": "active",
  "aqi": 171,
  "aqi_level": "unhealthy_sensitive",
  "system_status": "normal",
  "is_anomaly": true,
  "validation_issues": []
}
```

**Database Impact**:
- ✅ SensorReading created
- ✅ is_anomaly = TRUE
- 🚨 Alert: "Anomalous Sensor Reading" with spike details
- 🚨 SystemLog: anomaly_detected event
- ⚠️ Spike indicates possible sensor malfunction or real air quality change

---

### Example 5: High Latency

**Request** (with 3.5 second latency):
```json
{
  "mac_address": "DE:AD:BE:EF:00:05",
  "pm2_5": 35.0,
  "temperature": 26.8,
  "latency_ms": 3500
}
```

**Response** (201):
```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 3046,
  "node_status": "active",
  "aqi": 99,
  "aqi_level": "moderate",
  "system_status": "normal",
  "is_anomaly": false,
  "validation_issues": []
}
```

**Database Impact**:
- ✅ SensorReading created with latency_ms=3500
- ⚠️ SystemLog: high_latency event (severity=warning)
- 📊 Indicates network/communication issues

---

### Example 6: Out of Range Temperature

**Request** (temperature too high - likely invalid):
```json
{
  "mac_address": "DE:AD:BE:EF:00:06",
  "pm2_5": 25.0,
  "temperature": 75.0,
  "humidity": 120.0
}
```

**Response** (201):
```json
{
  "success": true,
  "message": "Reading recorded successfully",
  "reading_id": 3047,
  "node_status": "active",
  "aqi": 79,
  "aqi_level": "moderate",
  "system_status": "normal",
  "is_anomaly": false,
  "validation_issues": [
    "Temperature out of realistic range (-10 to 60°C): 75.0",
    "Humidity out of valid range (0-100%): 120.0"
  ]
}
```

**Database Impact**:
- ✅ SensorReading created
- ⚠️ Temperature and humidity marked as untrustworthy
- 📝 Validation issues logged for investigation

---

## 🔧 Arduino/ESP8266 Example Code

### Simple Request (Backward Compatible)

```cpp
#include <ArduinoJson.h>
#include <HTTPClient.h>

void sendSensorData(float pm2_5, float temperature) {
  HTTPClient http;
  
  DynamicJsonDocument doc(200);
  doc["mac_address"] = "AA:BB:CC:DD:EE:FF";
  doc["pm2_5"] = pm2_5;
  doc["temperature"] = temperature;
  
  String payload;
  serializeJson(doc, payload);
  
  http.begin("http://192.168.1.100:8000/api/sensor-data/");
  http.addHeader("Content-Type", "application/json");
  
  int httpCode = http.POST(payload);
  String response = http.getString();
  
  Serial.println("Response: " + response);
  http.end();
}
```

### Enhanced Request (With New Fields)

```cpp
void sendSensorDataEnhanced(
  float pm2_5, 
  float temperature,
  String systemStatus,
  String pmsStatus,
  int latency_ms
) {
  HTTPClient http;
  unsigned long startTime = millis();
  
  DynamicJsonDocument doc(300);
  doc["mac_address"] = "AA:BB:CC:DD:EE:FF";
  doc["pm2_5"] = pm2_5;
  doc["temperature"] = temperature;
  doc["system_status"] = systemStatus;    // NEW
  doc["pms_status"] = pmsStatus;          // NEW
  doc["latency_ms"] = latency_ms;         // NEW
  
  String payload;
  serializeJson(doc, payload);
  
  http.begin("http://192.168.1.100:8000/api/sensor-data/");
  http.addHeader("Content-Type", "application/json");
  
  int httpCode = http.POST(payload);
  
  unsigned long responseTime = millis() - startTime;
  Serial.print("HTTP Code: ");
  Serial.println(httpCode);
  Serial.print("Response Time: ");
  Serial.print(responseTime);
  Serial.println("ms");
  
  if (httpCode == 201) {
    DynamicJsonDocument responseDoc(300);
    DeserializationError error = deserializeJson(responseDoc, http.getString());
    
    if (!error) {
      boolean isAnomaly = responseDoc["is_anomaly"];
      int aqi = responseDoc["aqi"];
      
      Serial.print("AQI: ");
      Serial.println(aqi);
      Serial.print("Anomaly: ");
      Serial.println(isAnomaly ? "YES" : "NO");
    }
  }
  
  http.end();
}
```

### With Error Handling

```cpp
void sendSensorDataWithErrorHandling(
  float pm2_5,
  float temperature,
  float humidity,
  String systemStatus,
  String pmsStatus,
  String bmeStatus
) {
  // Validate sensor values before sending
  if (isnan(pm2_5) || pm2_5 < 0 || pm2_5 > 500) {
    Serial.println("ERROR: Invalid PM2.5 value");
    return;  // Don't send invalid data
  }
  
  if (isnan(temperature) || temperature < -10 || temperature > 60) {
    Serial.println("ERROR: Invalid temperature");
    return;
  }
  
  HTTPClient http;
  unsigned long startTime = millis();
  
  DynamicJsonDocument doc(350);
  doc["mac_address"] = "AA:BB:CC:DD:EE:FF";
  doc["pm2_5"] = pm2_5;
  doc["temperature"] = temperature;
  doc["humidity"] = humidity;
  doc["system_status"] = systemStatus;
  doc["pms_status"] = pmsStatus;
  doc["bme_status"] = bmeStatus;
  doc["latency_ms"] = millis() - startTime;
  
  String payload;
  serializeJson(doc, payload);
  
  try {
    http.setConnectTimeout(5000);
    http.setTimeout(10000);
    
    http.begin("http://192.168.1.100:8000/api/sensor-data/");
    http.addHeader("Content-Type", "application/json");
    
    int httpCode = http.POST(payload);
    
    if (httpCode == 201) {
      Serial.println("✓ Reading sent successfully");
    } else if (httpCode == 400) {
      Serial.println("✗ Bad request: " + http.getString());
    } else if (httpCode == 500) {
      Serial.println("✗ Server error: " + http.getString());
    } else {
      Serial.print("✗ HTTP Error: ");
      Serial.println(httpCode);
    }
  } catch (Exception e) {
    Serial.println("✗ Request failed: " + String(e.message()));
  }
  
  http.end();
}
```

---

## 🧪 Testing the API

### cURL Tests

**Test 1: Backward Compatibility**
```bash
curl -X POST http://localhost:8000/api/sensor-data/ \
  -H "Content-Type: application/json" \
  -d '{"mac_address":"TEST:001","pm2_5":25}'
```

**Test 2: With System Status**
```bash
curl -X POST http://localhost:8000/api/sensor-data/ \
  -H "Content-Type: application/json" \
  -d '{
    "mac_address":"TEST:002",
    "pm2_5":25,
    "system_status":"degraded",
    "pms_status":"ok",
    "bme_status":"ok"
  }'
```

**Test 3: Critical Status**
```bash
curl -X POST http://localhost:8000/api/sensor-data/ \
  -H "Content-Type: application/json" \
  -d '{
    "mac_address":"TEST:003",
    "system_status":"critical"
  }'
```

**Test 4: Missing MAC Address (Should Fail)**
```bash
curl -X POST http://localhost:8000/api/sensor-data/ \
  -H "Content-Type: application/json" \
  -d '{"pm2_5":25}'
```

---

## 📈 Database Queries for Monitoring

### Check Anomalies
```sql
SELECT * FROM sensor_reading 
WHERE is_anomaly = TRUE 
ORDER BY timestamp DESC 
LIMIT 10;
```

### Check Sensor Errors
```sql
SELECT * FROM alert 
WHERE title LIKE 'Sensor Failure%' 
  AND is_active = TRUE 
ORDER BY triggered_at DESC;
```

### Check Critical Events
```sql
SELECT * FROM systemlog 
WHERE event_type = 'system' 
  AND severity = 'hazardous' 
ORDER BY created_at DESC;
```

### Latency Warnings
```sql
SELECT * FROM systemlog 
WHERE event_type = 'high_latency' 
ORDER BY created_at DESC 
LIMIT 20;
```

---

## ✅ Verification Checklist

After implementing, verify:

- [ ] Old API requests work (backward compatibility)
- [ ] New fields accepted and stored
- [ ] Anomalies detected and alerted
- [ ] Sensor errors create alerts
- [ ] Critical status sets node to inactive
- [ ] Latency tracked and logged
- [ ] All events logged to SystemLog
- [ ] Database migration applied
- [ ] Tests passing

---

**For Support**: Check logs with `[API DEBUG]` prefix for troubleshooting.
