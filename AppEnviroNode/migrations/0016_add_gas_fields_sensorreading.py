# Generated migration to add gas quality fields
# This migration adds gas_quality, pollution_source, gas_alert, and mq135_raw fields
# to SensorReading model to fix NOT NULL constraint violations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('AppEnviroNode', '0015_alter_sensornodeapikey_api_key'),
    ]

    operations = [
        # Add gas quality field with default value
        migrations.AddField(
            model_name='sensorreading',
            name='gas_quality',
            field=models.CharField(
                choices=[
                    ('normal', 'Normal'),
                    ('good', 'Good'),
                    ('moderate', 'Moderate'),
                    ('poor', 'Poor'),
                    ('critical', 'Critical'),
                    ('unknown', 'Unknown'),
                ],
                default='normal',
                help_text='Computed gas quality from MQ135 sensor or BME680 gas resistance',
                max_length=20,
            ),
        ),
        # Add pollution source field with default value
        migrations.AddField(
            model_name='sensorreading',
            name='pollution_source',
            field=models.CharField(
                default='unknown',
                help_text='Inferred pollution source (e.g., traffic, industrial, biomass, unknown)',
                max_length=50,
            ),
        ),
        # Add gas alert field with default False
        migrations.AddField(
            model_name='sensorreading',
            name='gas_alert',
            field=models.BooleanField(
                default=False,
                help_text='Gas quality alert triggered (high pollution detected)',
            ),
        ),
        # Add raw MQ135 value field (nullable for backward compatibility)
        migrations.AddField(
            model_name='sensorreading',
            name='mq135_raw',
            field=models.IntegerField(
                blank=True,
                help_text='Raw MQ135 sensor value (0-1024) or -1 if unavailable',
                null=True,
            ),
        ),
    ]
