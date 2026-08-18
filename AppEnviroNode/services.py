"""
Email service module for EnviroPlus.
Centralizes all email sending logic for user invitations, password resets, and notifications.
"""

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging
import sys
import socket

logger = logging.getLogger(__name__)


class EmailService:
    """
    Centralized email service for EnviroPlus.
    Handles user invitations, password resets, and notifications.
    """
    
    DEFAULT_FROM_EMAIL = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@enviroplus.com')
    
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
            # Validate email config before attempting to send
            smtp_user = getattr(settings, 'EMAIL_HOST_USER', '').strip()
            smtp_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '').strip()
            email_host = getattr(settings, 'EMAIL_HOST', '')
            email_port = getattr(settings, 'EMAIL_PORT', 587)
            
            if not smtp_user or not smtp_pass:
                error_msg = 'Brevo SMTP credentials not configured in environment (BREVO_SMTP_USER, BREVO_SMTP_PASSWORD)'
                logger.error(f"Email config invalid: {error_msg}")
                raise ValueError(error_msg)
            
            subject = 'EnviroPlus - Activate Your Account'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'role': user.get_role_display(),
                'activation_link': activation_link,
                'organization': user.organization or 'EnviroPlus',
                'expiration_days': 7,
            }
            
            # Render HTML email with exception handling
            try:
                html_message = render_to_string('AppEnviroNode/email/invite.html', context)
            except Exception as template_err:
                raise ValueError(f'Failed to render invite template: {str(template_err)}')
            
            plain_message = strip_tags(html_message)
            
            logger.info(f"📧 Sending invitation email to {user.email} via {email_host}:{email_port}")

            # Send email with improved error handling
            try:
                send_mail(
                    subject=subject,
                    message=plain_message,
                    from_email=EmailService.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_message,
                    fail_silently=False,
                )
            except (socket.timeout, socket.gaierror) as net_err:
                error_msg = f'Network error connecting to Brevo SMTP ({email_host}): {str(net_err)}'
                logger.error(error_msg, exc_info=True)
                raise ValueError(error_msg)
            except Exception as smtp_err:
                error_msg = f'Brevo SMTP error: {str(smtp_err)}'
                logger.error(error_msg, exc_info=True)
                raise ValueError(error_msg)
            
            logger.info(f"✅ Invitation email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Invitation sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"❌ Failed to send invitation email to {user.email}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            print(f"ERROR: {error_msg}", file=sys.stderr)
            
            return {
                'success': False,
                'message': None,
                'error': error_msg
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
            # Validate email config
            smtp_user = getattr(settings, 'EMAIL_HOST_USER', '').strip()
            smtp_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '').strip()
            email_host = getattr(settings, 'EMAIL_HOST', '')
            email_port = getattr(settings, 'EMAIL_PORT', 587)
            
            if not smtp_user or not smtp_pass:
                error_msg = 'Brevo SMTP credentials not configured in environment (BREVO_SMTP_USER, BREVO_SMTP_PASSWORD)'
                logger.error(f"Email config invalid: {error_msg}")
                raise ValueError(error_msg)
            
            subject = 'EnviroPlus - Reset Your Password'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'reset_link': reset_link,
                'organization': user.organization or 'EnviroPlus',
                'expiration_days': 7,
            }
            
            # Render HTML email with exception handling
            try:
                html_message = render_to_string('AppEnviroNode/email/password_reset.html', context)
            except Exception as template_err:
                raise ValueError(f'Failed to render password reset template: {str(template_err)}')
            
            plain_message = strip_tags(html_message)
            
            logger.info(f"📧 Sending password reset email to {user.email} via {email_host}:{email_port}")
            
            # Send email with improved error handling
            try:
                send_mail(
                    subject=subject,
                    message=plain_message,
                    from_email=EmailService.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_message,
                    fail_silently=False,
                )
            except (socket.timeout, socket.gaierror) as net_err:
                error_msg = f'Network error connecting to Brevo SMTP ({email_host}): {str(net_err)}'
                logger.error(error_msg, exc_info=True)
                raise ValueError(error_msg)
            except Exception as smtp_err:
                error_msg = f'Brevo SMTP error: {str(smtp_err)}'
                logger.error(error_msg, exc_info=True)
                raise ValueError(error_msg)
            
            logger.info(f"Password reset email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Password reset link sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Failed to send password reset email to {user.email}: {str(e)}"
            logger.error(error_msg, exc_info=True)
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
            # Validate email config
            smtp_user = getattr(settings, 'EMAIL_HOST_USER', '')
            smtp_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
            if not smtp_user or not smtp_pass:
                raise ValueError('Brevo SMTP credentials not configured (EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)')
            
            subject = 'EnviroPlus - Password Reset Approved'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'reset_link': reset_link,
                'organization': user.organization or 'EnviroPlus',
                'expiration_days': 7,
                'status': 'approved',
            }
            
            # Render HTML email with exception handling
            try:
                html_message = render_to_string('AppEnviroNode/email/password_reset.html', context)
            except Exception as template_err:
                raise ValueError(f'Failed to render password reset template: {str(template_err)}')
            
            plain_message = strip_tags(html_message)
            
            # Send email with improved error handling
            try:
                send_mail(
                    subject=subject,
                    message=plain_message,
                    from_email=EmailService.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_message,
                    fail_silently=False,
                )
            except Exception as smtp_err:
                raise ValueError(f'Brevo SMTP error: {str(smtp_err)}')
            
            logger.info(f"Password reset approved email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Password reset approval sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Failed to send password reset approval email to {user.email}: {str(e)}"
            logger.error(error_msg, exc_info=True)
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
            # Validate email config
            smtp_user = getattr(settings, 'EMAIL_HOST_USER', '')
            smtp_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
            if not smtp_user or not smtp_pass:
                raise ValueError('Brevo SMTP credentials not configured (EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)')
            
            subject = 'EnviroPlus - Password Reset Request Denied'
            
            context = {
                'first_name': user.first_name or user.username,
                'email': user.email,
                'reason': reason,
                'organization': user.organization or 'EnviroPlus',
            }
            
            # Simple text message for denial
            message = f"""
Hello {user.first_name or user.username},

Your password reset request has been denied.

{f'Reason: {reason}' if reason else 'Please contact your administrator for more information.'}

If you believe this is a mistake, please contact your system administrator.

Best regards,
EnviroPlus Team
            """
            
            # Send email with improved error handling
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=EmailService.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as smtp_err:
                raise ValueError(f'Brevo SMTP error: {str(smtp_err)}')
            
            logger.info(f"Password reset denial email sent to {user.email} (user_id: {user.id})")
            
            return {
                'success': True,
                'message': f'Password reset denial sent to {user.email}',
                'error': None
            }
            
        except Exception as e:
            error_msg = f"Failed to send password reset denial email to {user.email}: {str(e)}"
            logger.error(error_msg, exc_info=True)
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
