"""Web versions of the iPhone app changes in WEB_PARITY_CHANGES.md (all but the Assistant)."""
import csv
import json
from datetime import date
from io import BytesIO, StringIO

from test_november_features import (  # noqa: F401  (app is a fixture)
    _block, _booking, _csrf, _restore, _workbook, add_txn, admin, app, partner, post, seed,
)


def _ledger_book(client, query):
    from openpyxl import load_workbook
    return load_workbook(BytesIO(client.get(f"/export.xlsx?{query}").data))


# ------------------------------- dashboard ----------------------------------

def test_dashboard_tile_captions(app):
    c = admin(app)
    seed(c)
    body = c.get("/?period=month&month=2026-10").get_data(as_text=True)
    assert "Brought forward to 01 Oct" in body and "As of 31 Oct 2026" in body
    assert "Net Profit (Monthly)" in body and "% margin" in body
    allt = c.get("/?period=all").get_data(as_text=True)
    assert "Starting balance" in allt and "All entries" in allt


def test_net_loss_label(app):
    c = admin(app)
    add_txn(c, "2026-10-09", "expense", 700)
    body = c.get("/?period=quarter&year=2026&quarter=4").get_data(as_text=True)
    assert "Net Loss (Quarterly)" in body and "No income" in body


def test_month_by_month_card_only_for_multi_month_periods(app):
    c = admin(app)
    seed(c)
    month = c.get("/?period=month&month=2026-10").get_data(as_text=True)
    assert "Month by month" not in month
    quarter = c.get("/?period=quarter&year=2026&quarter=4").get_data(as_text=True)
    card = quarter[quarter.index("Month by month"):quarter.index("Income vs expenses")]
    # Oct opens on 0 and closes on 44,000; Nov carries it; Dec is flat.
    assert card.index("Oct 2026") < card.index("Nov 2026") < card.index("Dec 2026")
    assert "+₹44,000" in card and "₹54,000" in card


def test_period_months_carries_balances(app):
    from finance import parse_period, period_months
    c = admin(app)
    seed(c)
    with app.app_context():
        rows = period_months(parse_period({"period": "custom", "from": "2026-10-07", "to": "2026-11-30"}))
    assert [r["label"] for r in rows] == ["Oct 2026", "Nov 2026"]
    # Starts mid-October: the 51,000 on 5 Oct is brought forward, only the 7,000 counts.
    assert rows[0]["opening"] == 51000 and rows[0]["net"] == -7000 and rows[0]["closing"] == 44000
    assert rows[1]["opening"] == 44000 and rows[1]["closing"] == 54000


def test_forecast_card_and_page(app):
    c = admin(app)
    seed(c)
    body = c.get("/").get_data(as_text=True)
    assert "Revenue forecast" in body and 'href="/forecast"' in body
    page = c.get("/forecast?years=2&basis=fy").get_data(as_text=True)
    assert "Year on year" in page and "FY 2027-28" in page and "How it" in page
    assert "Change rent" in page
    assert "Change rent" not in partner(app).get("/forecast").get_data(as_text=True)
    assert "2027" in c.get("/forecast?basis=cal").get_data(as_text=True)


def test_change_rent_is_admin_only_and_saved(app):
    c = admin(app)
    r = post(c, "/forecast/rent", {"rent_monthly": "75000", "rent_start": "2027-06"}, path="/forecast")
    assert "Ground rent set to ₹75,000 a month from Jun 2027" in r.get_data(as_text=True)
    from forecast import rent_settings
    with app.app_context():
        assert rent_settings() == (75000, date(2027, 6, 1))
    p = partner(app)
    page = p.get("/forecast").get_data(as_text=True)
    assert p.post("/forecast/rent", data={"csrf_token": _csrf(page), "rent_monthly": "1",
                                          "rent_start": "2027-04"}).status_code == 403
    bad = post(c, "/forecast/rent", {"rent_monthly": "-5", "rent_start": "2027-06"}, path="/forecast")
    assert "Rent must be a number" in bad.get_data(as_text=True)


# --------------------------------- export -----------------------------------

def test_export_preview(app):
    c = admin(app)
    seed(c)
    d = c.get("/export/preview?period=quarter&year=2026&quarter=4").get_json()
    assert d["label"] == "Q4 2026 (Oct–Dec)" and d["count"] == 3
    assert d["opening"] == "₹0" and d["income"] == "₹61,000" and d["closing"] == "₹54,000"
    assert d["files"]["calendar_csv"] == "BailsCalendar-Quarterly-Q4-2026-Oct-Dec.csv"


def test_export_dialog_has_arrows_and_full_backup(app):
    body = admin(app).get("/").get_data(as_text=True)
    assert 'data-pp-step="-1"' in body and 'data-pp-step="1"' in body
    assert "Download full backup" in body and "Export calendar" in body


def test_calendar_csv_and_calendar_only_workbook(app):
    from openpyxl import load_workbook
    c = admin(app)
    _block(c, "2026-11-10", "7:00 AM", "10:45 AM", "2:30 PM", by="ECL")
    _block(c, "2026-11-12", "2:30 PM", by="=cmd")
    text = c.get("/export/calendar.csv?period=month&month=2026-11").get_data(as_text=True).lstrip("﻿")
    rows = list(csv.reader(StringIO(text)))
    assert rows[0] == ["Date", "Day", "Status", "Slot", "Booked by", "Note"]
    assert rows[1][:4] == ["2026-11-10", "Tue", "Full day", "7:00 AM"]
    assert rows[-1][2] == "Some slots" and rows[-1][4] == "'=cmd"
    wb = load_workbook(BytesIO(c.get("/export/calendar.xlsx?period=month&month=2026-11").data))
    assert wb.sheetnames == ["Ground Calendar"]
    ws = wb["Ground Calendar"]
    # All three slots blocked counts as a full day: red on pink, Full Day column too.
    assert [ws.cell(row=10, column=col).value for col in range(3, 7)] == ["Blocked"] * 4
    assert ws.cell(row=10, column=6).fill.fgColor.rgb.endswith("F7D4D5")


def test_partner_sheet_lists_inactive_partners(app):
    c = admin(app)
    seed(c)
    page = c.get("/partners").get_data(as_text=True)
    import re
    ids = re.findall(r'name="name_(\d+)"', page)
    data = {}
    for pid in ids:
        data[f"name_{pid}"] = re.search(rf'name="name_{pid}" value="([^"]+)"', page).group(1)
        data[f"equity_{pid}"] = "20"
        data[f"active_{pid}"] = "on"
    data.pop(f"active_{ids[-1]}")
    post(c, "/partners/save", data)
    ws = _ledger_book(c, "period=month&month=2026-10")["Partner Profit"]
    statuses = [ws.cell(row=r, column=4).value for r in range(8, 8 + len(ids))]
    assert statuses[-1] == "Inactive" and statuses.count("Active") == len(ids) - 1
    assert ws.cell(row=7 + len(ids), column=3).value == 0


def test_loss_banner_on_partner_sheet(app):
    c = admin(app)
    add_txn(c, "2026-10-09", "expense", 700)
    ws = _ledger_book(c, "period=month&month=2026-10")["Partner Profit"]
    assert ws["A1"].value == "PARTNER SHARE OF LOSS"


# --------------------------------- backup -----------------------------------

def test_period_backup_carries_balance_forward_and_payments(app):
    c = admin(app)
    seed(c)
    data = json.loads(c.get("/admin/backup.json?period=month&month=2026-11").get_data(as_text=True))
    assert data["settings"]["opening_balance"] == "44000.00"
    assert data["period"] == "Nov 2026" and data["summary"]["transactions"] == 1


def test_full_backup_button_overrides_the_period(app):
    c = admin(app)
    seed(c)
    r = c.get("/admin/backup.json?period=month&month=2026-10&full=1")
    assert f'filename="bails-ledger-backup-{date.today().isoformat()}.json"' in r.headers["Content-Disposition"]
    data = json.loads(r.get_data(as_text=True))
    assert "period" not in data and len(data["transactions"]) == 3 and data["format"] == 8


def test_web_period_backup_restores_only_that_period(app):
    c = admin(app)
    seed(c)
    data = json.loads(c.get("/admin/backup.json?period=month&month=2026-10").get_data(as_text=True))
    add_txn(c, "2026-10-20", "income", 5)
    body = _restore(c, data)
    assert "Other periods were not touched" in body
    from finance import balance_as_of
    from models import Setting
    with app.app_context():
        assert balance_as_of(None) == 54000  # Oct back to two entries, Nov untouched
        assert (Setting.get("opening_balance", "0") or "0") in ("0", "0.00")


def test_app_period_backup_replaces_everything(app):
    """The iPhone app's period backups have `period` but no `scope`: a full replace."""
    c = admin(app)
    seed(c)
    data = json.loads(c.get("/admin/backup.json?period=month&month=2026-11").get_data(as_text=True))
    data.pop("scope")
    body = _restore(c, data)
    assert "Restored 1 transactions" in body
    from finance import balance_as_of
    with app.app_context():
        assert balance_as_of(None) == 54000  # 44,000 brought forward + 10,000


def test_format_9_backups_are_still_accepted(app):
    c = admin(app)
    seed(c)
    data = json.loads(c.get("/admin/backup.json").get_data(as_text=True))
    data["format"] = 9
    assert "Restored 3 transactions" in _restore(c, data)
    data["format"] = 10
    assert "newer than this app" in _restore(c, data)


# -------------------------------- calendar ----------------------------------

def test_unblock_whole_day_and_reblock(app):
    from models import GroundBooking
    c = admin(app)
    _block(c, "2026-11-21", "7:00 AM", "2:30 PM", by="ECL")
    r = post(c, "/calendar/day/unblock", {"booking_date": "2026-11-21",
                                          "next": "/calendar?month=2026-11&day=2026-11-21"}, path="/calendar")
    body = r.get_data(as_text=True)
    assert "Unblocked the whole day" in body
    freed = json.loads(body.split('id="calFreed" type="application/json">')[1].split("</script>")[0])
    assert {(u["slot"], u["by"]) for u in freed} == {("7:00 AM", "ECL"), ("2:30 PM", "ECL")}
    with app.app_context():
        assert GroundBooking.query.count() == 0
    r = post(c, "/calendar/block", {"booking_date": "2026-11-21", "slot": "7:00 AM", "booked_by": "ECL",
                                    "reblock": "1"}, path="/calendar")
    body = r.get_data(as_text=True)
    assert "Re-blocked 7:00 AM on 21 Nov 2026" in body
    freed = json.loads(body.split('id="calFreed" type="application/json">')[1].split("</script>")[0])
    assert [u["slot"] for u in freed] == ["2:30 PM"]


def test_unblock_one_slot_is_remembered(app):
    c = admin(app)
    _block(c, "2026-11-22", "10:45 AM", by="Club")
    bid = _booking(app, "2026-11-22", "10:45 AM")
    body = post(c, f"/calendar/{bid}/delete", {}, path="/calendar").get_data(as_text=True)
    assert '"slot": "10:45 AM"' in body.split('id="calFreed"')[1].split("</script>")[0]


def test_day_unblock_is_admin_only(app):
    c = admin(app)
    _block(c, "2026-11-23", "Full Day")
    p = partner(app)
    page = p.get("/calendar").get_data(as_text=True)
    assert p.post("/calendar/day/unblock", data={"csrf_token": _csrf(page),
                                                 "booking_date": "2026-11-23"}).status_code == 403
    assert "calFreed" in page and "[]" in page.split('id="calFreed"')[1][:60]


# -------------------------------- partners ----------------------------------

def test_partner_editor_shows_lease_split_and_payments(app):
    from models import ExPartner, GroundPayment, Partner, Setting, db
    c = admin(app)
    with app.app_context():
        db.session.merge(Setting(key="ground_lease_value", value="1000000"))
        ex = ExPartner(name="Seller", share_pct=100, closing_amount=1000000, account_number="", sort_order=0)
        db.session.add(ex)
        db.session.flush()
        first = Partner.query.order_by(Partner.sort_order).first()
        db.session.add(GroundPayment(detail="x", ex_partner_id=ex.id, partner_id=first.id, txn_number="",
                                     txn_date=date(2026, 10, 1), amount=50000, note=""))
        db.session.commit()
        first_name = first.name
    body = c.get("/partners").get_data(as_text=True)
    assert 'data-lease="1000000.00"' in body and "Lease split" in body and "Paid toward ground" in body
    assert "Has ground payments, so can" in body
    assert "Ground lease value" in body
    row = body[body.index(f'value="{first_name}"'):]
    assert 'data-paid="50000.00"' in body and "₹50,000" in row[:2500]
