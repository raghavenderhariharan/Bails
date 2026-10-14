"""Ground Payment ledger: admin-only, summary rolled up from the sellers +
payments ledger, share % per seller, editable like a spreadsheet, backed up."""
import io
import json
import os
import re
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/g.db")
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


# -------------------------------- seeding ---------------------------------- #

def test_seeded_from_spreadsheet(app):
    from finance import ground_settlement
    with app.app_context():
        g = ground_settlement()
    assert g["lease"] == Decimal("3950000.00")
    assert g["closing_total"] == Decimal("3950000.00")
    assert g["paid_total"] == Decimal("1790000.00")
    assert g["remaining_total"] == Decimal("2160000.00")
    assert len(g["ex_rows"]) == 6
    assert len(g["payments"]) == 6


# --------------------------- the calculation ------------------------------- #

def test_everything_tallies(app):
    from finance import ground_settlement
    with app.app_context():
        g = ground_settlement()
    assert g["closing_matches_lease"] is True
    assert g["split_matches_lease"] is True
    # paid side balances by construction
    assert sum(r["paid"] for r in g["ex_rows"]) == g["paid_total"]
    assert sum(r["paid"] for r in g["partner_rows"]) == g["paid_total"]


def test_partner_split_is_lease_times_equity(app):
    from finance import ground_settlement
    with app.app_context():
        g = ground_settlement()
    by = {r["name"]: r for r in g["partner_rows"]}
    assert by["Vara Prasad"]["split"] == Decimal("790000.00")   # 20% of 3.95M
    assert by["Bhanu"]["split"] == Decimal("395000.00")          # 10%


def test_paid_amounts_match_the_spreadsheet(app):
    from finance import ground_settlement
    with app.app_context():
        g = ground_settlement()
    byp = {r["name"]: r for r in g["partner_rows"]}
    assert byp["Raghavender Hariharan"]["paid"] == Decimal("790000.00")
    assert byp["Raghavender Hariharan"]["remaining"] == Decimal("0.00")
    assert byp["Aravind"]["paid"] == Decimal("500000.00")
    bye = {r["name"]: r for r in g["ex_rows"]}
    assert bye["Bhamandlapally Kishore"]["paid"] == Decimal("600000.00")
    assert bye["Nethula Nirosha / Nagaraju"]["paid"] == Decimal("390000.00")
    assert bye["Kallem Sridhar Reddy"]["remaining"] == Decimal("0.00")


def test_a_new_payment_updates_both_sides(app):
    """Recording a payment raises the seller's paid and the payer's paid together."""
    from finance import ground_settlement
    from models import ExPartner, Partner
    client = admin(app)
    with app.app_context():
        ex = ExPartner.query.filter_by(name="Naresh Kumar Jain").first()
        payer = Partner.query.filter_by(name="Vara Prasad").first()
        ex_id, payer_id = ex.id, payer.id
    page = client.get("/ground").get_data(as_text=True)
    client.post("/ground/payment/new", data={
        "csrf_token": _csrf(page), "detail": "Partner Payment - 6",
        "ex_partner_id": ex_id, "partner_id": payer_id,
        "txn_number": "TESTUTR", "txn_date": "2026-10-20", "amount": "100000",
        "next": "/ground"}, follow_redirects=True)
    with app.app_context():
        g = ground_settlement()
    byp = {r["name"]: r for r in g["partner_rows"]}
    bye = {r["name"]: r for r in g["ex_rows"]}
    assert byp["Vara Prasad"]["paid"] == Decimal("100000.00")
    assert bye["Naresh Kumar Jain"]["paid"] == Decimal("100000.00")
    assert g["paid_total"] == Decimal("1890000.00")
    # still tallies
    assert sum(r["paid"] for r in g["ex_rows"]) == sum(r["paid"] for r in g["partner_rows"])


# ------------------------------- editing ----------------------------------- #

def test_save_lease_and_closing_amounts(app):
    from finance import ground_settlement
    from models import ExPartner
    client = admin(app)
    with app.app_context():
        rows = ExPartner.query.order_by(ExPartner.sort_order).all()
        ids = [e.id for e in rows]
    page = client.get("/ground").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/ground", "lease_value": "4,000,000"}
    for e in rows:
        data[f"sname_{e.id}"] = e.name
        data[f"closing_{e.id}"] = str(int(e.closing_amount))
        data[f"account_{e.id}"] = e.account_number
    # bump the first seller's closing amount by 50,000 to keep the total at 4.0M
    data[f"closing_{ids[0]}"] = str(int(rows[0].closing_amount) + 50000)
    client.post("/ground/sellers/save", data=data, follow_redirects=True)
    with app.app_context():
        g = ground_settlement()
    assert g["lease"] == Decimal("4000000.00")
    assert g["closing_total"] == Decimal("4000000.00")
    assert g["closing_matches_lease"] is True


def test_save_rejects_bad_lease(app):
    from finance import ground_settlement
    from models import ExPartner
    client = admin(app)
    with app.app_context():
        rows = ExPartner.query.all()
    page = client.get("/ground").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/ground", "lease_value": "abc"}
    for e in rows:
        data[f"sname_{e.id}"] = e.name; data[f"closing_{e.id}"] = str(int(e.closing_amount))
    body = client.post("/ground/sellers/save", data=data, follow_redirects=True).get_data(as_text=True)
    assert "Lease value must be a number" in body
    with app.app_context():
        assert ground_settlement()["lease"] == Decimal("3950000.00")   # unchanged


def test_payment_edit_and_delete(app):
    from finance import ground_settlement
    from models import GroundPayment, db
    client = admin(app)
    with app.app_context():
        p = GroundPayment.query.order_by(GroundPayment.id).first()
        pid, ex_id, partner_id = p.id, p.ex_partner_id, p.partner_id
    page = client.get("/ground").get_data(as_text=True)
    client.post(f"/ground/payment/{pid}/edit", data={
        "csrf_token": _csrf(page), "detail": "Token Advance (revised)",
        "ex_partner_id": ex_id, "partner_id": partner_id,
        "txn_number": "X", "txn_date": "2026-09-09", "amount": "150000",
        "next": "/ground"}, follow_redirects=True)
    with app.app_context():
        assert db.session.get(GroundPayment, pid).amount == Decimal("150000.00")
    page = client.get("/ground").get_data(as_text=True)
    client.post(f"/ground/payment/{pid}/delete",
                data={"csrf_token": _csrf(page), "next": "/ground"}, follow_redirects=True)
    with app.app_context():
        assert db.session.get(GroundPayment, pid) is None
        assert ground_settlement()["paid_total"] == Decimal("1690000.00")  # 1.79M - 100k token


def test_payment_requires_both_sides(app):
    from models import GroundPayment
    client = admin(app)
    page = client.get("/ground").get_data(as_text=True)
    for bad in ({"detail": "X", "partner_id": "1", "amount": "5"},          # no ex
                {"detail": "X", "ex_partner_id": "1", "amount": "5"},        # no payer
                {"ex_partner_id": "1", "partner_id": "1", "amount": "5"}):   # no detail
        page = client.get("/ground").get_data(as_text=True)
        client.post("/ground/payment/new",
                    data=dict(bad, csrf_token=_csrf(page), next="/ground"), follow_redirects=True)
    with app.app_context():
        assert GroundPayment.query.count() == 6   # nothing added


# ---------------------------- admin-only access ---------------------------- #

def test_ground_tab_is_admin_only(app):
    assert partner(app).get("/ground").status_code == 403
    assert admin(app).get("/ground").status_code == 200


def test_partner_cannot_write_ground(app):
    from models import GroundPayment, ExPartner
    client = partner(app)
    page = client.get("/").get_data(as_text=True)
    with app.app_context():
        ids = [e.id for e in ExPartner.query.all()]
    assert client.post("/ground/payment/new", data={
        "csrf_token": _csrf(page), "detail": "hack", "ex_partner_id": ids[0],
        "partner_id": "1", "amount": "1", "next": "/ground"}).status_code == 403
    assert client.post("/ground/sellers/save", data={"csrf_token": _csrf(page), "next": "/ground",
                                             "lease_value": "1"}).status_code == 403


def test_nav_link_admin_only(app):
    assert 'href="/ground"' in admin(app).get("/").get_data(as_text=True)
    assert "/ground" not in partner(app).get("/").get_data(as_text=True)


def test_page_shows_the_ledger(app):
    body = admin(app).get("/ground").get_data(as_text=True)
    assert "Ground Payment Ledger" in body
    assert "Everything tallies" in body
    assert "Bhamandlapally Kishore" in body and "Vara Prasad" in body
    assert "39,50,000" in body            # lease value, Indian grouping


# --------------------------------- backup ---------------------------------- #

def test_backup_includes_ground(app):
    data = json.loads(admin(app).get("/admin/backup.json").get_data(as_text=True))
    assert data["format"] >= 4
    assert data["summary"]["ex_partners"] == 6
    assert data["summary"]["ground_payments"] == 6
    gp = data["ground_payments"][0]
    assert gp["paid_to"] and gp["paid_by"]   # linked by name


def test_backup_round_trip_preserves_ground(app):
    from backup import build_backup, restore_backup
    from finance import ground_settlement
    with app.app_context():
        before = build_backup()
        restore_backup(before)
        after = build_backup()
        assert after["ex_partners"] == before["ex_partners"]
        assert after["ground_payments"] == before["ground_payments"]
        assert ground_settlement()["paid_total"] == Decimal("1790000.00")


def test_old_backup_without_ground_still_restores(app):
    from backup import restore_backup
    from models import ExPartner
    legacy = {
        "format": 3,
        "partners": [{"name": "P", "equity_pct": "100", "sort_order": 0, "is_active": True}],
        "transactions": [], "settings": {"opening_balance": "0"},
    }
    with app.app_context():
        counts = restore_backup(legacy)
        assert counts["ex_partners"] == 0
        assert ExPartner.query.count() == 0


# ------------------------------- share % ----------------------------------- #

def test_sellers_seeded_with_share_pct(app):
    from finance import ground_settlement
    with app.app_context():
        g = ground_settlement()
    shares = {r["name"]: r["share"] for r in g["ex_rows"]}
    assert shares["Bhamandlapally Kishore"] == Decimal("20")
    assert shares["Kallem Sridhar Reddy"] == Decimal("10")
    assert shares["Santosh Gadre"] == Decimal("10")
    assert g["share_total"] == Decimal("100.00")
    assert g["shares_balanced"] is True


def test_summary_tiles_roll_up_from_the_ledger(app):
    """The top tiles must equal the ledger's own totals."""
    from finance import ground_settlement
    client = admin(app)
    body = client.get("/ground").get_data(as_text=True)
    with app.app_context():
        g = ground_settlement()
    assert g["tally_ok"] is True
    assert "39,50,000" in body                 # lease value
    assert "17,90,000" in body                 # paid to date = sum of payments
    assert "21,60,000" in body                 # remaining = lease - paid
    assert "Investment Summary" not in body    # the old table is gone


def _seller_form(app, client, overrides=None):
    from models import ExPartner
    with app.app_context():
        rows = ExPartner.query.order_by(ExPartner.sort_order).all()
        page = client.get("/ground").get_data(as_text=True)
        data = {"csrf_token": _csrf(page), "next": "/ground", "lease_value": "3950000"}
        for e in rows:
            data[f"sname_{e.id}"] = e.name
            data[f"share_{e.id}"] = str(e.share_pct)
            data[f"closing_{e.id}"] = str(int(e.closing_amount))
            data[f"account_{e.id}"] = e.account_number
        ids = [e.id for e in rows]
    for key, value in (overrides or {}).items():
        data[key.format(*ids)] = value
    return data


def test_share_pct_is_saved(app):
    from finance import ground_settlement
    client = admin(app)
    data = _seller_form(app, client, {"share_{0}": "25", "share_{1}": "15"})
    client.post("/ground/sellers/save", data=data, follow_redirects=True)
    with app.app_context():
        g = ground_settlement()
    assert g["ex_rows"][0]["share"] == Decimal("25")
    assert g["ex_rows"][1]["share"] == Decimal("15")
    assert g["share_total"] == Decimal("100.00")   # 25+15+20+20+10+10


def test_unbalanced_shares_flag_the_tally(app):
    from finance import ground_settlement
    client = admin(app)
    data = _seller_form(app, client, {"share_{0}": "30"})          # 110% total
    body = client.post("/ground/sellers/save", data=data,
                       follow_redirects=True).get_data(as_text=True)
    with app.app_context():
        g = ground_settlement()
    assert g["shares_balanced"] is False
    assert g["tally_ok"] is False
    assert "110.00%" in body and "not 100%" in body


def test_invalid_share_pct_is_rejected(app):
    from finance import ground_settlement
    client = admin(app)
    data = _seller_form(app, client, {"share_{0}": "150"})
    body = client.post("/ground/sellers/save", data=data,
                       follow_redirects=True).get_data(as_text=True)
    assert "between 0 and 100" in body
    with app.app_context():
        assert ground_settlement()["ex_rows"][0]["share"] == Decimal("20")   # unchanged


def test_backup_carries_share_pct(app):
    data = json.loads(admin(app).get("/admin/backup.json").get_data(as_text=True))
    assert data["format"] >= 7
    assert "ground_investors" not in data
    shares = {e["name"]: e["share_pct"] for e in data["ex_partners"]}
    assert shares["Bhamandlapally Kishore"] == "20.000"
    from backup import build_backup, restore_backup
    with app.app_context():
        before = build_backup()
        restore_backup(before)
        assert build_backup()["ex_partners"] == before["ex_partners"]


def test_share_pct_column_added_to_an_existing_table(tmp_path, monkeypatch):
    """A database from before this change gains ex_partners.share_pct on boot."""
    import sqlite3
    dbfile = tmp_path / "old.db"
    con = sqlite3.connect(dbfile)
    con.executescript(
        "CREATE TABLE ex_partners (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL UNIQUE,"
        " closing_amount NUMERIC(12,2) NOT NULL, account_number VARCHAR(255) NOT NULL DEFAULT '',"
        " sort_order INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO ex_partners (name, closing_amount) VALUES ('Old Seller', 100000);"
    )
    con.commit(); con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    for module in ("config", "models", "finance", "exporter", "backup", "app"):
        sys.modules.pop(module, None)
    import app  # noqa: F401 - bootstrap runs the migration
    cols = [r[1] for r in sqlite3.connect(dbfile).execute("PRAGMA table_info(ex_partners)")]
    assert "share_pct" in cols
    assert sqlite3.connect(dbfile).execute("SELECT COUNT(*) FROM ex_partners").fetchone()[0] == 1


def test_old_backup_with_investment_summary_still_restores(app):
    """Format-6 backups carried ground_investors; they must restore cleanly."""
    from backup import restore_backup
    from models import ExPartner
    legacy = {
        "format": 6, "partners": [], "transactions": [], "settings": {},
        "ground_investors": [{"name": "X", "shareholding": "20", "investment_amount": "7.9"}],
        "ex_partners": [{"name": "Seller A", "closing_amount": "100000.00", "sort_order": 0}],
        "ground_payments": [],
    }
    with app.app_context():
        restore_backup(legacy)
        ex = ExPartner.query.one()
        assert ex.name == "Seller A" and ex.share_pct == Decimal("0")
