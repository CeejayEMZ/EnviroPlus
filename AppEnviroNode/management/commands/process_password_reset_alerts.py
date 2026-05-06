"""
Management command to process password reset alerts.
Auto-approves pending password reset requests after 5 minutes.
Can be run manually or via cron/APScheduler.

Usage:
    python manage.py process_password_reset_alerts
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from datetime import timedelta
import logging

from AppEnviroNode.models import Alert, CustomUser, SystemLog
from AppEnviroNode.services import EmailService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process password reset alerts: auto-approve after 5 minutes, send emails'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(self.style.SUCCESS(f'Processing password reset alerts (dry_run={dry_run})'))
        
        # Find pending password reset requests that should be auto-approved
        now = timezone.now()
        pending_alerts = Alert.objects.filter(
            alert_type='password_reset_request',
            status='pending',
            auto_approval_time__lte=now,
        )
        
        count = pending_alerts.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING('No pending password reset alerts to process'))
            return
        
        self.stdout.write(self.style.WARNING(f'Found {count} alert(s) to auto-approve'))
        
        for alert in pending_alerts:
            try:
                user = alert.user
                token = alert.password_reset_token
                uid = alert.password_reset_uid
                
                if not dry_run:
                    # Build reset link using FRONTEND_BASE_URL from settings
                    base_url = getattr(settings, 'FRONTEND_BASE_URL', 'http://127.0.0.1:8000')
                    reset_link = f"{base_url}/reset-password/{uid}/{token}/"
                    
                    # Approve the alert
                    alert.status = 'approved'
                    alert.save()
                    
                    # Send password reset email using the same method as manual approval
                    result = EmailService.send_password_reset_email(user, reset_link)
                    
                    if result['success']:
                        # Log the approval
                        SystemLog.objects.create(
                            event_type='admin',
                            message=f'Password reset request auto-approved for user: {user.email} (Alert ID: {alert.id})',
                        )
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✓ Auto-approved and sent reset email to {user.email}'
                            )
                        )
                        logger.info(f"Password reset auto-approved for {user.email} (Alert ID: {alert.id})")
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f'✗ Approved but failed to send email to {user.email}: {result["error"]}'
                            )
                        )
                        logger.error(f"Auto-approval email failed for {user.email}: {result['error']}")
                else:
                    # Dry run - just show what would happen
                    self.stdout.write(
                        self.style.WARNING(
                            f'[DRY RUN] Would auto-approve and send reset email to {user.email}'
                        )
                    )
            
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'✗ Error processing alert {alert.id}: {str(e)}'
                    )
                )
                logger.error(f"Error processing password reset alert {alert.id}: {str(e)}")
        
        self.stdout.write(self.style.SUCCESS('Password reset alert processing completed'))
