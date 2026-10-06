"""Full-database backup and restore, independent of the storage backend.

The app runs on SQLite locally and Postgres on Render, so "the database" is not
always a single file. This module reads every row through the ORM and produces
one portable JSON document that can be downloaded, kept, and restored to either
backend. Money is emitted as strings so no precision is lost.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from models import Partner, Setting, Transaction, db

# Bump only if the shape below changes in a way a restore must branch on.
BACKUP_FORMAT = 1


def _iso(value):
    return value.isoformat() if value is not None else None


def build_backup(generated_at=None) -> dict:
    """Serialise partners, transactions and settings into one plain dict."""
    partners = Partner.query.order_by(Partner.sort_order, Partner.id).all()
    transactions = Transaction.query.order_by(Transaction.txn_date, Transaction.id).all()
    settings = Setting.query.order_by(Setting.key).all()

    income = sum((t.amount for t in transactions if t.kind == "income"), Decimal("0"))
    expense = sum((t.amount for t in transactions if t.kind == "expense"), Decimal("0"))

    return {
        "format": BACKUP_FORMAT,
        "app": "Bails Cricket Ground Ledger",
        "generated_at": _iso(generated_at or datetime.now(timezone.utc)),
        # A quick integrity glance without opening the rows.
        "summary": {
            "transactions": len(transactions),
            "partners": len(partners),
            "income": f"{income:.2f}",
            "expense": f"{expense:.2f}",
            "net": f"{income - expense:.2f}",
        },
        "settings": {s.key: s.value for s in settings},
        "partners": [
            {
                "name": p.name,
                "equity_pct": f"{Decimal(p.equity_pct or 0):.3f}",
                "sort_order": p.sort_order,
                "is_active": bool(p.is_active),
            }
            for p in partners
        ],
        "transactions": [
            {
                "txn_date": _iso(t.txn_date),
                "kind": t.kind,
                "category": t.category,
                "description": t.description,
                "slot": t.slot,
                "party": t.party,
                "amount": f"{Decimal(t.amount or 0):.2f}",
                "notes": t.notes,
                "created_at": _iso(t.created_at),
                "updated_at": _iso(t.updated_at),
            }
            for t in transactions
        ],
    }


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def restore_backup(data: dict) -> dict:
    """Replace all data with the contents of a backup dict. Returns counts.

    Everything happens in one transaction: either the whole restore commits, or
    nothing changes.
    """
    if not isinstance(data, dict) or "transactions" not in data or "partners" not in data:
        raise ValueError("This does not look like a Bails ledger backup.")
    if int(data.get("format", 0)) > BACKUP_FORMAT:
        raise ValueError(
            f"Backup format {data.get('format')} is newer than this app "
            f"understands ({BACKUP_FORMAT}). Update the app first."
        )

    Transaction.query.delete()
    Partner.query.delete()
    Setting.query.delete()

    for key, value in (data.get("settings") or {}).items():
        db.session.add(Setting(key=str(key)[:64], value=str(value)[:255]))

    for index, p in enumerate(data.get("partners") or []):
        db.session.add(
            Partner(
                name=str(p["name"])[:120],
                equity_pct=Decimal(str(p.get("equity_pct", "0"))),
                sort_order=int(p.get("sort_order", index)),
                is_active=bool(p.get("is_active", True)),
            )
        )

    for t in data.get("transactions") or []:
        txn_date = date.fromisoformat(t["txn_date"])
        kind = t["kind"]
        if kind not in ("income", "expense"):
            raise ValueError(f"Unknown transaction kind in backup: {kind!r}")
        row = Transaction(
            txn_date=txn_date,
            kind=kind,
            category=str(t.get("category", ""))[:80],
            description=str(t.get("description", ""))[:255],
            slot=str(t.get("slot", ""))[:40],
            party=str(t.get("party", ""))[:120],
            amount=Decimal(str(t.get("amount", "0"))),
            notes=str(t.get("notes", "")),
        )
        created = _parse_dt(t.get("created_at"))
        updated = _parse_dt(t.get("updated_at"))
        if created:
            row.created_at = created
        if updated:
            row.updated_at = updated
        db.session.add(row)

    db.session.commit()
    return {
        "partners": len(data.get("partners") or []),
        "transactions": len(data.get("transactions") or []),
        "settings": len(data.get("settings") or {}),
    }
