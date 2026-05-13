"""
ASGI config for MainEnviroNode project — updated for Django Channels.
Supports both HTTP (Django) and WebSocket (Channels) protocols.
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import AppEnviroNode.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MainEnviroNode.settings')

application = ProtocolTypeRouter({
    # Standard HTTP requests → Django views
    'http': get_asgi_application(),

    # WebSocket requests → Channels consumer
    'websocket': AuthMiddlewareStack(
        URLRouter(
            AppEnviroNode.routing.websocket_urlpatterns
        )
    ),
})
