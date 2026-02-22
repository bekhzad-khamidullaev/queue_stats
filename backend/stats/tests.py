
from django.test import TestCase, RequestFactory
from django.urls import reverse
from unittest.mock import patch, MagicMock
import json
from datetime import datetime

from .views import answered_report
from .models import ProductEvent
from accounts.models import User, UserRoles

class AnsweredReportTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpassword',
            role=UserRoles.ANALYST
        )
        self.factory = RequestFactory()

    @patch('stats.views._fetch_queuelog_rows')
    def test_answered_report(self, mock_fetch_queuelog_rows):
        mock_data = [
            {
                'agent': 'agent1',
                'queuename': 'queue1',
                'data1': '10', # hold
                'data2': '20', # talk
            },
            {
                'agent': 'agent1',
                'queuename': 'queue1',
                'data1': '15',
                'data2': '25',
            },
            {
                'agent': 'agent2',
                'queuename': 'queue2',
                'data1': '5',
                'data2': '30',
            },
        ]
        mock_fetch_queuelog_rows.return_value = mock_data

        request_body = json.dumps({
            'start': '2025-01-01 00:00:00',
            'end': '2025-01-01 23:59:59',
            'queues': ['queue1', 'queue2'],
            'agents': ['agent1', 'agent2'],
        }).encode('utf-8')

        request = self.factory.post('/', request_body, content_type='application/json')
        request.user = self.user

        response = answered_report(request)
        self.assertEqual(response.status_code, 200)

        response_data = json.loads(response.content)

        # Check summary
        summary = response_data['summary']
        self.assertEqual(summary['total_calls'], 3)
        self.assertEqual(summary['avg_talk_time'], 25.0)
        self.assertEqual(summary['total_talk_minutes'], 1.25)
        self.assertEqual(summary['avg_hold_time'], 10.0)

        # Check agents summary
        agents_summary = response_data['agents']
        self.assertEqual(len(agents_summary), 2)

        agent1_summary = next(item for item in agents_summary if item["agent"] == "agent1")
        self.assertEqual(agent1_summary['calls'], 2)
        self.assertEqual(agent1_summary['talk_time_total'], 45)
        self.assertEqual(agent1_summary['talk_time_avg'], 22.5)

        agent2_summary = next(item for item in agents_summary if item["agent"] == "agent2")
        self.assertEqual(agent2_summary['calls'], 1)
        self.assertEqual(agent2_summary['talk_time_total'], 30)
        self.assertEqual(agent2_summary['talk_time_avg'], 30.0)

        # Check response distribution
        response_distribution = response_data['response_distribution']
        self.assertEqual(response_distribution['queue1']['6-10'], 1)
        self.assertEqual(response_distribution['queue1']['11-15'], 1)
        self.assertEqual(response_distribution['queue2']['0-5'], 1)


class ProductEventTrackingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="analytics_user",
            password="strong-password",
            role=UserRoles.ANALYST,
        )
        self.client.force_login(self.user)
        self.url = reverse("ui-track-event")

    def test_track_share_clicked_event(self):
        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "event": "share_clicked",
                    "meta": {"page": "analytics", "source": "button", "shared_token": "abc123"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductEvent.objects.count(), 1)
        event = ProductEvent.objects.first()
        self.assertEqual(event.event_name, "share_clicked")
        self.assertEqual(event.page, "analytics")
        self.assertEqual(event.metadata.get("source"), "button")
        self.assertEqual(event.metadata.get("shared_token"), "abc123")

    def test_invalid_event_is_rejected(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"event": "unsupported_event", "meta": {"page": "analytics"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ProductEvent.objects.count(), 0)
