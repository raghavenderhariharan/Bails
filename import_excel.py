"""Import the existing BailsLedgerBook.xlsx into the ledger database.

Usage:
    python import_excel.py BailsLedgerBook.xlsx [--replace]

Reads the 'Transaction Ledger' sheet. Rows whose type is not Income/Expense
(for example the zero opening-balance row) are skipped and reported.
"""
import argparse
import sys
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

import os as _os

# These scripts only touch the database; they never serve a request, so they do
# not need a real session key. Set a placeholder before importing the app so the
# "SECRET_KEY is required in deployment" guard does not block a CLI run against
# a remote DATABASE_URL.
_os.environ.setdefault("SECRET_KEY", "cli-no-sessions")

from app import app
from models import EXPENSE, INCOME, Setting, Transaction, db

SHEET = "Transaction Ledger"
HEADERS = {
    "date": "txn_date", "type": "kind", "category": "category",
    "description": "description", "slot": "slot", "party": "party",
    "income": "income", "expense": "expense", "notes": "notes",
}


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _as_decimal(value):
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, str):
        value = value.replace(",", "").replace("₹", "").strip() or "0"
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, time):
        return value.strftime("%-I:%M %p") if sys.platform != "win32" else value.strftime("%I:%M %p")
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    return str(value).strip()


def load_rows(path):
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl is required for the import: pip install openpyxl")

    workbook = openpyxl.load_workbook(path, data_only=True)
    if SHEET not in workbook.sheetnames:
        sys.exit(f"Sheet {SHEET!r} not found. Found: {workbook.sheetnames}")
    sheet = workbook[SHEET]

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return [], []
    header = [(_as_text(c) or "").strip().lower() for c in rows[0]]
    index = {}
    for position, name in enumerate(header):
        if name in HEADERS:
            index[HEADERS[name]] = position

    for required in ("txn_date", "kind"):
        if required not in index:
            sys.exit(f"Could not find a '{required}' column in {SHEET!r}. Header was: {header}")

    parsed, skipped = [], []

    def cell(row, key):
        position = index.get(key)
        return row[position] if position is not None and position < len(row) else None

    for number, row in enumerate(rows[1:], start=2):
        if row is None or all(c is None or c == "" for c in row):
            continue
        txn_date = _as_date(cell(row, "txn_date"))
        raw_type = _as_text(cell(row, "kind")).lower()
        income = _as_decimal(cell(row, "income"))
        expense = _as_decimal(cell(row, "expense"))

        if txn_date is None:
            skipped.append((number, "no usable date"))
            continue

        if "income" in raw_type or "credit" in raw_type:
            kind, amount = INCOME, income or expense
        elif "expense" in raw_type or "debit" in raw_type:
            kind, amount = EXPENSE, expense or income
        elif income > 0:
            kind, amount = INCOME, income
        elif expense > 0:
            kind, amount = EXPENSE, expense
        else:
            skipped.append((number, f"type {raw_type!r} with no amount"))
            continue

        if amount <= 0:
            skipped.append((number, f"{raw_type or 'row'} with zero amount"))
            continue

        parsed.append(
            Transaction(
                txn_date=txn_date,
                kind=kind,
                category=_as_text(cell(row, "category"))[:80] or ("Ground booking" if kind == INCOME else "Miscellaneous"),
                description=_as_text(cell(row, "description"))[:255],
                slot=_as_text(cell(row, "slot"))[:40],
                party=_as_text(cell(row, "party"))[:120],
                amount=amount.quantize(Decimal("0.01")),
                notes=_as_text(cell(row, "notes"))[:2000],
            )
        )

    return parsed, skipped


def main():
    parser = argparse.ArgumentParser(description="Import an Excel ledger into the app database.")
    parser.add_argument("path", nargs="?", default="BailsLedgerBook.xlsx")
    parser.add_argument("--replace", action="store_true",
                        help="delete all existing transactions before importing")
    args = parser.parse_args()

    transactions, skipped = load_rows(args.path)

    with app.app_context():
        if args.replace:
            removed = Transaction.query.delete()
            print(f"Removed {removed} existing transaction(s).")
        elif Transaction.query.first() is not None:
            print("Database already holds transactions. Re-run with --replace to overwrite.")
            return

        for txn in transactions:
            db.session.add(txn)
        if Setting.get("opening_balance", "") == "":
            Setting.put("opening_balance", "0")
        db.session.commit()

        credits = sum(1 for t in transactions if t.kind == INCOME)
        total_in = sum((t.amount for t in transactions if t.kind == INCOME), Decimal("0"))
        total_out = sum((t.amount for t in transactions if t.kind == EXPENSE), Decimal("0"))
        print(f"Imported {len(transactions)} transaction(s): {credits} credit, {len(transactions) - credits} debit.")
        print(f"  Income  {total_in}")
        print(f"  Expense {total_out}")
        print(f"  Net     {total_in - total_out}")
        for number, reason in skipped:
            print(f"  skipped row {number}: {reason}")


if __name__ == "__main__":
    main()
