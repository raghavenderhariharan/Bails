"""Watchman settlement: salary minus petty cash, where petty cash is expense
transactions tagged to a watchman (entered on the Expenses tab)."""
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
def tagged(app):
    """Watchman 1: a 2000 and a 1500 petty-cash expense; Watchman 2: a 500. Oct 2026."""
    from models import EXPENSE, INCOME, Transaction, Watchman, db
    with app.app_context():
        w1, w2 = Watchman.query.order_by(Watchman.sort_order).all()
        db.session.add_all([
            Transaction(txn_date=date(2026, 10, 2), kind=INCOME, category="Ground booking",
                        description="7:00 AM", amount=Decimal("7000")),
            Transaction(txn_date=date(2026, 10, 5), kind=EXPENSE, category="Market expenses",
                        description="advance", amount=Decimal("2000"), watchman_id=w1.id),
            Transaction(txn_date=date(2026, 10, 18), kind=EXPENSE, category="Market expenses",
                        description="food", amount=Decimal("1500"), watchman_id=w1.id),
            Transaction(txn_date=date(2026, 10, 10), kind=EXPENSE, category="Market expenses",
                        description="advance", amount=Decimal("500"), watchman_id=w2.id),
            Transaction(txn_date=date(2026, 10, 12), kind=EXPENSE, category="Electricity",
                        description="untagged bill", amount=Decimal("900")),
        ])
        db.session.commit()
        return (w1.id, w2.id)


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


def test_transactions_have_a_watchman_column(app):
    from models import Transaction, db
    with app.app_context():
        cols = {c["name"] for c in db.inspect(db.engine).get_columns("transactions")}
        assert "watchman_id" in cols


# ----------------------------- the calculation ----------------------------- #

def test_net_payable_from_tagged_expenses(app, tagged):
    from finance import parse_period, watchman_settlement
    with app.app_context():
        s = watchman_settlement(parse_period({"period": "month", "month": "2026-10"}))
    assert s["rows"][0]["petty"] == Decimal("3500.00")   # 2000 + 1500
    assert s["rows"][0]["net"] == Decimal("16500.00")
    assert s["rows"][1]["petty"] == Decimal("500.00")
    assert s["rows"][1]["net"] == Decimal("19500.00")
    assert s["net_total"] == Decimal("36000.00")


def test_untagged_expense_does_not_count(app, tagged):
    """The 900 Electricity bill is not tagged, so it never touches a watchman."""
    from finance import parse_period, watchman_settlement
    with app.app_context():
        s = watchman_settlement(parse_period({"period": "month", "month": "2026-10"}))
    assert s["petty_total"] == Decimal("4000.00")   # 2000 + 1500 + 500, not 4900


def test_salary_scales_with_the_period(app, tagged):
    from finance import parse_period, watchman_settlement
    with app.app_context():
        q = watchman_settlement(parse_period({"period": "quarter", "year": "2026", "quarter": "4"}))
    assert q["months"] == 3
    assert q["rows"][0]["salary"] == Decimal("60000.00")
    assert q["rows"][0]["net"] == Decimal("56500.00")   # 60000 - 3500


# --------------------------- entering petty cash --------------------------- #

def test_expense_can_be_tagged_to_a_watchman(app):
    client = admin(app)
    from models import Watchman, Transaction
    with app.app_context():
        wid = Watchman.query.order_by(Watchman.sort_order).first().id
    page = client.get("/expenses").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "expense", "txn_date": "2026-10-09",
        "category": "Market expenses", "description": "torch batteries", "amount": "750",
        "watchman_id": str(wid), "next": "/expenses"}, follow_redirects=True)
    with app.app_context():
        t = Transaction.query.filter_by(description="torch batteries").first()
        assert t is not None and t.watchman_id == wid


def test_income_ignores_a_watchman_tag(app):
    """A watchman tag is meaningless on income and must be dropped."""
    client = admin(app)
    from models import Watchman, Transaction
    with app.app_context():
        wid = Watchman.query.first().id
    page = client.get("/income").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Ground booking", "description": "slot", "amount": "5000",
        "watchman_id": str(wid), "next": "/income"}, follow_redirects=True)
    with app.app_context():
        t = Transaction.query.filter_by(description="slot").first()
        assert t.watchman_id is None


def test_editing_an_expense_keeps_the_tag(app, tagged):
    client = admin(app)
    from models import Transaction, Watchman, db
    with app.app_context():
        t = Transaction.query.filter_by(description="advance", amount=Decimal("2000")).first()
        tid, wid = t.id, t.watchman_id
    page = client.get("/expenses").get_data(as_text=True)
    client.post(f"/transactions/{tid}/edit", data={
        "csrf_token": _csrf(page), "kind": "expense", "txn_date": "2026-10-05",
        "category": "Market expenses", "description": "advance revised", "amount": "2200",
        "watchman_id": str(wid), "next": "/expenses"}, follow_redirects=True)
    with app.app_context():
        t = db.session.get(Transaction, tid)
        assert t.amount == Decimal("2200.00") and t.watchman_id == wid


def test_an_invalid_watchman_tag_is_rejected(app):
    client = admin(app)
    from models import Transaction
    page = client.get("/expenses").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "expense", "txn_date": "2026-10-09",
        "category": "Market expenses", "amount": "100", "watchman_id": "9999",
        "next": "/expenses"}, follow_redirects=True)
    with app.app_context():
        assert Transaction.query.count() == 0


# -------------------------------- the page --------------------------------- #

def test_watchmen_page_shows_the_calculation(app, tagged):
    body = admin(app).get("/watchmen?period=month&month=2026-10").get_data(as_text=True)
    assert "16,500" in body and "19,500" in body
    assert "3,500" in body
    assert "advance" in body and "food" in body
    assert "untagged bill" not in body     # the non-watchman expense is absent


def test_watchmen_page_has_no_petty_entry_controls(app, tagged):
    """Petty cash is entered on the Expenses tab now, not here."""
    body = admin(app).get("/watchmen").get_data(as_text=True)
    assert "data-open-petty" not in body
    assert "pettyModal" not in body
    assert "/watchmen/petty" not in body
    assert "Add petty cash (on Expenses)" in body   # link points to Expenses


def test_expense_tab_shows_the_watchman_field_and_tag(app, tagged):
    body = admin(app).get("/expenses?period=month&month=2026-10").get_data(as_text=True)
    assert 'name="watchman_id"' in body            # dropdown in the entry modal
    assert "Watchman:" in body                      # tag on tagged rows


def test_petty_routes_are_gone(app):
    client = admin(app)
    assert client.post("/watchmen/petty/new", data={}).status_code == 404


def test_partner_sees_figures_no_controls(app, tagged):
    body = partner(app).get("/watchmen?period=month&month=2026-10").get_data(as_text=True)
    assert "16,500" in body
    assert "Save watchmen" not in body
    assert "Add petty cash" not in body


def test_partner_cannot_save_watchmen(app):
    client = partner(app)
    from models import Watchman
    with app.app_context():
        ids = [w.id for w in Watchman.query.all()]
    page = client.get("/watchmen").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/watchmen"}
    for i, wid in enumerate(ids):
        data[f"name_{wid}"] = f"X{i}"; data[f"salary_{wid}"] = "99999"; data[f"active_{wid}"] = "on"
    assert client.post("/watchmen/save", data=data).status_code == 403


# ---------------------------- salary editing ------------------------------- #

def test_admin_edits_salary_without_nul_crash(app):
    """Regression: the name-swap used a NUL temp name that 500s on Postgres."""
    client = admin(app)
    from models import Watchman
    with app.app_context():
        ids = [w.id for w in Watchman.query.order_by(Watchman.sort_order).all()]
    page = client.get("/watchmen").get_data(as_text=True)
    data = {"csrf_token": _csrf(page), "next": "/watchmen"}
    for i, wid in enumerate(ids):
        data[f"name_{wid}"] = ["Ramesh", "Suresh"][i]
        data[f"salary_{wid}"] = "22,000" if i == 0 else "20000"
        data[f"active_{wid}"] = "on"
    r = client.post("/watchmen/save", data=data, follow_redirects=True)
    assert r.status_code == 200
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
    for i, wid in enumerate(ids):
        data[f"name_{wid}"] = ["Alpha", "Beta"][i]; data[f"salary_{wid}"] = "20000"; data[f"active_{wid}"] = "on"
    client.post("/watchmen/save", data=data, follow_redirects=True)
    page = client.get("/watchmen").get_data(as_text=True)
    swapped = dict(data, csrf_token=_csrf(page))
    swapped[f"name_{ids[0]}"] = "Beta"; swapped[f"name_{ids[1]}"] = "Alpha"
    assert client.post("/watchmen/save", data=swapped, follow_redirects=True).status_code == 200
    with app.app_context():
        assert [w.name for w in Watchman.query.order_by(Watchman.sort_order).all()] == ["Beta", "Alpha"]


# --------------------------------- backup ---------------------------------- #

def test_backup_tags_transactions_with_watchman(app, tagged):
    import json
    data = json.loads(admin(app).get("/admin/backup.json").get_data(as_text=True))
    assert data["format"] >= 3
    assert data["summary"]["watchmen"] == 2
    assert data["summary"]["watchman_tagged"] == 3
    w1_rows = [t for t in data["transactions"] if t.get("watchman")]
    assert len(w1_rows) == 3
    # an untagged expense has watchman == None
    bill = next(t for t in data["transactions"] if t["description"] == "untagged bill")
    assert bill["watchman"] is None


def test_backup_round_trip_preserves_tags(app, tagged):
    from backup import build_backup, restore_backup
    from models import Transaction
    with app.app_context():
        before = build_backup()
        restore_backup(before)
        after = build_backup()
        assert after["transactions"] == before["transactions"]
        assert after["watchmen"] == before["watchmen"]
        # the tag actually points at a real watchman after restore
        tagged_rows = Transaction.query.filter(Transaction.watchman_id.isnot(None)).count()
        assert tagged_rows == 3


def test_old_format_backup_still_restores(app):
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


# --------------------------- schema migration ------------------------------ #

def test_watchman_id_column_is_added_to_an_existing_table(tmp_path, monkeypatch):
    import sqlite3
    dbfile = tmp_path / "old.db"
    con = sqlite3.connect(dbfile)
    con.executescript(
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, txn_date DATE, kind VARCHAR,"
        " category VARCHAR, description VARCHAR, slot VARCHAR, party VARCHAR, amount NUMERIC,"
        " notes TEXT, created_at DATETIME, updated_at DATETIME);"
        "INSERT INTO transactions (txn_date, kind, category, amount)"
        " VALUES ('2026-10-02','income','Ground booking',7000);"
    )
    con.commit(); con.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for module in ("config", "models", "finance", "exporter", "backup", "app"):
        sys.modules.pop(module, None)
    import app  # noqa: F401 - import runs the migration in _bootstrap

    cols = [r[1] for r in sqlite3.connect(dbfile).execute("PRAGMA table_info(transactions)")]
    assert "watchman_id" in cols
    n = sqlite3.connect(dbfile).execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert n == 1   # existing row preserved
