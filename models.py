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

# Bookable ground slots for the calendar. FULL_DAY blocks the whole day.
FULL_DAY = "Full Day"
BOOKING_SLOTS = ["7:00 AM", "10:45 AM", "2:30 PM"]


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


class ExPartner(db.Model):
    """A seller the ground is being bought from (previous owner).

    Each is owed a fixed ``closing_amount``; what they have been paid is the sum
    of the ground payments made to them, so it is computed, never stored.
    """

    __tablename__ = "ex_partners"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    closing_amount = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    # The seller's shareholding in the ground, as a percent (e.g. 20 = 20%).
    share_pct = db.Column(db.Numeric(6, 3), nullable=False, default=Decimal("0"))
    account_number = db.Column(db.String(255), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<ExPartner {self.name} {self.share_pct}% {self.closing_amount}>"


class GroundPayment(db.Model):
    """One payment toward the ground purchase: a current partner pays a seller.

    This is the single source of truth for "amount paid". Each payment adds to
    exactly one ex-partner's received total and one current partner's
    contributed total, so the two sides always tally.
    """

    __tablename__ = "ground_payments"

    id = db.Column(db.Integer, primary_key=True)
    detail = db.Column(db.String(120), nullable=False, default="")
    # Paid to a seller (ex-partner) by a current partner.
    ex_partner_id = db.Column(
        db.Integer, db.ForeignKey("ex_partners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    partner_id = db.Column(
        db.Integer, db.ForeignKey("partners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    txn_number = db.Column(db.String(80), nullable=False, default="")
    txn_date = db.Column(db.Date, nullable=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    note = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        db.CheckConstraint("amount >= 0", name="ck_ground_payments_amount_non_negative"),
    )

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<GroundPayment {self.detail} {self.amount}>"


class GroundBooking(db.Model):
    """A blocked slot (or the full day) on the ground calendar."""

    __tablename__ = "ground_bookings"

    id = db.Column(db.Integer, primary_key=True)
    booking_date = db.Column(db.Date, nullable=False, index=True)
    # One of BOOKING_SLOTS, or FULL_DAY.
    slot = db.Column(db.String(40), nullable=False)
    booked_by = db.Column(db.String(120), nullable=False, default="")
    note = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        # The same slot can't be blocked twice on one day.
        db.UniqueConstraint("booking_date", "slot", name="uq_ground_bookings_date_slot"),
    )

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<GroundBooking {self.booking_date} {self.slot}>"
