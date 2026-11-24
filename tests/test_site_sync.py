"""One-way calendar sync, ledger -> public website, against a fake website."""
import json
from datetime import date
from types import SimpleNamespace as B

import pytest

import sitesync
from test_november_features import _block, _csrf, admin, app, partner, post  # noqa: F401

TODAY = date(2026, 11, 24)


class FakeSite:
    """Behaves like the website's /api: refuses a slot that is already taken."""

    def __init__(self, bookings=()):
        self.rows = [dict(b) for b in bookings]
        self.next_id = 100
        self.calls = []

    def login(self):
        self.calls.append("login")

    def logout(self):
        self.calls.append("logout")

    def bookings(self):
        return [dict(r) for r in self.rows]

    def create(self, body):
        parts = sitesync.PARTS[body["slot"]]
        if any(r["date"] == body["date"] and parts & sitesync.PARTS[r["slot"]] for r in self.rows):
            raise sitesync.SyncError("That slot is already taken")
        self.next_id += 1
        self.rows.append({"id": f"b{self.next_id}", **body})
        self.calls.append(("create", body["date"], body["slot"]))

    def delete(self, bid):
        self.rows = [r for r in self.rows if r["id"] != bid]
        self.calls.append(("delete", bid))


def bk(id, day, slot, by="", note=""):
    return B(id=id, booking_date=date.fromisoformat(day), slot=slot, booked_by=by, note=note)


def test_payload_hides_the_contact_person_and_tags_the_block():
    p = sitesync.payload(bk(7, "2026-11-28", "7:00 AM", "Octa Legends (Rohit)"))
    assert p == {"date": "2026-11-28", "slot": "s1", "category": "private", "label": "Octa Legends",
                 "note": "Booked by Octa Legends (Rohit) [Ledger #7]"}
    assert sitesync.payload(bk(8, "2027-01-10", "Full Day", "A1 Corporate (Abdul Qadir)"))["slot"] == "full"
    assert sitesync.category_for("HCA", "") == "hca" and sitesync.category_for("ECL", "") == "tournament"


def test_creates_new_blocks_and_leaves_the_websites_own_alone():
    site = FakeSite([{"id": "h1", "date": "2026-11-25", "slot": "full", "category": "hca",
                      "label": "HCA Division C Matches", "note": ""}])
    local = [bk(1, "2026-11-28", "7:00 AM", "Octa Legends (Rohit)"),
             bk(2, "2026-11-28", "10:45 AM", "ECL"),
             bk(3, "2026-11-25", "7:00 AM", "Club"),          # clashes with the HCA day
             bk(4, "2026-11-20", "7:00 AM", "Past")]          # in the past: not pushed
    status = sitesync.run(local, site, today=TODAY)
    assert status["created"] == 2 and status["deleted"] == 0
    assert status["conflict_count"] == 1 and "HCA Division C Matches" in status["conflicts"][0]
    assert any(r["id"] == "h1" for r in site.rows)
    assert site.calls[0] == "login" and site.calls[-1] == "logout"
    # Running again changes nothing.
    again = sitesync.run(local, site, today=TODAY)
    assert again["created"] == 0 and again["deleted"] == 0


def test_unblock_and_edit_are_mirrored():
    site = FakeSite()
    local = [bk(1, "2026-11-28", "7:00 AM", "Octa"), bk(2, "2026-12-05", "7:00 AM", "Octa")]
    sitesync.run(local, site, today=TODAY)
    # 1 unblocked, 2 moved to 2:30 PM.
    status = sitesync.run([bk(2, "2026-12-05", "2:30 PM", "Octa")], site, today=TODAY)
    assert status["deleted"] == 2 and status["created"] == 1
    assert [(r["date"], r["slot"]) for r in site.rows] == [("2026-12-05", "s3")]


def test_full_day_replacing_slots_on_the_same_day():
    site = FakeSite()
    sitesync.run([bk(1, "2026-12-12", "7:00 AM"), bk(2, "2026-12-12", "2:30 PM")], site, today=TODAY)
    status = sitesync.run([bk(3, "2026-12-12", "Full Day", "HCA")], site, today=TODAY)
    assert status["ok"] and [(r["slot"], r["category"]) for r in site.rows] == [("full", "hca")]


def test_off_without_settings(app, monkeypatch):
    assert not sitesync.configured()
    assert sitesync.trigger(app) is False
    c = admin(app)
    body = post(c, "/calendar/site-sync", {}, path="/calendar").get_data(as_text=True)
    assert "isn&#39;t set up" in body or "isn't set up" in body
    assert "Sync website now" not in c.get("/calendar").get_data(as_text=True)


def test_calendar_changes_trigger_a_sync(app, monkeypatch):
    calls = []
    monkeypatch.setattr(sitesync, "trigger", lambda a: calls.append("sync") or True)
    c = admin(app)
    _block(c, "2026-12-19", "7:00 AM", by="Octa")
    post(c, "/calendar/bulk", {"mode": "paste", "rows": "Octa\t26-Dec-2026\tSaturday\t7:00 AM"}, path="/calendar")
    from models import GroundBooking
    with app.app_context():
        bid = GroundBooking.query.filter_by(booking_date=date(2026, 12, 19)).one().id
    post(c, f"/calendar/{bid}/delete", {}, path="/calendar")
    post(c, "/calendar/day/unblock", {"booking_date": "2026-12-26"}, path="/calendar")
    assert calls == ["sync"] * 4


def test_sync_now_saves_the_status_for_the_page(app, monkeypatch):
    monkeypatch.setenv("BAILS_SITE_URL", "https://example.invalid")
    monkeypatch.setenv("BAILS_SITE_USER", "admin")
    monkeypatch.setenv("BAILS_SITE_PASSWORD", "x")
    monkeypatch.setattr(sitesync, "today_ist", lambda: TODAY)
    c = admin(app)
    _block(c, "2026-12-19", "7:00 AM", by="Octa Legends (Rohit)")
    site = FakeSite()
    status = sitesync.sync_now(app, client=site)
    assert status["created"] == 1 and site.rows[0]["label"] == "Octa Legends"
    page = c.get("/calendar").get_data(as_text=True)
    assert "Sync website now" in page and "1 added, 0 removed" in page
    assert "Sync website now" not in partner(app).get("/calendar").get_data(as_text=True)


def test_unreachable_website_is_reported(app, monkeypatch):
    class Down(FakeSite):
        def login(self):
            raise sitesync.SyncError("could not reach the website (timed out)")
    monkeypatch.setenv("BAILS_SITE_URL", "https://example.invalid")
    monkeypatch.setenv("BAILS_SITE_USER", "admin")
    monkeypatch.setenv("BAILS_SITE_PASSWORD", "x")
    c = admin(app)
    sitesync.sync_now(app, client=Down())
    assert "failed &mdash; could not reach the website" in c.get("/calendar").get_data(as_text=True) or \
        "failed — could not reach the website" in c.get("/calendar").get_data(as_text=True)
