"""API tests. Run with:  .venv\\Scripts\\python -m unittest -v"""
import os
import tempfile
import unittest
from datetime import timedelta

_tmp = tempfile.mkdtemp()
os.environ["WARRIOR_DB"] = os.path.join(_tmp, "test.db")
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SMTP_HOST"] = ""

from server import app as server_app  # noqa: E402
from server import db  # noqa: E402
from server.availability import now_local  # noqa: E402

ADMIN = {"X-Requested-With": "fetch"}


class ApiTest(unittest.TestCase):
    def setUp(self):
        conn = db.connect()
        for table in ("bookings", "time_off", "date_overrides"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE weekly_hours SET open_time='10:00', close_time='19:00', closed=0")
        conn.close()
        server_app._hits.clear()
        self.client = server_app.app.test_client()
        self.day = (now_local().date() + timedelta(days=7)).isoformat()

    def login(self):
        self.assertEqual(self.client.post("/api/admin/login", json={"password": "test-password"}).status_code, 200)

    def slots(self, day=None):
        day = day or self.day
        response = self.client.get(f"/api/availability?service_id=1&from={day}&days=1")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["days"][0]["slots"]

    def book(self, time="10:00", phone="0701234567", **extra):
        payload = {"service_id": 1, "start": f"{self.day}T{time}", "customer_name": "Test Kund", "phone": phone}
        payload.update(extra)
        return self.client.post("/api/bookings", json=payload)

    def test_slots_follow_opening_hours(self):
        slots = self.slots()
        self.assertEqual(slots[0], "10:00")
        self.assertEqual(slots[-1], "18:30")  # 30 min service, closes 19:00
        self.assertEqual(len(slots), 35)

    def test_booking_removes_overlapping_slots(self):
        response = self.book("12:00")
        self.assertEqual(response.status_code, 201)
        slots = self.slots()
        for taken in ("11:45", "12:00", "12:15"):
            self.assertNotIn(taken, slots)
        self.assertIn("11:30", slots)
        self.assertIn("12:30", slots)

    def test_double_booking_is_refused(self):
        self.assertEqual(self.book("13:00").status_code, 201)
        self.assertEqual(self.book("13:00", phone="0709999999").status_code, 409)
        self.assertEqual(self.book("13:15", phone="0709999999").status_code, 409)

    def test_rejects_bad_input(self):
        self.assertEqual(self.book("10:07").status_code, 409)       # not on the grid
        self.assertEqual(self.book("08:00").status_code, 409)       # before opening
        self.assertEqual(self.book("10:00", phone="abc").status_code, 400)
        self.assertEqual(self.book("10:00", customer_name="").status_code, 400)
        self.assertEqual(self.book("10:00", email="nope").status_code, 400)
        self.assertEqual(self.book("10:00", website="spam").status_code, 400)
        past = (now_local() - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
        self.assertEqual(self.client.post("/api/bookings", json={
            "service_id": 1, "start": past, "customer_name": "Test", "phone": "0701234567"}).status_code, 409)

    def test_customer_can_cancel_and_reschedule(self):
        token = self.book("14:00").get_json()["booking"]["token"]
        moved = self.client.post(f"/api/bookings/{token}/reschedule", json={"start": f"{self.day}T15:00"})
        self.assertEqual(moved.status_code, 200)
        self.assertIn("14:00", self.slots())
        self.assertNotIn("15:00", self.slots())
        cancelled = self.client.post(f"/api/bookings/{token}/cancel")
        self.assertEqual(cancelled.get_json()["booking"]["status"], "cancelled")
        self.assertIn("15:00", self.slots())
        self.assertEqual(self.client.post(f"/api/bookings/{token}/cancel").status_code, 409)
        self.assertEqual(self.client.get("/api/bookings/wrong-token").status_code, 404)

    def test_admin_requires_login(self):
        self.assertEqual(self.client.get(f"/api/admin/bookings?from={self.day}&to={self.day}").status_code, 401)
        self.assertEqual(self.client.post("/api/admin/login", json={"password": "wrong"}).status_code, 401)
        self.login()
        # Logged in, but a cross-site style post without the header is refused.
        self.assertEqual(self.client.post("/api/admin/time-off", json={}).status_code, 403)

    def test_admin_rebook_and_cancel(self):
        self.book("10:00")
        self.book("11:00", phone="0702222222")
        self.login()
        next_day = (now_local().date() + timedelta(days=8)).isoformat()
        listing = self.client.get(f"/api/admin/bookings?from={self.day}&to={next_day}").get_json()["bookings"]
        self.assertEqual(len(listing), 2)
        first = listing[0]["id"]
        clash = self.client.patch(f"/api/admin/bookings/{first}", json={"start": f"{self.day}T11:15"}, headers=ADMIN)
        self.assertEqual(clash.status_code, 409)
        moved = self.client.patch(f"/api/admin/bookings/{first}", json={"start": f"{self.day}T16:00"}, headers=ADMIN)
        self.assertEqual(moved.get_json()["booking"]["start"], f"{self.day}T16:00")
        cancelled = self.client.patch(f"/api/admin/bookings/{first}", json={"status": "cancelled"}, headers=ADMIN)
        self.assertEqual(cancelled.get_json()["booking"]["status"], "cancelled")
        self.assertIn("16:00", self.slots())
        # Barber can add a booking outside opening hours, but not on top of another.
        late = {"service_id": 1, "start": f"{self.day}T20:00", "customer_name": "Sen kund"}
        self.assertEqual(self.client.post("/api/admin/bookings", json=late, headers=ADMIN).status_code, 201)
        self.assertEqual(self.client.post("/api/admin/bookings", json=late, headers=ADMIN).status_code, 409)

    def test_schedule_changes_affect_slots(self):
        self.book("12:00")
        self.login()
        blocked = self.client.post("/api/admin/time-off", headers=ADMIN, json={
            "start": f"{self.day}T12:00", "end": f"{self.day}T14:00", "note": "Lunch"})
        self.assertEqual(blocked.get_json()["conflicts"], 1)
        slots = self.slots()
        self.assertNotIn("13:00", slots)
        self.assertNotIn("13:45", slots)
        self.assertIn("14:00", slots)

        short = self.client.put(f"/api/admin/overrides/{self.day}", headers=ADMIN, json={
            "open_time": "15:00", "close_time": "17:00"})
        self.assertEqual(short.get_json()["conflicts"], 1)
        self.assertEqual(self.slots()[0], "15:00")
        self.assertEqual(self.slots()[-1], "16:30")

        self.client.put(f"/api/admin/overrides/{self.day}", headers=ADMIN, json={"closed": True})
        self.assertEqual(self.slots(), [])
        self.client.delete(f"/api/admin/overrides/{self.day}", headers=ADMIN)

        hours = [{"open_time": "09:00", "close_time": "12:00", "closed": False}] * 7
        self.assertEqual(self.client.put("/api/admin/hours", json={"hours": hours}, headers=ADMIN).status_code, 200)
        self.assertEqual(self.slots()[0], "09:00")
        self.assertEqual(self.slots()[-1], "11:30")

    def test_services_can_be_edited(self):
        self.login()
        update = {"name": "Klippning", "description": "", "duration_min": 45, "price_sek": 250, "active": True, "sort": 1}
        self.assertEqual(self.client.put("/api/admin/services/1", json=update, headers=ADMIN).status_code, 200)
        self.assertEqual(self.slots()[-1], "18:15")
        update["duration_min"] = 30
        update["price_sek"] = 200
        self.client.put("/api/admin/services/1", json=update, headers=ADMIN)


if __name__ == "__main__":
    unittest.main()
