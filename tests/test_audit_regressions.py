"""Regression tests for the defects found by the code audit.

Each test reproduces the original failure, so a reintroduced bug fails here.
"""
import os
import re
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "Admin123")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for module in ("config", "models", "finance", "exporter", "app"):
        sys.modules.pop(module, None)
    import app as app_module

    # The throttle is module-level state; start every test from clean.
    app_module._login_attempts.clear()
    app_module._global_failures.clear()
    application = app_module.app
    application.config.update(TESTING=True)
    yield application
    app_module._login_attempts.clear()
    app_module._global_failures.clear()


@pytest.fixture()
def seeded(app):
    from models import EXPENSE, INCOME, Transaction, db

    rows = [
        ("2026-10-01", EXPENSE, "Ground maintenance", "Roller hire", "2000"),
        ("2026-10-02", INCOME, "Ground booking", "7:00 AM slot", "7000"),
        ("2026-10-03", INCOME, "Ground booking", "7:00 AM slot", "8000"),
        ("2026-10-04", INCOME, "ECL booking", "All three slots", "17000"),
        ("2026-10-04", EXPENSE, "Market expenses", "Groundsman 1", "1000"),
        ("2026-10-05", EXPENSE, "Salary / chit payment", "Chit", "5000"),
    ]
    with app.app_context():
        for day, kind, category, description, amount in rows:
            db.session.add(Transaction(txn_date=date.fromisoformat(day), kind=kind,
                                       category=category, description=description,
                                       amount=Decimal(amount)))
        db.session.commit()
    return app


@pytest.fixture()
def client(seeded):
    return seeded.test_client()


def _csrf(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client):
    page = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={"csrf_token": _csrf(page), "password": "Admin123"})


# ---------------------------------------------------------------- finding 1 --
# Login throttle was keyed on client-controlled X-Forwarded-For.

def _attempt(client, xff=None):
    page = client.get("/login").get_data(as_text=True)
    headers = {"X-Forwarded-For": xff} if xff else {}
    return client.post("/login", data={"csrf_token": _csrf(page), "password": "wrong"},
                       headers=headers)


def test_rotating_x_forwarded_for_cannot_reset_the_throttle(client):
    """The original attack: a fresh XFF per request gave unlimited attempts."""
    codes = [_attempt(client, xff=f"1.2.3.{i}").status_code for i in range(14)]
    assert 429 in codes, "throttle never engaged despite 14 failures"
    assert codes.count(429) >= 4


def test_throttle_still_engages_without_the_header(client):
    codes = [_attempt(client).status_code for i in range(12)]
    assert codes[:8] == [401] * 8
    assert codes[8:] == [429] * 4


def test_lockout_cannot_be_bypassed_with_a_fresh_header(client):
    for i in range(10):
        _attempt(client)
    page = client.get("/login").get_data(as_text=True)
    response = client.post("/login",
                           data={"csrf_token": _csrf(page), "password": "Admin123"},
                           headers={"X-Forwarded-For": "9.9.9.9"})
    assert response.status_code == 429, "lockout bypassed by spoofing a new address"


def test_attempt_store_does_not_grow_per_spoofed_address(client):
    import app as app_module
    for i in range(30):
        _attempt(client, xff=f"10.0.0.{i}")
    assert len(app_module._login_attempts) <= 2, "unauthenticated caller grew the throttle store"


def test_x_forwarded_for_is_honoured_only_when_a_proxy_is_trusted(tmp_path, monkeypatch):
    """With TRUSTED_PROXY_COUNT=1 the header is used, via ProxyFix."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/p.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    for module in ("config", "models", "finance", "exporter", "app"):
        sys.modules.pop(module, None)
    import app as app_module
    app_module._login_attempts.clear()
    app_module._global_failures.clear()
    client = app_module.app.test_client()

    # Each distinct trusted-proxy-reported client gets its own bucket...
    for i in range(3):
        for _ in range(3):
            _attempt(client, xff=f"203.0.113.{i}")
    assert len(app_module._login_attempts) == 3
    # ...and one of them can still be locked out on its own.
    codes = [_attempt(client, xff="203.0.113.0").status_code for _ in range(8)]
    assert 429 in codes


# ---------------------------------------------------------------- finding 3 --
# _safe_redirect allowed an off-site target containing a control character.

@pytest.mark.parametrize("target", [
    "//evil.example.com",
    "/\tevil.example.com",
    "/\t/evil.example.com",
    "https://evil.example.com",
    "http://evil.example.com/x",
    "/\\evil.example.com",
    "\n/evil",
    "javascript:alert(1)",
    "//evil.example.com/\r\n",
])
def test_offsite_redirect_targets_are_refused(client, target):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    response = client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Tournament", "amount": "100", "next": target})
    location = response.headers.get("Location", "")
    assert "evil.example.com" not in location, f"off-site redirect allowed: {location}"
    assert not location.startswith("javascript:")


def test_same_site_redirect_target_still_works(client):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    response = client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-09",
        "category": "Tournament", "amount": "100", "next": "/expenses?period=all"})
    assert "/expenses" in response.headers["Location"]


# ------------------------------------------------------------- findings 4/6/9 --
# Running balance was accumulated over the kind/search-filtered rows only.

def test_running_balance_is_a_real_balance_under_a_kind_filter(client):
    """A 2,000 debit precedes the credits, so a true balance is offset by it."""
    login(client)
    body = client.get("/transactions?period=month&month=2026-10&kind=income").get_data(as_text=True)
    rows = re.findall(r'<td class="num[^"]*"><strong>\u20b9([\d,]+(?:\.\d+)?)</strong></td>', body)
    assert rows, "no balance cells found"
    # True ledger balances: -2,000 + 7,000 = 5,000 -> 13,000 -> 30,000.
    assert set(rows) == {"5,000", "13,000", "30,000"}, f"wrong balances: {rows}"
    # The old bug accumulated only the filtered rows: 7,000 / 15,000 / 32,000.
    assert "32,000" not in rows, "balance summed only the filtered rows"


def test_footer_totals_match_the_rows_shown(client):
    login(client)
    body = client.get("/transactions?period=month&month=2026-10&kind=expense").get_data(as_text=True)
    footer = body.split("<tfoot>")[1]
    assert "Totals — rows shown" in footer
    # Only the three debits are listed (2,000 + 1,000 + 5,000).
    assert "8,000" in footer, "shown debit subtotal missing"
    # The period-wide line is still offered, clearly labelled.
    assert "all entries" in footer
    assert "32,000" in footer, "period-wide income total missing from the secondary row"


def test_unfiltered_footer_has_a_single_total_row(client):
    login(client)
    body = client.get("/transactions?period=month&month=2026-10").get_data(as_text=True)
    footer = body.split("<tfoot>")[1]
    assert "all entries" not in footer
    assert "Totals — Oct 2026" in footer


# ------------------------------------------------------------- findings 5/7 --
# The custom date range was unreachable from the UI.

def test_custom_period_without_dates_renders_the_inputs(client):
    login(client)
    body = client.get("/?period=custom").get_data(as_text=True)
    assert 'name="from"' in body and 'name="to"' in body, "custom range inputs never render"
    assert "pick a range" in body.lower()


def test_custom_range_link_is_seeded_with_the_window(client):
    login(client)
    body = client.get("/?period=month&month=2026-10").get_data(as_text=True)
    match = re.search(r'href="([^"]*period=custom[^"]*)"', body)
    assert match, "no Custom range link"
    href = match.group(1)
    assert "from=2026-10-01" in href, f"link not seeded: {href}"
    assert "to=2026-10-31" in href, f"link not seeded: {href}"


def test_custom_range_filters_correctly(client):
    login(client)
    body = client.get("/?period=custom&from=2026-10-01&to=2026-10-03").get_data(as_text=True)
    match = re.search(r'Income · Credit.*?kpi__value[^>]*>\s*<span class="cur">[^<]*</span>([^<]*)',
                      body, re.S)
    assert match.group(1).strip() == "15,000"


# -------------------------------------------------------------- finding 12 --
# Swapping two partner names hit the unique constraint and 500'd.

def test_partner_names_can_be_swapped(client):
    login(client)
    page = client.get("/partners").get_data(as_text=True)
    ids = re.findall(r'name="name_(\d+)"', page)
    data = {"csrf_token": _csrf(page), "next": "/partners"}
    names = ["Anil", "Bala", "Chandra", "Deepak", "Esha", "Farid"]
    for index, pid in enumerate(ids):
        data[f"name_{pid}"] = names[index]
        data[f"equity_{pid}"] = "20" if index < 4 else "10"
        data[f"active_{pid}"] = "on"
    client.post("/partners/save", data=data, follow_redirects=True)

    # Now swap the first two names - this used to raise IntegrityError.
    page = client.get("/partners").get_data(as_text=True)
    swapped = dict(data, csrf_token=_csrf(page))
    swapped[f"name_{ids[0]}"] = "Bala"
    swapped[f"name_{ids[1]}"] = "Anil"
    response = client.post("/partners/save", data=swapped, follow_redirects=True)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Partners updated" in body or "Bala" in body
    order = re.findall(r'name="name_\d+" value="([^"]+)"', client.get("/partners").get_data(as_text=True))
    assert order[:2] == ["Bala", "Anil"], f"swap did not persist: {order[:2]}"


def test_duplicate_partner_names_are_still_refused(client):
    login(client)
    page = client.get("/partners").get_data(as_text=True)
    ids = re.findall(r'name="name_(\d+)"', page)
    data = {"csrf_token": _csrf(page), "next": "/partners"}
    for index, pid in enumerate(ids):
        data[f"name_{pid}"] = "Same" if index < 2 else f"P{index}"
        data[f"equity_{pid}"] = "20" if index < 4 else "10"
        data[f"active_{pid}"] = "on"
    body = client.post("/partners/save", data=data, follow_redirects=True).get_data(as_text=True)
    assert "Duplicate partner name" in body


# -------------------------------------------------------------- finding 15 --
# Reserved url_for options splatted from the query string 500'd the page.

@pytest.mark.parametrize("query", [
    "_external=1", "_anchor=x", "_method=GET", "_scheme=https",
])
def test_reserved_url_for_options_in_the_query_string_are_ignored(client, query):
    login(client)
    for path in ("/", "/income", "/expenses", "/transactions", "/partners"):
        response = client.get(f"{path}?period=month&month=2026-10&{query}")
        assert response.status_code == 200, f"{path}?{query} -> {response.status_code}"


# -------------------------------------------------------------- finding 17 --
# The year dropdown omitted a selected year outside the data range.

def test_year_dropdown_includes_the_selected_year(client):
    login(client)
    body = client.get("/?period=year&year=2031").get_data(as_text=True)
    assert 'value="2031"' in body, "selected year missing from the dropdown"
    assert re.search(r'<option value="2031"\s+selected', body), "selected year not marked selected"
    assert "Year 2031" in body


# ----------------------------------------------------------- findings 11/13 --
# A stale CSRF token dropped the operator on a raw 400 page.

def test_missing_csrf_token_redirects_with_a_message(client):
    login(client)
    response = client.post("/transactions/new", data={
        "kind": "income", "txn_date": "2026-10-09", "category": "Tournament",
        "amount": "100", "next": "/income"})
    assert response.status_code == 400
    assert response.headers.get("Location"), "no redirect offered after a CSRF failure"
    body = client.get("/income").get_data(as_text=True)
    assert "expired or could not be verified" in body


def test_csrf_tokens_do_not_expire_before_the_session(app):
    assert app.config["WTF_CSRF_TIME_LIMIT"] is None


# ----------------------------------------------------------- findings 2/10/16 --
# .env was never loaded, and SECRET_KEY was random per process.

def test_dotenv_is_available_and_wired(app):
    import config
    assert "dotenv" in open(config.__file__).read()
    import dotenv  # noqa: F401  - must be installed, not just referenced


def test_secret_key_persists_locally_across_reloads(tmp_path, monkeypatch):
    """Without SECRET_KEY set, a local run must still reuse one stable key."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.path", sys.path)
    keys = []
    for _ in range(2):
        for module in ("config",):
            sys.modules.pop(module, None)
        import config
        keys.append(config.Config.SECRET_KEY)
    assert keys[0] == keys[1], "SECRET_KEY changed between processes"
    assert len(keys[0]) >= 32


def test_deployment_without_secret_key_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    for module in ("config",):
        sys.modules.pop(module, None)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        import config  # noqa: F401


# -------------------------------------------------------------- finding 14 --
# The Net legend swatch and the plotted line used different colours.

def test_net_series_colour_comes_from_one_token():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    css = open(os.path.join(root, "static/css/app.css")).read()
    js = open(os.path.join(root, "static/js/charts.js")).read()
    html = open(os.path.join(root, "templates/dashboard.html")).read()
    assert "--chart-net" in css
    assert css.count("--chart-net:") >= 3, "needs a light value and both dark overrides"
    assert 'token("--chart-net"' in js
    assert "var(--chart-net)" in html
    assert "#8E97E8" not in js, "hard-coded dark colour still in the chart script"
