"""Admin database backup: download, role-gating, completeness, and restore."""
import json
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/b.db")
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

    from models import EXPENSE, INCOME, Transaction, db
    rows = [
        ("2026-10-02", INCOME, "Ground booking", "7:00 AM slot", "Customer", "7000", "morning"),
        ("2026-10-03", INCOME, "ECL booking", "All slots", "ECL", "8000", ""),
        ("2026-10-04", EXPENSE, "Market expenses", "Allowance", "Groundsman 1", "1000", "weekly"),
    ]
    with app_module.app.app_context():
        for d, kind, cat, desc, party, amt, notes in rows:
            db.session.add(Transaction(txn_date=date.fromisoformat(d), kind=kind, category=cat,
                                       description=desc, party=party, amount=Decimal(amt), notes=notes))
        db.session.commit()
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


# ------------------------------ route access ------------------------------- #

def test_admin_can_download_backup(app):
    r = admin(app).get("/admin/backup.json")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/json")
    assert "attachment" in r.headers["Content-Disposition"]
    assert ".json" in r.headers["Content-Disposition"]
    data = json.loads(r.get_data(as_text=True))
    assert data["app"] == "Bails Cricket Ground Ledger"


def test_partner_cannot_download_backup(app):
    assert partner(app).get("/admin/backup.json").status_code == 403


def test_backup_requires_login(app):
    r = app.test_client().get("/admin/backup.json")
    assert r.status_code in (301, 302, 308)
    assert "/login" in r.headers["Location"]


# ------------------------------ completeness ------------------------------- #

def test_backup_contains_everything(app):
    data = json.loads(admin(app).get("/admin/backup.json").get_data(as_text=True))
    assert data["summary"]["transactions"] == 3
    assert data["summary"]["partners"] == 6
    assert data["summary"]["income"] == "15000.00"
    assert data["summary"]["expense"] == "1000.00"
    assert data["summary"]["net"] == "14000.00"
    assert len(data["transactions"]) == 3
    assert len(data["partners"]) == 6
    assert "opening_balance" in data["settings"]
    # Every field of a transaction is preserved.
    ecl = next(t for t in data["transactions"] if t["category"] == "ECL booking")
    assert ecl["amount"] == "8000.00" and ecl["party"] == "ECL" and ecl["kind"] == "income"


def test_money_is_strings_not_floats(app):
    raw = admin(app).get("/admin/backup.json").get_data(as_text=True)
    data = json.loads(raw)
    for t in data["transactions"]:
        assert isinstance(t["amount"], str)
    for p in data["partners"]:
        assert isinstance(p["equity_pct"], str)


# -------------------------------- restore ---------------------------------- #

def test_backup_restores_byte_for_byte(app):
    """Download, wipe, restore, and the backup of the restored DB must match."""
    from backup import build_backup, restore_backup

    original = json.loads(admin(app).get("/admin/backup.json").get_data(as_text=True))

    with app.app_context():
        counts = restore_backup(original)
        assert counts["transactions"] == 3
        assert counts["partners"] == 6
        # A fresh backup of the restored data equals the original (bar the timestamp).
        again = build_backup()
        for key in ("summary", "settings", "partners", "transactions"):
            assert again[key] == original[key], f"{key} changed across a restore round-trip"


def test_restore_is_atomic_on_bad_data(app):
    """A malformed row must leave the existing data untouched."""
    from backup import restore_backup
    from models import Transaction

    bad = {
        "format": 1, "partners": [{"name": "X", "equity_pct": "100", "sort_order": 0, "is_active": True}],
        "transactions": [{"txn_date": "2026-10-09", "kind": "banana", "amount": "5"}],
        "settings": {},
    }
    with app.app_context():
        before = Transaction.query.count()
        with pytest.raises(ValueError):
            restore_backup(bad)
        app.extensions["sqlalchemy"].session.rollback()
        assert Transaction.query.count() == before, "a bad restore changed the data"


def test_restore_rejects_a_non_backup(app):
    from backup import restore_backup
    with app.app_context():
        with pytest.raises(ValueError, match="does not look like"):
            restore_backup({"hello": "world"})


def test_restore_rejects_a_newer_format(app):
    from backup import restore_backup
    with app.app_context():
        with pytest.raises(ValueError, match="newer"):
            restore_backup({"format": 999, "partners": [], "transactions": []})
