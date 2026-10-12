"""Ground Investment Summary: admin-only, pending/totals auto-computed in lakh,
reconciliation flagged, editable like a spreadsheet, backed up."""
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

def test_seeded_from_image(app):
    from finance import investment_summary
    with app.app_context():
        s = investment_summary()
    assert len(s["rows"]) == 6
    assert s["stated_total"] == Decimal("39.50")
    assert [r["name"] for r in s["rows"]] == [
        "Kishore", "Naresh Jain", "Bhanu K", "Nagaraju", "Sridhar Reddy", "Wowinsite LLP"]
    by = {r["name"]: r for r in s["rows"]}
    assert by["Bhanu K"]["investment"] == Decimal("8.85")
    assert by["Sridhar Reddy"]["adjustment"] == Decimal("-0.95")


# ----------------------------- the calculation ----------------------------- #

def test_totals_match_the_image(app):
    from finance import investment_summary
    with app.app_context():
        s = investment_summary()
    assert s["shareholding_total"] == Decimal("100.00")
    assert s["received_total"] == Decimal("17.90")
    assert s["pending_total"] == Decimal("22.55")
    assert s["adjustment_total"] == Decimal("0.00")
    assert s["investment_total"] == Decimal("40.45")   # listed sum (Bhanu +0.95)


def test_pending_is_investment_minus_received(app):
    from finance import investment_summary
    with app.app_context():
        by = {r["name"]: r for r in investment_summary()["rows"]}
    assert by["Kishore"]["pending"] == Decimal("1.90")
    assert by["Naresh Jain"]["pending"] == Decimal("7.90")
    assert by["Bhanu K"]["pending"] == Decimal("3.85")
    assert by["Nagaraju"]["pending"] == Decimal("4.00")
    assert by["Sridhar Reddy"]["pending"] == Decimal("0.95")
    assert by["Wowinsite LLP"]["pending"] == Decimal("3.95")


def test_reconciliation_gap_is_flagged(app):
    """Listed 40.45 vs stated 39.50 differ by 0.95 (adjustments net to zero)."""
    from finance import investment_summary
    with app.app_context():
        s = investment_summary()
    assert s["shareholding_ok"] is True
    assert s["adjustment_balanced"] is True
    assert s["reconcile_gap"] == Decimal("0.95")
    assert s["investment_matches_stated"] is False
    assert s["tally_ok"] is False


# ------------------------------- editing ----------------------------------- #

def test_edit_a_row_updates_pending_and_totals(app):
    from finance import investment_summary
    from models import GroundInvestor
    client = admin(app)
    with app.app_context():
        rows = GroundInvestor.query.order_by(GroundInvestor.sort_order).all()
    page = client.get("/ground").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/ground", "stated_total": "39.5"}
    for g in rows:
        data[f"name_{g.id}"] = g.name
        data[f"share_{g.id}"] = str(g.shareholding)
        data[f"invest_{g.id}"] = str(g.investment_amount)
        data[f"received_{g.id}"] = str(g.amount_received)
        data[f"adjust_{g.id}"] = str(g.adjustment)
        data[f"details_{g.id}"] = g.payment_details
        data[f"notes_{g.id}"] = g.status_notes
    # Naresh Jain pays in 7.9 (fully received)
    naresh = next(g for g in rows if g.name == "Naresh Jain")
    data[f"received_{naresh.id}"] = "7.9"
    client.post("/ground/save", data=data, follow_redirects=True)
    with app.app_context():
        s = investment_summary()
        by = {r["name"]: r for r in s["rows"]}
    assert by["Naresh Jain"]["pending"] == Decimal("0.00")
    assert s["received_total"] == Decimal("25.80")   # 17.9 + 7.9
    assert s["pending_total"] == Decimal("14.65")


def test_save_in_lakh_supports_decimals_and_negatives(app):
    from finance import investment_summary
    from models import GroundInvestor
    client = admin(app)
    with app.app_context():
        rows = GroundInvestor.query.order_by(GroundInvestor.sort_order).all()
        sridhar = next(g for g in rows if g.name == "Sridhar Reddy").id
    page = client.get("/ground").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/ground", "stated_total": "39.5"}
    for g in rows:
        data[f"name_{g.id}"] = g.name; data[f"share_{g.id}"] = str(g.shareholding)
        data[f"invest_{g.id}"] = str(g.investment_amount); data[f"received_{g.id}"] = str(g.amount_received)
        data[f"adjust_{g.id}"] = str(g.adjustment)
    data[f"adjust_{sridhar}"] = "-1.25"   # negative adjustment accepted
    client.post("/ground/save", data=data, follow_redirects=True)
    with app.app_context():
        from models import GroundInvestor as G, db
        assert db.session.get(G, sridhar).adjustment == Decimal("-1.25")


def test_add_and_remove_investor(app):
    from models import GroundInvestor
    client = admin(app)
    page = client.get("/ground").get_data(as_text=True)
    client.post("/ground/investor/new",
                data={"csrf_token": _csrf(page), "name": "New Investor", "next": "/ground"},
                follow_redirects=True)
    with app.app_context():
        g = GroundInvestor.query.filter_by(name="New Investor").first()
        assert g is not None
        gid = g.id
    page = client.get("/ground").get_data(as_text=True)
    client.post(f"/ground/investor/{gid}/delete",
                data={"csrf_token": _csrf(page), "next": "/ground"}, follow_redirects=True)
    with app.app_context():
        from models import GroundInvestor as G, db
        assert db.session.get(G, gid) is None


def test_duplicate_investor_rejected(app):
    from models import GroundInvestor
    client = admin(app)
    page = client.get("/ground").get_data(as_text=True)
    body = client.post("/ground/investor/new",
                       data={"csrf_token": _csrf(page), "name": "Kishore", "next": "/ground"},
                       follow_redirects=True).get_data(as_text=True)
    assert "already exists" in body
    with app.app_context():
        assert GroundInvestor.query.filter_by(name="Kishore").count() == 1


def test_bad_shareholding_rejected(app):
    from finance import investment_summary
    from models import GroundInvestor
    client = admin(app)
    with app.app_context():
        rows = GroundInvestor.query.all()
        first = rows[0].id
    page = client.get("/ground").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/ground", "stated_total": "39.5"}
    for g in rows:
        data[f"name_{g.id}"] = g.name; data[f"share_{g.id}"] = str(g.shareholding)
        data[f"invest_{g.id}"] = str(g.investment_amount); data[f"received_{g.id}"] = str(g.amount_received)
        data[f"adjust_{g.id}"] = str(g.adjustment)
    data[f"share_{first}"] = "150"
    body = client.post("/ground/save", data=data, follow_redirects=True).get_data(as_text=True)
    assert "between 0 and 100" in body


# ---------------------------- admin-only access ---------------------------- #

def test_tab_is_admin_only(app):
    assert partner(app).get("/ground").status_code == 403
    assert admin(app).get("/ground").status_code == 200


def test_partner_cannot_write(app):
    client = partner(app)
    page = client.get("/").get_data(as_text=True)
    assert client.post("/ground/save", data={"csrf_token": _csrf(page), "next": "/ground",
                                             "stated_total": "1"}).status_code == 403
    assert client.post("/ground/investor/new", data={"csrf_token": _csrf(page), "name": "X",
                                                     "next": "/ground"}).status_code == 403


def test_nav_link_admin_only(app):
    assert 'href="/ground"' in admin(app).get("/").get_data(as_text=True)
    assert "/ground" not in partner(app).get("/").get_data(as_text=True)


def test_page_renders_the_summary(app):
    body = admin(app).get("/ground").get_data(as_text=True)
    assert "Investment Summary" in body
    assert "Kishore" in body and "Wowinsite LLP" in body
    assert "39.5" in body            # stated total in lakh
    assert "Needs reconciliation" in body
    assert "require reconciliation" in body


# --------------------------------- backup ---------------------------------- #

def test_backup_includes_ground_investors(app):
    data = json.loads(admin(app).get("/admin/backup.json").get_data(as_text=True))
    assert data["format"] >= 5
    assert data["summary"]["ground_investors"] == 6
    g = {r["name"]: r for r in data["ground_investors"]}
    assert g["Bhanu K"]["investment_amount"] == "8.85"
    assert g["Sridhar Reddy"]["adjustment"] == "-0.95"


def test_backup_round_trip_preserves_ground(app):
    from backup import build_backup, restore_backup
    from finance import investment_summary
    with app.app_context():
        before = build_backup()
        restore_backup(before)
        after = build_backup()
        assert after["ground_investors"] == before["ground_investors"]
        assert investment_summary()["pending_total"] == Decimal("22.55")


def test_old_backup_without_ground_restores(app):
    from backup import restore_backup
    from models import GroundInvestor
    legacy = {"format": 3, "partners": [], "transactions": [], "settings": {}}
    with app.app_context():
        counts = restore_backup(legacy)
        assert counts["ground_investors"] == 0
        assert GroundInvestor.query.count() == 0
