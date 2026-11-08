"""Opening balances, period export/backup, booking edits, partner editing, email."""
import json
import os
import re
import sys
from datetime import date
from io import BytesIO

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/n.db")
    for module in ("config", "models", "finance", "exporter", "backup", "mailer", "app"):
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


def token(client, path="/partners"):
    return _csrf(client.get(path).get_data(as_text=True))


def post(client, url, data, path="/partners"):
    data = {"csrf_token": token(client, path), **data}
    return client.post(url, data=data, follow_redirects=True)


def add_txn(client, day, kind, amount, category=None):
    category = category or ("Ground booking" if kind == "income" else "Electricity")
    r = post(client, "/transactions/new", {"txn_date": day, "kind": kind, "amount": str(amount),
                                           "category": category}, path="/")
    assert r.status_code == 200


def seed(client):
    add_txn(client, "2026-10-05", "income", 51000)
    add_txn(client, "2026-10-09", "expense", 7000)
    add_txn(client, "2026-11-03", "income", 10000)


def tile(html, label):
    m = re.search(re.escape(label) + r'.*?kpi__value[^>]*>\s*<span class="cur">[^<]*</span>([^<]*)', html, re.S)
    return m.group(1).strip()


# ----------------------------- 1. opening balance -----------------------------

def test_dashboard_shows_opening_and_closing_for_the_month(app):
    c = admin(app)
    seed(c)
    nov = c.get("/?period=month&month=2026-11").get_data(as_text=True)
    assert tile(nov, "Opening balance") == "44,000"
    assert tile(nov, "Closing balance") == "54,000"
    oct_ = c.get("/?period=month&month=2026-10").get_data(as_text=True)
    assert tile(oct_, "Opening balance") == "0"
    assert tile(oct_, "Closing balance") == "44,000"


def test_monthly_table_has_opening_and_closing(app):
    from finance import parse_period, trend_window
    c = admin(app)
    seed(c)
    with app.app_context():
        series = {m["key"]: m for m in trend_window(parse_period({"period": "all"}))["series"]}
    assert series["2026-10"]["opening"] == 0 and series["2026-10"]["closing"] == 44000
    assert series["2026-11"]["opening"] == 44000 and series["2026-11"]["closing"] == 54000
    assert series["2026-12"]["opening"] == 54000 == series["2026-12"]["closing"]
    body = c.get("/?period=all").get_data(as_text=True)
    assert "<th class=\"num\">Opening</th>" in body and "<th class=\"num\">Closing</th>" in body


# ----------------------------- 5. graph / table toggle -------------------------

def test_trend_card_toggles_graph_and_table(app):
    body = admin(app).get("/").get_data(as_text=True)
    assert 'data-view="graph"' in body and 'data-view="table"' in body
    assert 'data-view-pane="table" hidden' in body
    assert "View as table" not in body


# ----------------------------- 2. export / backup by period ---------------------

def test_export_dialog_available_to_partner_without_backup(app):
    body = partner(app).get("/").get_data(as_text=True)
    assert 'id="exportModal"' in body and "Download Excel" in body
    assert "Download backup" not in body and 'id="mailModal"' not in body


@pytest.mark.parametrize("query,slug", [
    ("period=month&month=2026-10", "2026-10"),
    ("period=quarter&year=2026&quarter=4", "2026-Q4"),
    ("period=year&year=2026", "2026"),
    ("period=all", "all"),
])
def test_export_filename_names_the_period(app, query, slug):
    cd = admin(app).get(f"/export.xlsx?{query}").headers["Content-Disposition"]
    assert f'BailsLedgerBook-{slug}-{date.today().isoformat()}.xlsx' in cd


def test_month_backup_holds_only_that_month(app):
    c = admin(app)
    seed(c)
    r = c.get("/admin/backup.json?period=month&month=2026-10")
    assert "bails-ledger-backup-2026-10-" in r.headers["Content-Disposition"]
    data = json.loads(r.get_data(as_text=True))
    assert data["scope"]["start"] == "2026-10-01" and data["scope"]["end"] == "2026-10-31"
    assert [t["txn_date"] for t in data["transactions"]] == ["2026-10-05", "2026-10-09"]
    assert "partners" not in data


def test_quarter_and_year_backups(app):
    c = admin(app)
    seed(c)
    q = json.loads(c.get("/admin/backup.json?period=quarter&year=2026&quarter=4").get_data(as_text=True))
    assert len(q["transactions"]) == 3
    y = json.loads(c.get("/admin/backup.json?period=year&year=2025").get_data(as_text=True))
    assert y["transactions"] == []


def test_all_time_backup_is_full(app):
    c = admin(app)
    seed(c)
    for url in ("/admin/backup.json", "/admin/backup.json?period=all"):
        data = json.loads(c.get(url).get_data(as_text=True))
        assert "scope" not in data and data["partners"] and len(data["transactions"]) == 3
        assert data["mail_recipients"] == ["bailscricketground@gmail.com", "medallion76@gmail.com"]


def _restore(client, data):
    page = client.get("/").get_data(as_text=True)
    return client.post("/admin/restore", data={
        "csrf_token": _csrf(page), "confirm": "RESTORE",
        "backup_file": (BytesIO(json.dumps(data).encode()), "b.json"),
    }, content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)


def test_restoring_a_month_backup_only_replaces_that_month(app):
    from models import Transaction
    c = admin(app)
    seed(c)
    october = json.loads(c.get("/admin/backup.json?period=month&month=2026-10").get_data(as_text=True))
    # Damage October and add to November after the backup was taken.
    add_txn(c, "2026-10-20", "expense", 999)
    add_txn(c, "2026-11-20", "expense", 500)
    body = _restore(c, october)
    assert "Restored Oct 2026" in body and "Other periods were not touched" in body
    with app.app_context():
        rows = sorted((t.txn_date.isoformat(), int(t.amount)) for t in Transaction.query.all())
    assert rows == [("2026-10-05", 51000), ("2026-10-09", 7000), ("2026-11-03", 10000), ("2026-11-20", 500)]


def test_period_restore_rejects_rows_outside_its_range(app):
    from models import Transaction
    c = admin(app)
    seed(c)
    data = json.loads(c.get("/admin/backup.json?period=month&month=2026-10").get_data(as_text=True))
    data["transactions"][0]["txn_date"] = "2026-12-01"
    body = _restore(c, data)
    assert "outside the backup" in body and "Nothing was changed" in body
    with app.app_context():
        assert Transaction.query.count() == 3


def test_full_restore_keeps_partner_contacts(app):
    from backup import build_backup, restore_backup
    from models import Partner
    c = admin(app)
    with app.app_context():
        p = Partner.query.first()
        p.phone, p.email = "98450 00000", "p@example.com"
        from models import db
        db.session.commit()
        snap = build_backup()
        restore_backup(snap)
        p = Partner.query.filter_by(name=snap["partners"][0]["name"]).one()
        assert (p.phone, p.email) == ("98450 00000", "p@example.com")


# ----------------------------- 3. calendar edit / unblock -----------------------

def _block(client, day, *slots, by=""):
    return post(client, "/calendar/block", {"booking_date": day, "slot": list(slots), "booked_by": by},
                path="/calendar")


def _booking(app, day, slot):
    from models import GroundBooking
    with app.app_context():
        return GroundBooking.query.filter_by(booking_date=date.fromisoformat(day), slot=slot).one().id


def test_booking_can_be_moved_and_reentered(app):
    from models import GroundBooking
    c = admin(app)
    _block(c, "2026-11-10", "7:00 AM", by="ECL")
    bid = _booking(app, "2026-11-10", "7:00 AM")
    body = post(c, f"/calendar/{bid}/edit", {"booking_date": "2026-11-12", "slot": "2:30 PM",
                                             "booked_by": "Club", "note": "moved"}, path="/calendar")
    assert "Updated: 2:30 PM on 12 Nov 2026" in body.get_data(as_text=True)
    with app.app_context():
        b = db_get(GroundBooking, bid)
        assert (b.booking_date.isoformat(), b.slot, b.booked_by, b.note) == ("2026-11-12", "2:30 PM", "Club", "moved")


def db_get(model, ident):
    from models import db
    return db.session.get(model, ident)


def test_booking_edit_respects_clashes(app):
    c = admin(app)
    _block(c, "2026-11-10", "7:00 AM")
    _block(c, "2026-11-10", "10:45 AM")
    _block(c, "2026-11-11", "Full Day")
    bid = _booking(app, "2026-11-10", "7:00 AM")
    edit = lambda **kw: post(c, f"/calendar/{bid}/edit", kw, path="/calendar").get_data(as_text=True)
    assert "already blocked" in edit(booking_date="2026-11-10", slot="10:45 AM")
    assert "remove those first" in edit(booking_date="2026-11-10", slot="Full Day")
    assert "already blocked for the full day" in edit(booking_date="2026-11-11", slot="2:30 PM")
    # Changing only the name on the same slot is not a clash with itself.
    assert "Updated" in edit(booking_date="2026-11-10", slot="7:00 AM", booked_by="New")


def test_single_slot_booking_can_become_full_day(app):
    c = admin(app)
    _block(c, "2026-11-15", "7:00 AM")
    bid = _booking(app, "2026-11-15", "7:00 AM")
    body = post(c, f"/calendar/{bid}/edit", {"booking_date": "2026-11-15", "slot": "Full Day"},
                path="/calendar").get_data(as_text=True)
    assert "Updated: Full Day" in body


def test_calendar_shows_edit_controls_to_admin_only(app):
    c = admin(app)
    _block(c, "2026-11-10", "7:00 AM", by="ECL")
    body = c.get("/calendar?month=2026-11").get_data(as_text=True)
    assert 'id="bookingModal"' in body and "data-edit-booking" in body
    p = partner(app).get("/calendar?month=2026-11").get_data(as_text=True)
    assert "data-edit-booking" not in p and "bookingModal" not in p


def test_partner_cannot_edit_booking(app):
    c = admin(app)
    _block(c, "2026-11-10", "7:00 AM")
    bid = _booking(app, "2026-11-10", "7:00 AM")
    p = partner(app)
    r = p.post(f"/calendar/{bid}/edit", data={"csrf_token": token(p, "/calendar"),
                                              "booking_date": "2026-11-11", "slot": "7:00 AM"})
    assert r.status_code == 403


# ----------------------------- 4. partners -------------------------------------

def test_add_and_remove_partner(app):
    from models import Partner
    c = admin(app)
    body = post(c, "/partners/new", {"name": "New Partner", "equity": "5"}).get_data(as_text=True)
    assert "Added New Partner at 5%" in body
    with app.app_context():
        pid = Partner.query.filter_by(name="New Partner").one().id
    assert "There is already a partner" in post(c, "/partners/new", {"name": "new partner"}).get_data(as_text=True)
    assert "Removed New Partner" in post(c, f"/partners/{pid}/delete", {}).get_data(as_text=True)
    with app.app_context():
        assert Partner.query.filter_by(name="New Partner").first() is None


def test_partner_with_ground_payments_cannot_be_removed(app):
    from models import GroundPayment, Partner, db
    c = admin(app)
    with app.app_context():
        p = Partner.query.first()
        db.session.add(GroundPayment(detail="x", partner_id=p.id, amount=100))
        db.session.commit()
        pid = p.id
    body = post(c, f"/partners/{pid}/delete", {}).get_data(as_text=True)
    assert "can&#39;t be removed" in body or "can't be removed" in body
    with app.app_context():
        assert db.session.get(Partner, pid) is not None


def _partner_form(app, **changes):
    from models import Partner
    with app.app_context():
        rows = Partner.query.order_by(Partner.sort_order, Partner.id).all()
        form = {}
        for p in rows:
            form[f"name_{p.id}"] = p.name
            form[f"equity_{p.id}"] = str(p.equity_pct)
            form[f"active_{p.id}"] = "on"
            form[f"phone_{p.id}"] = ""
            form[f"email_{p.id}"] = ""
        first = rows[0].id
    for k, v in changes.items():
        form[f"{k}_{first}"] = v
    return form, first


def test_partner_contact_details_saved_and_shown(app):
    from models import Partner, db
    c = admin(app)
    form, pid = _partner_form(app, phone="98450 12345", email="Partner@Example.com")
    post(c, "/partners/save", form)
    with app.app_context():
        p = db.session.get(Partner, pid)
        assert (p.phone, p.email) == ("98450 12345", "partner@example.com")
    assert "98450 12345" in partner(app).get("/partners").get_data(as_text=True)


def test_partner_bad_email_rejected(app):
    c = admin(app)
    form, _ = _partner_form(app, email="not-an-email")
    assert "not a valid address" in post(c, "/partners/save", form).get_data(as_text=True)


def test_partner_edit_changes_shares(app):
    c = admin(app)
    seed(c)
    form, pid = _partner_form(app, equity="30")
    post(c, "/partners/save", form)
    body = c.get("/partners?period=month&month=2026-10").get_data(as_text=True)
    assert "Should total 100%" not in body  # computed live in JS, not server text
    assert "13,200" in body  # 30% of 44,000


def test_partner_page_has_live_calc_hooks(app):
    body = admin(app).get("/partners").get_data(as_text=True)
    assert 'id="partnersForm"' in body and "data-equity" in body and "data-share" in body
    assert "Add partner" in body


# ----------------------------- 6. email ----------------------------------------

def test_default_recipients_seeded(app):
    from models import MailRecipient
    admin(app)
    with app.app_context():
        assert [m.email for m in MailRecipient.query.order_by(MailRecipient.sort_order)] == [
            "bailscricketground@gmail.com", "medallion76@gmail.com"]


def test_mail_draft_is_written_for_the_period(app):
    c = admin(app)
    seed(c)
    d = c.get("/mail/draft?period=month&month=2026-10").get_json()
    assert d["subject"] == "Bail's Cricket Ground — Monthly ledger: Oct 2026"
    assert "Income (credit):   ₹51,000" in d["body"]
    assert "Net profit:" in d["body"] and "₹44,000" in d["body"]
    assert "Closing balance:   ₹44,000" in d["body"]
    assert d["filename"].startswith("BailsLedgerBook-2026-10-")
    assert d["recipients"] == ["bailscricketground@gmail.com", "medallion76@gmail.com"]
    q = c.get("/mail/draft?period=quarter&year=2026&quarter=4").get_json()
    assert q["subject"].endswith("Quarterly ledger: Q4 2026 (Oct–Dec)")
    y = c.get("/mail/draft?period=year&year=2026").get_json()
    assert "Yearly ledger: Year 2026" in y["subject"]


def test_partner_cannot_use_mail(app):
    p = partner(app)
    assert p.get("/mail/draft").status_code == 403
    r = p.post("/mail/send", data={"csrf_token": token(p, "/"), "recipients": "a@b.com"})
    assert r.status_code == 403


def test_send_mail_attaches_workbook(app, monkeypatch):
    import mailer
    from models import MailRecipient
    sent = []
    monkeypatch.setattr(mailer, "transport", lambda: "gmail")
    monkeypatch.setattr(mailer, "deliver", lambda msg: sent.append(msg))
    c = admin(app)
    seed(c)
    body = post(c, "/mail/send", {"period": "month", "month": "2026-10",
                                  "recipients": "bailscricketground@gmail.com; New@Example.com",
                                  "subject": "", "body": "", "remember": "on"}, path="/").get_data(as_text=True)
    assert "Emailed the Oct 2026 ledger" in body
    msg = sent[0]
    assert msg["To"] == "bailscricketground@gmail.com, new@example.com"
    assert "Monthly ledger: Oct 2026" in msg["Subject"]
    attachments = list(msg.iter_attachments())
    assert attachments[0].get_filename().startswith("BailsLedgerBook-2026-10-")
    assert attachments[0].get_payload(decode=True)[:2] == b"PK"  # a real xlsx (zip)
    with app.app_context():
        assert [m.email for m in MailRecipient.query.order_by(MailRecipient.sort_order)] == [
            "bailscricketground@gmail.com", "new@example.com"]


def test_send_mail_without_remember_keeps_saved_list(app, monkeypatch):
    import mailer
    from models import MailRecipient
    monkeypatch.setattr(mailer, "transport", lambda: "smtp")
    monkeypatch.setattr(mailer, "deliver", lambda msg: None)
    c = admin(app)
    post(c, "/mail/send", {"period": "all", "recipients": "x@example.com"}, path="/")
    with app.app_context():
        assert MailRecipient.query.count() == 2


def test_send_mail_rejects_bad_addresses(app, monkeypatch):
    import mailer
    sent = []
    monkeypatch.setattr(mailer, "transport", lambda: "gmail")
    monkeypatch.setattr(mailer, "deliver", lambda msg: sent.append(msg))
    c = admin(app)
    body = post(c, "/mail/send", {"period": "all", "recipients": "good@example.com, nope"}, path="/")
    assert "not a valid email address" in body.get_data(as_text=True) and not sent
    body = post(c, "/mail/send", {"period": "all", "recipients": " "}, path="/")
    assert "at least one email" in body.get_data(as_text=True) and not sent


def test_send_mail_unconfigured_says_so(app):
    c = admin(app)
    body = post(c, "/mail/send", {"period": "all", "recipients": "a@example.com"}, path="/").get_data(as_text=True)
    assert "isn&#39;t set up" in body or "isn't set up" in body
    page = c.get("/").get_data(as_text=True)
    assert "Open in Gmail" in page


def test_send_mail_failure_is_reported(app, monkeypatch):
    import mailer
    monkeypatch.setattr(mailer, "transport", lambda: "gmail")

    def boom(msg):
        raise mailer.MailError("Gmail refused the request (401).")
    monkeypatch.setattr(mailer, "deliver", boom)
    c = admin(app)
    body = post(c, "/mail/send", {"period": "all", "recipients": "a@example.com"}, path="/").get_data(as_text=True)
    assert "Email not sent: Gmail refused the request (401)." in body


def test_transport_detection(monkeypatch):
    sys.modules.pop("mailer", None)
    import mailer
    assert mailer.transport() == ""
    monkeypatch.setenv("SMTP_USER", "a@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    assert mailer.transport() == "smtp"
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    assert mailer.transport() == "gmail"


def test_gmail_api_request_shape(monkeypatch):
    sys.modules.pop("mailer", None)
    import base64
    import mailer
    calls = []

    def fake_post(url, data, headers):
        calls.append((url, data, headers))
        return {"access_token": "tok"} if "oauth2" in url else {"id": "1"}
    for k, v in (("GMAIL_CLIENT_ID", "cid"), ("GMAIL_CLIENT_SECRET", "sec"), ("GMAIL_REFRESH_TOKEN", "ref")):
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(mailer, "_post", fake_post)
    msg = mailer.build_message(["a@example.com"], "Subj", "Body", b"PKdata", "f.xlsx")
    mailer.deliver(msg)
    assert b"refresh_token=ref" in calls[0][1]
    assert calls[1][0].endswith("/users/me/messages/send")
    assert calls[1][2]["Authorization"] == "Bearer tok"
    raw = base64.urlsafe_b64decode(json.loads(calls[1][1])["raw"])
    assert b"Subject: Subj" in raw and b"f.xlsx" in raw


# ----------------------------- calendar export ---------------------------------

def _workbook(client, query):
    from openpyxl import load_workbook
    return load_workbook(BytesIO(client.get(f"/export.xlsx?{query}").data))


def test_workbook_has_ground_calendar_sheet(app):
    c = admin(app)
    _block(c, "2026-11-10", "7:00 AM", "2:30 PM", by="ECL")
    _block(c, "2026-11-14", "Full Day", by="Tournament")
    _block(c, "2026-12-01", "10:45 AM")
    ws = _workbook(c, "period=month&month=2026-11")["Ground Calendar"]
    assert ws["B4"].value == "Nov 2026"
    assert [ws.cell(row=r, column=4).value for r in (5, 6, 7)] == [2, 1, 5]
    # Day-by-slot grid
    assert ws["A10"].value.date() == date(2026, 11, 10)
    assert [ws.cell(row=10, column=c_).value for c_ in range(3, 7)] == ["Blocked", "Free", "Blocked", "Free"]
    assert ws["G10"].value == "ECL"
    assert [ws.cell(row=11, column=c_).value for c_ in range(3, 7)] == ["Blocked"] * 4
    # December booking is outside the month.
    values = [str(cell.value) for row in ws.iter_rows() for cell in row if cell.value]
    assert not any("2026-12-01" in v for v in values)


def test_calendar_sheet_follows_period_and_handles_empty(app):
    c = admin(app)
    _block(c, "2026-12-01", "10:45 AM")
    assert _workbook(c, "period=year&year=2026")["Ground Calendar"]["D7"].value == 1
    empty = _workbook(c, "period=month&month=2026-10")["Ground Calendar"]
    assert empty["A10"].value == "Nothing blocked in this period."
    assert _workbook(partner(app), "period=all")["Ground Calendar"]["D7"].value == 1


def test_mail_includes_calendar(app, monkeypatch):
    import mailer
    from openpyxl import load_workbook
    sent = []
    monkeypatch.setattr(mailer, "transport", lambda: "gmail")
    monkeypatch.setattr(mailer, "deliver", lambda msg: sent.append(msg))
    c = admin(app)
    _block(c, "2026-11-14", "Full Day", by="Tournament")
    d = c.get("/mail/draft?period=month&month=2026-11").get_json()
    assert "Ground calendar" in d["body"] and "Full days blocked:  1" in d["body"]
    assert "Sat 14 Nov 2026  Full Day — Tournament" in d["body"]
    assert "Nothing blocked in this period." in c.get("/mail/draft?period=month&month=2026-10").get_json()["body"]
    post(c, "/mail/send", {"period": "month", "month": "2026-11", "recipients": "a@example.com"}, path="/")
    wb = load_workbook(BytesIO(next(sent[0].iter_attachments()).get_payload(decode=True)))
    assert "Ground Calendar" in wb.sheetnames


def test_calendar_page_has_export_and_mail(app):
    body = admin(app).get("/calendar?month=2026-11").get_data(as_text=True)
    assert 'data-open-modal="exportModal"' in body and 'id="exportModal"' in body
    assert 'id="mailModal"' in body and 'value="2026-11"' in body
    p = partner(app).get("/calendar?month=2026-11").get_data(as_text=True)
    assert 'id="exportModal"' in p and 'id="mailModal"' not in p
