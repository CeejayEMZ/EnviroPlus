"""
Django signals for automatic logging and event creation.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import SensorReading, SystemLog, SensorNode


@receiver(post_save, sender=SensorReading)
def create_system_log_on_reading(sender, instance, created, **kwargs):
    if kwargs.get('raw', False):
        return
    
    if created:
        # Determine severity based on AQI level
        severity = instance.aqi_level or 'moderate'
        
        # Create log message based on sensor type
        sensor_type = 'aqi'
        message = f"Node {instance.node.name} recorded AQI {instance.aqi}"
        
        SystemLog.objects.create(
            node=instance.node,
            reading=instance,
            event_type='reading',
            severity=severity,
            message=message,
            value=instance.aqi,
            sensor_type=sensor_type,
            created_at=instance.timestamp
        )


@receiver(post_save, sender=SensorNode)
def log_node_status_change(sender, instance, created, **kwargs):
    """
    Create a SystemLog when a node comes online/offline.
    Skip during fixture loading (when raw=True).
    """
    # Skip if loading from a fixture (Django passes raw=True)
    if kwargs.get('raw', False):
        return
    
    if not created:
        # Check if status changed
        try:
            old_instance = SensorNode.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                if instance.status == 'active':
                    event_type = 'device_online'
                    message = f"Node {instance.name} came online"
                elif instance.status == 'inactive':
                    event_type = 'device_offline'
                    message = f"Node {instance.name} went offline"
                else:
                    return
                
                SystemLog.objects.create(
                    node=instance,
                    event_type=event_type,
                    severity='good' if event_type == 'device_online' else 'unhealthy',
                    message=message
                )
        except SensorNode.DoesNotExist:
            pass
