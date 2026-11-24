"""Bulk calendar blocks: repeat on weekdays, or rows pasted from a spreadsheet."""
from datetime import date

from test_november_features import _block, _csrf, admin, app, partner, post  # noqa: F401

# The organiser's sheet as Excel copies it: tab-separated, with header and Total rows.
SHEET = """Organizer\tDate\tDay\tTime
Octa Legends (Rohit)\t14-Nov-2026\tSaturday\t7:00 AM
Octa Legends (Rohit)\t21-Nov-2026\tSaturday\t7:00 AM
Octa Legends (Rohit)\t28-Nov-2026\tSaturday\t7:00 AM
A1 Corporate (Abdul Qadir)\t10-Jan-2027\tSunday\tFull day
A1 Corporate (Abdul Qadir)\t26-Jan-2027\tTuesday\tFull day
Total\t\t\t
"""


def _rows(app):
    from models import GroundBooking
    with app.app_context():
        return sorted((b.booking_date.isoformat(), b.slot, b.booked_by) for b in GroundBooking.query.all())


def _preview(client, data):
    page = client.get("/calendar").get_data(as_text=True)
    return client.post("/calendar/bulk/preview", data={"csrf_token": _csrf(page), **data}).get_json()


def test_paste_rows_from_excel(app):
    c = admin(app)
    d = _preview(c, {"mode": "paste", "rows": SHEET})
    assert d["problems"] == [] and d["add"] == 5
    assert d["rows"][0] == {"date": "2026-11-14", "label": "Sat 14 Nov 2026", "slot": "7:00 AM",
                            "by": "Octa Legends (Rohit)", "status": "add", "reason": ""}
    body = post(c, "/calendar/bulk", {"mode": "paste", "rows": SHEET}, path="/calendar").get_data(as_text=True)
    assert "Blocked 5 slots." in body
    assert _rows(app)[-1] == ("2027-01-26", "Full Day", "A1 Corporate (Abdul Qadir)")
    assert len(_rows(app)) == 5


def test_paste_skips_what_is_already_there_and_flags_clashes(app):
    c = admin(app)
    _block(c, "2026-11-28", "7:00 AM", by="Octa Legends (Rohit)")   # same booking: skipped quietly
    _block(c, "2027-01-10", "2:30 PM", by="ECL")                    # clashes with the full day
    d = _preview(c, {"mode": "paste", "rows": SHEET})
    status = {r["date"]: (r["status"], r["reason"]) for r in d["rows"]}
    assert status["2026-11-28"] == ("already", "Already blocked")
    assert status["2027-01-10"] == ("clash", "2:30 PM already blocked")
    assert d["add"] == 3
    body = post(c, "/calendar/bulk", {"mode": "paste", "rows": SHEET}, path="/calendar").get_data(as_text=True)
    assert "Blocked 3 slots. Skipped 2 already blocked." in body


def test_paste_accepts_other_shapes_and_reports_bad_lines(app):
    c = admin(app)
    text = ("Octa Legends 05/12/2026 Saturday 7 am\n"
            "Club, 2026-12-06, 2.30 pm\n"
            "Team X\t07-Dec-2026\tMonday\n"
            "Team Y\t31-Feb-2027\tSunday\tFull day\n")
    d = _preview(c, {"mode": "paste", "rows": text})
    assert [(r["date"], r["slot"], r["by"]) for r in d["rows"]] == [
        ("2026-12-05", "7:00 AM", "Octa Legends"), ("2026-12-06", "2:30 PM", "Club")]
    assert any("Line 3" in p and "no slot" in p for p in d["problems"])
    assert any("Line 4" in p for p in d["problems"])
    # With problems nothing is saved.
    body = post(c, "/calendar/bulk", {"mode": "paste", "rows": text}, path="/calendar").get_data(as_text=True)
    assert "no slot" in body and _rows(app) == []


def test_repeat_every_saturday(app):
    c = admin(app)
    data = {"mode": "repeat", "start": "2026-11-14", "end": "2027-02-27", "weekday": "5",
            "slot": "7:00 AM", "booked_by": "Octa Legends (Rohit)"}
    d = _preview(c, data)
    assert d["add"] == 16 and all(r["label"].startswith("Sat") for r in d["rows"])
    assert "Blocked 16 slots." in post(c, "/calendar/bulk", data, path="/calendar").get_data(as_text=True)
    rows = _rows(app)
    assert rows[0] == ("2026-11-14", "7:00 AM", "Octa Legends (Rohit)") and rows[-1][0] == "2027-02-27"


def test_repeat_validates_input(app):
    c = admin(app)
    assert "Tick at least one day" in _preview(c, {"mode": "repeat", "start": "2026-11-01", "end": "2026-11-30",
                                                   "slot": "7:00 AM"})["problems"][0]
    assert "a year or less" in _preview(c, {"mode": "repeat", "start": "2026-01-01", "end": "2027-06-01",
                                            "weekday": "5", "slot": "7:00 AM"})["problems"][0]
    full = _preview(c, {"mode": "repeat", "start": "2026-11-01", "end": "2026-11-08", "weekday": "6",
                        "slot": ["Full Day", "7:00 AM"]})
    assert [r["slot"] for r in full["rows"]] == ["Full Day", "Full Day"]


def test_bulk_is_admin_only(app):
    p = partner(app)
    page = p.get("/calendar").get_data(as_text=True)
    assert 'id="bulkModal"' not in page and "Bulk block" not in page
    for url in ("/calendar/bulk", "/calendar/bulk/preview"):
        assert p.post(url, data={"csrf_token": _csrf(page), "mode": "paste", "rows": SHEET}).status_code == 403


def test_calendar_shows_free_slots_green_and_blocked_red(app):
    c = admin(app)
    _block(c, "2026-11-18", "7:00 AM", by="ECL")
    _block(c, "2026-11-14", "Full Day", by="HCA")
    body = c.get("/calendar?month=2026-11").get_data(as_text=True)
    day = body[body.index('data-date="2026-11-18" tabindex'):]
    day = day[:day.index('class="cal__day')]
    assert "cal__chip--booked" in day and day.count("cal__chip--free") == 2
    assert 'data-slot="10:45 AM"' in day and 'data-slot="2:30 PM"' in day
    full = body[body.index('data-date="2026-11-14" tabindex'):]
    full = full[:full.index('class="cal__day')]
    assert "cal__chip--full" in full and "cal__chip--free" not in full
    # Partners see the bars but can't click a free one to block it.
    pb = partner(app).get("/calendar?month=2026-11").get_data(as_text=True)
    assert "cal__chip--free" in pb and "data-open-block" not in pb


def test_unblocking_twice_goes_back_to_the_calendar(app):
    """A double click sends the unblock twice; the second must not 404."""
    from test_november_features import _booking
    c = admin(app)
    _block(c, "2027-01-16", "7:00 AM", by="Octa")
    bid = _booking(app, "2027-01-16", "7:00 AM")
    nxt = "/calendar?month=2027-01&day=2027-01-16"
    first = post(c, f"/calendar/{bid}/delete", {"next": nxt}, path="/calendar")
    second = post(c, f"/calendar/{bid}/delete", {"next": nxt}, path="/calendar")
    assert first.status_code == 200 and second.status_code == 200
    assert "That slot is already unblocked." in second.get_data(as_text=True)
    edit = post(c, f"/calendar/{bid}/edit", {"next": nxt, "booking_date": "2027-01-16", "slot": "7:00 AM"},
                path="/calendar")
    assert edit.status_code == 200 and "unblocked meanwhile" in edit.get_data(as_text=True)
