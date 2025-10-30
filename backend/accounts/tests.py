
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import UserRoles

User = get_user_model()

class UserTestCase(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(
            username='testuser',
            password='testpassword',
            role=UserRoles.AGENT
        )
        self.assertEqual(user.username, 'testuser')
        self.assertTrue(user.check_password('testpassword'))
        self.assertEqual(user.role, UserRoles.AGENT)
