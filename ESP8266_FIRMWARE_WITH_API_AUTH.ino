#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h> // Added for HTTPS
#include <Wire.h>
#include <Adafruit_BME680.h>
#include <SoftwareSerial.h>

// ================= GLOBALS =================
bool pmsConnected = false;
bool bmeConnected = false;
int anomalyCount = 0;
unsigned long lastLatencyMs = 0; // Tracks HTTP POST latency

// State tracking for debug logs
String lastSysStatus = "booting";

// ================= LED PINS =================
const int RED_LED = D5;
const int YELLOW_LED = D6;
const int GREEN_LED = D7;

// ================= WIFI =================
const char* ssid = "CAMERING";
const char* password = "B@byB0ss23";

// ✅ SECURITY FIX: Django API endpoint (HTTPS)
const char* serverUrl = "https://environode.onrender.com/api/sensor-data/";

// ✅ SECURITY FIX: API Key Authentication (replaces MAC-only auth)
// Generate this via Django admin after creating SensorNode
const char* API_KEY = "YOUR_API_KEY_HERE";  // ← Replace with actual key from admin

// ================= TIMING & WATCHDOG =================
unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL = 10000; // Send every 10 seconds

unsigned long lastPmsReadTime = 0;
const unsigned long PMS_TIMEOUT = 60000; // Reboot if no PMS data for 60 seconds

// BME680 Watchdog & Healing Variables
unsigned long lastBmeSuccessTime = 0;
const unsigned long BME_TIMEOUT = 60000; // Reboot if no BME data for 60 sec
int bmeFailCount = 0;

// ================= PMS5003 =================
SoftwareSerial pmsSerial(D2, D1); // RX, TX

struct PMSData {
  uint16_t pm1_0;
  uint16_t pm2_5;
  uint16_t pm10;
  bool hasValidData = false;
};

PMSData pms;

// PMS5003 Smoothing Variables
const int PMS_HISTORY_SIZE = 3;
uint16_t pm1History[PMS_HISTORY_SIZE] = {0};
uint16_t pm25History[PMS_HISTORY_SIZE] = {0};
uint16_t pm10History[PMS_HISTORY_SIZE] = {0};
int pmsHistoryIndex = 0;
int pmsHistoryCount = 0;

// ================= BME680 =================
Adafruit_BME680 bme;

// ================= HELPER: LED CONTROL =================
void updateLEDs(uint16_t pm25) {
  if (pm25 <= 12) {
    digitalWrite(GREEN_LED, HIGH);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, LOW);
  } 
  else if (pm25 > 12 && pm25 <= 35) {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, HIGH);
    digitalWrite(RED_LED, LOW);
  } 
  else {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, HIGH);
  }
}

void updateLEDsSafe() {
  if (!pmsConnected) {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(RED_LED, LOW);
    digitalWrite(YELLOW_LED, millis() % 1000 < 500);
    return;
  }
  updateLEDs(pms.pm2_5);
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  Serial.println("\n\n--- System Booting (API Auth Enabled) ---");

  // Validate API key is set
  if (strcmp(API_KEY, "YOUR_API_KEY_HERE") == 0) {
    Serial.println("ERROR: API_KEY not configured! Set it in firmware code.");
    while(1) {
      digitalWrite(RED_LED, HIGH);
      delay(100);
      digitalWrite(RED_LED, LOW);
      delay(100);
    }
  }

  pinMode(RED_LED, OUTPUT);
  pinMode(YELLOW_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);

  digitalWrite(RED_LED, HIGH);
  delay(2000);
  digitalWrite(RED_LED, LOW);
  
  digitalWrite(RED_LED, HIGH); digitalWrite(YELLOW_LED, HIGH); digitalWrite(GREEN_LED, HIGH);
  delay(500);
  digitalWrite(RED_LED, LOW); digitalWrite(YELLOW_LED, LOW); digitalWrite(GREEN_LED, LOW);

  pmsSerial.begin(9600);
  Serial.println("DEBUG: PMS5003 Serial Started");

  Wire.begin(D4, D3);

  if (!bme.begin(0x76) && !bme.begin(0x77)) {
    Serial.println("ERROR: BME680 NOT FOUND!");
    bmeConnected = false;
  } else {
    Serial.println("DEBUG: BME680 FOUND");
    bmeConnected = true;
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setGasHeater(320, 150);
  }

  connectWiFi();
  
  lastPmsReadTime = millis();
  lastBmeSuccessTime = millis();
}

// ================= HELPER: WIFI =================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  
  Serial.print("DEBUG: Connecting to WiFi...");
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nDEBUG: WiFi Connected! IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nERROR: WiFi Connection Failed.");
  }
}

// ================= HELPER: VALIDATION & ANOMALY =================
bool isValidPMS(uint16_t newPm1, uint16_t newPm25, uint16_t newPm10) {
  // 1. Minimum realistic threshold
  if (newPm25 <= 2) {
    Serial.println("DEBUG (Validation): PMS value unrealistically low (<= 2). Rejected.");
    return false;
  }

  // 2. Edge-level Anomaly Detection (Sudden drop)
  if (pms.hasValidData) {
    if (pms.pm2_5 >= 30 && newPm25 <= 5) {
      anomalyCount++;
      Serial.println("DEBUG (Anomaly): Sudden drop detected! Prev: " + String(pms.pm2_5) + " -> New: " + String(newPm25));
      return false;
    }
  }

  return true;
}

// ================= HELPER: FILTER & STORE =================
void applyPMSFilter(uint16_t newPm1, uint16_t newPm25, uint16_t newPm10) {
  // Existing Spike Rejection Logic
  if (pms.hasValidData) {
    if (abs((int)newPm1 - (int)pms.pm1_0) > 300 ||
        abs((int)newPm25 - (int)pms.pm2_5) > 300 ||
        abs((int)newPm10 - (int)pms.pm10) > 300) {
      Serial.println("WARNING: PMS Data Spike Detected! Ignoring frame.");
      return; 
    }
  }

  pm1History[pmsHistoryIndex] = newPm1;
  pm25History[pmsHistoryIndex] = newPm25;
  pm10History[pmsHistoryIndex] = newPm10;
  
  pmsHistoryIndex = (pmsHistoryIndex + 1) % PMS_HISTORY_SIZE;
  if (pmsHistoryCount < PMS_HISTORY_SIZE) {
    pmsHistoryCount++;
  }

  uint32_t sumPm1 = 0, sumPm25 = 0, sumPm10 = 0;
  for (int i = 0; i < pmsHistoryCount; i++) {
    sumPm1 += pm1History[i];
    sumPm25 += pm25History[i];
    sumPm10 += pm10History[i];
  }

  pms.pm1_0 = sumPm1 / pmsHistoryCount;
  pms.pm2_5 = sumPm25 / pmsHistoryCount;
  pms.pm10 = sumPm10 / pmsHistoryCount;

  pms.hasValidData = true;
  pmsConnected = true;
  lastPmsReadTime = millis();
}

// ================= HELPER: READ PMS =================
void processPMS() {
  while (pmsSerial.available() > 0) {
    if (pmsSerial.peek() != 0x42) {
      pmsSerial.read(); 
      continue;
    }
    
    if (pmsSerial.available() >= 32) {
      uint8_t buffer[32];
      pmsSerial.readBytes(buffer, 32);

      if (buffer[0] == 0x42 && buffer[1] == 0x4D) {
        uint16_t calculatedChecksum = 0;
        for (int i = 0; i < 30; i++) {
          calculatedChecksum += buffer[i];
        }
        
        uint16_t receivedChecksum = (buffer[30] << 8) | buffer[31];

        if (calculatedChecksum == receivedChecksum) {
          uint16_t rawPm1_0 = (buffer[4] << 8) | buffer[5];
          uint16_t rawPm2_5 = (buffer[6] << 8) | buffer[7];
          uint16_t rawPm10  = (buffer[8] << 8) | buffer[9];

          if (rawPm1_0 <= 500 && rawPm2_5 <= 500 && rawPm10 <= 500) {
            // Apply Validation BEFORE Filter
            if (isValidPMS(rawPm1_0, rawPm2_5, rawPm10)) {
              applyPMSFilter(rawPm1_0, rawPm2_5, rawPm10);
            }
          } else {
            Serial.println("WARNING: PMS Data out of bounds (>500). Discarding.");
          }
        } else {
          Serial.println("ERROR: PMS Checksum Mismatch!");
        }
      }
    } else {
      break; 
    }
  }
}

// ================= LOOP =================
void loop() {
  processPMS();

  // Connection timeout check
  if (millis() - lastPmsReadTime > 10000) {
    pmsConnected = false;
  }

  // Hardware watchdog timers
  if (millis() - lastPmsReadTime > PMS_TIMEOUT) {
    Serial.println("\nCRITICAL ERROR: No valid data from PMS5003 for 60 seconds!");
    ESP.restart(); 
  }

  if (millis() - lastBmeSuccessTime > BME_TIMEOUT) {
    Serial.println("\nCRITICAL ERROR: BME680 unresponsive for 60 seconds!");
    ESP.restart();
  }

  updateLEDsSafe();

  if (millis() - lastSendTime >= SEND_INTERVAL) {
    lastSendTime = millis();
    connectWiFi();

    // ================= BME680 READ =================
    bool bmeOK = false;
    for (int i = 0; i < 3; i++) {
      if (bme.performReading()) {
        bmeOK = true;
        bmeConnected = true;
        lastBmeSuccessTime = millis(); 
        bmeFailCount = 0;
        break;
      }
      delay(100);
    }

    if (!bmeOK) {
      bmeFailCount++;
      bmeConnected = false;
      if (bmeFailCount >= 3) {
        if (!bme.begin(0x76) && !bme.begin(0x77)) {
          Serial.println("ERROR: BME680 reinit FAILED!");
        } else {
          bme.setTemperatureOversampling(BME680_OS_8X);
          bme.setHumidityOversampling(BME680_OS_2X);
          bme.setPressureOversampling(BME680_OS_4X);
          bme.setGasHeater(320, 150);
          bmeFailCount = 0;
          bmeConnected = true;
        }
      }
    }

    // ================= HEALTH STATUS LOGIC =================
    String pmsStatusStr = (pmsConnected && pms.hasValidData) ? "ok" : "error";
    String bmeStatusStr = bmeConnected ? "ok" : "error";
    String currentSysStatus = "normal";

    if (pmsStatusStr == "error" && bmeStatusStr == "error") {
      currentSysStatus = "critical";
    } else if (pmsStatusStr == "error" || bmeStatusStr == "error") {
      currentSysStatus = "degraded";
    }

    // Debug Status Transitions
    if (currentSysStatus != lastSysStatus) {
      Serial.println("\nDEBUG (Status): System state changed: " + lastSysStatus + " -> " + currentSysStatus);
      lastSysStatus = currentSysStatus;
    }

    // Allocate fallback values
    float temperature = bmeConnected ? bme.temperature : -1.0;
    float humidity = bmeConnected ? bme.humidity : -1.0;
    float pressure = bmeConnected ? (bme.pressure / 100.0) : -1.0; 
    float gas = bmeConnected ? (bme.gas_resistance / 1000.0) : -1.0; 

    // ===== SYSTEM & SENSOR DEBUG OUTPUT =====
    Serial.println("\n===== SYSTEM STATUS [" + String(millis() / 1000) + "s uptime] =====");
    Serial.println("System Health: " + currentSysStatus);
    Serial.println("PMS Status:    " + pmsStatusStr);
    Serial.println("BME Status:    " + bmeStatusStr);
    Serial.println("Anomalies:     " + String(anomalyCount));

    Serial.println("\n===== SENSOR DATA =====");
    Serial.print("PM1.0: "); Serial.println(pmsConnected ? String(pms.pm1_0) : "ERR");
    Serial.print("PM2.5: "); Serial.println(pmsConnected ? String(pms.pm2_5) : "ERR");
    Serial.print("PM10:  "); Serial.println(pmsConnected ? String(pms.pm10) : "ERR");
    Serial.print("Temp:     "); Serial.print(temperature); Serial.println(" °C");
    Serial.print("Humidity: "); Serial.print(humidity); Serial.println(" %");

    // ================= HTTP POST TO DJANGO WITH API KEY AUTH =================
    if (WiFi.status() == WL_CONNECTED) {
      
      // ✅ SECURITY FIX: Use HTTPS + API Key Authentication
      WiFiClientSecure client;
      client.setInsecure(); // Skips certificate validation (OK for development)

      HTTPClient http;
      http.begin(client, serverUrl);
      
      // ✅ SECURITY FIX: Add Authorization header with API key (Issue 2.1)
      String authHeader = "Bearer " + String(API_KEY);
      http.addHeader("Authorization", authHeader);
      http.addHeader("Content-Type", "application/json");

      String json = "";

      // Option A: Full System Failure minimal payload
      if (currentSysStatus == "critical") {
        json = "{";
        json += "\"mac_address\":\"ENVIRONODE_001\",";
        json += "\"system_status\":\"critical\",";
        json += "\"pms_status\":\"error\",";
        json += "\"bme_status\":\"error\",";
        json += "\"error_code\":\"ALL_SENSORS_FAILED\",";
        json += "\"latency_ms\":" + String(lastLatencyMs);
        json += "}";
        Serial.println("WARNING: Sending Critical Failure Payload.");
      } 
      // Partial Failure or Normal operation
      else {
        json = "{";
        json += "\"mac_address\":\"ENVIRONODE_001\",";
        json += "\"pm1_0\":" + String(pmsConnected ? pms.pm1_0 : -1) + ",";
        json += "\"pm2_5\":" + String(pmsConnected ? pms.pm2_5 : -1) + ",";
        json += "\"pm10\":" + String(pmsConnected ? pms.pm10 : -1) + ",";
        json += "\"temperature\":" + String(temperature) + ",";
        json += "\"humidity\":" + String(humidity) + ",";
        json += "\"pressure\":" + String(pressure) + ",";
        json += "\"gas_resistance\":" + String(gas) + ",";
        json += "\"aqi\":0,";
        json += "\"pms_status\":\"" + pmsStatusStr + "\",";
        json += "\"bme_status\":\"" + bmeStatusStr + "\",";
        json += "\"system_status\":\"" + currentSysStatus + "\",";
        json += "\"latency_ms\":" + String(lastLatencyMs);
        json += "}";
      }

      Serial.println("\n===== DJANGO HTTP POST (WITH API AUTH) =====");
      
      // Measure Latency
      unsigned long postStartTime = millis();
      int httpResponseCode = http.POST(json);
      unsigned long postEndTime = millis();
      
      lastLatencyMs = postEndTime - postStartTime; // Store for the NEXT payload

      if (httpResponseCode > 0) {
        String response = http.getString();
        Serial.println("HTTP Response code: " + String(httpResponseCode));
        Serial.println("Server response: " + response);
        Serial.print("Request Latency: ");
        Serial.print(lastLatencyMs);
        Serial.println(" ms");
        
        // Check for 401 (authentication failure)
        if (httpResponseCode == 401) {
          Serial.println("ERROR: Authentication failed! Check API_KEY.");
          digitalWrite(RED_LED, HIGH);
          delay(500);
          digitalWrite(RED_LED, LOW);
        }
      } else {
        Serial.print("Error sending POST, HTTP code: ");
        Serial.println(httpResponseCode);
        Serial.println("Error details: " + http.errorToString(httpResponseCode));
      }

      http.end();
    }
  }
}
