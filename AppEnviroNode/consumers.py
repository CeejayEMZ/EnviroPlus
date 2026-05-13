"""
consumers.py — EnviroNode WebSocket Consumer
Handles ws://127.0.0.1:8000/ws/realtime/

Sends 5 message types the frontend expects:
  - node_update     → updates node table row + live AQI label
  - alert_update    → adds alert to the active alerts panel
  - event_update    → adds entry to the live event feed
  - chart_update    → updates the aggregated AQI chart
  - system_status   → updates the system status banner
"""

import json
import asyncio
from datetime import timedelta

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.db.models import Avg


class RealtimeConsumer(AsyncWebsocketConsumer):

    # ── Connection lifecycle ───────────────────────────────────────────────

    async def connect(self):
        self.room_group_name = 'realtime'
        self.subscribed_channels = []
        self._broadcast_task = None

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

        # Start the broadcast loop
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    async def disconnect(self, close_code):
        if self._broadcast_task:
            self._broadcast_task.cancel()

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # ── Messages from frontend ─────────────────────────────────────────────

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')

            if msg_type == 'subscribe':
                self.subscribed_channels = data.get('channels', [])

        except (json.JSONDecodeError, KeyError):
            pass

    # ── Broadcast loop — runs every 10 seconds ─────────────────────────────

    async def _broadcast_loop(self):
        """Push live data to the frontend every 10 seconds."""
        try:
            while True:
                await self._push_all()
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def _push_all(self):
        """Fetch data and send all message types."""
        nodes_data   = await self._get_nodes_data()
        alerts_data  = await self._get_active_alerts()
        system_data  = await self._get_system_status()
        chart_data   = await self._get_chart_values()

        # 1. system_status — always first so the banner updates
        await self.send(text_data=json.dumps({
            'type':         'system_status',
            'status':       system_data['status'],
            'active_count': system_data['active_count'],
            'total_count':  system_data['total_count'],
            'avg_aqi':      system_data['avg_aqi'],
        }))

        # 2. node_update — one message per node
        for node in nodes_data:
            await self.send(text_data=json.dumps({
                'type':         'node_update',
                'node':         node,
                'active_count': system_data['active_count'],
                'total_count':  system_data['total_count'],
            }))

        # 3. alert_update — one message per active alert
        for alert in alerts_data:
            await self.send(text_data=json.dumps({
                'type':  'alert_update',
                'alert': alert,
            }))

        # 4. chart_update — aggregated AQI values for the chart
        await self.send(text_data=json.dumps({
            'type':         'chart_update',
            'chart_values': chart_data,
            'live_aqi':     system_data['avg_aqi'],
        }))

        # 5. event_update — system ready / heartbeat event
        await self.send(text_data=json.dumps({
            'type': 'event_update',
            'event': {
                'title':    'Data Sync',
                'message':  f"{system_data['active_count']} active node(s) reporting.',",
                'severity': 'info',
                'timestamp': timezone.now().isoformat(),
            }
        }))

    # ── Channel layer message handlers (group_send) ────────────────────────

    async def realtime_node_update(self, event):
        await self.send(text_data=json.dumps(event['data']))

    async def realtime_alert_update(self, event):
        await self.send(text_data=json.dumps(event['data']))

    async def realtime_system_status(self, event):
        await self.send(text_data=json.dumps(event['data']))

    # ── Database queries (sync → async) ───────────────────────────────────

    @database_sync_to_async
    def _get_nodes_data(self):
        from AppEnviroNode.models import SensorNode, SensorReading

        nodes = SensorNode.objects.all().prefetch_related('readings')
        result = []

        for node in nodes:
            latest = node.readings.order_by('-timestamp').first()
            result.append({
                'name':      node.name,
                'location':  node.location or '',
                'status':    node.status,
                'mac':       node.mac_address,
                'aqi':       latest.aqi       if latest else None,
                'pm2_5':     latest.pm2_5     if latest else None,
                'pm10':      latest.pm10      if latest else None,
                'temperature': latest.temperature if latest else None,
                'humidity':  latest.humidity  if latest else None,
                'timestamp': latest.timestamp.isoformat() if latest and latest.timestamp else None,
            })

        return result

    @database_sync_to_async
    def _get_active_alerts(self):
        from AppEnviroNode.models import Alert

        alerts = Alert.objects.filter(
            is_active=True
        ).select_related('node').order_by('-triggered_at')[:10]

        result = []
        for alert in alerts:
            result.append({
                'title':       alert.title,
                'description': alert.description,
                'severity':    alert.severity,
                'node_name':   alert.node.name if alert.node else 'System',
                'triggered_at': alert.triggered_at.isoformat(),
            })

        return result

    @database_sync_to_async
    def _get_system_status(self):
        from AppEnviroNode.models import SensorNode, SensorReading

        total   = SensorNode.objects.count()
        active  = SensorNode.objects.filter(status='active').count()

        # avg AQI from latest reading of each active node
        five_min_ago = timezone.now() - timedelta(minutes=5)
        avg_result = SensorReading.objects.filter(
            timestamp__gte=five_min_ago,
            aqi__isnull=False
        ).aggregate(avg=Avg('aqi'))

        avg_aqi = round(avg_result['avg'], 1) if avg_result['avg'] else None

        # Determine status string
        if active == 0:
            status = 'CRITICAL'
        elif (total - active) > 0 or (avg_aqi and avg_aqi > 150):
            status = 'CRITICAL'
        elif avg_aqi and avg_aqi > 100:
            status = 'WARNING'
        else:
            status = 'GOOD'

        return {
            'status':       status,
            'active_count': active,
            'total_count':  total,
            'avg_aqi':      avg_aqi,
        }

    @database_sync_to_async
    def _get_chart_values(self):
        """Last 30 AQI readings for the aggregated chart."""
        from AppEnviroNode.models import SensorReading

        readings = (SensorReading.objects
                    .filter(aqi__isnull=False)
                    .order_by('-timestamp')[:30]
                    .values_list('aqi', flat=True))

        return list(reversed(readings))
