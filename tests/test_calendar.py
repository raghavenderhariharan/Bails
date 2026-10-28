"""Ground calendar: block slots or a full day, conflict rules, roles, backup."""
import json
import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/c.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "Admin123")
    monkeypatch.setenv("PARTNER_PASSCODE", "")
    monkeypatch.setenv("DRIVE_EXPORT_DIR", "")
    for module in ("config", "models", "finance", "exporter", "backup", "app"):
        sys.modules.pop(module, None)
    import app as app_module
    app_module._login_attempts.clear()
    app_module._global_failures.clear()
    app_module.app.config.update(TESTING=True)
    return app_module.app


def _csrf(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def admin(app):
    c = app.test_client()
    page = c.get("/login?as=admin").get_data(as_text=True)
    c.post("/login", data={"csrf_token": _csrf(page), "password": "Admin123"})
    return c


def partner(app):
    c = app.test_client()
    page = c.get("/login").get_data(as_text=True)
    c.post("/login/partner", data={"csrf_token": _csrf(page)})
    return c


def block(client, day, *slots, booked_by="", note=""):
    page = client.get("/calendar").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "booking_date": day, "slot": list(slots),
            "booked_by": booked_by, "note": note, "next": "/calendar?month=" + day[:7]}
    return client.post("/calendar/block", data=data, follow_redirects=True).get_data(as_text=True)


def stored(app):
    from models import GroundBooking
    with app.app_context():
        return sorted((b.booking_date.isoformat(), b.slot) for b in GroundBooking.query.all())


def test_calendar_renders_month_grid(app):
    body = admin(app).get("/calendar?month=2026-11").get_data(as_text=True)
    assert "Ground Calendar" in body and "November 2026" in body
    assert body.count('class="cal__day') >= 28


def test_bad_month_falls_back_to_current(app):
    body = admin(app).get("/calendar?month=garbage").get_data(as_text=True)
    assert date.today().strftime("%B %Y") in body


def test_block_single_and_multiple_slots(app):
    c = admin(app)
    body = block(c, "2026-11-05", "7:00 AM", booked_by="ECL")
    assert "Blocked 7:00 AM" in body
    block(c, "2026-11-06", "10:45 AM", "2:30 PM")
    assert stored(app) == [("2026-11-05", "7:00 AM"), ("2026-11-06", "10:45 AM"), ("2026-11-06", "2:30 PM")]
    page = c.get("/calendar?month=2026-11").get_data(as_text=True)
    assert "ECL" in page and "cal__day--partial" in page


def test_block_full_day(app):
    c = admin(app)
    block(c, "2026-11-10", "Full Day", booked_by="Tournament")
    assert stored(app) == [("2026-11-10", "Full Day")]
    assert "cal__day--full" in c.get("/calendar?month=2026-11").get_data(as_text=True)


def test_full_day_wins_when_combined_with_slots(app):
    block(admin(app), "2026-11-11", "Full Day", "7:00 AM")
    assert stored(app) == [("2026-11-11", "Full Day")]


def test_same_slot_cannot_be_blocked_twice(app):
    c = admin(app)
    block(c, "2026-11-12", "7:00 AM")
    body = block(c, "2026-11-12", "7:00 AM")
    assert "already blocked" in body
    assert stored(app) == [("2026-11-12", "7:00 AM")]


def test_slot_refused_on_a_full_day(app):
    c = admin(app)
    block(c, "2026-11-13", "Full Day")
    body = block(c, "2026-11-13", "2:30 PM")
    assert "already blocked for the full day" in body
    assert stored(app) == [("2026-11-13", "Full Day")]


def test_full_day_refused_when_slots_exist(app):
    c = admin(app)
    block(c, "2026-11-14", "7:00 AM")
    body = block(c, "2026-11-14", "Full Day")
    assert "remove those first" in body
    assert stored(app) == [("2026-11-14", "7:00 AM")]


def test_all_three_slots_shows_as_full(app):
    c = admin(app)
    block(c, "2026-11-15", "7:00 AM", "10:45 AM", "2:30 PM")
    assert "cal__day--full" in c.get("/calendar?month=2026-11").get_data(as_text=True)


def test_invalid_inputs_rejected(app):
    c = admin(app)
    assert "Choose at least one slot" in block(c, "2026-11-16")
    assert "Unknown slot" in block(c, "2026-11-16", "Midnight")
    assert "Date" in block(c, "not-a-date", "7:00 AM")
    assert stored(app) == []


def test_unblock(app):
    from models import GroundBooking
    c = admin(app)
    block(c, "2026-11-17", "7:00 AM")
    with app.app_context():
        bid = GroundBooking.query.one().id
    page = c.get("/calendar").get_data(as_text=True)
    c.post(f"/calendar/{bid}/delete", data={"csrf_token": _csrf(page), "next": "/calendar"})
    assert stored(app) == []


def test_partner_can_view_but_not_edit(app):
    block(admin(app), "2026-11-18", "7:00 AM", booked_by="Club")
    p = partner(app)
    body = p.get("/calendar?month=2026-11").get_data(as_text=True)
    assert "Club" in body
    assert "blockModal" not in body and "data-open-block" not in body and "Unblock" not in body
    page = p.get("/calendar").get_data(as_text=True)
    r = p.post("/calendar/block", data={"csrf_token": _csrf(page), "booking_date": "2026-11-19",
                                        "slot": "7:00 AM"})
    assert r.status_code == 403
    assert stored(app) == [("2026-11-18", "7:00 AM")]


def test_calendar_requires_login(app):
    assert app.test_client().get("/calendar").status_code in (301, 302, 308)


def test_nav_link_present(app):
    assert 'href="/calendar"' in partner(app).get("/").get_data(as_text=True)


def test_backup_round_trip_includes_bookings(app):
    from backup import build_backup, restore_backup
    c = admin(app)
    block(c, "2026-11-20", "Full Day", booked_by="ECL", note="Final")
    block(c, "2026-11-21", "10:45 AM")
    data = json.loads(c.get("/admin/backup.json").get_data(as_text=True))
    assert data["format"] >= 8 and data["summary"]["ground_bookings"] == 2
    with app.app_context():
        restore_backup(data)
        assert build_backup()["ground_bookings"] == data["ground_bookings"]
    assert stored(app) == [("2026-11-20", "Full Day"), ("2026-11-21", "10:45 AM")]


def test_slots_listed_in_time_order(app):
    c = admin(app)
    block(c, "2026-11-22", "2:30 PM", "7:00 AM", "10:45 AM")
    body = c.get("/calendar?month=2026-11").get_data(as_text=True)
    table = body[body.index("Blocked this month"):]
    assert table.index("7:00 AM") < table.index("10:45 AM") < table.index("2:30 PM")
