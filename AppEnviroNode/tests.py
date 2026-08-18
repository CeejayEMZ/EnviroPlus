from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()


class LoginLockoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='StrongPass123!',
            role='admin',
            is_approved=True,
            is_active=True,
        )

    def test_login_locks_user_after_five_failed_attempts(self):
        for _ in range(5):
            response = self.client.post(
                reverse('app:login'),
                {'username': 'admin', 'password': 'wrong-password'},
                follow=True,
            )

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked_out())
        self.assertContains(response, 'try again later')

    def test_successful_login_resets_failed_attempts(self):
        self.user.record_failed_login()
        self.user.record_failed_login()
        self.user.record_failed_login()
        self.user.record_failed_login()
        self.assertEqual(self.user.failed_login_attempts, 4)

        self.client.post(
            reverse('app:login'),
            {'username': 'admin', 'password': 'StrongPass123!'},
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)
