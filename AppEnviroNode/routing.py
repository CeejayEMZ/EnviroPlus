"""
routing.py — EnviroNode WebSocket URL routing
Maps ws://127.0.0.1:8000/ws/realtime/ to RealtimeConsumer
"""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/realtime/$', consumers.RealtimeConsumer.as_asgi()),
]
