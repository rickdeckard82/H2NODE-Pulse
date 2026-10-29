from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase


class HealthTests(SimpleTestCase):
    def test_liveness_does_not_require_database(self):
        response = self.client.get("/api/v1/health/live/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @patch("core.views.connection")
    def test_readiness_checks_database(self, connection):
        response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 200)
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SELECT 1"
        )

    @patch("core.views.connection")
    def test_database_failure_returns_503_without_secrets(self, connection):
        connection.cursor.side_effect = OperationalError("sensitive connection details")
        response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_schema_requires_privileged_session(self):
        self.assertEqual(self.client.get("/api/v1/schema/").status_code, 403)

    def test_invalid_host_is_rejected(self):
        response = self.client.get("/api/v1/health/live/", HTTP_HOST="attacker.invalid")
        self.assertEqual(response.status_code, 400)
