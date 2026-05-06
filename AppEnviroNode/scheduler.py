"""
APScheduler configuration for EnviroNode background jobs.
Handles periodic tasks like auto-approving password reset requests.

Install: pip install apscheduler
"""

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)


def process_password_reset_alerts_job():
    """Background job to process password reset alerts."""
    try:
        call_command('process_password_reset_alerts', verbosity=0)
    except Exception as e:
        logger.error(f"Error in password reset alerts background job: {str(e)}")


def start_scheduler():
    """Start the background scheduler for periodic tasks."""
    scheduler = BackgroundScheduler()
    
    # Add job to process password reset alerts every minute
    scheduler.add_job(
        process_password_reset_alerts_job,
        'interval',
        minutes=1,
        id='process_password_reset_alerts',
        name='Process Password Reset Alerts',
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("Background scheduler started")
