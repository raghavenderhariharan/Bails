"""Watchman salary settlement: calculation, role-gating, petty cash, backup."""
import os
import re
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/w.db")
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


@pytest.fixture()
def petty(app):
    """Watchman 1 takes 2000 + 1500; Watchman 2 takes 500 — all in Oct 2026."""
    from models import Watchman, WatchmanPettyCash, db
    with app.app_context():
        w1, w2 = Watchman.query.order_by(Watchman.sort_order).all()
        db.session.add_all([
            WatchmanPettyCash(watchman_id=w1.id, entry_date=date(2026, 10, 5), amount=Decimal("2000"), note="advance"),
            WatchmanPettyCash(watchman_id=w1.id, entry_date=date(2026, 10, 18), amount=Decimal("1500"), note="food"),
            WatchmanPettyCash(watchman_id=w2.id, entry_date=date(2026, 10, 10), amount=Decimal("500"), note="advance"),
        ])
        db.session.commit()
        return (w1.id, w2.id)
    return app


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


# ------------------------------- seeding ----------------------------------- #

def test_two_watchmen_seeded_at_20000(app):
    from models import Watchman
    with app.app_context():
        ws = Watchman.query.order_by(Watchman.sort_order).all()
        assert len(ws) == 2
        assert all(w.monthly_salary == Decimal("20000.00") for w in ws)
        assert all(w.is_active for w in ws)


# ----------------------------- the calculation ----------------------------- #

def test_net_payable_is_salary_minus_petty_cash(app, petty):
    from finance import parse_period, watchman_settlement
    with app.app_context():
        s = watchman_settlement(parse_period({"period": "month", "month": "2026-10"}))
    assert s["months"] == 1
    assert s["rows"][0]["salary"] == Decimal("20000.00")
    assert s["rows"][0]["petty"] == Decimal("3500.00")
    assert s["rows"][0]["net"] == Decimal("16500.00")
    assert s["rows"][1]["net"] == Decimal("19500.00")
    assert s["salary_total"] == Decimal("40000.00")
    assert s["petty_total"] == Decimal("4000.00")
    assert s["net_total"] == Decimal("36000.00")


def test_salary_scales_with_the_period_length(app, petty):
    from finance import parse_period, watchman_settlement
    with app.app_context():
        q = watchman_settlement(parse_period({"period": "quarter", "year": "2026", "quarter": "4"}))
    assert q["months"] == 3
    assert q["rows"][0]["salary"] == Decimal("60000.00")      # 3 × 20,000
    assert q["rows"][0]["net"] == Decimal("56500.00")          # 60,000 − 3,500


def test_petty_cash_is_scoped_to_the_period(app, petty):
    from finance import parse_period, watchman_settlement
    with app.app_context():
        nov = watchman_settlement(parse_period({"period": "month", "month": "2026-11"}))
    assert nov["petty_total"] == Decimal("0.00")
    assert nov["rows"][0]["net"] == Decimal("20000.00")         # full salary, nothing taken


def test_salary_change_flows_through(app, petty):
    from finance import parse_period, watchman_settlement
    from models import Watchman, db
    with app.app_context():
        w1 = Watchman.query.order_by(Watchman.sort_order).first()
        w1.monthly_salary = Decimal("25000")
        db.session.commit()
        s = watchman_settlement(parse_period({"period": "month", "month": "2026-10"}))
    assert s["rows"][0]["salary"] == Decimal("25000.00")
    assert s["rows"][0]["net"] == Decimal("21500.00")           # 25,000 − 3,500


# -------------------------------- the page --------------------------------- #

def test_watchmen_page_shows_the_calculation(app, petty):
    body = admin(app).get("/watchmen?period=month&month=2026-10").get_data(as_text=True)
    assert "Watchmen" in body
    assert "16,500" in body and "19,500" in body   # net per watchman
    assert "3,500" in body                          # petty deducted
    assert "advance" in body and "food" in body     # the entries are listed


def test_partner_sees_the_figures_but_no_controls(app, petty):
    body = partner(app).get("/watchmen?period=month&month=2026-10").get_data(as_text=True)
    assert "16,500" in body                          # can read
    assert "Add petty cash" not in body
    assert "data-edit-petty" not in body
    assert "Save watchmen" not in body
    assert "pettyModal" not in body


# --------------------------- petty cash writes ----------------------------- #

def test_admin_adds_petty_cash(app):
    client = admin(app)
    from models import Watchman
    with app.app_context():
        wid = Watchman.query.order_by(Watchman.sort_order).first().id
    page = client.get("/watchmen").get_data(as_text=True)
    client.post("/watchmen/petty/new", data={
        "csrf_token": _csrf(page), "watchman_id": wid, "entry_date": "2026-10-07",
        "amount": "750", "note": "torch batteries", "next": "/watchmen"}, follow_redirects=True)
    from models import WatchmanPettyCash
    with app.app_context():
        assert WatchmanPettyCash.query.count() == 1
        assert WatchmanPettyCash.query.first().amount == Decimal("750.00")


def test_partner_cannot_add_petty_cash(app):
    client = partner(app)
    from models import Watchman
    with app.app_context():
        wid = Watchman.query.first().id
    page = client.get("/watchmen").get_data(as_text=True)
    r = client.post("/watchmen/petty/new", data={
        "csrf_token": _csrf(page), "watchman_id": wid, "entry_date": "2026-10-07",
        "amount": "750", "next": "/watchmen"})
    assert r.status_code == 403
    from models import WatchmanPettyCash
    with app.app_context():
        assert WatchmanPettyCash.query.count() == 0


def test_petty_cash_edit_and_delete(app, petty):
    client = admin(app)
    from models import WatchmanPettyCash
    with app.app_context():
        eid = WatchmanPettyCash.query.order_by(WatchmanPettyCash.id).first().id
        wid = WatchmanPettyCash.query.get(eid).watchman_id
    page = client.get("/watchmen").get_data(as_text=True)
    client.post(f"/watchmen/petty/{eid}/edit", data={
        "csrf_token": _csrf(page), "watchman_id": wid, "entry_date": "2026-10-05",
        "amount": "2500", "note": "advance (revised)", "next": "/watchmen"}, follow_redirects=True)
    with app.app_context():
        from models import WatchmanPettyCash as W, db
        assert db.session.get(W, eid).amount == Decimal("2500.00")
    page = client.get("/watchmen").get_data(as_text=True)
    client.post(f"/watchmen/petty/{eid}/delete",
                data={"csrf_token": _csrf(page), "next": "/watchmen"}, follow_redirects=True)
    with app.app_context():
        from models import WatchmanPettyCash as W, db
        assert db.session.get(W, eid) is None


def test_invalid_petty_cash_is_rejected(app):
    client = admin(app)
    from models import Watchman, WatchmanPettyCash
    with app.app_context():
        wid = Watchman.query.first().id
    for payload in (
        {"watchman_id": wid, "entry_date": "2026-10-07", "amount": "-5"},
        {"watchman_id": wid, "entry_date": "2026-10-07", "amount": "0"},
        {"watchman_id": wid, "entry_date": "bad", "amount": "5"},
        {"watchman_id": 9999, "entry_date": "2026-10-07", "amount": "5"},
    ):
        page = client.get("/watchmen").get_data(as_text=True)
        client.post("/watchmen/petty/new",
                    data=dict(payload, csrf_token=_csrf(page), next="/watchmen"), follow_redirects=True)
    with app.app_context():
        assert WatchmanPettyCash.query.count() == 0


def test_admin_edits_salary(app):
    client = admin(app)
    from models import Watchman
    with app.app_context():
        ids = [w.id for w in Watchman.query.order_by(Watchman.sort_order).all()]
    page = client.get("/watchmen").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/watchmen"}
    for i, wid in enumerate(ids):
        data[f"name_{wid}"] = ["Ramesh", "Suresh"][i]
        data[f"salary_{wid}"] = "22000" if i == 0 else "20000"
        data[f"active_{wid}"] = "on"
    client.post("/watchmen/save", data=data, follow_redirects=True)
    with app.app_context():
        w = Watchman.query.order_by(Watchman.sort_order).first()
        assert w.name == "Ramesh" and w.monthly_salary == Decimal("22000.00")


def test_watchman_names_can_be_swapped(app):
    client = admin(app)
    from models import Watchman
    with app.app_context():
        ids = [w.id for w in Watchman.query.order_by(Watchman.sort_order).all()]
    page = client.get("/watchmen").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/watchmen"}
    names = ["Alpha", "Beta"]
    for i, wid in enumerate(ids):
        data[f"name_{wid}"] = names[i]; data[f"salary_{wid}"] = "20000"; data[f"active_{wid}"] = "on"
    client.post("/watchmen/save", data=data, follow_redirects=True)
    page = client.get("/watchmen").get_data(as_text=True)
    swapped = dict(data, csrf_token=_csrf(page))
    swapped[f"name_{ids[0]}"] = "Beta"; swapped[f"name_{ids[1]}"] = "Alpha"
    r = client.post("/watchmen/save", data=swapped, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        order = [w.name for w in Watchman.query.order_by(Watchman.sort_order).all()]
        assert order == ["Beta", "Alpha"]


# --------------------------------- backup ---------------------------------- #

def test_backup_includes_watchmen(app, petty):
    import json
    body = admin(app).get("/admin/backup.json").get_data(as_text=True)
    data = json.loads(body)
    assert data["format"] >= 2
    assert data["summary"]["watchmen"] == 2
    assert data["summary"]["watchman_petty_cash"] == 3
    assert len(data["watchmen"]) == 2
    assert len(data["watchman_petty_cash"]) == 3
    assert data["watchmen"][0]["monthly_salary"] == "20000.00"


def test_backup_round_trip_preserves_watchmen(app, petty):
    from backup import build_backup, restore_backup
    with app.app_context():
        before = build_backup()
        restore_backup(before)
        after = build_backup()
        assert after["watchmen"] == before["watchmen"]
        assert after["watchman_petty_cash"] == before["watchman_petty_cash"]


def test_old_format_1_backup_restores_without_watchmen_key(app):
    """A pre-watchman backup must still restore cleanly."""
    from backup import restore_backup
    from models import Transaction
    legacy = {
        "format": 1,
        "partners": [{"name": "P", "equity_pct": "100", "sort_order": 0, "is_active": True}],
        "transactions": [{"txn_date": "2026-10-02", "kind": "income", "category": "X", "amount": "100"}],
        "settings": {"opening_balance": "0"},
    }
    with app.app_context():
        counts = restore_backup(legacy)
        assert counts["watchmen"] == 0
        assert Transaction.query.count() == 1


# ------------------------------- navigation -------------------------------- #

def test_watchmen_tab_in_nav(app):
    body = admin(app).get("/").get_data(as_text=True)
    assert 'href="/watchmen"' in body or "/watchmen" in body
    assert ">Watchmen<" in body or "Watchmen" in body
