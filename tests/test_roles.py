"""Admin vs Partner access control.

The templates hide the write controls, but the permission boundary that matters
is server-side: a partner who hand-posts a form must be refused.
"""
import os
import re
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture()
def make_app(tmp_path, monkeypatch):
    def _build(**env):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/{env.get('_db','r')}.db")
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ADMIN_PASSWORD", "Admin123")
        monkeypatch.setenv("PARTNER_PASSCODE", "")
        for key, value in env.items():
            if not key.startswith("_"):
                monkeypatch.setenv(key, value)
        for module in ("config", "models", "finance", "exporter", "app"):
            sys.modules.pop(module, None)
        import app as app_module
        app_module._login_attempts.clear()
        app_module._global_failures.clear()
        app_module.app.config.update(TESTING=True)
        return app_module.app
    return _build


@pytest.fixture()
def app(make_app):
    application = make_app()
    from models import EXPENSE, INCOME, Transaction, db
    with application.app_context():
        db.session.add(Transaction(txn_date=date(2026, 10, 2), kind=INCOME,
                                   category="Ground booking", description="7:00 AM slot",
                                   amount=Decimal("7000")))
        db.session.add(Transaction(txn_date=date(2026, 10, 4), kind=EXPENSE,
                                   category="Market expenses", description="Allowance",
                                   amount=Decimal("1000")))
        db.session.commit()
    return application


def _csrf(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no CSRF token on page"
    return match.group(1)


def as_admin(app):
    client = app.test_client()
    page = client.get("/login?as=admin").get_data(as_text=True)
    response = client.post("/login", data={"csrf_token": _csrf(page), "password": "Admin123"})
    assert response.status_code in (301, 302, 308), "admin login failed"
    return client


def as_partner(app):
    client = app.test_client()
    page = client.get("/login").get_data(as_text=True)
    response = client.post("/login/partner", data={"csrf_token": _csrf(page)})
    assert response.status_code in (301, 302, 308), "partner login failed"
    return client


def txn_id(app):
    from models import Transaction
    with app.app_context():
        return Transaction.query.order_by(Transaction.id).first().id


# ------------------------------ start screen ------------------------------- #

def test_start_screen_offers_both_roles(app):
    body = app.test_client().get("/login").get_data(as_text=True)
    assert "How are you signing in?" in body
    assert ">Admin<" in body and ">Partner<" in body
    assert "Password required" in body
    assert "No password needed" in body
    # The chooser must not itself ask for a password.
    assert 'name="password"' not in body


def test_admin_step_asks_for_a_password(app):
    body = app.test_client().get("/login?as=admin").get_data(as_text=True)
    assert 'name="password"' in body
    assert "Sign in as Admin" in body


def test_protected_page_redirects_to_the_start_screen(app):
    response = app.test_client().get("/")
    assert response.status_code in (301, 302, 308)
    assert "/login" in response.headers["Location"]


# ------------------------------- partner door ------------------------------ #

def test_partner_signs_in_without_a_password(app):
    client = app.test_client()
    page = client.get("/login").get_data(as_text=True)
    response = client.post("/login/partner", data={"csrf_token": _csrf(page)})
    assert response.status_code in (301, 302, 308)
    with client.session_transaction() as session:
        assert session["authed"] is True
        assert session["role"] == "partner"


def test_admin_password_is_still_required(app):
    client = app.test_client()
    page = client.get("/login?as=admin").get_data(as_text=True)
    assert client.post("/login", data={"csrf_token": _csrf(page), "password": "nope"}).status_code == 401
    with client.session_transaction() as session:
        assert "role" not in session


# --------------------------- partner can read ------------------------------ #

@pytest.mark.parametrize("path", ["/", "/income", "/expenses", "/partners",
                                  "/transactions", "/export.xlsx"])
def test_partner_can_view_everything(app, path):
    response = as_partner(app).get(path)
    assert response.status_code == 200, f"partner blocked from reading {path}"


def test_partner_sees_the_figures_and_their_share(app):
    body = as_partner(app).get("/partners?period=month&month=2026-10").get_data(as_text=True)
    assert "7,000" in body and "1,000" in body
    assert "6,000" in body  # net profit
    assert "1,200" in body  # a 20% share of 6,000


# -------------------------- partner cannot write --------------------------- #

def test_partner_is_refused_on_create(app):
    client = as_partner(app)
    page = client.get("/income").get_data(as_text=True)
    response = client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Tournament", "amount": "5000", "next": "/income"})
    assert response.status_code == 403
    from models import Transaction
    with app.app_context():
        assert Transaction.query.count() == 2, "partner managed to create an entry"


def test_partner_is_refused_on_edit(app):
    client = as_partner(app)
    page = client.get("/income").get_data(as_text=True)
    target = txn_id(app)
    response = client.post(f"/transactions/{target}/edit", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-02",
        "category": "Tournament", "amount": "99999", "next": "/income"})
    assert response.status_code == 403
    from models import Transaction, db
    with app.app_context():
        assert db.session.get(Transaction, target).amount == Decimal("7000.00"), "partner edited an entry"


def test_partner_is_refused_on_delete(app):
    client = as_partner(app)
    page = client.get("/income").get_data(as_text=True)
    target = txn_id(app)
    response = client.post(f"/transactions/{target}/delete",
                           data={"csrf_token": _csrf(page), "next": "/income"})
    assert response.status_code == 403
    from models import Transaction, db
    with app.app_context():
        assert db.session.get(Transaction, target) is not None, "partner deleted an entry"


def test_partner_is_refused_on_equity_change(app):
    client = as_partner(app)
    page = client.get("/partners").get_data(as_text=True)
    from models import Partner
    with app.app_context():
        ids = [p.id for p in Partner.query.all()]
        before = Partner.query.order_by(Partner.sort_order).first().name
    data = {"csrf_token": _csrf(page), "next": "/partners"}
    for index, pid in enumerate(ids):
        data[f"name_{pid}"] = f"Hacked{index}"
        data[f"equity_{pid}"] = "16.66"
        data[f"active_{pid}"] = "on"
    assert client.post("/partners/save", data=data).status_code == 403
    with app.app_context():
        assert Partner.query.order_by(Partner.sort_order).first().name == before


def test_403_page_explains_the_restriction(app):
    client = as_partner(app)
    page = client.get("/income").get_data(as_text=True)
    body = client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Tournament", "amount": "5000"}).get_data(as_text=True)
    assert "view-only" in body.lower()
    assert "Admin" in body


# ----------------------------- UI differences ------------------------------ #

def test_partner_ui_hides_every_write_control(app):
    client = as_partner(app)
    for path in ("/", "/income", "/expenses", "/transactions", "/partners"):
        body = client.get(path).get_data(as_text=True)
        assert "New entry" not in body, f"'New entry' shown to partner on {path}"
        assert "data-open-entry" not in body, f"entry dialog trigger on {path}"
        assert "data-edit-entry" not in body, f"edit button shown to partner on {path}"
        assert ">Delete<" not in body, f"delete button shown to partner on {path}"
        assert "entryModal" not in body, f"entry dialog markup present on {path}"
        assert "Save equity split" not in body, f"equity form shown to partner on {path}"


def test_partner_sees_a_view_only_badge(app):
    body = as_partner(app).get("/").get_data(as_text=True)
    assert "view only" in body.lower()
    assert "Partner" in body


def test_admin_ui_shows_the_write_controls(app):
    client = as_admin(app)
    body = client.get("/").get_data(as_text=True)
    assert "New entry" in body and "entryModal" in body
    income = client.get("/income").get_data(as_text=True)
    assert "data-edit-entry" in income and ">Delete<" in income
    partners = client.get("/partners").get_data(as_text=True)
    assert "Save equity split" in partners


def test_admin_can_still_write(app):
    client = as_admin(app)
    page = client.get("/income").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Tournament", "description": "Admin entry", "amount": "5000",
        "next": "/income"}, follow_redirects=True)
    from models import Transaction
    with app.app_context():
        assert Transaction.query.count() == 3


# --------------------------- session tampering ----------------------------- #

def test_unknown_role_in_the_session_is_treated_as_signed_out(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["authed"] = True
        session["role"] = "superuser"
    response = client.get("/")
    assert response.status_code in (301, 302, 308)
    assert "/login" in response.headers["Location"]


def test_authed_without_a_role_is_treated_as_signed_out(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["authed"] = True
    assert client.get("/").status_code in (301, 302, 308)
    page = client.get("/login").get_data(as_text=True)
    assert client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Tournament", "amount": "1"}).status_code in (301, 302, 308)


def test_logout_clears_the_role(app):
    client = as_partner(app)
    page = client.get("/").get_data(as_text=True)
    client.post("/logout", data={"csrf_token": _csrf(page)})
    with client.session_transaction() as session:
        assert "role" not in session
    assert client.get("/").status_code in (301, 302, 308)


# ------------------------- optional partner passcode ----------------------- #

def test_partner_passcode_is_enforced_when_set(make_app):
    application = make_app(PARTNER_PASSCODE="Bails2026", _db="pc")
    client = application.test_client()
    page = client.get("/login").get_data(as_text=True)
    assert "Passcode required" in page

    wrong = client.post("/login/partner", data={"csrf_token": _csrf(page), "passcode": "nope"})
    assert wrong.status_code == 401
    with client.session_transaction() as session:
        assert "role" not in session

    page = client.get("/login").get_data(as_text=True)
    right = client.post("/login/partner", data={"csrf_token": _csrf(page), "passcode": "Bails2026"})
    assert right.status_code in (301, 302, 308)
    with client.session_transaction() as session:
        assert session["role"] == "partner"


def test_no_passcode_means_no_passcode(make_app):
    application = make_app(_db="nopc")
    client = application.test_client()
    page = client.get("/login").get_data(as_text=True)
    assert "No password needed" in page
    assert client.post("/login/partner",
                       data={"csrf_token": _csrf(page)}).status_code in (301, 302, 308)
