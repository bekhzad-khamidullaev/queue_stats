
from django.test import TestCase
from .models import GeneralSettings

class GeneralSettingsTestCase(TestCase):
    def test_create_general_settings(self):
        settings = GeneralSettings.objects.create(
            download_url="http://example.com/download",
            download_token="test_token",
            download_user="test_user",
            download_password="test_password",
            db_host="db_host",
            db_port=3306,
            db_name="db_name",
            db_user="db_user",
            db_password="db_password",
            ami_host="ami_host",
            ami_port=5038,
            ami_user="ami_user",
            ami_password="ami_password",
        )
        self.assertEqual(settings.download_url, "http://example.com/download")
        self.assertEqual(settings.download_token, "test_token")
        self.assertEqual(settings.download_user, "test_user")
        self.assertEqual(settings.download_password, "test_password")
        self.assertEqual(settings.db_host, "db_host")
        self.assertEqual(settings.db_port, 3306)
        self.assertEqual(settings.db_name, "db_name")
        self.assertEqual(settings.db_user, "db_user")
        self.assertEqual(settings.db_password, "db_password")
        self.assertEqual(settings.ami_host, "ami_host")
        self.assertEqual(settings.ami_port, 5038)
        self.assertEqual(settings.ami_user, "ami_user")
        self.assertEqual(settings.ami_password, "ami_password")

    def test_update_general_settings(self):
        settings = GeneralSettings.objects.create(
            download_url="http://example.com/download",
            download_token="test_token",
            download_user="test_user",
            download_password="test_password",
            db_host="db_host",
            db_port=3306,
            db_name="db_name",
            db_user="db_user",
            db_password="db_password",
            ami_host="ami_host",
            ami_port=5038,
            ami_user="ami_user",
            ami_password="ami_password",
        )
        settings.download_url = "http://updated.com/download"
        settings.save()
        updated_settings = GeneralSettings.objects.get(pk=settings.pk)
        self.assertEqual(updated_settings.download_url, "http://updated.com/download")
