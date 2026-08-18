"""
Utility functions for environmental monitoring.
Includes AQI (Air Quality Index) calculations based on PM2.5.
"""


def calculate_aqi(pm2_5):
    """
    Calculate Air Quality Index (AQI) from PM2.5 concentration (µg/m³).
    Uses WHO/EPA standard AQI calculation method.
    
    Args:
        pm2_5 (float): PM2.5 concentration in µg/m³
        
    Returns:
        tuple: (aqi_score, aqi_level)
            - aqi_score: Integer between 0-500
            - aqi_level: String ('good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous')
    """
    if pm2_5 is None:
        return None, None
    
    # AQI Breakpoints for PM2.5 (µg/m³) - based on EPA standard
    # Format: (PM2.5_low, PM2.5_high, AQI_low, AQI_high, category)
    breakpoints = [
        (0, 12.0, 0, 50, 'good'),
        (12.1, 35.4, 51, 100, 'moderate'),
        (35.5, 55.4, 101, 150, 'unhealthy_sensitive'),
        (55.5, 150.4, 151, 200, 'unhealthy'),
        (150.5, 250.4, 201, 300, 'very_unhealthy'),
        (250.5, 500.0, 301, 500, 'hazardous'),
    ]
    
    # Clamp PM2.5 value
    pm2_5 = max(0, min(pm2_5, 500.0))
    
    for pm_low, pm_high, aqi_low, aqi_high, category in breakpoints:
        if pm_low <= pm2_5 <= pm_high:
            # Linear interpolation to calculate exact AQI
            aqi = ((aqi_high - aqi_low) / (pm_high - pm_low)) * (pm2_5 - pm_low) + aqi_low
            
            # Round to nearest integer
            aqi_score = round(aqi)
            
            return aqi_score, category
    
    # Fallback (shouldn't reach here)
    return 500, 'hazardous'


def get_aqi_category(aqi):
    """
    Get AQI category from AQI score.
    
    Args:
        aqi (float): AQI score
        
    Returns:
        str: Category ('good', 'moderate', 'unhealthy_sensitive', etc)
    """
    if aqi is None:
        return 'unknown'
    
    aqi = float(aqi)
    if aqi <= 50:
        return 'good'
    elif aqi <= 100:
        return 'moderate'
    elif aqi <= 150:
        return 'unhealthy_sensitive'
    elif aqi <= 200:
        return 'unhealthy'
    elif aqi <= 300:
        return 'very_unhealthy'
    else:
        return 'hazardous'


def get_aqi_health_advice(aqi_level):
    """
    Get health advice based on AQI level.
    
    Args:
        aqi_level (str): AQI category level
        
    Returns:
        str: Health advice message
    """
    advice_map = {
        'good': 'Air quality is satisfactory, and air pollution poses little or no risk.',
        'moderate': 'Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution.',
        'unhealthy_sensitive': 'Members of sensitive groups (children, elderly, people with respiratory or heart conditions) may experience health effects.',
        'unhealthy': 'Some members of the general public may begin to experience health effects; members of sensitive groups may experience more serious health effects.',
        'very_unhealthy': 'Health alert: The risk of health effects is increased for everyone.',
        'hazardous': 'Health warning of emergency conditions: The entire population is more likely to be affected.',
    }
    
    return advice_map.get(aqi_level, 'Unknown air quality level')


def calculate_gas_quality(mq135_raw=None, gas_resistance=None):
    """
    Calculate gas quality from MQ135 raw sensor value or BME680 gas resistance.
    
    MQ135 Sensor:
    - Raw value 0-1024 (analog reading)
    - Lower values = higher pollution (lower resistance)
    - -1 or None = sensor unavailable
    
    BME680 Gas Resistance:
    - Measured in kΩ
    - Lower values = higher pollution (lower air quality)
    
    Returns:
        tuple: (gas_quality_level, pollution_source, gas_alert)
            - gas_quality_level: 'normal', 'good', 'moderate', 'poor', 'critical', 'unknown'
            - pollution_source: 'traffic', 'industrial', 'biomass', 'unknown'
            - gas_alert: True if critical, False otherwise
    """
    import logging
    logger = logging.getLogger('enviroplus')
    
    # Defensive fallback: treat None/0 as "no reading available"
    if mq135_raw is None:
        mq135_raw = -1
    if mq135_raw < 0:
        mq135_raw = -1
    
    # Log incoming values for debugging
    logger.debug(f"[Gas Calc] mq135_raw={mq135_raw}, gas_resistance={gas_resistance}")
    
    # Default: no gas data available
    if mq135_raw == -1 and (gas_resistance is None or gas_resistance <= 0):
        logger.debug("[Gas Calc] No gas data available, using defaults")
        return 'normal', 'unknown', False
    
    # Prefer MQ135 if available
    if mq135_raw > 0:
        # MQ135 calibration: 
        # 0-200: Very high pollution (critical)
        # 200-400: High pollution (poor)
        # 400-600: Moderate pollution (moderate)
        # 600-800: Good air (good)
        # 800-1024: Very good air (normal)
        
        if mq135_raw < 200:
            quality = 'critical'
            source = 'industrial'
            alert = True
        elif mq135_raw < 400:
            quality = 'poor'
            source = 'traffic'
            alert = True
        elif mq135_raw < 600:
            quality = 'moderate'
            source = 'traffic'
            alert = False
        elif mq135_raw < 800:
            quality = 'good'
            source = 'unknown'
            alert = False
        else:
            quality = 'normal'
            source = 'unknown'
            alert = False
        
        logger.debug(f"[Gas Calc] Using MQ135: quality={quality}, source={source}, alert={alert}")
        return quality, source, alert
    
    # Fallback to BME680 gas resistance
    if gas_resistance is not None and gas_resistance > 0:
        # Gas resistance calibration (kΩ):
        # 0-5: Very high pollution (critical)
        # 5-10: High pollution (poor)
        # 10-20: Moderate pollution (moderate)
        # 20-50: Good air (good)
        # 50+: Very good air (normal)
        
        if gas_resistance < 5:
            quality = 'critical'
            source = 'industrial'
            alert = True
        elif gas_resistance < 10:
            quality = 'poor'
            source = 'traffic'
            alert = True
        elif gas_resistance < 20:
            quality = 'moderate'
            source = 'traffic'
            alert = False
        elif gas_resistance < 50:
            quality = 'good'
            source = 'unknown'
            alert = False
        else:
            quality = 'normal'
            source = 'unknown'
            alert = False
        
        logger.debug(f"[Gas Calc] Using gas_resistance: quality={quality}, source={source}, alert={alert}")
        return quality, source, alert
    
    # Final fallback
    logger.debug("[Gas Calc] No valid gas data, using defaults")
    return 'normal', 'unknown', False


def infer_pollution_source(aqi_level, gas_quality, pm2_5=None, pm10=None, temperature=None, humidity=None):
    """
    Infer pollution source based on AQI level and gas quality measurements.
    
    Args:
        aqi_level: AQI category from PM measurements
        gas_quality: Gas quality level
        pm2_5: PM2.5 concentration
        pm10: PM10 concentration
        temperature: Temperature (°C)
        humidity: Humidity (%)
    
    Returns:
        str: Inferred pollution source ('traffic', 'industrial', 'biomass', 'unknown')
    """
    import logging
    logger = logging.getLogger('enviroplus')
    
    # If gas measurement is poor/critical, likely to be industrial or traffic
    if gas_quality in ['critical', 'poor']:
        # Check PM2.5/PM10 ratio to distinguish
        if pm2_5 is not None and pm10 is not None and pm10 > 0:
            ratio = pm2_5 / pm10
            if ratio > 0.5:
                logger.debug(f"[Pollution Source] High PM2.5/PM10 ratio ({ratio:.2f}) suggests traffic")
                return 'traffic'
            else:
                logger.debug(f"[Pollution Source] Low PM2.5/PM10 ratio ({ratio:.2f}) suggests industrial or biomass")
                return 'industrial'
        
        # Default to traffic if PM ratio unclear
        logger.debug("[Pollution Source] Poor gas quality, defaulting to traffic")
        return 'traffic'
    
    # Moderate pollution might be biomass (seasonal burning)
    if gas_quality == 'moderate' and temperature is not None and humidity is not None:
        # Biomass burning often occurs in warm, dry conditions
        if temperature > 25 and humidity < 60:
            logger.debug("[Pollution Source] Warm, dry conditions suggest possible biomass burning")
            return 'biomass'
    
    logger.debug("[Pollution Source] No clear source detected, marking as unknown")
    return 'unknown'


def get_pm2_5_category(pm2_5):
    """
    Quick lookup for PM2.5 category without calculating full AQI.
    
    Args:
        pm2_5 (float): PM2.5 concentration in µg/m³
        
    Returns:
        str: Category name
    """
    if pm2_5 is None:
        return None
    
    if pm2_5 <= 12.0:
        return 'good'
    elif pm2_5 <= 35.4:
        return 'moderate'
    elif pm2_5 <= 55.4:
        return 'unhealthy_sensitive'
    elif pm2_5 <= 150.4:
        return 'unhealthy'
    elif pm2_5 <= 250.4:
        return 'very_unhealthy'
    else:
        return 'hazardous'


# ============================================================================
# FORECAST & TREND ANALYSIS
# ============================================================================

def calculate_weighted_average(values, weights=None):
    """
    Calculate weighted moving average for trend smoothing.
    
    Args:
        values: List of numeric values
        weights: List of weights (optional, defaults to linear weights)
        
    Returns:
        float: Weighted average
    """
    if not values:
        return None
    
    if weights is None:
        # Linear weights: more recent values weighted higher
        weights = [i + 1 for i in range(len(values))]
    
    total_weight = sum(weights)
    if total_weight == 0:
        return sum(values) / len(values) if values else None
    
    weighted_sum = sum(v * w for v, w in zip(values, weights))
    return weighted_sum / total_weight


def calculate_simple_trend(values, period=3):
    """
    Calculate simple trend direction based on recent values.
    
    Args:
        values: List of numeric values (ordered chronologically)
        period: Number of recent values to compare (default 3)
        
    Returns:
        tuple: (trend_direction, strength)
            - trend_direction: 'up', 'down', or 'stable'
            - strength: Float -1.0 to 1.0 (negative=down, 0=stable, positive=up)
    """
    if not values or len(values) < 2:
        return 'stable', 0.0
    
    # Compare recent period vs previous period
    if len(values) < period * 2:
        # Not enough data, use simple comparison
        recent = values[-1]
        previous = values[0]
    else:
        recent = sum(values[-period:]) / period
        previous = sum(values[-(period*2):-period]) / period
    
    if recent > previous:
        strength = min(1.0, (recent - previous) / max(previous, 1))
        return 'up', strength
    elif recent < previous:
        strength = min(1.0, (previous - recent) / max(previous, 1))
        return 'down', -strength
    else:
        return 'stable', 0.0


def predict_next_day_aqi(historical_readings, confidence_threshold=0.6):
    """
    Predict AQI for next day using historical trend analysis.
    
    Args:
        historical_readings: List of (timestamp, aqi) tuples
        confidence_threshold: Minimum data confidence (0-1)
        
    Returns:
        dict: {
            'predicted_aqi': float,
            'confidence': float (0-1),
            'trend': 'up' | 'down' | 'stable',
            'range': {'min': float, 'max': float}
        }
    """
    if not historical_readings:
        return {
            'predicted_aqi': None,
            'confidence': 0.0,
            'trend': 'unknown',
            'range': {'min': None, 'max': None}
        }
    
    # Extract AQI values only
    aqi_values = [aqi for _, aqi in historical_readings if aqi is not None]
    
    if not aqi_values:
        return {
            'predicted_aqi': None,
            'confidence': 0.0,
            'trend': 'unknown',
            'range': {'min': None, 'max': None}
        }
    
    # Calculate basic statistics
    avg_aqi = sum(aqi_values) / len(aqi_values)
    min_aqi = min(aqi_values)
    max_aqi = max(aqi_values)
    
    # Determine trend
    trend, strength = calculate_simple_trend(aqi_values)
    
    # Predict next value using weighted average
    recent_weight = calculate_weighted_average(aqi_values[-5:] if len(aqi_values) >= 5 else aqi_values)
    
    # If trend is strong, adjust prediction
    if trend == 'up' and strength > 0.3:
        predicted = recent_weight * 1.05 if recent_weight else avg_aqi * 1.05
    elif trend == 'down' and strength < -0.3:
        predicted = recent_weight * 0.95 if recent_weight else avg_aqi * 0.95
    else:
        predicted = recent_weight if recent_weight else avg_aqi
    
    # Clamp prediction to reasonable range (don't predict outside observed extremes)
    predicted = max(min_aqi, min(max_aqi * 1.1, predicted))
    
    # Calculate confidence based on data consistency
    if len(aqi_values) < 5:
        confidence = 0.4  # Low confidence with few data points
    elif max_aqi - min_aqi < 20:
        confidence = 0.9  # High confidence when readings are stable
    else:
        confidence = 0.6  # Medium confidence with variation
    
    return {
        'predicted_aqi': round(predicted, 1),
        'confidence': round(confidence, 2),
        'trend': trend,
        'range': {'min': min_aqi, 'max': max_aqi}
    }


# ============================================================================
# ANOMALY DETECTION & VALIDATION (NEW FUNCTIONS)
# ============================================================================

def detect_pm_anomaly(current_pm2_5, previous_pm2_5, anomaly_threshold=50):
    """
    Detect anomalies in PM2.5 readings by comparing to previous reading.
    
    Anomaly Rules:
    - Sudden spike/drop > threshold (default 50 µg/m³)
    - Unrealistic transitions (e.g., 70 → 0 in one reading)
    - Persistent low values when typically higher
    
    Args:
        current_pm2_5 (float): Current PM2.5 value
        previous_pm2_5 (float): Previous PM2.5 value
        anomaly_threshold (int): Threshold for anomaly detection (default 50)
        
    Returns:
        tuple: (is_anomaly, reason)
            - is_anomaly: Boolean indicating if anomaly detected
            - reason: String describing the anomaly
    """
    # Handle None values
    if current_pm2_5 is None or previous_pm2_5 is None:
        return False, None
    
    # Check for sudden spikes or drops
    diff = abs(current_pm2_5 - previous_pm2_5)
    
    if diff > anomaly_threshold:
        # Determine if it's a spike or drop
        if current_pm2_5 > previous_pm2_5:
            reason = f"Anomalous PM2.5 spike detected: {previous_pm2_5:.1f} → {current_pm2_5:.1f} µg/m³ (Δ {diff:.1f})"
        else:
            reason = f"Anomalous PM2.5 drop detected: {previous_pm2_5:.1f} → {current_pm2_5:.1f} µg/m³ (Δ {diff:.1f})"
        
        return True, reason
    
    # Check for unrealistic drops to near-zero
    if previous_pm2_5 > 40 and current_pm2_5 < 5:
        reason = f"Unrealistic PM2.5 drop to near-zero: {previous_pm2_5:.1f} → {current_pm2_5:.1f} µg/m³"
        return True, reason
    
    return False, None


def validate_sensor_data(data):
    """
    Validate incoming sensor data from ESP8266.
    
    Validation Rules:
    - If system_status == 'critical': Don't trust sensor values
    - If pms_status == 'error': Ignore/mark PM values invalid
    - If bme_status == 'error': Temperature/humidity may be unreliable
    - Check for realistic value ranges
    
    Args:
        data (dict): Raw sensor data from ESP8266
        
    Returns:
        dict: {
            'is_valid': bool,
            'issues': list of validation issues (empty if valid),
            'trusted_fields': dict with only trusted field values,
            'system_status': 'normal' | 'degraded' | 'critical'
        }
    """
    validation_result = {
        'is_valid': True,
        'issues': [],
        'trusted_fields': {},
        'system_status': data.get('system_status', 'normal'),
    }
    
    system_status = data.get('system_status', 'normal')
    pms_status = data.get('pms_status', 'ok')
    bme_status = data.get('bme_status', 'ok')
    
    # If system is in critical state, mark entire reading as untrusted
    if system_status == 'critical':
        validation_result['is_valid'] = False
        validation_result['issues'].append("System critical: sensor data not trusted")
        return validation_result
    
    # Check PMS5003 (particulate matter)
    pm_values_trusted = pms_status != 'error'
    if not pm_values_trusted:
        validation_result['issues'].append("PMS5003 sensor error: PM values marked unreliable")
    
    # Check BME680 (environmental)
    bme_values_trusted = bme_status != 'error'
    if not bme_values_trusted:
        validation_result['issues'].append("BME680 sensor error: temperature/humidity marked unreliable")
    
    # Validate individual field ranges
    if pm_values_trusted:
        pm2_5 = data.get('pm2_5')
        if pm2_5 is not None:
            if pm2_5 < 0 or pm2_5 > 500:
                validation_result['issues'].append(f"PM2.5 out of valid range (0-500): {pm2_5}")
                pm_values_trusted = False
            else:
                validation_result['trusted_fields']['pm2_5'] = pm2_5
        
        pm10 = data.get('pm10')
        if pm10 is not None:
            if pm10 < 0 or pm10 > 600:
                validation_result['issues'].append(f"PM10 out of valid range (0-600): {pm10}")
                pm_values_trusted = False
            else:
                validation_result['trusted_fields']['pm10'] = pm10
    
    if bme_values_trusted:
        temp = data.get('temperature')
        if temp is not None:
            if temp < -10 or temp > 60:
                validation_result['issues'].append(f"Temperature out of realistic range (-10 to 60°C): {temp}")
                bme_values_trusted = False
            else:
                validation_result['trusted_fields']['temperature'] = temp
        
        humidity = data.get('humidity')
        if humidity is not None:
            if humidity < 0 or humidity > 100:
                validation_result['issues'].append(f"Humidity out of valid range (0-100%): {humidity}")
                bme_values_trusted = False
            else:
                validation_result['trusted_fields']['humidity'] = humidity
    
    # Determine overall validation status
    validation_result['is_valid'] = len(validation_result['issues']) == 0
    
    return validation_result


def check_latency_issue(latency_ms):
    """
    Check if latency indicates a system issue.
    
    Args:
        latency_ms (int): Request latency in milliseconds
        
    Returns:
        tuple: (has_issue, severity, message)
            - has_issue: Boolean
            - severity: 'info', 'warning', 'critical'
            - message: Description
    """
    if latency_ms is None:
        return False, None, None
    
    if latency_ms > 5000:
        return True, 'critical', f"Critical latency detected: {latency_ms}ms (expected < 5000ms)"
    elif latency_ms > 2000:
        return True, 'warning', f"High latency detected: {latency_ms}ms (expected < 2000ms)"
    
    return False, None, None
