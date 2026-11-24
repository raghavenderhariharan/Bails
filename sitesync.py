"""Keep the public Bails website's calendar in step with the ledger's.

One way: ledger -> website. The ledger is the master record: after every
calendar change, the website's blocked slots, past and future, are made to
match the ledger's exactly (bails-cricket-ground.onrender.com admin API).
Website blocks the ledger doesn't have are removed, even ones added there by
hand, and the ledger's are added. Each block the ledger creates carries a
"[Ledger #<id>]" tag in its admin-only note so later syncs recognise it.
The website's fixtures (a separate list of matches) are left alone.

Configured only by environment variables (never commit the password):

    BAILS_SITE_URL       https://bails-cricket-ground.onrender.com
    BAILS_SITE_USER      admin
    BAILS_SITE_PASSWORD  (the website's admin password)

With any of them missing, syncing is switched off and nothing is sent.
"""
import http.cookiejar
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

# Ledger slot -> website slot id.
SLOT_IDS = {"7:00 AM": "s1", "10:45 AM": "s2", "2:30 PM": "s3", "Full Day": "full"}
PARTS = {"full": {"s1", "s2", "s3"}, "s1": {"s1"}, "s2": {"s2"}, "s3": {"s3"}}
TAG_RE = re.compile(r"\[Ledger #(\d+)\]")
STATUS_KEY = "site_sync_status"
IST = timezone(timedelta(hours=5, minutes=30))


class SyncError(Exception):
    pass


def settings():
    env = os.environ
    url = env.get("BAILS_SITE_URL", "").strip().rstrip("/")
    user = env.get("BAILS_SITE_USER", "").strip()
    password = env.get("BAILS_SITE_PASSWORD", "")
    return (url, user, password) if url and user and password else None


def configured() -> bool:
    return settings() is not None


def today_ist() -> date:
    return datetime.now(IST).date()


# --------------------------------------------------------------------------- #
# What a ledger block looks like on the website
# --------------------------------------------------------------------------- #

def category_for(booked_by: str, note: str) -> str:
    text = f"{booked_by} {note}".lower()
    if "hca" in text:
        return "hca"
    if re.search(r"tournament|\bcup\b|league|\becl\b|final", text):
        return "tournament"
    if re.search(r"maintenance|roller|pitch work", text):
        return "maintenance"
    if re.search(r"practice|\bnets?\b", text):
        return "practice"
    return "private"


def public_label(booked_by: str) -> str:
    """What the public calendar shows: the team, without the contact person
    in brackets ("Octa Legends (Rohit)" -> "Octa Legends")."""
    return re.sub(r"\s*\([^)]*\)\s*", " ", booked_by or "").strip()[:100]


def payload(b) -> dict:
    who = (b.booked_by or "").strip()
    bits = [x for x in ((b.note or "").strip(), f"Booked by {who}" if who else "") if x]
    tag = f"[Ledger #{b.id}]"
    note = " · ".join(bits)
    note = (note[: 300 - len(tag) - 1] + " " + tag).strip() if note else tag
    return {
        "date": b.booking_date.isoformat(),
        "slot": SLOT_IDS[b.slot],
        "category": category_for(who, b.note or ""),
        "label": public_label(who),
        "note": note,
    }


def plan(local, remote, today):
    """Work out the website changes. ``local``: ledger bookings; ``remote``:
    the website's booking dicts. Returns (creates, deletes) where creates are
    (ledger booking, payload) and deletes are website booking dicts."""
    # ``today`` is kept for callers; the whole calendar is mirrored.
    wanted = {b.id: (b, payload(b)) for b in local if b.slot in SLOT_IDS}
    creates, deletes, have = [], [], set()
    for r in remote:
        m = TAG_RE.search(r.get("note") or "")
        if not m:
            deletes.append(r)  # added on the website by hand: the ledger is the master record
            continue
        lid = int(m.group(1))
        if lid in wanted:
            want = wanted[lid][1]
            same = all((r.get(k) or "") == want[k] for k in ("date", "slot", "category", "label", "note"))
            if same and lid not in have:
                have.add(lid)
                continue
            deletes.append(r)  # changed in the ledger (or a duplicate): replace it
        else:
            deletes.append(r)  # unblocked in the ledger
    for lid, (b, body) in sorted(wanted.items(), key=lambda kv: (kv[1][1]["date"], kv[1][1]["slot"])):
        if lid not in have:
            creates.append((b, body))
    return creates, deletes


# --------------------------------------------------------------------------- #
# The website's admin API
# --------------------------------------------------------------------------- #

class Client:
    def __init__(self, url, user, password, timeout=90):
        self.url, self.user, self.password, self.timeout = url, user, password, timeout
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "BailsLedger-sync"})
        try:
            with self.opener.open(req, timeout=self.timeout) as res:
                return json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read() or b"{}").get("error") or ""
            except ValueError:
                message = ""
            raise SyncError(message or f"website answered {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SyncError(f"could not reach the website ({getattr(exc, 'reason', exc)})") from None

    def login(self):
        self.call("POST", "/api/login", {"username": self.user, "password": self.password})

    def bookings(self):
        return self.call("GET", "/api/admin-data").get("bookings") or []

    def create(self, body):
        return self.call("POST", "/api/bookings", body)

    def delete(self, booking_id):
        self.call("DELETE", f"/api/bookings/{booking_id}")

    def logout(self):
        try:
            self.call("POST", "/api/logout")
        except SyncError:
            pass


# --------------------------------------------------------------------------- #
# Running a sync
# --------------------------------------------------------------------------- #

def run(local, client, today=None):
    """One full pass. Returns a status dict (also what the calendar page shows)."""
    today = today or today_ist()
    client.login()
    try:
        remote = client.bookings()
        creates, deletes = plan(local, remote, today)
        for r in deletes:
            client.delete(r["id"])
        gone = {r["id"] for r in deletes}
        taken = {}
        for r in remote:
            if r["id"] not in gone:
                for part in PARTS.get(r.get("slot"), ()):
                    taken[(r.get("date"), part)] = r.get("label") or r.get("category") or "a booking"
        created, conflicts = 0, []
        for b, body in creates:
            clash = next((taken[(body["date"], p)] for p in PARTS[body["slot"]] if (body["date"], p) in taken), None)
            if clash:
                conflicts.append(f"{b.booking_date:%d %b %Y} {b.slot}: the website already has {clash}")
                continue
            try:
                client.create(body)
                created += 1
                for p in PARTS[body["slot"]]:
                    taken[(body["date"], p)] = body["label"] or "this block"
            except SyncError as exc:
                conflicts.append(f"{b.booking_date:%d %b %Y} {b.slot}: {exc}")
    finally:
        client.logout()
    return {"ok": not conflicts, "created": created, "deleted": len(deletes), "conflicts": conflicts[:20],
            "conflict_count": len(conflicts), "error": ""}


_lock = threading.Lock()
_pending = threading.Event()


def sync_now(app, client=None):
    """Run a sync for ``app`` and save the outcome. Safe to call from a thread."""
    from models import GroundBooking, Setting, db

    cfg = settings()
    if cfg is None and client is None:
        return None
    with app.app_context():
        local = GroundBooking.query.all()
        try:
            status = run(local, client or Client(*cfg))
        except SyncError as exc:
            status = {"ok": False, "created": 0, "deleted": 0, "conflicts": [], "conflict_count": 0,
                      "error": str(exc)}
        except Exception as exc:  # pragma: no cover - never let a sync take the app down
            app.logger.warning("site sync failed: %s", exc)
            status = {"ok": False, "created": 0, "deleted": 0, "conflicts": [], "conflict_count": 0,
                      "error": "unexpected error; see the server log"}
        status["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # The settings column holds 255 characters: keep as many conflict lines as fit.
        saved = dict(status)
        while len(json.dumps(saved)) > 255 and saved["conflicts"]:
            saved["conflicts"] = saved["conflicts"][:-1]
        saved["error"] = saved["error"][:120]
        Setting.put(STATUS_KEY, json.dumps(saved)[:255])
        db.session.commit()
        if status["error"] or status["conflict_count"]:
            app.logger.warning("site sync: %s", status)
        return status


def trigger(app):
    """Sync in the background after a calendar change. Changes made while a
    sync is running are picked up by one more pass straight after it."""
    if not configured():
        return False
    _pending.set()
    if not _lock.acquire(blocking=False):
        return True  # the running sync will loop once more

    def worker():
        try:
            while _pending.is_set():
                _pending.clear()
                sync_now(app)
        finally:
            _lock.release()

    threading.Thread(target=worker, name="site-sync", daemon=True).start()
    return True


def last_status():
    from models import Setting

    raw = Setting.get(STATUS_KEY, "")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None
