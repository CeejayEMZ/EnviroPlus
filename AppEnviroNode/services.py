"""
Email service module for EnviroNode.
Centralizes all email sending logic for user invitations, password resets, and notifications.
"""

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging
import sys

logger = logging.getLogger(__name__)


class EmailService:
    """
    Centralized email service for EnviroNode.
    Handles user invitations, password resets, and notifications.
    """
    
    DEFAULT_FROM_EMAIL = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@environode.com')
    
    @staticmethod
    def send_user_invite_email(user, activation_link):
        """
        Send invitation email with activation link to a pending user.
        
        Args:
            user: CustomUser instance (pending/inactive)
            activation_link: Full URL to activation page with token
            
        Returns:
            dict: {'success': bool, 'message': str, 'error': str or None}
        """
        try:
            subject = 'EnviroNode - Activate Your Account'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'role': user.get_role_display(),
                'activation_link': activation_link,
                'organization': user.organization or 'EnviroNode',
                'expiration_days': 7,
            }
            
            # Render HTML email
            html_message = render_to_string('AppEnviroNode/email/invite.html', context)
            plain_message = strip_tags(html_message)
            
            # Debug info
            backend = settings.EMAIL_BACKEND
            api_key_status = "SET" if settings.SENDGRID_API_KEY else "NOT SET"
            log_msg = f"📧 Sending invitation to {user.email} via {backend} (API Key: {api_key_status})"
            logger.info(log_msg)
            print(f"✅ {log_msg}", file=sys.stdout)
            
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=EmailService.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"✅ Invitation email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Invitation sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"❌ Failed to send invitation email to {user.email}: {str(e)}"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}", file=sys.stderr)
            
            # Add debugging for SendGrid-specific errors
            if "403" in str(e):
                debug_hint = "This is likely a sender verification issue. Verify your sender email in SendGrid dashboard."
            elif "401" in str(e) or "authentication" in str(e).lower():
                debug_hint = "API key issue. Check SENDGRID_API_KEY in .env file."
            else:
                debug_hint = str(e)
            
            return {
                'success': False,
                'message': None,
                'error': f"{error_msg}\n💡 Debug: {debug_hint}"
            }
    
    @staticmethod
    def send_password_reset_email(user, reset_link):
        """
        Send password reset email with reset link.
        
        Args:
            user: CustomUser instance
            reset_link: Full URL to password reset page with token
            
        Returns:
            dict: {'success': bool, 'message': str, 'error': str or None}
        """
        try:
            subject = 'EnviroNode - Reset Your Password'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'reset_link': reset_link,
                'organization': user.organization or 'EnviroNode',
                'expiration_days': 7,
            }
            
            # Render HTML email
            html_message = render_to_string('AppEnviroNode/email/password_reset.html', context)
            plain_message = strip_tags(html_message)
            
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=EmailService.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Password reset email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Password reset link sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Failed to send password reset email to {user.email}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': None,
                'error': error_msg
            }
    
    @staticmethod
    def send_password_reset_approved_email(user, reset_link):
        """
        Send password reset approval email with reset link.
        
        Args:
            user: CustomUser instance
            reset_link: Full URL to password reset page with token
            
        Returns:
            dict: {'success': bool, 'message': str, 'error': str or None}
        """
        try:
            subject = 'EnviroNode - Password Reset Approved'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'reset_link': reset_link,
                'organization': user.organization or 'EnviroNode',
                'expiration_days': 7,
                'status': 'approved',
            }
            
            # Render HTML email
            html_message = render_to_string('AppEnviroNode/email/password_reset.html', context)
            plain_message = strip_tags(html_message)
            
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=EmailService.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Password reset approved email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Password reset approval sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Failed to send password reset approval email to {user.email}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': None,
                'error': error_msg
            }
    
    @staticmethod
    def send_password_reset_denied_email(user, reason=''):
        """
        Send password reset denial email.
        
        Args:
            user: CustomUser instance
            reason: Reason for denial
            
        Returns:
            dict: {'success': bool, 'message': str, 'error': str or None}
        """
        try:
            subject = 'EnviroNode - Password Reset Request Denied'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'reason': reason,
                'organization': user.organization or 'EnviroNode',
            }
            
            # Simple text message for denial
            message = f"""
Hello {user.first_name or user.username},

Your password reset request has been denied.

{f'Reason: {reason}' if reason else 'Please contact your administrator for more information.'}

If you believe this is a mistake, please contact your system administrator.

Best regards,
EnviroNode Team
            """
            
            # Send email
            send_mail(
                subject=subject,
                message=message,
                from_email=EmailService.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            logger.info(f"Password reset denial email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Password reset denial sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Failed to send password reset denial email to {user.email}: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': None,
                'error': error_msg
            }


# Convenience functions for backward compatibility
def send_user_invite_email(user, activation_link):
    """Wrapper function for EmailService.send_user_invite_email()"""
    result = EmailService.send_user_invite_email(user, activation_link)
    return result['success']


def send_password_reset_email(user, reset_link):
    """Wrapper function for EmailService.send_password_reset_email()"""
    result = EmailService.send_password_reset_email(user, reset_link)
    return result['success']
