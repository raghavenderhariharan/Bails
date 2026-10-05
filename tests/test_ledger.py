"""Test suite for the Bails Cricket Ground ledger.

Run with:  python -m pytest -q
"""
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "Admin123")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    for module in ("config", "models", "finance", "exporter", "app"):
        sys.modules.pop(module, None)
    import app as app_module

    application = app_module.app
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture()
def seeded(app):
    """Load the same figures as the original Excel sheet."""
    from models import EXPENSE, INCOME, Transaction, db

    rows = [
        ("2026-10-02", INCOME, "Ground booking", "7:00 AM slot", "7000"),
        ("2026-10-02", INCOME, "Ground booking", "10:45 AM slot", "6000"),
        ("2026-10-02", INCOME, "Ground booking", "2:30 PM slot", "6000"),
        ("2026-10-02", INCOME, "Other income", "Unallocated", "1000"),
        ("2026-10-03", INCOME, "Ground booking", "7:00 AM slot", "8000"),
        ("2026-10-03", INCOME, "Ground booking", "2:30 PM slot", "6000"),
        ("2026-10-04", INCOME, "ECL booking", "All three slots", "17000"),
        ("2026-10-04", EXPENSE, "Market expenses", "Groundsman 1", "1000"),
        ("2026-10-04", EXPENSE, "Market expenses", "Groundsman 2", "1000"),
        ("2026-10-04", EXPENSE, "Salary / chit payment", "Chit", "5000"),
    ]
    with app.app_context():
        for day, kind, category, description, amount in rows:
            db.session.add(Transaction(
                txn_date=date.fromisoformat(day), kind=kind, category=category,
                description=description, amount=Decimal(amount)))
        db.session.commit()
    return app


@pytest.fixture()
def client(seeded):
    return seeded.test_client()


def _csrf(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no CSRF token in page"
    return match.group(1)


def login(client, password="Admin123"):
    page = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={"csrf_token": _csrf(page), "password": password},
                       follow_redirects=False)


def kpi(html, label):
    """Pull one KPI tile's value out of the rendered page."""
    match = re.search(
        re.escape(label) + r'.*?kpi__value[^>]*>\s*<span class="cur">[^<]*</span>([^<]*)',
        html, re.S)
    return match.group(1).strip() if match else None


# ----------------------------- money formatting ---------------------------- #

@pytest.mark.parametrize("value,expected", [
    (0, "0"), (5, "5"), (999, "999"), (1000, "1,000"), (99999, "99,999"),
    (100000, "1,00,000"), (1234567, "12,34,567"), (10000000, "1,00,00,000"),
    (51000, "51,000"), (-44000, "-44,000"), (Decimal("1234.50"), "1,234.50"),
    (Decimal("0.05"), "0.05"), (Decimal("12500.50"), "12,500.50"),
])
def test_indian_digit_grouping(app, value, expected):
    from finance import fmt_money
    assert fmt_money(value) == expected


# ------------------------------- period maths ------------------------------ #

@pytest.mark.parametrize("args,start,end", [
    ({"period": "month", "month": "2026-10"}, "2026-10-01", "2026-10-31"),
    ({"period": "month", "month": "2026-02"}, "2026-02-01", "2026-02-28"),
    ({"period": "month", "month": "2024-02"}, "2024-02-01", "2024-02-29"),  # leap year
    ({"period": "month", "month": "2026-12"}, "2026-12-01", "2026-12-31"),
    ({"period": "quarter", "year": "2026", "quarter": "1"}, "2026-01-01", "2026-03-31"),
    ({"period": "quarter", "year": "2026", "quarter": "4"}, "2026-10-01", "2026-12-31"),
    ({"period": "year", "year": "2026"}, "2026-01-01", "2026-12-31"),
    ({"period": "custom", "from": "2026-10-01", "to": "2026-10-03"}, "2026-10-01", "2026-10-03"),
])
def test_period_boundaries(seeded, args, start, end):
    from finance import parse_period
    with seeded.app_context():
        period = parse_period(args)
    assert period.start.isoformat() == start
    assert period.end.isoformat() == end


def test_custom_range_reversed_dates_are_swapped(seeded):
    from finance import parse_period
    with seeded.app_context():
        period = parse_period({"period": "custom", "from": "2026-12-01", "to": "2026-01-01"})
    assert period.start < period.end


@pytest.mark.parametrize("args", [
    {"period": "bogus"}, {"period": "month", "month": "nonsense"},
    {"period": "month", "month": "2026-99"}, {"period": "quarter", "year": "abc", "quarter": "9"},
    {"period": "year", "year": "-5"}, {"period": "custom", "from": "2026-13-45", "to": "zzz"},
    {},
])
def test_malformed_periods_never_raise(seeded, args):
    from finance import parse_period
    with seeded.app_context():
        period = parse_period(args)
    assert period.label


def test_all_time_has_no_bounds(seeded):
    from finance import parse_period
    with seeded.app_context():
        period = parse_period({"period": "all"})
    assert period.start is None and period.end is None


# --------------------------------- totals ---------------------------------- #

def test_totals_match_the_excel(seeded):
    from finance import parse_period, totals
    with seeded.app_context():
        summary = totals(parse_period({"period": "month", "month": "2026-10"}))
    assert summary["income"] == Decimal("51000.00")
    assert summary["expense"] == Decimal("7000.00")
    assert summary["net"] == Decimal("44000.00")
    assert summary["count"] == 10


def test_totals_respect_period_bounds(seeded):
    from finance import parse_period, totals
    with seeded.app_context():
        # 1-3 Oct excludes the 4 Oct ECL booking and all three expenses.
        early = totals(parse_period({"period": "custom", "from": "2026-10-01", "to": "2026-10-03"}))
        assert early["income"] == Decimal("34000.00")
        assert early["expense"] == Decimal("0.00")

        empty = totals(parse_period({"period": "month", "month": "2026-11"}))
        assert empty["income"] == Decimal("0.00")
        assert empty["net"] == Decimal("0.00")
        assert empty["margin"] is None


def test_closing_balance_is_cumulative(seeded):
    from finance import balance_as_of
    with seeded.app_context():
        assert balance_as_of(date(2026, 10, 2)) == Decimal("20000.00")
        assert balance_as_of(date(2026, 10, 31)) == Decimal("44000.00")
        # A later month still reflects everything banked before it.
        assert balance_as_of(date(2026, 11, 30)) == Decimal("44000.00")


# ------------------------------ monthly trend ------------------------------ #

def test_monthly_trend_walks_back_across_a_year_boundary(seeded):
    from finance import monthly_trend
    with seeded.app_context():
        series = monthly_trend(date(2027, 2, 28), months=12)
    assert len(series) == 12
    assert series[0]["key"] == "2026-03"
    assert series[-1]["key"] == "2027-02"
    keys = [row["key"] for row in series]
    assert keys == sorted(keys), "months must be chronological"
    october = next(row for row in series if row["key"] == "2026-10")
    assert october["income"] == Decimal("51000.00")
    assert october["net"] == Decimal("44000.00")


def test_monthly_trend_from_january_reaches_previous_year(seeded):
    from finance import monthly_trend
    with seeded.app_context():
        series = monthly_trend(date(2027, 1, 15), months=12)
    assert series[0]["key"] == "2026-02"
    assert series[-1]["key"] == "2027-01"


# ----------------------------- partner shares ------------------------------ #

class FakePartner:
    def __init__(self, name, equity):
        self.name = name
        self.equity_pct = Decimal(str(equity))


def six_partners():
    return [FakePartner(f"P{i}", 20) for i in range(1, 5)] + \
           [FakePartner(f"P{i}", 10) for i in range(5, 7)]


def test_shares_split_44000_correctly(app):
    from finance import partner_shares
    result = partner_shares(Decimal("44000"), six_partners())
    assert [row["share"] for row in result["rows"]] == [
        Decimal("8800.00")] * 4 + [Decimal("4400.00")] * 2
    assert result["allocated"] == Decimal("44000.00")
    assert result["balanced"] is True
    assert result["unallocated"] == Decimal("0.00")


def test_shares_always_resum_to_the_whole(app):
    """A net that does not divide cleanly must still allocate exactly."""
    from finance import partner_shares
    for net in ["100.01", "0.01", "33333.33", "1", "7", "99999.99", "12345.67"]:
        result = partner_shares(Decimal(net), six_partners())
        assert result["allocated"] == Decimal(net), f"net {net} lost money in the split"
        assert result["unallocated"] == Decimal("0.00")


def test_shares_handle_a_loss(app):
    from finance import partner_shares
    result = partner_shares(Decimal("-10000"), six_partners())
    assert result["allocated"] == Decimal("-10000.00")
    assert all(row["share"] < 0 for row in result["rows"])


def test_shares_handle_zero_and_no_partners(app):
    from finance import partner_shares
    zero = partner_shares(Decimal("0"), six_partners())
    assert zero["allocated"] == Decimal("0.00")
    none = partner_shares(Decimal("5000"), [])
    assert none["rows"] == []
    assert none["balanced"] is False


def test_unbalanced_equity_is_prorata_and_flagged(app):
    from finance import partner_shares
    result = partner_shares(Decimal("1000"), [FakePartner("A", 20), FakePartner("B", 30)])
    assert result["balanced"] is False
    assert result["equity_total"] == Decimal("50.00")
    assert [row["share"] for row in result["rows"]] == [Decimal("200.00"), Decimal("300.00")]
    assert result["unallocated"] == Decimal("500.00")


# --------------------------------- routes ---------------------------------- #

@pytest.mark.parametrize("path", ["/", "/income", "/expenses", "/partners",
                                  "/transactions", "/export.xlsx"])
def test_routes_require_login(client, path):
    response = client.get(path)
    assert response.status_code in (301, 302, 308)
    assert "/login" in response.headers["Location"]


def test_wrong_password_is_rejected(client):
    assert login(client, "nope").status_code == 401


def test_correct_password_signs_in(client):
    assert login(client).status_code in (301, 302, 308)


@pytest.mark.parametrize("path,needle", [
    ("/", "Dashboard"), ("/income", "Income"), ("/expenses", "Expenses"),
    ("/partners", "Partner Profit"), ("/transactions", "All Transactions"),
])
def test_pages_render(client, path, needle):
    login(client)
    body = client.get(path).get_data(as_text=True)
    assert needle in body
    assert "Traceback" not in body and "UndefinedError" not in body


def test_dashboard_kpis_follow_the_filter(client):
    login(client)
    october = client.get("/?period=month&month=2026-10").get_data(as_text=True)
    assert kpi(october, "Income · Credit") == "51,000"
    assert kpi(october, "Expenses · Debit") == "7,000"
    assert kpi(october, "Net profit") == "44,000"

    november = client.get("/?period=month&month=2026-11").get_data(as_text=True)
    assert kpi(november, "Income · Credit") == "0"
    assert kpi(november, "Net profit") == "0"
    # Balance carried forward is still cumulative.
    assert kpi(november, "Closing balance") == "44,000"

    partial = client.get("/?period=custom&from=2026-10-01&to=2026-10-03").get_data(as_text=True)
    assert kpi(partial, "Income · Credit") == "34,000"
    assert kpi(partial, "Expenses · Debit") == "0"


def test_latest_entries_card_respects_the_filter(client):
    """The card must not contradict the KPIs by listing out-of-period entries."""
    login(client)
    body = client.get("/?period=month&month=2026-11").get_data(as_text=True)
    # Slice just the card: from its heading to the start of the entry dialog.
    card = body.split("Latest entries")[1].split('id="entryModal"')[0]
    assert "ECL booking" not in card, "out-of-period entry shown in the period card"
    assert "No entries for" in card

    # And for a month that does have data, the card is populated.
    october = client.get("/?period=month&month=2026-10").get_data(as_text=True)
    card = october.split("Latest entries")[1].split('id="entryModal"')[0]
    assert "ECL booking" in card


def test_csrf_is_required_for_writes(client):
    login(client)
    response = client.post("/transactions/new", data={
        "kind": "income", "txn_date": "2026-10-06", "category": "Tournament", "amount": "777"})
    assert response.status_code == 400
    assert kpi(client.get("/").get_data(as_text=True), "Net profit") == "44,000"


def test_create_edit_delete_roundtrip(client):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-06",
        "category": "Tournament", "description": "Night league", "amount": "12500.50",
        "next": "/income"}, follow_redirects=True)

    body = client.get("/income").get_data(as_text=True)
    assert "Night league" in body and "12,500.50" in body
    txn_id = re.search(r'data-id="(\d+)"[^>]*data-description="Night league"', body)
    assert txn_id, "created entry not editable"
    txn_id = txn_id.group(1)

    page = client.get("/income").get_data(as_text=True)
    client.post(f"/transactions/{txn_id}/edit", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-06",
        "category": "Tournament", "description": "Night league final", "amount": "900",
        "next": "/income"}, follow_redirects=True)
    assert "Night league final" in client.get("/income").get_data(as_text=True)

    page = client.get("/income").get_data(as_text=True)
    client.post(f"/transactions/{txn_id}/delete",
                data={"csrf_token": _csrf(page), "next": "/income"}, follow_redirects=True)
    assert "Night league final" not in client.get("/income").get_data(as_text=True)
    assert kpi(client.get("/").get_data(as_text=True), "Net profit") == "44,000"


@pytest.mark.parametrize("payload", [
    {"kind": "income", "txn_date": "2026-10-06", "category": "Tournament", "amount": "-500"},
    {"kind": "income", "txn_date": "2026-10-06", "category": "Tournament", "amount": "0"},
    {"kind": "income", "txn_date": "2026-10-06", "category": "Tournament", "amount": "abc"},
    {"kind": "income", "txn_date": "2026-10-06", "category": "Tournament", "amount": "NaN"},
    {"kind": "income", "txn_date": "2026-10-06", "category": "Tournament", "amount": ""},
    {"kind": "income", "txn_date": "bad-date", "category": "Tournament", "amount": "100"},
    {"kind": "banana", "txn_date": "2026-10-06", "category": "Tournament", "amount": "100"},
    {"kind": "income", "txn_date": "2026-10-06", "category": "", "amount": "100"},
])
def test_invalid_entries_are_rejected(client, payload):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    data = dict(payload, csrf_token=_csrf(page), next="/income")
    client.post("/transactions/new", data=data, follow_redirects=True)
    assert kpi(client.get("/").get_data(as_text=True), "Net profit") == "44,000"


def test_amount_accepts_commas_and_currency_symbol(client):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-07",
        "category": "Tournament", "description": "Comma test", "amount": "₹1,500",
        "next": "/income"}, follow_redirects=True)
    assert kpi(client.get("/").get_data(as_text=True), "Net profit") == "45,500"


def test_editing_a_missing_entry_is_404(client):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    response = client.post("/transactions/999999/delete",
                           data={"csrf_token": _csrf(page), "next": "/income"})
    assert response.status_code == 404


def test_partner_equity_can_be_renamed_and_validated(client):
    login(client)
    page = client.get("/partners").get_data(as_text=True)
    ids = re.findall(r'name="name_(\d+)"', page)
    assert len(ids) == 6

    data = {"csrf_token": _csrf(page), "next": "/partners"}
    names = ["Ravi", "Suresh", "Anil", "Vikram", "Kiran", "Deepak"]
    for index, pid in enumerate(ids):
        data[f"name_{pid}"] = names[index]
        data[f"equity_{pid}"] = "20" if index < 4 else "10"
        data[f"active_{pid}"] = "on"
    body = client.post("/partners/save", data=data, follow_redirects=True).get_data(as_text=True)
    assert "Ravi" in body and "Deepak" in body

    # Non-numeric equity is refused and nothing is written.
    page = client.get("/partners").get_data(as_text=True)
    bad = dict(data, csrf_token=_csrf(page))
    bad[f"equity_{ids[0]}"] = "abc"
    body = client.post("/partners/save", data=bad, follow_redirects=True).get_data(as_text=True)
    assert "must be a number" in body
    assert "Ravi" in client.get("/partners").get_data(as_text=True)

    # Out-of-range equity is refused.
    page = client.get("/partners").get_data(as_text=True)
    bad = dict(data, csrf_token=_csrf(page))
    bad[f"equity_{ids[0]}"] = "150"
    body = client.post("/partners/save", data=bad, follow_redirects=True).get_data(as_text=True)
    assert "between 0 and 100" in body

    # A blank name is refused.
    page = client.get("/partners").get_data(as_text=True)
    bad = dict(data, csrf_token=_csrf(page))
    bad[f"name_{ids[0]}"] = ""
    body = client.post("/partners/save", data=bad, follow_redirects=True).get_data(as_text=True)
    assert "cannot be blank" in body


def test_partner_page_shows_each_share(client):
    login(client)
    body = client.get("/partners?period=month&month=2026-10").get_data(as_text=True)
    assert body.count("8,800") >= 4
    assert body.count("4,400") >= 2


def test_running_balance_in_transactions_view(client):
    login(client)
    body = client.get("/transactions?period=month&month=2026-10").get_data(as_text=True)
    assert "44,000" in body  # final running balance
    assert "Credit" in body and "Debit" in body


def test_xss_in_a_description_is_escaped(client):
    login(client)
    page = client.get("/income").get_data(as_text=True)
    client.post("/transactions/new", data={
        "csrf_token": _csrf(page), "kind": "income", "txn_date": "2026-10-08",
        "category": "Tournament", "description": '<script>alert(1)</script>',
        "party": '"><img src=x onerror=alert(2)>', "amount": "100",
        "next": "/income"}, follow_redirects=True)
    body = client.get("/income").get_data(as_text=True)
    # The payload must never appear as live markup...
    assert "<script>alert(1)" not in body
    assert "<img src=x" not in body
    # ...and the quote must be escaped so it cannot break out of an attribute.
    assert re.search(r'data-party="[^"]*&#34;', body), "quote not escaped in attribute"
    # ...while still being present as inert, escaped text.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_logout_clears_the_session(client):
    login(client)
    page = client.get("/").get_data(as_text=True)
    client.post("/logout", data={"csrf_token": _csrf(page)})
    response = client.get("/")
    assert response.status_code in (301, 302, 308)
    assert "/login" in response.headers["Location"]


def test_healthz(client):
    assert client.get("/healthz").status_code == 200


def test_404_page(client):
    login(client)
    assert client.get("/no-such-page").status_code == 404


# ------------------------- dashboard trend window -------------------------- #

def test_trend_window_starts_at_the_first_month_with_data(seeded):
    """A ledger beginning Oct 2026 must open on Oct 2026, not on empty columns."""
    from finance import parse_period, trend_window
    with seeded.app_context():
        window = trend_window(parse_period({"period": "month", "month": "2026-10"}))
    keys = [row["key"] for row in window["series"]]
    assert len(keys) == 12
    assert keys[0] == "2026-10"
    assert keys[-1] == "2027-09"
    assert keys == sorted(keys)
    assert window["label"] == "Oct 2026 – Sep 2027"
    october = window["series"][0]
    assert october["income"] == Decimal("51000.00")
    assert october["expense"] == Decimal("7000.00")
    assert october["net"] == Decimal("44000.00")


def test_trend_window_is_stable_across_period_choices(seeded):
    """Filtering to a later month inside the window must not shift the chart."""
    from finance import parse_period, trend_window
    with seeded.app_context():
        for args in ({"period": "month", "month": "2026-11"},
                     {"period": "quarter", "year": "2026", "quarter": "4"},
                     {"period": "year", "year": "2026"},
                     {"period": "all"}):
            window = trend_window(parse_period(args))
            assert window["series"][0]["key"] == "2026-10", args


def test_trend_window_rolls_forward_once_the_ledger_outgrows_it(seeded):
    """Past 12 months of history the chart must follow the data, not stay in 2026."""
    from models import INCOME, Transaction, db
    from finance import parse_period, trend_window
    with seeded.app_context():
        db.session.add(Transaction(txn_date=date(2028, 3, 10), kind=INCOME,
                                   category="Tournament", amount=Decimal("500")))
        db.session.commit()
        window = trend_window(parse_period({"period": "month", "month": "2028-03"}))
    keys = [row["key"] for row in window["series"]]
    assert keys[-1] == "2028-03", keys
    assert keys[0] == "2027-04", keys


def test_trend_window_never_starts_after_the_month_in_view(seeded):
    """Selecting a month before the data still shows that month on the chart."""
    from finance import parse_period, trend_window
    with seeded.app_context():
        window = trend_window(parse_period({"period": "month", "month": "2026-05"}))
    keys = [row["key"] for row in window["series"]]
    assert keys[0] == "2026-05", keys
    assert "2026-05" in keys


def test_trend_window_with_an_empty_ledger(app):
    from finance import parse_period, trend_window
    with app.app_context():
        window = trend_window(parse_period({"period": "month", "month": "2026-10"}))
    keys = [row["key"] for row in window["series"]]
    assert len(keys) == 12
    assert keys[-1] == "2026-10"
    assert all(row["income"] == Decimal("0") for row in window["series"])


def test_dashboard_chart_title_names_the_window(client):
    login(client)
    body = client.get("/?period=month&month=2026-10").get_data(as_text=True)
    assert "Income vs expenses &mdash; Oct 2026 – Sep 2027" in body or \
           "Income vs expenses — Oct 2026 – Sep 2027" in body, "chart title not showing the window"
    assert "last 12 months" not in body, "stale 'last 12 months' label still present"


# ------------------------- ledger row ordering ----------------------------- #

def _dates_in(html):
    """Dates as they appear down a ledger table body."""
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    return re.findall(r'<td class="nowrap">(\d{2} \w{3} \d{4})</td>', body)


@pytest.mark.parametrize("path", ["/income", "/expenses", "/transactions"])
def test_ledger_tables_read_oldest_first(client, path):
    login(client)
    html = client.get(f"{path}?period=month&month=2026-10").get_data(as_text=True)
    dates = [datetime.strptime(d, "%d %b %Y").date() for d in _dates_in(html)]
    assert dates, f"no rows found on {path}"
    assert dates == sorted(dates), f"{path} is not ascending: {dates}"


def test_transactions_running_balance_builds_downwards(client):
    login(client)
    html = client.get("/transactions?period=month&month=2026-10").get_data(as_text=True)
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    balances = re.findall(r'<strong>₹([\d,]+(?:\.\d+)?)</strong>', body)
    numbers = [float(b.replace(",", "")) for b in balances]
    assert numbers[0] == 7000.0, f"first row should be the earliest entry: {numbers[:3]}"
    assert numbers[-1] == 44000.0, f"last row should close at the period total: {numbers[-3:]}"


def test_dashboard_latest_entries_stays_newest_first(client):
    """That card is labelled 'Latest', so it legitimately reads the other way."""
    login(client)
    html = client.get("/?period=month&month=2026-10").get_data(as_text=True)
    card = html.split("Latest entries")[1].split('id="entryModal"')[0]
    days = re.findall(r'<td class="nowrap small">(\d{2}) \w{3}</td>', card)
    numbers = [int(d) for d in days]
    assert numbers == sorted(numbers, reverse=True), f"not newest-first: {numbers}"


def test_csv_export_route_is_gone(client):
    login(client)
    assert client.get("/export.csv").status_code == 404
