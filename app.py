"""Bails Cricket Ground - income & expenditure ledger.

A single-operator Flask app: password gate, credit/debit entry, period filters
and partner profit shares.
"""
import os
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from urllib.parse import urlsplit

from flask import (
    Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from finance import (
    MONTH_NAMES, apply_period, balance_as_of, category_breakdown, data_bounds, fmt_money,
    opening_balance, parse_period, partner_shares, q2, totals, trend_window,
)
from models import (
    EXPENSE, EXPENSE_CATEGORIES, INCOME, INCOME_CATEGORIES, KINDS,
    ROLE_ADMIN, ROLE_LABELS, ROLE_PARTNER, ROLES, SLOTS,
    Partner, Setting, Transaction, db,
)

csrf = CSRFProtect()

# In-process login throttle. Good enough for a single-instance deployment; it
# resets on restart, which is acceptable for a one-operator tool.
_login_attempts: dict = {}
# Timestamps of recent failures from any address, used as a backstop against an
# attacker rotating source addresses to dodge the per-address counter.
_global_failures: list = []


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)
    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash(app.config["ADMIN_PASSWORD"])

    # Only honour X-Forwarded-* when we know how many proxies to trust, so
    # request.remote_addr is the address the trusted hop actually observed
    # rather than anything the caller chose to send.
    hops = app.config.get("TRUSTED_PROXY_COUNT", 0)
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        _bootstrap(app)

    _register_filters(app)
    _register_routes(app)
    return app


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #

# Seeded from the "Partner Amounts Paid" sheet in BAILS TRANSACTION LEDGER.xlsx.
# Editable at any time on the Partner Profit tab.
DEFAULT_PARTNERS = [
    ("Vara Prasad", Decimal("20")),
    ("Aravind", Decimal("20")),
    ("Siva Konderu", Decimal("20")),
    ("Raghavender Hariharan", Decimal("20")),
    ("Bhanu", Decimal("10")),
    ("DRR sir", Decimal("10")),
]


def _bootstrap(app: Flask) -> None:
    """Create tables and seed defaults, safely under multiple Gunicorn workers.

    Every worker runs this at import. On Postgres two workers can reach
    create_all() or the seed insert at the same moment, so both steps tolerate
    "someone else already did it" instead of crashing the worker.
    """
    for attempt in range(3):
        try:
            db.create_all()
            break
        except (IntegrityError, OperationalError, ProgrammingError) as exc:
            # Another worker is creating the same tables; re-check and move on.
            db.session.rollback()
            if attempt == 2:
                app.logger.warning("create_all() did not settle: %s", exc)
            else:
                time.sleep(0.3 * (attempt + 1))

    try:
        if db.session.query(Partner.id).first() is None:
            for index, (name, equity) in enumerate(DEFAULT_PARTNERS):
                db.session.add(Partner(name=name, equity_pct=equity, sort_order=index, is_active=True))
        if db.session.get(Setting, "opening_balance") is None:
            db.session.add(Setting(key="opening_balance", value="0"))
        db.session.commit()
    except IntegrityError:
        # A concurrent worker seeded first. Its rows are equivalent to ours.
        db.session.rollback()
    except (OperationalError, ProgrammingError) as exc:  # pragma: no cover
        db.session.rollback()
        app.logger.warning("seeding skipped: %s", exc)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def current_role():
    """The signed-in role, or None. Unknown values are treated as signed out."""
    if not session.get("authed"):
        return None
    role = session.get("role")
    return role if role in ROLES else None


def is_admin() -> bool:
    return current_role() == ROLE_ADMIN


def login_required(view):
    """Any signed-in role may read."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_role() is None:
            return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Only the admin role may change data.

    This is the real permission boundary: the templates also hide the controls,
    but a partner who posts the form by hand must still be refused here.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        role = current_role()
        if role is None:
            return redirect(url_for("login", next=None))
        if role != ROLE_ADMIN:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _drive_ready(app) -> bool:
    """True when a usable Drive (or any) mirror folder is configured."""
    folder = app.config.get("DRIVE_EXPORT_DIR", "")
    if not folder:
        return False
    return os.path.isdir(os.path.abspath(os.path.expanduser(folder)))


def _throttle_key() -> str:
    """The caller's address.

    This is deliberately NOT read from X-Forwarded-For: that header is
    attacker-controlled, and keying the throttle on it would hand out a fresh
    attempt counter on every request. ProxyFix has already rewritten
    remote_addr from the trusted hop when TRUSTED_PROXY_COUNT says to.
    """
    return request.remote_addr or "unknown"


def _prune_attempts(window: float) -> None:
    """Drop expired buckets so an unauthenticated caller cannot grow the dict."""
    now = time.monotonic()
    for key in [k for k, (_, seen) in _login_attempts.items() if now - seen > window]:
        _login_attempts.pop(key, None)
    if len(_login_attempts) > Config.MAX_THROTTLE_ENTRIES:
        # Pathological case only: keep the most recent buckets.
        for key, _ in sorted(_login_attempts.items(), key=lambda kv: kv[1][1])[
            : len(_login_attempts) - Config.MAX_THROTTLE_ENTRIES
        ]:
            _login_attempts.pop(key, None)


def _locked_out(app) -> int:
    """Seconds remaining on a lockout, or 0 when the caller may try again."""
    window = app.config["LOGIN_LOCKOUT_SECONDS"]
    _prune_attempts(window)
    record = _login_attempts.get(_throttle_key())
    if not record:
        return 0
    count, first_seen = record
    if time.monotonic() - first_seen > window:
        _login_attempts.pop(_throttle_key(), None)
        return 0
    if count >= app.config["MAX_LOGIN_ATTEMPTS"]:
        return int(window - (time.monotonic() - first_seen)) + 1
    return 0


def _global_pressure(app) -> int:
    """How many failures from any address landed inside the current window."""
    window = app.config["LOGIN_LOCKOUT_SECONDS"]
    cutoff = time.monotonic() - window
    _global_failures[:] = [t for t in _global_failures if t > cutoff][-10000:]
    return len(_global_failures)


def _record_failure(app) -> None:
    key = _throttle_key()
    now = time.monotonic()
    count, first_seen = _login_attempts.get(key, (0, now))
    if now - first_seen > app.config["LOGIN_LOCKOUT_SECONDS"]:
        count, first_seen = 0, now
    _login_attempts[key] = (count + 1, first_seen)
    _global_failures.append(now)
    _prune_attempts(app.config["LOGIN_LOCKOUT_SECONDS"])


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

class FormError(ValueError):
    """Raised with a human-readable message when submitted data is unusable."""


def _parse_amount(raw) -> Decimal:
    text = (raw or "").strip().replace(",", "").replace("₹", "")
    if not text:
        raise FormError("Amount is required.")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise FormError("Amount must be a number.")
    if not value.is_finite():
        raise FormError("Amount must be a number.")
    if value <= 0:
        raise FormError("Amount must be greater than zero.")
    if value >= Decimal("100000000"):
        raise FormError("Amount looks too large — please check it.")
    return q2(value)


def _parse_date(raw) -> date:
    text = (raw or "").strip()
    if not text:
        raise FormError("Date is required.")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise FormError("Date must be in YYYY-MM-DD format.")


def _parse_kind(raw) -> str:
    kind = (raw or "").strip().lower()
    if kind not in KINDS:
        raise FormError("Type must be Income or Expense.")
    return kind


def _clip(raw, limit: int) -> str:
    return (raw or "").strip()[:limit]


def _txn_from_form(form) -> dict:
    kind = _parse_kind(form.get("kind"))
    category = _clip(form.get("category"), 80)
    if not category:
        raise FormError("Category is required.")
    return {
        "txn_date": _parse_date(form.get("txn_date")),
        "kind": kind,
        "category": category,
        "description": _clip(form.get("description"), 255),
        "slot": _clip(form.get("slot"), 40),
        "party": _clip(form.get("party"), 120),
        "amount": _parse_amount(form.get("amount")),
        "notes": _clip(form.get("notes"), 2000),
    }


def _safe_redirect(target, fallback_endpoint="dashboard"):
    """Only ever redirect to a plain path on this host.

    Prefix checks alone are not enough: browsers strip tabs, newlines and other
    control characters before resolving a URL, so "/\tevil.com" and
    "/\\evil.com" can both leave the site. Parse it and require an empty
    scheme and netloc.
    """
    if not target:
        return redirect(url_for(fallback_endpoint))
    candidate = str(target)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        return redirect(url_for(fallback_endpoint))
    candidate = candidate.strip()
    if not candidate.startswith("/") or candidate.startswith("//") or candidate.startswith("/\\"):
        return redirect(url_for(fallback_endpoint))
    parts = urlsplit(candidate)
    if parts.scheme or parts.netloc:
        return redirect(url_for(fallback_endpoint))
    return redirect(candidate)


# --------------------------------------------------------------------------- #
# Template filters
# --------------------------------------------------------------------------- #

def _register_filters(app: Flask) -> None:
    app.jinja_env.filters["money"] = fmt_money

    @app.template_filter("signed_money")
    def _signed_money(value):
        amount = q2(value)
        return ("+" if amount > 0 else "") + fmt_money(amount)

    @app.context_processor
    def _inject():
        return {
            "CURRENCY": app.config["CURRENCY_SYMBOL"],
            "INCOME": INCOME,
            "EXPENSE": EXPENSE,
            "INCOME_CATEGORIES": INCOME_CATEGORIES,
            "EXPENSE_CATEGORIES": EXPENSE_CATEGORIES,
            "SLOTS": SLOTS,
            "today_iso": date.today().isoformat(),
            "now_date": date.today(),
            "role": current_role(),
            "role_label": ROLE_LABELS.get(current_role(), ""),
            "is_admin": is_admin(),
            "can_edit": is_admin(),
            "partner_passcode_required": bool(app.config.get("PARTNER_PASSCODE")),
            "drive_sync_ready": _drive_ready(app),
            "current_year": date.today().year,
            "MONTH_NAMES": MONTH_NAMES,
        }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

def _year_choices():
    first, last = data_bounds()
    years = {date.today().year}
    if first:
        years.update(range(first.year, (last or first).year + 1))
    return sorted(years, reverse=True)


def _filter_context(period):
    return {"period": period, "year_choices": _year_choices()}


def _register_routes(app: Flask) -> None:

    def _sign_in(role: str, next_target):
        session.clear()
        session["authed"] = True
        session["role"] = role
        session.permanent = True
        return _safe_redirect(next_target)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """The start screen: choose Admin (password) or Partner (view only)."""
        if current_role() is not None:
            return redirect(url_for("dashboard"))

        next_target = request.values.get("next")
        # ?as=admin shows the password step; otherwise show the role chooser.
        step = "admin" if request.values.get("as") == "admin" else "choose"
        wait = _locked_out(app)

        if request.method == "POST":
            if wait:
                flash(f"Too many failed attempts. Try again in {wait} seconds.", "error")
                return render_template("login.html", step="admin", locked=True,
                                       next_target=next_target), 429
            # Slow every attempt once the window is busy, so rotating source
            # addresses buys an attacker rate but not speed.
            if _global_pressure(app) >= app.config["GLOBAL_FAILURE_THRESHOLD"]:
                time.sleep(app.config["GLOBAL_FAILURE_DELAY_SECONDS"])
            password = request.form.get("password", "")
            if check_password_hash(app.config["ADMIN_PASSWORD_HASH"], password):
                _login_attempts.pop(_throttle_key(), None)
                return _sign_in(ROLE_ADMIN, next_target)
            _record_failure(app)
            flash("Incorrect password.", "error")
            return render_template("login.html", step="admin", locked=False,
                                   next_target=next_target), 401

        return render_template("login.html", step=step, locked=bool(wait),
                               next_target=next_target)

    @app.post("/login/partner")
    def login_partner():
        """Partner sign-in: view only, and password-free unless PARTNER_PASSCODE is set."""
        if current_role() is not None:
            return redirect(url_for("dashboard"))

        expected = app.config.get("PARTNER_PASSCODE", "")
        if expected:
            wait = _locked_out(app)
            if wait:
                flash(f"Too many failed attempts. Try again in {wait} seconds.", "error")
                return render_template("login.html", step="partner", locked=True,
                                       next_target=request.form.get("next")), 429
            supplied = request.form.get("passcode", "")
            if not secrets.compare_digest(supplied, expected):
                _record_failure(app)
                flash("Incorrect partner passcode.", "error")
                return render_template("login.html", step="partner", locked=False,
                                       next_target=request.form.get("next")), 401
            _login_attempts.pop(_throttle_key(), None)

        return _sign_in(ROLE_PARTNER, request.form.get("next"))

    @app.post("/logout")
    def logout():
        session.clear()
        flash("Signed out.", "success")
        return redirect(url_for("login"))

    # ---------------- dashboard ----------------

    @app.get("/")
    @login_required
    def dashboard():
        period = parse_period(request.args)
        summary = totals(period)
        partners = Partner.query.filter_by(is_active=True).order_by(Partner.sort_order, Partner.id).all()
        shares = partner_shares(summary["net"], partners)
        trend = trend_window(period)
        # Scoped to the selected period so the card never contradicts the KPIs above.
        recent = (
            apply_period(Transaction.query, period)
            .order_by(Transaction.txn_date.desc(), Transaction.id.desc())
            .limit(8)
            .all()
        )
        return render_template(
            "dashboard.html",
            summary=summary,
            shares=shares,
            trend=trend["series"],
            trend_label=trend["label"],
            recent=recent,
            income_breakdown=category_breakdown(period, INCOME),
            expense_breakdown=category_breakdown(period, EXPENSE),
            closing_balance=balance_as_of(period.end),
            opening=opening_balance(),
            **_filter_context(period),
        )

    # ---------------- ledger tabs ----------------

    def _ledger(kind: str, template: str):
        period = parse_period(request.args)
        query = apply_period(Transaction.query.filter(Transaction.kind == kind), period)
        search = (request.args.get("q") or "").strip()
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    Transaction.description.ilike(like),
                    Transaction.party.ilike(like),
                    Transaction.category.ilike(like),
                    Transaction.notes.ilike(like),
                )
            )
        category = (request.args.get("category") or "").strip()
        if category:
            query = query.filter(Transaction.category == category)

        # Oldest first, so the ledger reads the way a book does.
        rows = query.order_by(Transaction.txn_date.asc(), Transaction.id.asc()).all()
        subtotal = q2(sum((r.amount for r in rows), Decimal("0")))
        return render_template(
            template,
            kind=kind,
            rows=rows,
            subtotal=subtotal,
            summary=totals(period),
            breakdown=category_breakdown(period, kind),
            search=search,
            active_category=category,
            categories=(INCOME_CATEGORIES if kind == INCOME else EXPENSE_CATEGORIES),
            **_filter_context(period),
        )

    @app.get("/income")
    @login_required
    def income():
        return _ledger(INCOME, "income.html")

    @app.get("/expenses")
    @login_required
    def expenses():
        return _ledger(EXPENSE, "expenses.html")

    @app.get("/transactions")
    @login_required
    def transactions():
        period = parse_period(request.args)
        query = apply_period(Transaction.query, period)
        kind = (request.args.get("kind") or "").strip().lower()
        if kind in KINDS:
            query = query.filter(Transaction.kind == kind)
        search = (request.args.get("q") or "").strip()
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    Transaction.description.ilike(like),
                    Transaction.party.ilike(like),
                    Transaction.category.ilike(like),
                    Transaction.notes.ilike(like),
                )
            )

        # The running balance must be a real ledger balance, so accumulate it
        # over EVERY entry in the period -- not just the rows that survive the
        # kind/search filters -- and then show it against the rows on display.
        unfiltered = (
            apply_period(Transaction.query, period)
            .order_by(Transaction.txn_date.asc(), Transaction.id.asc())
            .all()
        )
        running = balance_as_of(period.start - timedelta(days=1)) if period.start else opening_balance()
        balances = {}
        for row in unfiltered:
            running = q2(running + row.signed_amount)
            balances[row.id] = running

        ascending = query.order_by(Transaction.txn_date.asc(), Transaction.id.asc()).all()
        for row in ascending:
            row.running_balance = balances.get(row.id, running)

        # Footer totals describe the rows actually listed, so they reconcile
        # with the body even when a kind or search filter is applied.
        shown_income = q2(sum((r.amount for r in ascending if r.kind == INCOME), Decimal("0")))
        shown_expense = q2(sum((r.amount for r in ascending if r.kind == EXPENSE), Decimal("0")))

        return render_template(
            "transactions.html",
            # Ascending, so the running balance builds downwards.
            rows=ascending,
            summary=totals(period),
            shown={"income": shown_income, "expense": shown_expense,
                   "net": q2(shown_income - shown_expense)},
            filtered=bool(kind or search),
            kind_filter=kind,
            search=search,
            **_filter_context(period),
        )

    # ---------------- partners ----------------

    @app.get("/partners")
    @login_required
    def partners():
        period = parse_period(request.args)
        summary = totals(period)
        partner_rows = Partner.query.order_by(Partner.sort_order, Partner.id).all()
        active = [p for p in partner_rows if p.is_active]
        return render_template(
            "partners.html",
            summary=summary,
            shares=partner_shares(summary["net"], active),
            all_partners=partner_rows,
            **_filter_context(period),
        )

    @app.post("/partners/save")
    @admin_required
    def partners_save():
        partner_rows = Partner.query.order_by(Partner.sort_order, Partner.id).all()
        seen = set()
        try:
            for partner in partner_rows:
                name = _clip(request.form.get(f"name_{partner.id}"), 120)
                if not name:
                    raise FormError("Partner names cannot be blank.")
                if name.lower() in seen:
                    raise FormError(f"Duplicate partner name: {name}")
                seen.add(name.lower())
                raw_equity = (request.form.get(f"equity_{partner.id}") or "0").strip()
                try:
                    equity = Decimal(raw_equity or "0")
                except (InvalidOperation, ValueError):
                    raise FormError(f"Equity for {name} must be a number.")
                if not equity.is_finite() or not (Decimal("0") <= equity <= Decimal("100")):
                    raise FormError(f"Equity for {name} must be between 0 and 100.")
                partner.name = name
                partner.equity_pct = equity
                partner.is_active = request.form.get(f"active_{partner.id}") == "on"
        except FormError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return _safe_redirect(request.form.get("next"), "partners")

        try:
            # Swapping two names would momentarily duplicate one, so stage the
            # rename behind temporary unique values first.
            final_names = {p.id: p.name for p in partner_rows}
            for partner in partner_rows:
                partner.name = f"\u0000tmp-{partner.id}"
            db.session.flush()
            for partner in partner_rows:
                partner.name = final_names[partner.id]
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Those partner names clash with each other. Please make them unique.", "error")
            return _safe_redirect(request.form.get("next"), "partners")

        total = sum((Decimal(p.equity_pct or 0) for p in partner_rows if p.is_active), Decimal("0"))
        if total != Decimal("100"):
            flash(f"Saved, but active equity totals {total}% — it should be 100%.", "warning")
        else:
            flash("Partners updated.", "success")
        return _safe_redirect(request.form.get("next"), "partners")

    # ---------------- transaction writes ----------------

    @app.post("/transactions/new")
    @admin_required
    def transaction_create():
        try:
            payload = _txn_from_form(request.form)
        except FormError as exc:
            flash(str(exc), "error")
            return _safe_redirect(request.form.get("next"))
        db.session.add(Transaction(**payload))
        db.session.commit()
        noun = "Income" if payload["kind"] == INCOME else "Expense"
        flash(f"{noun} of {app.config['CURRENCY_SYMBOL']}{fmt_money(payload['amount'])} recorded.", "success")
        return _safe_redirect(request.form.get("next"))

    @app.post("/transactions/<int:txn_id>/edit")
    @admin_required
    def transaction_update(txn_id: int):
        txn = db.session.get(Transaction, txn_id)
        if txn is None:
            abort(404)
        try:
            payload = _txn_from_form(request.form)
        except FormError as exc:
            flash(str(exc), "error")
            return _safe_redirect(request.form.get("next"))
        for key, value in payload.items():
            setattr(txn, key, value)
        db.session.commit()
        flash("Entry updated.", "success")
        return _safe_redirect(request.form.get("next"))

    @app.post("/transactions/<int:txn_id>/delete")
    @admin_required
    def transaction_delete(txn_id: int):
        txn = db.session.get(Transaction, txn_id)
        if txn is None:
            abort(404)
        db.session.delete(txn)
        db.session.commit()
        flash("Entry deleted.", "success")
        return _safe_redirect(request.form.get("next"))

    # ---------------- excel export ----------------

    def _workbook_bytes(period):
        import io
        from exporter import build_workbook

        workbook = build_workbook(period, generated_at=datetime.now(timezone.utc))
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    @app.get("/export.xlsx")
    @login_required
    def export_xlsx():
        period = parse_period(request.args)
        payload = _workbook_bytes(period)
        stamp = (period.end or date.today()).isoformat()
        return Response(
            payload,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="BailsLedgerBook-{stamp}.xlsx"',
                "Content-Length": str(len(payload)),
            },
        )

    def _drive_target():
        """The configured mirror folder, or None when it is not usable."""
        folder = app.config.get("DRIVE_EXPORT_DIR", "")
        if not folder:
            return None
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            return None
        return folder

    @app.post("/export/drive")
    @admin_required
    def export_to_drive():
        """Write the workbook into the mirror folder, replacing the file in place."""
        folder = _drive_target()
        if folder is None:
            flash("No sync folder is configured. Set DRIVE_EXPORT_DIR to a Google "
                  "Drive folder on this machine.", "error")
            return _safe_redirect(request.form.get("next"))

        period = parse_period(request.args if request.method == "GET" else request.form)
        filename = os.path.basename(app.config.get("DRIVE_EXPORT_FILENAME") or "BailsLedgerBook.xlsx")
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"
        destination = os.path.join(folder, filename)

        try:
            payload = _workbook_bytes(period)
            # Write to a temp file in the same folder, then move it into place, so
            # Drive never uploads a half-written workbook.
            temporary = destination + ".part"
            with open(temporary, "wb") as handle:
                handle.write(payload)
            os.replace(temporary, destination)
        except OSError as exc:
            app.logger.warning("drive export failed: %s", exc)
            flash(f"Could not write to the sync folder: {exc.strerror or exc}", "error")
            return _safe_redirect(request.form.get("next"))

        size_kb = max(1, len(payload) // 1024)
        flash(f"Saved {filename} ({size_kb} KB) to the sync folder \u2014 "
              f"Google Drive will upload it shortly.", "success")
        return _safe_redirect(request.form.get("next"))

    # ---------------- backup ----------------

    @app.get("/admin/backup.json")
    @admin_required
    def admin_backup():
        """Download a complete, portable snapshot of the whole database.

        Works the same on SQLite and Postgres: it reads every row through the
        ORM rather than copying a file, so a Render (Postgres) admin gets the
        same backup a laptop (SQLite) admin does. Restore with restore_backup.py.
        """
        import json
        from backup import build_backup

        snapshot = build_backup(generated_at=datetime.now(timezone.utc))
        payload = json.dumps(snapshot, indent=2, ensure_ascii=False)
        stamp = date.today().isoformat()
        return Response(
            payload,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="bails-ledger-backup-{stamp}.json"',
                "Content-Length": str(len(payload.encode("utf-8"))),
            },
        )

    # ---------------- ops ----------------

    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok"), 200
        except Exception:  # pragma: no cover - surfaced to the platform probe
            return jsonify(status="degraded"), 503

    @app.errorhandler(CSRFError)
    def csrf_expired(_):
        """A stale or missing token should send the operator back, not 400."""
        flash("That form expired or could not be verified. Please try again.", "error")
        target = request.form.get("next") or request.referrer
        if target and urlsplit(target).netloc in ("", urlsplit(request.url_root).netloc):
            return _safe_redirect(urlsplit(target).path or "/"), 400
        return redirect(url_for("dashboard" if session.get("authed") else "login")), 400

    @app.errorhandler(403)
    def forbidden(_):
        return render_template(
            "error.html", code=403,
            message="Partner access is view-only. Sign in as Admin to add, edit or delete entries.",
        ), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                              message="That page does not exist."), 404

    @app.errorhandler(500)
    def server_error(_):  # pragma: no cover
        db.session.rollback()
        return render_template("error.html", code=500,
                               message="Something went wrong on our side."), 500


app = create_app()

if __name__ == "__main__":
    app.run(debug=bool(os.environ.get("FLASK_DEBUG")), port=int(os.environ.get("PORT", 5000)))
