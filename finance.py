"""Period filtering, aggregation and partner-share maths.

All money is handled as ``Decimal`` end to end and rounded only at the final
presentation/allocation step, so totals never drift.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import case, func

from models import EXPENSE, INCOME, Setting, Transaction, db

TWOPLACES = Decimal("0.01")
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def q2(value) -> Decimal:
    """Round to 2 decimal places, half-up (what people expect for money)."""
    return Decimal(value or 0).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def fmt_money(value) -> str:
    """Format a number with Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    amount = q2(value)
    negative = amount < 0
    if negative:
        amount = -amount
    whole, _, frac = f"{amount:.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = f"{whole}.{frac}" if frac != "00" else whole
    return f"-{out}" if negative else out


# --------------------------------------------------------------------------- #
# Period filter
# --------------------------------------------------------------------------- #

PERIOD_KINDS = ("month", "quarter", "year", "all", "custom")


@dataclass(frozen=True)
class Period:
    kind: str
    start: Optional[date]
    end: Optional[date]
    label: str
    # Echoed back into links and the filter form so the choice survives navigation.
    params: dict

    def query_args(self, **overrides) -> dict:
        merged = {"period": self.kind, **self.params}
        merged.update(overrides)
        return merged


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _safe_int(raw, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _parse_iso(raw) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        return None


def data_bounds():
    """Earliest and latest transaction dates, or (None, None) when empty."""
    row = db.session.query(func.min(Transaction.txn_date), func.max(Transaction.txn_date)).one()
    return row[0], row[1]


def default_anchor() -> date:
    """Anchor the default view on the newest data, falling back to today."""
    _, latest = data_bounds()
    return latest or date.today()


def parse_period(args) -> Period:
    """Build a Period from request query args, tolerating any bad input."""
    anchor = default_anchor()
    kind = (args.get("period") or "month").strip().lower()
    if kind not in PERIOD_KINDS:
        kind = "month"

    if kind == "month":
        raw = (args.get("month") or "").strip()
        year, month = anchor.year, anchor.month
        if len(raw) == 7 and raw[4] == "-":
            year = _safe_int(raw[:4], year)
            month = _safe_int(raw[5:7], month)
        if not 1 <= month <= 12:
            month = anchor.month
        year = min(max(year, 1970), 2200)
        start, end = date(year, month, 1), _month_end(year, month)
        return Period(kind, start, end, f"{MONTH_NAMES[month - 1]} {year}", {"month": f"{year:04d}-{month:02d}"})

    if kind == "quarter":
        year = min(max(_safe_int(args.get("year"), anchor.year), 1970), 2200)
        quarter = _safe_int(args.get("quarter"), (anchor.month - 1) // 3 + 1)
        if not 1 <= quarter <= 4:
            quarter = (anchor.month - 1) // 3 + 1
        first = 3 * (quarter - 1) + 1
        start, end = date(year, first, 1), _month_end(year, first + 2)
        label = f"Q{quarter} {year} ({MONTH_NAMES[first - 1]}–{MONTH_NAMES[first + 1]})"
        return Period(kind, start, end, label, {"year": str(year), "quarter": str(quarter)})

    if kind == "year":
        year = min(max(_safe_int(args.get("year"), anchor.year), 1970), 2200)
        return Period(kind, date(year, 1, 1), date(year, 12, 31), f"Year {year}", {"year": str(year)})

    if kind == "custom":
        start = _parse_iso(args.get("from"))
        end = _parse_iso(args.get("to"))
        if start and end and start > end:
            start, end = end, start
        if not start and not end:
            # Stay in the custom branch with no bounds so the From/To inputs
            # actually render; downgrading to a month would make the custom
            # range unreachable from the UI.
            return Period(kind, None, None, "All dates \u2014 pick a range", {"from": "", "to": ""})
        lo = start.isoformat() if start else ""
        hi = end.isoformat() if end else ""
        if start and end:
            label = f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
        elif start:
            label = f"From {start.strftime('%d %b %Y')}"
        else:
            label = f"Up to {end.strftime('%d %b %Y')}"
        return Period(kind, start, end, label, {"from": lo, "to": hi})

    return Period("all", None, None, "All time", {})


def apply_period(query, period: Period):
    if period.start:
        query = query.filter(Transaction.txn_date >= period.start)
    if period.end:
        query = query.filter(Transaction.txn_date <= period.end)
    return query


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def opening_balance() -> Decimal:
    return q2(Setting.get("opening_balance", "0") or "0")


def totals(period: Period) -> dict:
    """Income, expense and net for a period, computed in one query."""
    rows = (
        apply_period(db.session.query(Transaction.kind, func.sum(Transaction.amount)), period)
        .group_by(Transaction.kind)
        .all()
    )
    by_kind = {kind: q2(total) for kind, total in rows}
    income = by_kind.get(INCOME, Decimal("0"))
    expense = by_kind.get(EXPENSE, Decimal("0"))
    count = apply_period(db.session.query(func.count(Transaction.id)), period).scalar() or 0
    return {
        "income": income,
        "expense": expense,
        "net": q2(income - expense),
        "count": count,
        "margin": q2((income - expense) / income * 100) if income > 0 else None,
    }


def balance_as_of(day: Optional[date]) -> Decimal:
    """Opening balance plus every signed transaction up to and including ``day``."""
    query = db.session.query(
        func.coalesce(func.sum(case((Transaction.kind == INCOME, Transaction.amount), else_=-Transaction.amount)), 0)
    )
    if day:
        query = query.filter(Transaction.txn_date <= day)
    return q2(opening_balance() + q2(query.scalar()))


def category_breakdown(period: Period, kind: str, limit: int = 8) -> list:
    """Totals per category for one kind, largest first, tail folded into 'Other'."""
    rows = (
        apply_period(
            db.session.query(Transaction.category, func.sum(Transaction.amount)).filter(Transaction.kind == kind),
            period,
        )
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount).desc())
        .all()
    )
    items = [{"label": (cat or "Uncategorised"), "amount": q2(total)} for cat, total in rows]
    if len(items) > limit:
        head, tail = items[: limit - 1], items[limit - 1 :]
        head.append({"label": f"Other ({len(tail)} categories)", "amount": q2(sum(i["amount"] for i in tail))})
        items = head
    return items


def _month_index(day: date) -> int:
    """Months since year 0, so window arithmetic never has to special-case December."""
    return day.year * 12 + (day.month - 1)


def _from_month_index(index: int):
    year, month = divmod(index, 12)
    return year, month + 1


def monthly_series(start_year: int, start_month: int, months: int = 12) -> list:
    """Income/expense/net per month for ``months`` starting at the given month."""
    start_index = start_year * 12 + (start_month - 1)
    end_year, end_month = _from_month_index(start_index + months - 1)
    window_start = date(start_year, start_month, 1)
    window_end = _month_end(end_year, end_month)

    rows = (
        db.session.query(Transaction.txn_date, Transaction.kind, Transaction.amount)
        .filter(Transaction.txn_date >= window_start, Transaction.txn_date <= window_end)
        .all()
    )
    buckets = {}
    for txn_date, kind, amount in rows:
        key = (txn_date.year, txn_date.month)
        slot = buckets.setdefault(key, {"income": Decimal("0"), "expense": Decimal("0")})
        slot["income" if kind == INCOME else "expense"] += Decimal(amount or 0)

    series = []
    for offset in range(months):
        yy, mm = _from_month_index(start_index + offset)
        slot = buckets.get((yy, mm), {"income": Decimal("0"), "expense": Decimal("0")})
        income, expense = q2(slot["income"]), q2(slot["expense"])
        series.append(
            {
                "key": f"{yy:04d}-{mm:02d}",
                "label": f"{MONTH_NAMES[mm - 1]} {str(yy)[2:]}",
                "full_label": f"{MONTH_NAMES[mm - 1]} {yy}",
                "income": income,
                "expense": expense,
                "net": q2(income - expense),
            }
        )
    return series


def monthly_trend(end_day: Optional[date] = None, months: int = 12) -> list:
    """The ``months`` window ENDING at ``end_day`` (trailing view)."""
    anchor = end_day or default_anchor()
    start_year, start_month = _from_month_index(_month_index(anchor) - (months - 1))
    return monthly_series(start_year, start_month, months)


def trend_window(period: "Period", months: int = 12) -> dict:
    """The 12-month window the dashboard chart should show.

    Anchored at the first month that actually has entries, so a ledger that
    begins in Oct 2026 opens on Oct 2026 rather than on eleven empty columns.
    Once the ledger (or the selected period) runs past that window, the window
    rolls forward to end on the month in view, so the chart stays current.
    """
    first, last = data_bounds()
    focus = period.end or last or date.today()
    focus_index = _month_index(focus)

    if first is None:
        # No entries yet: show the month in view plus the eleven before it.
        start_index = focus_index - (months - 1)
    else:
        start_index = _month_index(first)
        if focus_index > start_index + months - 1:
            start_index = focus_index - (months - 1)
        # Never start after the month in view (e.g. a filter set before the data).
        start_index = min(start_index, focus_index)

    start_year, start_month = _from_month_index(start_index)
    series = monthly_series(start_year, start_month, months)
    return {
        "series": series,
        "start_label": series[0]["full_label"],
        "end_label": series[-1]["full_label"],
        "label": f"{series[0]['full_label']} \u2013 {series[-1]['full_label']}",
    }


# --------------------------------------------------------------------------- #
# Partner shares
# --------------------------------------------------------------------------- #

def partner_shares(net: Decimal, partners: list) -> dict:
    """Split ``net`` across partners by equity, with the rounding remainder
    given to the largest stake so the parts always re-sum to the whole.
    """
    net = q2(net)
    equity_total = sum((Decimal(p.equity_pct or 0) for p in partners), Decimal("0"))
    rows = []
    for partner in partners:
        equity = Decimal(partner.equity_pct or 0)
        share = q2(net * equity / Decimal("100")) if equity_total else Decimal("0")
        rows.append({"partner": partner, "name": partner.name, "equity": equity, "share": share})

    allocated = sum((r["share"] for r in rows), Decimal("0"))
    remainder = q2(net - allocated)
    if rows and remainder != 0 and equity_total == Decimal("100"):
        # Hand the sub-paisa remainder to the biggest stake (stable tie-break by name).
        target = max(rows, key=lambda r: (r["equity"], r["name"]))
        target["share"] = q2(target["share"] + remainder)
        allocated = q2(allocated + remainder)

    return {
        "rows": rows,
        "equity_total": q2(equity_total),
        "allocated": q2(allocated),
        "unallocated": q2(net - allocated),
        "balanced": q2(equity_total) == Decimal("100.00"),
        "net": net,
    }
