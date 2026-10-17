
from datetime import date
import json
import os
import unittest

from dotenv import load_dotenv

from app import create_app, classify_follow_up
from database import get_connection

load_dotenv()


class SmartJobTrackerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_database_url = os.getenv("TEST_DATABASE_URL")

        if not cls.test_database_url:
            raise RuntimeError(
                "TEST_DATABASE_URL is missing from your .env file."
            )

        if not cls.test_database_url.startswith(
            ("postgresql://", "postgres://")
        ):
            raise RuntimeError(
                "TEST_DATABASE_URL must be a PostgreSQL connection URL."
            )

    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "DATABASE": self.test_database_url,
            "SECRET_KEY": "test-secret",
        })

        self.client = self.app.test_client()

        self.valid_payload = {
            "company_name": "Acme",
            "job_role": "Software Engineer",
            "application_date": "2026-10-10",
            "status": "Applied",
            "job_url": "https://example.com/jobs/1",
            "notes": "Campus role",
            "follow_up_date": None,
        }

    def tearDown(self):
        # Clean only the dedicated test database.
        with get_connection(self.test_database_url) as connection:
            connection.execute("DELETE FROM applications")

    def create_record(self, payload=None):
        response = self.client.post(
            "/api/applications",
            json=payload or self.valid_payload,
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_create_and_retrieve_applications(self):
        created = self.create_record()
        self.assertEqual(created["company_name"], "Acme")
        self.assertIn("follow_up_status", created)

        listing = self.client.get("/api/applications")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.get_json()), 1)

        one = self.client.get(f"/api/applications/{created['id']}")
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.get_json()["job_role"], "Software Engineer")

    def test_update_application(self):
        created = self.create_record()

        response = self.client.patch(
            f"/api/applications/{created['id']}",
            json={"status": "Interview", "notes": "Round 1"},
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["status"], "Interview")
        self.assertEqual(response.get_json()["notes"], "Round 1")

    def test_delete_application_and_missing_record(self):
        created = self.create_record()

        response = self.client.delete(
            f"/api/applications/{created['id']}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/applications").get_json(), [])
        self.assertEqual(
            self.client.delete(
                f"/api/applications/{created['id']}"
            ).status_code,
            404,
        )

    def test_search_and_status_filter(self):
        self.create_record()
        self.create_record({
            **self.valid_payload,
            "company_name": "Beta Labs",
            "status": "Interview",
        })

        response = self.client.get("/?q=Beta")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Beta Labs", response.data)
        self.assertNotIn(b"Acme", response.data)

        response = self.client.get("/?status=Interview")
        self.assertIn(b"Beta Labs", response.data)
        self.assertNotIn(b"Acme", response.data)

    def test_follow_up_classification(self):
        today = date(2026, 10, 17)

        self.assertEqual(
            classify_follow_up("2026-10-16", "Applied", today),
            "Overdue",
        )
        self.assertEqual(
            classify_follow_up("2026-10-17", "Interview", today),
            "Due today",
        )
        self.assertEqual(
            classify_follow_up("2026-10-18", "Applied", today),
            "Upcoming",
        )
        self.assertIsNone(
            classify_follow_up("2026-10-17", "Selected", today)
        )
        self.assertIsNone(
            classify_follow_up("2026-10-17", "Rejected", today)
        )
        self.assertIsNone(classify_follow_up(None, "Applied", today))

    def test_invalid_required_fields_dates_and_status(self):
        missing = self.client.post(
            "/api/applications",
            json={"company_name": "Acme"},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("required", missing.get_json()["error"])

        empty = self.client.post(
            "/api/applications",
            json={**self.valid_payload, "company_name": "  "},
        )
        self.assertEqual(empty.status_code, 400)

        invalid_date = self.client.post(
            "/api/applications",
            json={
                **self.valid_payload,
                "application_date": "31-12-2026",
            },
        )
        self.assertEqual(invalid_date.status_code, 400)

        invalid_status = self.client.post(
            "/api/applications",
            json={
                **self.valid_payload,
                "status": "Hired maybe",
            },
        )
        self.assertEqual(invalid_status.status_code, 400)

    def test_invalid_json_and_content_type(self):
        wrong_type = self.client.post(
            "/api/applications",
            data="{}",
            content_type="text/plain",
        )
        self.assertEqual(wrong_type.status_code, 415)

        invalid_json = self.client.post(
            "/api/applications",
            data="{bad",
            content_type="application/json",
        )
        self.assertEqual(invalid_json.status_code, 400)

        not_object = self.client.post(
            "/api/applications",
            data=json.dumps([1, 2]),
            content_type="application/json",
        )
        self.assertEqual(not_object.status_code, 400)

    def test_missing_api_record(self):
        self.assertEqual(
            self.client.get("/api/applications/999").status_code,
            404,
        )

        response = self.client.patch(
            "/api/applications/999",
            json={"status": "Interview"},
        )
        self.assertEqual(response.status_code, 404)

    def test_dashboard_renders_and_counts_database_records(self):
        self.create_record()

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Total applications", response.data)
        self.assertIn(b"Acme", response.data)

    def test_data_persists_across_app_instances(self):
        self.create_record()

        second_app = create_app({
            "TESTING": True,
            "DATABASE": self.test_database_url,
            "SECRET_KEY": "test-secret",
        })

        response = second_app.test_client().get("/api/applications")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
