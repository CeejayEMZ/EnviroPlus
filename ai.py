# ============================================================
#  ai.py — EnviroNode AI Functions (Groq Integration)
#  Place this file inside: appenvironode/ai.py
#  (same folder as views.py, models.py)
# ============================================================

import os
import json
import requests
from django.conf import settings

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"  # ← fixed: was llama3-8b-8192


def _get_api_key():
    """Read GROQ_API_KEY from environment / Django settings."""
    key = os.environ.get("GROQ_API_KEY", getattr(settings, "GROQ_API_KEY", ""))
    return key

# ── Public EnviroAI chat ─────────────────────────────────────
def ask_enviro_ai(user_message: str, aqi, aqi_level) -> str:
    """
    Send a user message to Groq together with the current AQI context.
    Returns the AI's reply as a plain string.
    Called by: views.api_enviro_ai_chat
    """
    api_key = _get_api_key()
    if not api_key:
        return "EnviroAI is currently unavailable. Please try again later."

    aqi_info = (
        f"The current Air Quality Index (AQI) in Barangay Pembo is {aqi} ({aqi_level})."
        if aqi is not None
        else "No live AQI data is available at the moment."
    )

    system_content = f"""You are EnviroAI, a friendly and helpful health assistant
for the EnviroNode air quality monitoring system deployed in Barangay Pembo, Taguig City.

{aqi_info}

Your job is to:
- Answer questions about air quality, health effects of pollution, and protective actions.
- Give practical, easy-to-understand advice based on the current AQI.
- Be concise (2-4 sentences max per reply).
- Always base health advice on the current AQI level provided above.
- Do not make up sensor data. If no data is available, say so kindly."""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.7,
        "max_tokens":  300,
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
            timeout=15
        )
        data  = response.json()
        reply = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return reply if reply else "I'm having trouble generating a response. Please try again."
    except Exception as e:
        print(f"Groq error: {e}")
        return "EnviroAI is temporarily unavailable. Please try again in a moment."


# ── Admin AI Insights ────────────────────────────────────────
def generate_ai_insights(sensor_summary: dict) -> dict:
    """
    Generate AI-powered insights for the admin AI Insights page.
    Called by: views.client_ai and views.api_ai_insights
    """
    api_key = _get_api_key()
    if not api_key:
        return {
            "summary": "AI insights unavailable.",
            "recommendations": [],
            "anomalies": [],
            "forecast": "Unavailable."
        }

    user_content = f"""Here is the latest sensor data summary (last 7 days):
- Average AQI: {sensor_summary.get('avg_aqi', 'N/A')}
- Maximum AQI: {sensor_summary.get('max_aqi', 'N/A')}
- Minimum AQI: {sensor_summary.get('min_aqi', 'N/A')}
- Average PM2.5: {sensor_summary.get('avg_pm2_5', 'N/A')} µg/m³
- Average Temperature: {sensor_summary.get('avg_temp', 'N/A')}°C
- Total Readings: {sensor_summary.get('total_readings', 'N/A')}
- Active Nodes: {sensor_summary.get('active_nodes', 'N/A')}
- Inactive Nodes: {sensor_summary.get('inactive_nodes', 'N/A')}
- Critical Alerts: {sensor_summary.get('critical_alerts', 'N/A')}

Respond ONLY with a valid JSON object (no markdown, no backticks) with these exact keys:
{{
  "summary": "2-3 sentence overall summary of air quality conditions",
  "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"],
  "anomalies": ["anomaly or pattern 1", "anomaly or pattern 2"],
  "forecast": "1-2 sentence short-term forecast or trend prediction"
}}"""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are an environmental data analyst AI for EnviroNode, an IoT air quality monitoring system in Barangay Pembo, Taguig City, Philippines. Always respond with valid JSON only."
            },
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.4,
        "max_tokens":  600,
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
            timeout=20
        )
        data = response.json()
        raw  = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "{}")
            .strip()
        )
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {
            "summary": "Unable to generate insights at this time.",
            "recommendations": ["Check sensor connectivity.", "Review recent alerts."],
            "anomalies": [],
            "forecast": "Forecast unavailable."
        }
