"""Revenue forecast: exponential smoothing over the monthly ledger history.

Implements WEB_PARITY_CHANGES.md section 10 (and the settings keys in 11.1).

* Income and running expenses are fitted separately from **complete** months
  only (the current month is still in progress).
* "Rent / lease" expenses dated on or after the rent start month are the
  scheduled ground rent: they're kept out of running costs (``rentPaid``) so
  rent is never counted twice.
* The model is picked by the number of complete months: none (0), average
  month (1-2), simple exponential smoothing (3-5), Holt's damped trend (6-23)
  or additive damped Holt-Winters with a 12-month season (24+). Smoothing
  parameters come from a grid search minimising one-step-ahead squared error.

The maths runs in floats (stdlib only); everything returned is ``Decimal``
quantized to 0.01. ``forecast_from_history`` is pure and needs no database;
``build_forecast`` loads the ledger and the rent settings and calls it.
"""
from __future__ import annotations

import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

RENT_CATEGORY = "Rent / lease"
DEFAULT_RENT_MONTHLY = Decimal("60000")
DEFAULT_RENT_START = date(2027, 4, 1)
YEARS_CHOICES = (1, 2, 3, 5)

RENT_MONTHLY_KEY = "forecast_rent_monthly"
RENT_START_KEY = "forecast_rent_start"

METHOD_NONE = "No history"
METHOD_AVERAGE = "Average month"
METHOD_SES = "Simple exponential smoothing"
METHOD_HOLT = "Holt's damped trend"
METHOD_HW = "Holt–Winters (additive, damped, 12-month season)"

Z80 = 1.2816  # two-sided 80% normal interval

ALPHAS = tuple(round(0.05 * i, 2) for i in range(1, 20))  # 0.05 .. 0.95
BETAS = tuple(round(0.05 * i, 2) for i in range(1, 11))  # 0.05 .. 0.50
PHIS_HOLT = (0.80, 0.85, 0.90, 0.95)
PHIS_HW = (0.80, 0.85, 0.90, 0.95, 0.98)
GAMMAS = (0.05, 0.10, 0.20, 0.30)
SEASON = 12

_TWOPLACES = Decimal("0.01")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _q2(value) -> Decimal:
    if isinstance(value, float):
        value = repr(value)
    return Decimal(value or 0).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)


def _money(value) -> str:
    """'₹1,23,676' style (Indian grouping, paise only when non-zero)."""
    amount = _q2(value)
    sign = "-" if amount < 0 else ""
    whole, _, frac = f"{abs(amount):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = whole if frac == "00" else f"{whole}.{frac}"
    return f"{sign}₹{out}"


def _month_start(day: date) -> date:
    return date(day.year, day.month, 1)


def _add_months(month: date, n: int) -> date:
    index = month.year * 12 + (month.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def _months_between(a: date, b: date) -> int:
    """Whole months from month ``a`` to month ``b`` (b - a)."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def _label(month: date) -> str:
    return f"{_MONTHS[month.month - 1]} {month.year}"


def _year_start(month: date, fiscal: bool) -> date:
    if not fiscal:
        return date(month.year, 1, 1)
    return date(month.year if month.month >= 4 else month.year - 1, 4, 1)


def _year_label(start: date, fiscal: bool) -> str:
    if fiscal:
        return f"FY {start.year}-{(start.year + 1) % 100:02d}"
    return str(start.year)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _entry_fields(entry):
    """(txn_date, kind, category, amount) from a Transaction, namespace, dict or tuple."""
    if isinstance(entry, dict):
        return entry["txn_date"], entry["kind"], entry.get("category", ""), entry["amount"]
    if isinstance(entry, (tuple, list)):
        txn_date, kind, category, amount = entry[:4]
        return txn_date, kind, category, amount
    return entry.txn_date, entry.kind, getattr(entry, "category", ""), entry.amount


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

def _fit_none() -> dict:
    return {"method": METHOD_NONE, "n": 0, "l": 0.0, "b": 0.0, "phi": 0.0, "alpha": 0.0,
            "beta": 0.0, "gamma": 0.0, "seasons": None, "sigma": 0.0, "avg": 0.0}


def _fit_average(y: list) -> dict:
    n = len(y)
    mean = sum(y) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in y) / (n - 1)) if n > 1 else 0.0
    sigma = max(sd, 0.25 * mean, 0.10 * mean)
    fit = _fit_none()
    fit.update(method=METHOD_AVERAGE, n=n, l=mean, sigma=sigma, avg=mean)
    return fit


def _sse_ses(y, alpha):
    level = y[0]
    sse = 0.0
    for value in y[1:]:
        err = value - level
        sse += err * err
        level += alpha * err
    return sse, level


def _fit_ses(y: list) -> dict:
    best = None
    for alpha in ALPHAS:
        sse, level = _sse_ses(y, alpha)
        if best is None or sse < best[0]:
            best = (sse, alpha, level)
    sse, alpha, level = best
    fit = _fit_none()
    fit.update(method=METHOD_SES, n=len(y), l=level, alpha=alpha, avg=sum(y) / len(y))
    fit["sigma"] = _sigma(sse, len(y) - 1, 1, fit["avg"])
    return fit


def _run_holt(y, alpha, beta, phi, b0):
    level, trend = y[0], b0
    sse = 0.0
    ab = alpha * beta
    for value in y[1:]:
        pred = level + phi * trend
        err = value - pred
        sse += err * err
        level = pred + alpha * err
        trend = phi * trend + ab * err
    return sse, level, trend


def _fit_holt(y: list) -> dict:
    n = len(y)
    m = min(3, n - 1)
    b0 = (y[m] - y[0]) / m
    best = None
    for alpha in ALPHAS:
        for beta in BETAS:
            for phi in PHIS_HOLT:
                sse, level, trend = _run_holt(y, alpha, beta, phi, b0)
                if best is None or sse < best[0]:
                    best = (sse, alpha, beta, phi, level, trend)
    sse, alpha, beta, phi, level, trend = best
    fit = _fit_none()
    fit.update(method=METHOD_HOLT, n=n, l=level, b=trend, alpha=alpha, beta=beta, phi=phi,
               avg=sum(y) / n)
    fit["sigma"] = _sigma(sse, n - 1, 3, fit["avg"])
    return fit


def _run_hw(y, alpha, beta, gamma, phi, l0, b0, s0):
    level, trend = l0, b0
    seasons = list(s0)
    sse = 0.0
    ab = alpha * beta
    for t in range(SEASON, len(y)):
        s_prev = seasons[t - SEASON]
        damped = level + phi * trend
        err = y[t] - (damped + s_prev)
        sse += err * err
        level = damped + alpha * err
        trend = phi * trend + ab * err
        seasons.append(s_prev + gamma * err)
    return sse, level, trend, seasons


def _fit_hw(y: list) -> dict:
    n = len(y)
    mean1 = sum(y[:SEASON]) / SEASON
    mean2 = sum(y[SEASON:2 * SEASON]) / SEASON
    l0 = mean1
    b0 = (mean2 - mean1) / SEASON
    s0 = [y[i] - mean1 for i in range(SEASON)]
    best = None
    for alpha in ALPHAS:
        for beta in BETAS:
            for gamma in GAMMAS:
                for phi in PHIS_HW:
                    sse, level, trend, seasons = _run_hw(y, alpha, beta, gamma, phi, l0, b0, s0)
                    if best is None or sse < best[0]:
                        best = (sse, alpha, beta, gamma, phi, level, trend, seasons)
    sse, alpha, beta, gamma, phi, level, trend, seasons = best
    fit = _fit_none()
    fit.update(method=METHOD_HW, n=n, l=level, b=trend, alpha=alpha, beta=beta, gamma=gamma,
               phi=phi, seasons=seasons, avg=sum(y) / n)
    fit["sigma"] = _sigma(sse, n - SEASON, 4, fit["avg"])
    return fit


def _sigma(sse: float, n_errors: int, k: int, avg: float) -> float:
    sigma = math.sqrt(sse / max(n_errors - k, 1))
    return max(sigma, 0.10 * avg)


def method_for(n_complete: int) -> str:
    if n_complete <= 0:
        return METHOD_NONE
    if n_complete <= 2:
        return METHOD_AVERAGE
    if n_complete <= 5:
        return METHOD_SES
    if n_complete <= 23:
        return METHOD_HOLT
    return METHOD_HW


def fit_series(y: list) -> dict:
    """Fit the model the spec picks for ``len(y)`` complete months."""
    y = [float(v) for v in y]
    method = method_for(len(y))
    if method == METHOD_NONE:
        return _fit_none()
    if method == METHOD_AVERAGE:
        return _fit_average(y)
    if method == METHOD_SES:
        return _fit_ses(y)
    if method == METHOD_HOLT:
        return _fit_holt(y)
    return _fit_hw(y)


def predict(fit: dict, h: int) -> tuple:
    """(mean, variance) ``h`` months after the last complete month (h=1 is the current month)."""
    if fit["method"] == METHOD_NONE:
        return 0.0, 0.0
    phi, alpha, beta, gamma = fit["phi"], fit["alpha"], fit["beta"], fit["gamma"]
    phi_sum = sum(phi ** i for i in range(1, h + 1)) if phi else 0.0
    mean = fit["l"] + phi_sum * fit["b"]
    seasons = fit["seasons"]
    if seasons:
        mean += seasons[fit["n"] - SEASON + (h - 1) % SEASON]
    mean = max(mean, 0.0)

    total = 1.0
    partial = 0.0
    for j in range(1, h):
        partial += phi ** j if phi else 0.0
        c = alpha + alpha * beta * partial + (gamma if j % SEASON == 0 else 0.0)
        total += c * c
    return mean, fit["sigma"] ** 2 * total


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def _parse_rent_monthly(raw) -> Decimal:
    if raw is None or str(raw).strip() == "":
        return DEFAULT_RENT_MONTHLY
    try:
        value = Decimal(str(raw).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return DEFAULT_RENT_MONTHLY
    if not value.is_finite() or value < 0:
        return DEFAULT_RENT_MONTHLY
    return value


def _parse_rent_start(raw) -> date:
    text = (raw or "").strip()
    try:
        year_s, month_s = text.split("-")[:2]
        year, month = int(year_s), int(month_s)
        return date(year, month, 1)
    except (ValueError, TypeError):
        return DEFAULT_RENT_START


def rent_settings() -> tuple:
    """(monthly rent, start month) from settings; absent or unreadable values fall back to defaults."""
    from models import Setting

    amount = _parse_rent_monthly(Setting.get(RENT_MONTHLY_KEY, ""))
    start = _parse_rent_start(Setting.get(RENT_START_KEY, ""))
    return amount, start


def save_rent_settings(amount: Decimal, start: date) -> None:
    """Upsert both rent settings ("60000.00" and "2027-04") in one commit."""
    from models import Setting, db

    amount = _q2(amount)
    if amount < 0:
        raise ValueError("Rent can't be negative.")
    Setting.put(RENT_MONTHLY_KEY, f"{amount:.2f}")
    Setting.put(RENT_START_KEY, f"{start.year:04d}-{start.month:02d}")
    db.session.commit()


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #

def build_forecast(today: date | None = None, years: int = 3, fiscal: bool = True) -> dict:
    """Load the whole ledger and the rent settings, then forecast."""
    from models import Transaction, db

    rows = db.session.query(
        Transaction.txn_date, Transaction.kind, Transaction.category, Transaction.amount
    ).all()
    rent_monthly, rent_start = rent_settings()
    return forecast_from_history(
        rows, today or date.today(), years=years, fiscal=fiscal,
        rent_monthly=rent_monthly, rent_start=rent_start,
    )


def forecast_from_history(entries, today, years=3, fiscal=True,
                          rent_monthly=DEFAULT_RENT_MONTHLY, rent_start=DEFAULT_RENT_START) -> dict:
    """Forecast from an iterable of ledger entries (pure; see module docstring)."""
    today = today or date.today()
    years = max(int(years or 1), 1)
    fiscal = bool(fiscal)
    rent_monthly = _to_decimal(rent_monthly)
    if rent_monthly < 0:
        rent_monthly = Decimal("0")
    rent_monthly = _q2(rent_monthly)
    rent_start = _month_start(rent_start or DEFAULT_RENT_START)
    rent_on = rent_monthly > 0
    current = _month_start(today)
    zero = Decimal("0")

    # ---- 10.1 monthly history ------------------------------------------------
    income_m: dict = {}
    running_m: dict = {}
    rent_paid_m: dict = {}
    category_m: dict = {}  # (month, category) -> running amount
    first_month = None
    for entry in entries:
        txn_date, kind, category, amount = _entry_fields(entry)
        if txn_date is None:
            continue
        month = _month_start(txn_date)
        amount = _to_decimal(amount)
        first_month = month if first_month is None or month < first_month else first_month
        if kind == "income":
            income_m[month] = income_m.get(month, zero) + amount
        elif kind == "expense":
            if rent_on and category == RENT_CATEGORY and month >= rent_start:
                rent_paid_m[month] = rent_paid_m.get(month, zero) + amount
            else:
                running_m[month] = running_m.get(month, zero) + amount
                key = category or "Uncategorised"
                category_m[(month, key)] = category_m.get((month, key), zero) + amount

    has_entries = first_month is not None
    if first_month is None or first_month > current:
        first_month = current

    n_complete = _months_between(first_month, current) if has_entries else 0
    fit_months = [_add_months(first_month, i) for i in range(n_complete)]
    income_fit = fit_series([income_m.get(m, zero) for m in fit_months])
    running_fit = fit_series([running_m.get(m, zero) for m in fit_months])
    method = income_fit["method"]

    # ---- 10.3 month-by-month -------------------------------------------------
    first_year = _year_start(first_month, fiscal)
    current_year_start = _year_start(current, fiscal)
    last_year_start = date(current_year_start.year + years, current_year_start.month, 1)
    end_month = _add_months(last_year_start, 11)

    months = []
    variances = {}  # month -> (income var, running var)
    month = first_month
    while month <= end_month:
        scheduled = rent_monthly if rent_on and month >= rent_start else zero
        if month < current:
            status = "actual"
            income = income_m.get(month, zero)
            running = running_m.get(month, zero)
            rent = rent_paid_m.get(month, zero)
            inc_var = run_var = 0.0
            low = high = _q2(income)
        else:
            h = _months_between(current, month) + 1
            inc_mean, inc_var = predict(income_fit, h)
            run_mean, run_var = predict(running_fit, h)
            income = _q2(inc_mean)
            running = _q2(run_mean)
            rent = scheduled
            floor = zero
            if month == current:
                status = "current"
                recorded_income = income_m.get(month, zero)
                income = max(income, recorded_income)
                running = max(running, running_m.get(month, zero))
                rent = max(scheduled, rent_paid_m.get(month, zero))
                floor = recorded_income
            else:
                status = "forecast"
            spread = Decimal(repr(Z80 * math.sqrt(inc_var)))
            low = _q2(max(income - spread, floor, zero))
            high = _q2(income + spread)
        income, running, rent = _q2(income), _q2(running), _q2(rent)
        months.append({
            "month": month,
            "label": _label(month),
            "income": income,
            "running": running,
            "rent": rent,
            "expenses": running + rent,
            "net": income - running - rent,
            "income_low": low,
            "income_high": high,
            "status": status,
        })
        variances[month] = (inc_var, run_var)
        month = _add_months(month, 1)

    # ---- 10.4 yearly roll-up -------------------------------------------------
    year_rows = []
    start = first_year
    while start <= last_year_start:
        nxt = date(start.year + 1, start.month, 1)
        in_year = [m for m in months if start <= m["month"] < nxt]
        income = sum((m["income"] for m in in_year), zero)
        running = sum((m["running"] for m in in_year), zero)
        rent = sum((m["rent"] for m in in_year), zero)
        net = income - running - rent
        var = sum(variances[m["month"]][0] + variances[m["month"]][1] for m in in_year)
        spread = _q2(Decimal(repr(Z80 * math.sqrt(var))))
        statuses = {m["status"] for m in in_year}
        if statuses == {"actual"}:
            basis = "Actual"
        elif "actual" in statuses:
            basis = "Actual + forecast"
        else:
            basis = "Forecast"
        covered = len(in_year)
        partial = covered < 12
        year_rows.append({
            "label": _year_label(start, fiscal),
            "start": start,
            "end": _add_months(start, 11),
            "income": _q2(income),
            "running": _q2(running),
            "rent": _q2(rent),
            "expenses": _q2(running + rent),
            "net": _q2(net),
            "net_low": _q2(net - spread),
            "net_high": _q2(net + spread),
            "basis": basis,
            "months_covered": covered,
            "partial": partial,
            "basis_label": f"{basis} · {covered} mo" if partial else basis,
            "yoy": None,
            "months": in_year,
        })
        start = nxt
    for prev, row in zip(year_rows, year_rows[1:]):
        if prev["months_covered"] == 12 and prev["income"] > 0:
            row["yoy"] = ((row["income"] - prev["income"]) / prev["income"]).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP)

    current_year = next((y for y in year_rows if y["start"] == current_year_start), None)
    next_year = next((y for y in year_rows if y["start"] > current_year_start), None)

    # ---- 10.5 item 6: projected monthly expenses -----------------------------
    running_next = _q2(predict(running_fit, 2)[0])
    projected = []
    if n_complete:
        averages: dict = {}
        for (m, category), amount in category_m.items():
            if first_month <= m < current:
                averages[category] = averages.get(category, zero) + amount
        total_avg = sum(averages.values(), zero)
        if total_avg > 0:
            scale = running_next / total_avg
            projected = [
                {"category": category, "monthly": _q2(amount * scale)}
                for category, amount in averages.items() if amount > 0
            ]
            projected.sort(key=lambda r: (-r["monthly"], r["category"]))

    notes = _notes(method, n_complete, income_fit, running_fit, first_month, current,
                   year_rows, rent_monthly, rent_start, rent_on)

    return {
        "method": method,
        "notes": notes,
        "rent": {"monthly": rent_monthly, "start": rent_start},
        "fiscal": fiscal,
        "years_ahead": years,
        "months": months,
        "years": year_rows,
        "next_year": next_year,
        "current_year": current_year,
        "projected_expenses": projected,
        "running_next": running_next,
        "total_with_rent": _q2(running_next + rent_monthly),
    }


def _params(fit: dict) -> str:
    parts = [f"α {fit['alpha']:.2f}"]
    if fit["method"] in (METHOD_HOLT, METHOD_HW):
        parts.append(f"β {fit['beta']:.2f}")
    if fit["method"] == METHOD_HW:
        parts.append(f"γ {fit['gamma']:.2f}")
    if fit["method"] in (METHOD_HOLT, METHOD_HW):
        parts.append(f"φ {fit['phi']:.2f}")
    return ", ".join(parts)


def _notes(method, n, income_fit, running_fit, first_month, current, year_rows,
           rent_monthly, rent_start, rent_on) -> list:
    months_txt = _plural(n, "complete month")
    notes = []
    if method == METHOD_NONE:
        notes.append(
            "There's no complete month of history yet, so every month is forecast as ₹0 "
            f"apart from what's already recorded in {_label(current)}. "
            "The forecast fills in once the first month closes."
        )
    elif method == METHOD_AVERAGE:
        notes.append(
            f"Only {months_txt} of history, so the forecast assumes every month looks like "
            "the average so far, with no trend. The range is wide (at least ±25% a month) "
            "until more months are in."
        )
    elif method == METHOD_SES:
        notes.append(
            f"{months_txt.capitalize()} of history, fitted with simple exponential smoothing: "
            "recent months count more, and no trend or seasonality is assumed yet "
            f"(income {_params(income_fit)}; running costs {_params(running_fit)})."
        )
    elif method == METHOD_HOLT:
        notes.append(
            f"{months_txt.capitalize()} of history, fitted with Holt's damped trend: the recent "
            "trend carries forward but flattens out over time "
            f"(income {_params(income_fit)}; running costs {_params(running_fit)})."
        )
    else:
        notes.append(
            f"{months_txt.capitalize()} of history, fitted with additive Holt–Winters: a damped "
            "trend plus a 12-month seasonal pattern, so busy and quiet months repeat each year "
            f"(income {_params(income_fit)}; running costs {_params(running_fit)})."
        )
    if method != METHOD_NONE:
        notes.append(
            "Income and running costs are fitted separately, choosing the smoothing settings "
            "that best predicted each past month from the months before it."
        )
    notes.append(
        f"{_label(current)} is still in progress, so it counts as the larger of the forecast "
        "and what's recorded so far."
    )
    if year_rows and year_rows[0]["partial"]:
        first = year_rows[0]
        notes.append(
            f"{first['label']} covers only {first['months_covered']} months because the ledger "
            f"starts mid-year ({_label(first_month)}), so it has no year-on-year comparison."
        )
    if rent_on:
        notes.append(
            f"Ground rent of {_money(rent_monthly)} a month is added from {_label(rent_start)}. "
            f"\"{RENT_CATEGORY}\" entries from then on are treated as that rent, not as running "
            "costs, so it's never counted twice."
        )
    else:
        notes.append("No ground rent is scheduled.")
    if method != METHOD_NONE:
        notes.append(
            "The shaded band and net ranges are 80% ranges (forecast ± 1.28 standard deviations), "
            "widening the further ahead they look."
        )
    return notes
