"""Build an .xlsx export that mirrors the layout of BailsLedgerBook.xlsx.

Two sheets reproduce the original workbook (``Dashboard`` and
``Transaction Ledger``); ``Partner Profit`` adds the equity split the app
computes, and ``Ground Calendar`` lists the blocked slots and full days. Regenerating always produces the same shape, so the file can be
overwritten in place as "the latest".
"""
from copy import copy
from datetime import date, timedelta, timezone
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from finance import (
    apply_period, balance_as_of, opening_balance, q2, totals,
)
from models import EXPENSE, INCOME, Partner, Transaction

# Brand palette, taken from the ground's badge.
GREEN_DARK = "17593C"
GREEN = "2CAA70"
CREAM = "FDF4A3"
RED = "D72228"
NAVY = "273076"
GREY_BG = "F1F4EF"
TEAL = "17876A"
SLATE = "5B6660"
MUTED = "7C8780"
FULL_RED_BG = "F7D4D5"

MONEY = '#,##0.00'
MONEY_INT = '#,##0'
DATE_FMT = 'dd mmm yyyy'
MONTH_FMT = 'mmm yyyy'

THIN = Side(style="thin", color="D3DAD0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _title(ws, cell_range, text):
    first = cell_range.split(":")[0]
    ws.merge_cells(cell_range)
    cell = ws[first]
    cell.value = text
    cell.font = Font(name="Calibri", size=15, bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=GREEN_DARK)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _header_row(ws, row, headers, start=1, colour=GREEN_DARK):
    for offset, text in enumerate(headers):
        cell = ws.cell(row=row, column=start + offset, value=text)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=colour)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX


def _widths(ws, widths):
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _card(ws, col, row, label, value, colour, number_format=MONEY_INT):
    """A two-column card: label band over a merged two-row value."""
    left, right = get_column_letter(col), get_column_letter(col + 1)
    ws.merge_cells(f"{left}{row}:{right}{row}")
    cell = ws[f"{left}{row}"]
    cell.value = label
    cell.font = Font(bold=True, size=9, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=colour)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(f"{left}{row + 1}:{right}{row + 2}")
    cell = ws[f"{left}{row + 1}"]
    cell.value = float(value) if isinstance(value, Decimal) else value
    cell.number_format = number_format
    cell.font = Font(bold=True, size=18, color=colour)
    cell.fill = PatternFill("solid", fgColor=GREY_BG)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _section(ws, row, text):
    ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=12, color=GREEN_DARK)


def _total_row(ws, row, columns):
    for column in range(1, columns + 1):
        cell = ws.cell(row=row, column=column)
        cell.fill = PatternFill("solid", fgColor=CREAM)
        cell.border = BOX
        font = copy(cell.font)
        font.bold = True
        cell.font = font


def _build_dashboard(wb, period, summary, months, generated_at=None):
    from datetime import datetime

    from finance import category_breakdown, net_label

    ws = wb.create_sheet("Dashboard")
    ws.sheet_view.showGridLines = False
    _widths(ws, [24, 16, 16, 16, 16, 16])

    _title(ws, "A1:F2", "BAILS CRICKET GROUND \u2014 LEDGER DASHBOARD")
    ws.row_dimensions[1].height = 22

    stamp = generated_at or datetime.now(timezone.utc)
    for row, (label, value) in ((4, ("Selected Period", period.label)),
                                (5, ("Generated", stamp.strftime("%d %b %Y %H:%M") + (" UTC" if stamp.tzinfo else "")))):
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value).font = Font(italic=True)

    _card(ws, 1, 7, "INCOME (CREDIT)", summary["income"], GREEN_DARK)
    _card(ws, 3, 7, "EXPENSE (DEBIT)", summary["expense"], RED)
    _card(ws, 5, 7, net_label(period.kind, summary["net"]).upper(), summary["net"], NAVY)
    _card(ws, 1, 11, "OPENING BALANCE", summary["opening"], TEAL)
    _card(ws, 3, 11, "CLOSING BALANCE", summary["closing"], GREEN_DARK)
    _card(ws, 5, 11, "ENTRIES", summary["count"], SLATE, number_format="0")

    # Month by month, inside the period.
    row = 15
    _section(ws, row, "Month by month")
    row += 1
    _header_row(ws, row, ["Month", "Opening", "Income", "Expense", "Net", "Closing"])
    for m in months:
        row += 1
        ws.cell(row=row, column=1, value=m["month"]).number_format = MONTH_FMT
        for column, key in ((2, "opening"), (3, "income"), (4, "expense"), (5, "net"), (6, "closing")):
            cell = ws.cell(row=row, column=column, value=float(m[key]))
            cell.number_format = MONEY_INT
        ws.cell(row=row, column=5).font = Font(color=GREEN if m["net"] >= 0 else RED)
        for column in range(1, 7):
            ws.cell(row=row, column=column).border = BOX
    row += 1
    ws.cell(row=row, column=1, value="TOTAL")
    if months:
        values = (months[0]["opening"], sum(m["income"] for m in months), sum(m["expense"] for m in months),
                  sum(m["net"] for m in months), months[-1]["closing"])
        for column, value in enumerate(values, start=2):
            ws.cell(row=row, column=column, value=float(value)).number_format = MONEY_INT
    _total_row(ws, row, 6)

    # Category splits.
    for kind, heading in ((INCOME, "Income by category"), (EXPENSE, "Expenses by category")):
        row += 2
        _section(ws, row, heading)
        row += 1
        _header_row(ws, row, ["Category", "Amount"])
        items = category_breakdown(period, kind, limit=1000)
        for item in items:
            row += 1
            ws.cell(row=row, column=1, value=item["label"]).border = BOX
            cell = ws.cell(row=row, column=2, value=float(item["amount"]))
            cell.number_format = MONEY_INT
            cell.border = BOX
        row += 1
        ws.cell(row=row, column=1, value="TOTAL")
        ws.cell(row=row, column=2, value=float(sum(i["amount"] for i in items))).number_format = MONEY_INT
        _total_row(ws, row, 2)
    return ws


def _build_ledger(wb, period):
    ws = wb.create_sheet("Transaction Ledger")
    ws.freeze_panes = "A2"
    _widths(ws, [13, 11, 15, 22, 34, 12, 20, 13, 13, 13, 16, 30, 16])
    _header_row(ws, 1, LEDGER_HEADERS)

    rows, start_balance, opening_date, watchman_name = _ledger_source(period)
    ws.cell(row=2, column=1, value=opening_date).number_format = DATE_FMT
    ws.cell(row=2, column=2, value=DAY_NAMES[opening_date.weekday()])
    ws.cell(row=2, column=3, value="Opening Balance")
    ws.cell(row=2, column=4, value="Opening balance")
    ws.cell(row=2, column=5, value=f"Starting balance for {period.label}")
    for column, value in ((8, 0), (9, 0), (10, 0), (11, float(start_balance))):
        cell = ws.cell(row=2, column=column, value=value)
        cell.number_format = MONEY
    for column in range(1, 14):
        ws.cell(row=2, column=column).fill = PatternFill("solid", fgColor=GREY_BG)
        ws.cell(row=2, column=column).border = BOX

    running = start_balance
    for offset, txn in enumerate(rows):
        row = 3 + offset
        running = q2(running + txn.signed_amount)
        income = float(txn.amount) if txn.kind == INCOME else 0.0
        expense = float(txn.amount) if txn.kind == EXPENSE else 0.0

        ws.cell(row=row, column=1, value=txn.txn_date).number_format = DATE_FMT
        ws.cell(row=row, column=2, value=DAY_NAMES[txn.txn_date.weekday()])
        ws.cell(row=row, column=3, value="Income" if txn.kind == INCOME else "Expense")
        ws.cell(row=row, column=4, value=txn.category)
        ws.cell(row=row, column=5, value=txn.description)
        ws.cell(row=row, column=6, value=txn.slot)
        ws.cell(row=row, column=7, value=txn.party)
        for column, value in ((8, income), (9, expense),
                              (10, float(txn.signed_amount)), (11, float(running))):
            cell = ws.cell(row=row, column=column, value=value)
            cell.number_format = MONEY
        ws.cell(row=row, column=12, value=txn.notes)
        ws.cell(row=row, column=13, value=watchman_name.get(txn.watchman_id, ""))

        colour = GREEN if txn.kind == INCOME else RED
        ws.cell(row=row, column=3).font = Font(bold=True, color=colour)
        ws.cell(row=row, column=10).font = Font(color=colour)
        for column in range(1, 14):
            ws.cell(row=row, column=column).border = BOX

    last = 2 + len(rows)
    total_row = last + 1
    ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
    ws.cell(row=total_row, column=7, value=f"{period.label}").font = Font(bold=True, italic=True)
    income_total = sum(float(t.amount) for t in rows if t.kind == INCOME)
    expense_total = sum(float(t.amount) for t in rows if t.kind == EXPENSE)
    for column, value in ((8, income_total), (9, expense_total),
                          (10, income_total - expense_total), (11, float(running))):
        cell = ws.cell(row=total_row, column=column, value=value)
        cell.number_format = MONEY
        cell.font = Font(bold=True)
    for column in range(1, 14):
        ws.cell(row=total_row, column=column).fill = PatternFill("solid", fgColor=CREAM)
        ws.cell(row=total_row, column=column).border = BOX

    # No auto_filter here on purpose: openpyxl expresses it as an
    # `_xlnm._FilterDatabase` defined name, which Excel frequently rejects with
    # "We found a problem with some content". The frozen header row gives the
    # same practical benefit, and the reader can switch filtering on themselves.
    return ws


def _build_partners(wb, period, summary, shares, all_partners):
    from finance import net_label

    ws = wb.create_sheet("Partner Profit")
    ws.sheet_view.showGridLines = False
    _widths(ws, [30, 14, 20, 14])
    loss = summary["net"] < 0

    _title(ws, "A1:D2", "PARTNER SHARE OF LOSS" if loss else "PARTNER PROFIT SHARE")
    ws["A4"] = "Period"
    ws["A4"].font = Font(bold=True)
    ws["B4"] = period.label

    ws["A5"] = f"Distributable net {'loss' if loss else 'profit'} ({net_label(period.kind, summary['net']).split('(')[1]}"
    ws["A5"].font = Font(bold=True)
    cell = ws["B5"]
    cell.value = float(summary["net"])
    cell.number_format = MONEY
    cell.font = Font(bold=True, color=NAVY)

    _header_row(ws, 7, ["Partner", "Equity %", "Share of net loss" if loss else "Share of net profit", "Status"])
    share_of = {r["partner"].id: r["share"] for r in shares["rows"]}
    line = 7
    for partner in all_partners:
        line += 1
        ws.cell(row=line, column=1, value=partner.name)
        equity = ws.cell(row=line, column=2, value=float(partner.equity_pct or 0) / 100.0)
        equity.number_format = '0.00%'
        share = ws.cell(row=line, column=3, value=float(share_of.get(partner.id, 0)) if partner.is_active else 0.0)
        share.number_format = MONEY
        status = ws.cell(row=line, column=4, value="Active" if partner.is_active else "Inactive")
        status.font = Font(bold=True, color=GREEN) if partner.is_active else Font(color=MUTED)
        if not partner.is_active:
            for column in (1, 2, 3):
                ws.cell(row=line, column=column).font = Font(color=MUTED)
        for column in range(1, 5):
            ws.cell(row=line, column=column).border = BOX

    total_row = line + 1
    ws.cell(row=total_row, column=1, value="TOTAL")
    equity = ws.cell(row=total_row, column=2, value=float(shares["equity_total"]) / 100.0)
    equity.number_format = '0.00%'
    allocated = ws.cell(row=total_row, column=3, value=float(shares["allocated"]))
    allocated.number_format = MONEY
    _total_row(ws, total_row, 4)

    if not shares["balanced"]:
        note = ws.cell(row=total_row + 2, column=1,
                       value=f"Active equity totals {shares['equity_total']}%, not 100%. "
                             f"Unallocated: {shares['unallocated']}")
        note.font = Font(italic=True, color=RED)
    return ws


def _build_calendar(wb, period):
    """Every blocked slot / full day in the period, one row per booking."""
    from finance import booking_summary
    from models import BOOKING_SLOTS, FULL_DAY

    stats = booking_summary(period.start, period.end)
    ws = wb.create_sheet("Ground Calendar")
    ws.sheet_view.showGridLines = False
    _widths(ws, [16, 12, 13, 13, 13, 13, 26, 34])

    _title(ws, "A1:H2", "GROUND CALENDAR \u2014 BLOCKED SLOTS")
    ws["A4"] = "Period"
    ws["A4"].font = Font(bold=True)
    ws["B4"] = period.label
    for row, (label, value) in enumerate((
        ("Days with bookings", stats["days_blocked"]),
        ("Full days blocked", stats["full_days"]),
        (f"Slots blocked (a full day = {stats['slots_per_day']})", stats["blocked_slots"]),
    ), start=5):
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=4, value=value).font = Font(bold=True, color=NAVY)

    # Day-by-slot grid: one row per booked day, so "which day, which slot" reads at a glance.
    _header_row(ws, 9, ["Date", "Day"] + BOOKING_SLOTS + [FULL_DAY, "Booked by", "Note"])
    line = 9
    by_date = {}
    for b in stats["bookings"]:
        by_date.setdefault(b.booking_date, []).append(b)
    full_fill = PatternFill("solid", fgColor=FULL_RED_BG)
    slot_fill = PatternFill("solid", fgColor=CREAM)
    for day, items in by_date.items():
        line += 1
        cell = ws.cell(row=line, column=1, value=day)
        cell.number_format = DATE_FMT
        ws.cell(row=line, column=2, value=DAY_NAMES[day.weekday()][:3])
        slots = {b.slot for b in items}
        whole_day = FULL_DAY in slots or set(BOOKING_SLOTS) <= slots
        for offset, slot in enumerate(BOOKING_SLOTS + [FULL_DAY]):
            mark = ws.cell(row=line, column=3 + offset)
            if whole_day or slot in slots:
                mark.value = "Blocked"
                mark.fill = full_fill if whole_day else slot_fill
                mark.font = Font(bold=True, color=RED if whole_day else "000000")
            else:
                mark.value = "Free"
                mark.font = Font(color=MUTED)
            mark.alignment = Alignment(horizontal="center")
        ws.cell(row=line, column=7, value=", ".join(dict.fromkeys(b.booked_by for b in items if b.booked_by)))
        ws.cell(row=line, column=8, value="; ".join(dict.fromkeys(b.note for b in items if b.note)))
        for column in range(1, 9):
            ws.cell(row=line, column=column).border = BOX
    if not by_date:
        ws.cell(row=10, column=1, value="Nothing blocked in this period.").font = Font(italic=True, color=MUTED)

    # And the plain list, one row per booking, for filtering or copying.
    start = line + 3
    ws.cell(row=start - 1, column=1, value="All bookings").font = Font(bold=True, size=12, color=GREEN_DARK)
    _header_row(ws, start, ["Date", "Day", "Slot", "Booked by", "Note"])
    for offset, b in enumerate(stats["bookings"], start=1):
        row = start + offset
        cell = ws.cell(row=row, column=1, value=b.booking_date)
        cell.number_format = DATE_FMT
        ws.cell(row=row, column=2, value=DAY_NAMES[b.booking_date.weekday()][:3])
        slot = ws.cell(row=row, column=3, value=b.slot)
        if b.slot == FULL_DAY:
            slot.font = Font(bold=True, color=RED)
        ws.cell(row=row, column=4, value=b.booked_by or "")
        ws.cell(row=row, column=5, value=b.note or "")
        for column in range(1, 6):
            ws.cell(row=row, column=column).border = BOX
    ws.freeze_panes = "A10"
    return ws


LEDGER_HEADERS = ["Date", "Day", "Type", "Category", "Description", "Slot", "Party",
                  "Income", "Expense", "Net", "Running Balance", "Notes", "Watchman"]
# Fixed English day names, whatever the server's locale.
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _ledger_source(period):
    """Rows, balance brought forward, opening-row date and watchman names."""
    from models import Watchman

    rows = (
        apply_period(Transaction.query, period)
        .order_by(Transaction.txn_date.asc(), Transaction.id.asc())
        .all()
    )
    start_balance = (
        balance_as_of(period.start - timedelta(days=1)) if period.start else opening_balance()
    )
    # One date drives both the cell and its day name, so they cannot disagree.
    opening_date = period.start or (rows[0].txn_date if rows else date.today())
    watchman_name = {w.id: w.name for w in Watchman.query.all()}
    return rows, start_balance, opening_date, watchman_name


def _csv_text(value) -> str:
    """Neutralise text a spreadsheet would run as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv(rows) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(rows)
    # A BOM so Excel opens it as UTF-8 (rupee signs, em dashes).
    return "\ufeff" + buffer.getvalue()


def ledger_csv(period) -> str:
    """The Transaction Ledger sheet as CSV: opening row, then each entry."""
    rows, running, opening_date, watchman_name = _ledger_source(period)
    out = [LEDGER_HEADERS, [
        opening_date.isoformat(), DAY_NAMES[opening_date.weekday()], "Opening Balance", "Opening balance",
        _csv_text(f"Starting balance for {period.label}"), "", "", "0.00", "0.00", "0.00", f"{running:.2f}", "", "",
    ]]
    for txn in rows:
        running = q2(running + txn.signed_amount)
        income = txn.amount if txn.kind == INCOME else Decimal("0")
        expense = txn.amount if txn.kind == EXPENSE else Decimal("0")
        out.append([
            txn.txn_date.isoformat(), DAY_NAMES[txn.txn_date.weekday()],
            "Income" if txn.kind == INCOME else "Expense",
            _csv_text(txn.category), _csv_text(txn.description), _csv_text(txn.slot), _csv_text(txn.party),
            f"{q2(income):.2f}", f"{q2(expense):.2f}", f"{q2(txn.signed_amount):.2f}", f"{running:.2f}",
            _csv_text(txn.notes), _csv_text(watchman_name.get(txn.watchman_id, "")),
        ])
    return _csv(out)


def calendar_csv(period) -> str:
    """One row per block: Date,Day,Status,Slot,Booked by,Note."""
    from finance import booking_summary

    stats = booking_summary(period.start, period.end)
    out = [["Date", "Day", "Status", "Slot", "Booked by", "Note"]]
    for b in stats["bookings"]:
        status = "Full day" if b.booking_date in stats["full_day_dates"] else "Some slots"
        out.append([b.booking_date.isoformat(), DAY_NAMES[b.booking_date.weekday()][:3], status,
                    b.slot, _csv_text(b.booked_by), _csv_text(b.note)])
    return _csv(out)


def _finish(wb, generated_at, title="Bails Cricket Ground - Ledger"):
    # An empty <workbookProtection/> element serves no purpose and is one more
    # thing for Excel to object to.
    wb.security = None
    props = wb.properties
    props.title = title
    props.creator = "Bails Ledger"
    if generated_at is not None:
        # openpyxl appends "Z" to whatever it serialises, so a tz-aware value
        # produces "...+00:00Z" -- invalid W3CDTF, and Excel then offers to
        # "recover" the file. Store a naive UTC timestamp instead.
        stamp = generated_at
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
        props.created = stamp
        props.modified = stamp
    wb.active = 0
    return wb


def build_workbook(period, generated_at=None):
    """Assemble the whole workbook for a period. Caller supplies the timestamp."""
    from finance import partner_shares, period_months, period_opening

    summary = totals(period)
    summary["opening"] = period_opening(period)
    summary["closing"] = balance_as_of(period.end)
    all_partners = Partner.query.order_by(Partner.sort_order, Partner.id).all()
    shares = partner_shares(summary["net"], [p for p in all_partners if p.is_active])

    wb = Workbook()
    wb.remove(wb.active)
    _build_dashboard(wb, period, summary, period_months(period), generated_at)
    _build_ledger(wb, period)
    _build_partners(wb, period, summary, shares, all_partners)
    _build_calendar(wb, period)
    return _finish(wb, generated_at)


def build_calendar_workbook(period, generated_at=None):
    """Just the Ground Calendar sheet (Export calendar as Excel)."""
    wb = Workbook()
    wb.remove(wb.active)
    _build_calendar(wb, period)
    return _finish(wb, generated_at, title="Bails Cricket Ground - Calendar")
