"""Revenue forecast engine (WEB_PARITY_CHANGES.md section 10 and 11.1)."""
import os
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forecast as fc  # noqa: E402

D = Decimal
TODAY = date(2026, 11, 15)

# The 10.6 per-category running costs for Oct 2026 (total 1,23,676).
OCT_EXPENSES = {
    "Miscellaneous": D("32580"),
    "Salary / chit payment": D("31000"),
    "Groundsman wages": D("21980"),
    "Electricity": D("13479"),
    "Ground maintenance": D("13017"),
    "Market expenses": D("7020"),
    "Repairs": D("4600"),
}


def inc(day, amount, category="Ground booking"):
    return SimpleNamespace(txn_date=day, kind="income", category=category, amount=D(str(amount)))


def exp(day, amount, category="Miscellaneous"):
    return SimpleNamespace(txn_date=day, kind="expense", category=category, amount=D(str(amount)))


def worked_example_entries():
    entries = [inc(date(2026, 10, 3), 100000), inc(date(2026, 10, 20), 86000)]
    for i, (category, amount) in enumerate(OCT_EXPENSES.items()):
        entries.append(exp(date(2026, 10, 1 + i), amount, category))
    # November in progress: well below the forecast.
    entries += [inc(date(2026, 11, 2), 40000), exp(date(2026, 11, 4), 9000, "Electricity")]
    return entries


def monthly_entries(first, values_income, values_running):
    """One income and one expense entry per month starting at ``first``."""
    out = []
    for i, (a, b) in enumerate(zip(values_income, values_running)):
        m = fc._add_months(first, i)
        out.append(inc(date(m.year, m.month, 10), a))
        out.append(exp(date(m.year, m.month, 12), b))
    return out


def by_label(result):
    return {y["label"]: y for y in result["years"]}


def month_row(result, year, month):
    return next(m for m in result["months"] if m["month"] == date(year, month, 1))


# --------------------------------------------------------------------------- #
# 10.6 worked example
# --------------------------------------------------------------------------- #

def test_worked_example_years():
    r = fc.forecast_from_history(worked_example_entries(), TODAY, years=3, fiscal=True)
    assert r["method"] == "Average month"
    years = by_label(r)
    assert list(years) == ["FY 2026-27", "FY 2027-28", "FY 2028-29", "FY 2029-30"]

    fy26 = years["FY 2026-27"]
    assert fy26["income"] == D("1116000.00")
    assert fy26["running"] == D("742056.00")
    assert fy26["rent"] == D("0.00")
    assert fy26["net"] == D("373944.00")
    assert fy26["partial"] is True
    assert fy26["months_covered"] == 6
    assert fy26["basis"] == "Actual + forecast"
    assert fy26["basis_label"] == "Actual + forecast · 6 mo"
    assert fy26["yoy"] is None
    assert fy26["start"] == date(2026, 4, 1)

    fy27 = years["FY 2027-28"]
    assert fy27["income"] == D("2232000.00")
    assert fy27["running"] == D("1484112.00")
    assert fy27["rent"] == D("720000.00")
    assert fy27["expenses"] == D("2204112.00")
    assert fy27["net"] == D("27888.00")
    assert fy27["yoy"] is None  # previous year is partial
    assert fy27["basis"] == "Forecast"
    assert fy27["partial"] is False
    assert fy27["net_low"] < fy27["net"] < fy27["net_high"]

    fy28 = years["FY 2028-29"]
    assert fy28["net"] == D("27888.00")
    assert fy28["yoy"] == D("0")

    assert r["current_year"] is fy26
    assert r["next_year"] is fy27
    assert r["rent"] == {"monthly": D("60000.00"), "start": date(2027, 4, 1)}


def test_worked_example_months():
    r = fc.forecast_from_history(worked_example_entries(), TODAY)
    months = r["months"]
    assert months[0]["month"] == date(2026, 10, 1)  # months before the ledger are omitted
    assert months[-1]["month"] == date(2030, 3, 1)
    assert months[0]["status"] == "actual"
    assert months[1]["status"] == "current"
    assert months[1]["label"] == "Nov 2026"
    assert all(m["status"] == "forecast" for m in months[2:])
    for m in months:
        if m["month"] < date(2027, 4, 1):
            assert m["net"] == D("62324.00"), m["label"]
            assert m["rent"] == D("0.00")
        else:
            assert m["net"] == D("2324.00"), m["label"]
            assert m["rent"] == D("60000.00")
            assert m["expenses"] == D("183676.00")
    oct_row = months[0]
    assert oct_row["income_low"] == oct_row["income_high"] == D("186000.00")
    dec = months[2]
    assert dec["income_low"] < dec["income"] < dec["income_high"]
    assert dec["income_low"] >= 0


def test_worked_example_projected_expenses():
    r = fc.forecast_from_history(worked_example_entries(), TODAY)
    assert r["projected_expenses"] == [
        {"category": c, "monthly": a.quantize(D("0.01"))} for c, a in OCT_EXPENSES.items()
    ]
    assert r["running_next"] == D("123676.00")
    assert r["total_with_rent"] == D("183676.00")
    assert any("Ground rent of ₹60,000 a month is added from Apr 2027" in n for n in r["notes"])
    assert any("FY 2026-27 covers only 6 months" in n for n in r["notes"])
    assert any("Only 1 complete month" in n for n in r["notes"])


def test_accepts_tuples_and_dicts():
    entries = [(e.txn_date, e.kind, e.category, e.amount) for e in worked_example_entries()]
    r = fc.forecast_from_history(entries, TODAY)
    assert by_label(r)["FY 2026-27"]["net"] == D("373944.00")
    dicts = [dict(txn_date=e.txn_date, kind=e.kind, category=e.category, amount=e.amount)
             for e in worked_example_entries()]
    r = fc.forecast_from_history(dicts, TODAY)
    assert by_label(r)["FY 2027-28"]["net"] == D("27888.00")


# --------------------------------------------------------------------------- #
# Model selection
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("n, method", [
    (0, "No history"),
    (2, "Average month"),
    (4, "Simple exponential smoothing"),
    (8, "Holt's damped trend"),
    (24, "Holt–Winters (additive, damped, 12-month season)"),
    (30, "Holt–Winters (additive, damped, 12-month season)"),
])
def test_model_selection_by_complete_months(n, method):
    first = fc._add_months(date(2026, 11, 1), -n)
    income = [100000 + 1000 * (i % 5) for i in range(n)]
    running = [60000 + 500 * (i % 3) for i in range(n)]
    entries = monthly_entries(first, income, running)
    # an entry in the current month never counts as a complete month
    entries.append(inc(date(2026, 11, 3), 500))
    r = fc.forecast_from_history(entries, TODAY)
    assert r["method"] == method
    assert sum(1 for m in r["months"] if m["status"] == "actual") == n


def test_method_for_boundaries():
    assert [fc.method_for(n) for n in (0, 1, 2, 3, 5, 6, 23, 24)] == [
        "No history", "Average month", "Average month", "Simple exponential smoothing",
        "Simple exponential smoothing", "Holt's damped trend", "Holt's damped trend",
        "Holt–Winters (additive, damped, 12-month season)",
    ]


def test_no_history_shape():
    r = fc.forecast_from_history([], TODAY, years=1)
    assert r["method"] == "No history"
    assert r["notes"]
    assert [y["label"] for y in r["years"]] == ["FY 2026-27", "FY 2027-28"]
    assert r["months"][0]["month"] == date(2026, 11, 1)
    assert all(m["income"] == 0 and m["running"] == 0 for m in r["months"])
    assert r["projected_expenses"] == []
    assert r["running_next"] == D("0.00")
    assert r["total_with_rent"] == D("60000.00")
    assert r["next_year"]["label"] == "FY 2027-28"


def test_average_month_sigma_floor_is_25_percent():
    fit = fc.fit_series([100000])
    assert fit["sigma"] == pytest.approx(25000)
    mean, var = fc.predict(fit, 3)
    assert mean == pytest.approx(100000)
    assert var == pytest.approx(25000 ** 2)


def test_ses_tracks_level():
    fit = fc.fit_series([100, 100, 100, 100, 100])
    assert fit["method"] == "Simple exponential smoothing"
    mean, _ = fc.predict(fit, 1)
    assert mean == pytest.approx(100)
    assert fit["sigma"] == pytest.approx(10)  # 10% of the average month floor


def test_holt_damped_trend_rises_but_flattens():
    y = [100000 + 5000 * i for i in range(12)]
    fit = fc.fit_series(y)
    assert fit["method"] == "Holt's damped trend"
    m1, v1 = fc.predict(fit, 1)
    m12, v12 = fc.predict(fit, 12)
    m60, _ = fc.predict(fit, 60)
    assert m1 > y[-1]
    assert m12 > m1
    # damped: the increase over the next 48 months is much less than straight-line
    assert (m60 - m12) < 5000 * 48 * 0.5
    assert v12 > v1


def test_holt_winters_reproduces_seasonality():
    # 29 complete months, Jun 2024 .. Oct 2026: monsoon dip Jun-Sep, peak Dec-Jan.
    first = date(2024, 6, 1)
    income, running = [], []
    for i in range(29):
        m = fc._add_months(first, i)
        base = 150000 + 500 * i
        if m.month in (6, 7, 8, 9):
            base -= 60000
        elif m.month in (12, 1):
            base += 70000
        income.append(base)
        running.append(90000 + (5000 if m.month in (12, 1) else 0))
    r = fc.forecast_from_history(monthly_entries(first, income, running), TODAY, years=1)
    assert r["method"] == "Holt–Winters (additive, damped, 12-month season)"
    peak = [month_row(r, 2026, 12)["income"], month_row(r, 2027, 1)["income"]]
    dip = [month_row(r, 2027, mo)["income"] for mo in (6, 7, 8, 9)]
    other = [month_row(r, 2027, mo)["income"] for mo in (2, 3, 4, 5, 10, 11)]
    assert min(peak) > max(other)
    assert min(other) > max(dip)
    assert all(m["status"] == "actual" for m in r["months"][:29])
    assert r["months"][29]["status"] == "current"
    assert any("Holt–Winters" in n for n in r["notes"])
    # 29 months from Jun 2024: FY 2024-25 is partial (10 mo), FY 2025-26 complete -> YoY shown.
    years = by_label(r)
    assert years["FY 2024-25"]["partial"] and years["FY 2024-25"]["months_covered"] == 10
    assert years["FY 2024-25"]["basis"] == "Actual"
    assert years["FY 2025-26"]["yoy"] is None
    assert years["FY 2026-27"]["yoy"] is not None
    assert years["FY 2027-28"]["yoy"] is not None


# --------------------------------------------------------------------------- #
# Rent
# --------------------------------------------------------------------------- #

def test_rent_entries_after_start_not_double_counted():
    today = date(2027, 6, 15)
    entries = []
    for m in range(1, 6):  # Jan-May 2027
        entries.append(inc(date(2027, m, 5), 200000))
        entries.append(exp(date(2027, m, 6), 50000, "Electricity"))
        # A lease payment before the rent start counts as running cost; after it, as rent.
        entries.append(exp(date(2027, m, 7), 60000, "Rent / lease"))
    r = fc.forecast_from_history(entries, today, years=1)
    jan, mar, apr, may = (month_row(r, 2027, mo) for mo in (1, 3, 4, 5))
    assert jan["running"] == D("110000.00") and jan["rent"] == D("0.00")
    assert mar["running"] == D("110000.00") and mar["rent"] == D("0.00")
    assert apr["running"] == D("50000.00") and apr["rent"] == D("60000.00")
    assert may["running"] == D("50000.00") and may["expenses"] == D("110000.00")
    # Future months: scheduled rent only once.
    july = month_row(r, 2027, 7)
    assert july["rent"] == D("60000.00")
    # Only the three pre-start lease payments (Jan-Mar) count as running cost history.
    assert sum(m["running"] for m in r["months"] if m["status"] == "actual") == D("430000.00")
    assert sum(m["rent"] for m in r["months"] if m["status"] == "actual") == D("120000.00")


def test_rent_zero_disables_rent():
    r = fc.forecast_from_history(worked_example_entries(), TODAY, rent_monthly=D("0"))
    assert all(m["rent"] == 0 for m in r["months"])
    years = by_label(r)
    assert years["FY 2027-28"]["rent"] == 0
    assert years["FY 2027-28"]["net"] == D("747888.00")
    assert r["total_with_rent"] == r["running_next"]
    assert any("No ground rent" in n for n in r["notes"])


def test_rent_zero_keeps_lease_entries_as_running():
    entries = [inc(date(2027, 5, 1), 100000), exp(date(2027, 5, 2), 30000, "Rent / lease")]
    r = fc.forecast_from_history(entries, date(2027, 6, 10), rent_monthly=0)
    assert month_row(r, 2027, 5)["running"] == D("30000.00")


def test_custom_rent_start_and_amount():
    r = fc.forecast_from_history(worked_example_entries(), TODAY,
                                 rent_monthly=D("50000"), rent_start=date(2027, 1, 1))
    assert month_row(r, 2026, 12)["rent"] == 0
    assert month_row(r, 2027, 1)["rent"] == D("50000.00")
    assert by_label(r)["FY 2026-27"]["rent"] == D("150000.00")


def test_current_month_rent_is_max_of_scheduled_and_recorded():
    today = date(2027, 4, 20)
    entries = [inc(date(2027, 3, 1), 100000), exp(date(2027, 4, 2), 75000, "Rent / lease")]
    r = fc.forecast_from_history(entries, today, years=1)
    assert month_row(r, 2027, 4)["rent"] == D("75000.00")


# --------------------------------------------------------------------------- #
# Current month
# --------------------------------------------------------------------------- #

def test_current_month_uses_max_of_forecast_and_recorded():
    entries = worked_example_entries()
    r = fc.forecast_from_history(entries, TODAY)
    nov = month_row(r, 2026, 11)
    assert nov["income"] == D("186000.00")  # forecast beats the 40,000 recorded
    assert nov["running"] == D("123676.00")

    entries += [inc(date(2026, 11, 10), 210000), exp(date(2026, 11, 11), 150000, "Repairs")]
    r = fc.forecast_from_history(entries, TODAY)
    nov = month_row(r, 2026, 11)
    assert nov["income"] == D("250000.00")  # recorded so far beats the forecast
    assert nov["running"] == D("159000.00")
    assert nov["income_low"] >= D("250000.00")
    assert nov["status"] == "current"


# --------------------------------------------------------------------------- #
# Calendar years
# --------------------------------------------------------------------------- #

def test_calendar_year_mode():
    r = fc.forecast_from_history(worked_example_entries(), TODAY, years=2, fiscal=False)
    assert r["fiscal"] is False and r["years_ahead"] == 2
    labels = [y["label"] for y in r["years"]]
    assert labels == ["2026", "2027", "2028"]
    y2026, y2027 = r["years"][0], r["years"][1]
    assert y2026["start"] == date(2026, 1, 1) and y2026["end"] == date(2026, 12, 1)
    assert y2026["months_covered"] == 3 and y2026["partial"]
    assert y2026["basis_label"] == "Actual + forecast · 3 mo"
    assert y2026["income"] == D("558000.00")
    # 2027: rent from April = 9 months.
    assert y2027["rent"] == D("540000.00")
    assert r["current_year"]["label"] == "2026"
    assert r["next_year"]["label"] == "2027"
    assert r["months"][-1]["month"] == date(2028, 12, 1)


@pytest.mark.parametrize("years", fc.YEARS_CHOICES)
def test_years_ahead(years):
    r = fc.forecast_from_history(worked_example_entries(), TODAY, years=years)
    assert len(r["years"]) == years + 1
    assert r["years"][-1]["months_covered"] == 12


# --------------------------------------------------------------------------- #
# Settings (needs a database)
# --------------------------------------------------------------------------- #

@pytest.fixture()
def db_app(tmp_path):
    for module in ("models", "forecast"):
        sys.modules.pop(module, None)
    from flask import Flask

    import forecast
    import models

    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/f.db", TESTING=True)
    models.db.init_app(app)
    with app.app_context():
        models.db.create_all()
        yield app, models, forecast
        models.db.session.remove()


def test_rent_settings_round_trip_and_fallback(db_app):
    app, models, forecast = db_app
    assert forecast.rent_settings() == (D("60000"), date(2027, 4, 1))

    forecast.save_rent_settings(D("45000.5"), date(2028, 1, 1))
    assert models.Setting.get("forecast_rent_monthly") == "45000.50"
    assert models.Setting.get("forecast_rent_start") == "2028-01"
    assert forecast.rent_settings() == (D("45000.50"), date(2028, 1, 1))

    forecast.save_rent_settings(D("0"), date(2027, 4, 1))
    assert models.Setting.get("forecast_rent_monthly") == "0.00"
    assert forecast.rent_settings() == (D("0"), date(2027, 4, 1))

    for monthly, start in (("abc", "2027-13"), ("-5", "nope"), ("NaN", "")):
        models.Setting.put("forecast_rent_monthly", monthly)
        models.Setting.put("forecast_rent_start", start)
        models.db.session.commit()
        assert forecast.rent_settings() == (D("60000"), date(2027, 4, 1))


def test_build_forecast_reads_db_and_settings(db_app):
    app, models, forecast = db_app
    for e in worked_example_entries():
        models.db.session.add(models.Transaction(
            txn_date=e.txn_date, kind=e.kind, category=e.category, amount=e.amount))
    models.db.session.commit()
    r = forecast.build_forecast(today=TODAY)
    fy27 = next(y for y in r["years"] if y["label"] == "FY 2027-28")
    assert fy27["net"] == D("27888.00")

    forecast.save_rent_settings(D("0"), date(2027, 4, 1))
    r = forecast.build_forecast(today=TODAY, years=1, fiscal=False)
    assert [y["label"] for y in r["years"]] == ["2026", "2027"]
    assert all(m["rent"] == 0 for m in r["months"])
