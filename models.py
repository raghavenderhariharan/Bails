"""Database models for the Bails Cricket Ground ledger."""
from datetime import date, datetime, timezone
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

INCOME = "income"
EXPENSE = "expense"
KINDS = (INCOME, EXPENSE)

# Access roles. ADMIN may create/edit/delete; PARTNER is strictly read-only.
ROLE_ADMIN = "admin"
ROLE_PARTNER = "partner"
ROLES = (ROLE_ADMIN, ROLE_PARTNER)
ROLE_LABELS = {ROLE_ADMIN: "Admin", ROLE_PARTNER: "Partner"}

INCOME_CATEGORIES = [
    "Ground booking",
    "ECL booking",
    "Tournament",
    "Net practice",
    "Cafeteria",
    "Equipment rental",
    "Floodlight charges",
    "Other income",
]

EXPENSE_CATEGORIES = [
    "Market expenses",
    "Salary / chit payment",
    "Groundsman wages",
    "Pitch maintenance",
    "Ground maintenance",
    "Electricity",
    "Water",
    "Equipment purchase",
    "Repairs",
    "Cafeteria supplies",
    "Rent / lease",
    "Miscellaneous",
]

SLOTS = ["7:00 AM", "10:45 AM", "2:30 PM", "6:00 PM", "All slots", "Morning", "Evening", "Other"]


def _utcnow():
    return datetime.now(timezone.utc)


class Partner(db.Model):
    __tablename__ = "partners"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    # Percent of net profit, e.g. 20 or 10. Stored as Numeric to avoid float drift.
    equity_pct = db.Column(db.Numeric(6, 3), nullable=False, default=Decimal("0"))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<Partner {self.name} {self.equity_pct}%>"


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    txn_date = db.Column(db.Date, nullable=False, index=True, default=date.today)
    # 'income' (credit) or 'expense' (debit)
    kind = db.Column(db.String(16), nullable=False, index=True)
    category = db.Column(db.String(80), nullable=False, default="")
    description = db.Column(db.String(255), nullable=False, default="")
    slot = db.Column(db.String(40), nullable=False, default="")
    party = db.Column(db.String(120), nullable=False, default="")
    # Always stored positive; `kind` carries the sign.
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    notes = db.Column(db.Text, nullable=False, default="")
    # When an expense is petty cash drawn by a watchman, it is tagged here and
    # rolls up as a deduction on the Watchmen tab. NULL for everything else.
    watchman_id = db.Column(
        db.Integer, db.ForeignKey("watchmen.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        db.Index("ix_transactions_kind_date", "kind", "txn_date"),
        db.CheckConstraint("amount >= 0", name="ck_transactions_amount_non_negative"),
    )

    @property
    def signed_amount(self) -> Decimal:
        amt = self.amount or Decimal("0")
        return amt if self.kind == INCOME else -amt

    @property
    def day_name(self) -> str:
        return self.txn_date.strftime("%A") if self.txn_date else ""

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<Transaction {self.txn_date} {self.kind} {self.amount}>"


class Setting(db.Model):
    """Small key/value store for app-level values such as the opening balance."""

    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False, default="")

    @staticmethod
    def get(key: str, default: str = "") -> str:
        row = db.session.get(Setting, key)
        return row.value if row else default

    @staticmethod
    def put(key: str, value: str) -> None:
        row = db.session.get(Setting, key)
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))


class Watchman(db.Model):
    """A watchman on a fixed monthly salary.

    Petty cash a watchman takes during the month is recorded as an **expense**
    entry tagged to them (``Transaction.watchman_id``) and deducted from the
    salary on the Watchmen tab to work out the net amount payable.
    """

    __tablename__ = "watchmen"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    monthly_salary = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("20000"))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<Watchman {self.name} {self.monthly_salary}/mo>"
