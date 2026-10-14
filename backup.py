"""Full-database backup and restore, independent of the storage backend.

The app runs on SQLite locally and Postgres on Render, so "the database" is not
always a single file. This module reads every row through the ORM and produces
one portable JSON document that can be downloaded, kept, and restored to either
backend. Money is emitted as strings so no precision is lost.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from models import ExPartner, GroundPayment, Partner, Setting, Transaction, Watchman, db

# Bump only if the shape below changes in a way a restore must branch on.
BACKUP_FORMAT = 7


def _iso(value):
    return value.isoformat() if value is not None else None


def build_backup(generated_at=None) -> dict:
    """Serialise partners, transactions and settings into one plain dict."""
    partners = Partner.query.order_by(Partner.sort_order, Partner.id).all()
    transactions = Transaction.query.order_by(Transaction.txn_date, Transaction.id).all()
    settings = Setting.query.order_by(Setting.key).all()
    watchmen = Watchman.query.order_by(Watchman.sort_order, Watchman.id).all()
    ex_partners = ExPartner.query.order_by(ExPartner.sort_order, ExPartner.id).all()
    ground_payments = GroundPayment.query.order_by(GroundPayment.txn_date, GroundPayment.id).all()
    # Names are the stable keys that survive a restore (ids are reassigned).
    watchman_name = {w.id: w.name for w in watchmen}
    ex_name = {e.id: e.name for e in ex_partners}
    partner_name_by_id = {p.id: p.name for p in partners}

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
            "watchmen": len(watchmen),
            "watchman_tagged": sum(1 for t in transactions if t.watchman_id),
            "ex_partners": len(ex_partners),
            "ground_payments": len(ground_payments),
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
                "watchman": watchman_name.get(t.watchman_id),
                "created_at": _iso(t.created_at),
                "updated_at": _iso(t.updated_at),
            }
            for t in transactions
        ],
        "watchmen": [
            {
                "name": w.name,
                "monthly_salary": f"{Decimal(w.monthly_salary or 0):.2f}",
                "sort_order": w.sort_order,
                "is_active": bool(w.is_active),
            }
            for w in watchmen
        ],
        "ex_partners": [
            {
                "name": e.name,
                "share_pct": f"{Decimal(e.share_pct or 0):.3f}",
                "closing_amount": f"{Decimal(e.closing_amount or 0):.2f}",
                "account_number": e.account_number,
                "sort_order": e.sort_order,
            }
            for e in ex_partners
        ],
        "ground_payments": [
            {
                "detail": gp.detail,
                "paid_to": ex_name.get(gp.ex_partner_id),
                "paid_by": partner_name_by_id.get(gp.partner_id),
                "txn_number": gp.txn_number,
                "txn_date": _iso(gp.txn_date),
                "amount": f"{Decimal(gp.amount or 0):.2f}",
                "note": gp.note,
            }
            for gp in ground_payments
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

    GroundPayment.query.delete()
    ExPartner.query.delete()
    Watchman.query.delete()
    Transaction.query.delete()
    Partner.query.delete()
    Setting.query.delete()

    for key, value in (data.get("settings") or {}).items():
        db.session.add(Setting(key=str(key)[:64], value=str(value)[:255]))

    # Watchmen first, so transactions can be re-tagged to them by name.
    watchmen_by_name = {}
    for index, w in enumerate(data.get("watchmen") or []):
        watchman = Watchman(
            name=str(w["name"])[:120],
            monthly_salary=Decimal(str(w.get("monthly_salary", "20000"))),
            sort_order=int(w.get("sort_order", index)),
            is_active=bool(w.get("is_active", True)),
        )
        db.session.add(watchman)
        watchmen_by_name[watchman.name] = watchman

    ex_by_name = {}
    for index, e in enumerate(data.get("ex_partners") or []):
        ex = ExPartner(
            name=str(e["name"])[:120],
            share_pct=Decimal(str(e.get("share_pct", "0"))),
            closing_amount=Decimal(str(e.get("closing_amount", "0"))),
            account_number=str(e.get("account_number", ""))[:255],
            sort_order=int(e.get("sort_order", index)),
        )
        db.session.add(ex)
        ex_by_name[ex.name] = ex
    db.session.flush()

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
        tagged = watchmen_by_name.get(t.get("watchman")) if t.get("watchman") else None
        if tagged is not None and kind == "expense":
            row.watchman_id = tagged.id
        created = _parse_dt(t.get("created_at"))
        updated = _parse_dt(t.get("updated_at"))
        if created:
            row.created_at = created
        if updated:
            row.updated_at = updated
        db.session.add(row)

    partners_by_name = {p.name: p for p in Partner.query.all()}
    for gp in data.get("ground_payments") or []:
        ex = ex_by_name.get(gp.get("paid_to"))
        payer = partners_by_name.get(gp.get("paid_by"))
        when = None
        if gp.get("txn_date"):
            try:
                when = date.fromisoformat(gp["txn_date"])
            except ValueError:
                when = None
        db.session.add(GroundPayment(
            detail=str(gp.get("detail", ""))[:120],
            ex_partner_id=ex.id if ex else None,
            partner_id=payer.id if payer else None,
            txn_number=str(gp.get("txn_number", ""))[:80],
            txn_date=when,
            amount=Decimal(str(gp.get("amount", "0"))),
            note=str(gp.get("note", ""))[:255],
        ))

    db.session.commit()
    return {
        "partners": len(data.get("partners") or []),
        "transactions": len(data.get("transactions") or []),
        "settings": len(data.get("settings") or {}),
        "watchmen": len(data.get("watchmen") or []),
        "watchman_tagged": sum(1 for t in (data.get("transactions") or []) if t.get("watchman")),
        "ex_partners": len(data.get("ex_partners") or []),
        "ground_payments": len(data.get("ground_payments") or []),
    }
