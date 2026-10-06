"""Application configuration.

Reads everything from environment variables so the same code runs on a laptop
(SQLite) and on Render (Postgres) with no edits.
"""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

# Load a local .env if one exists, so ADMIN_PASSWORD/SECRET_KEY set there are
# actually honoured. Real environment variables always win over the file.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
except ImportError:  # pragma: no cover - dotenv is in requirements.txt
    pass


def _database_uri() -> str:
    """Prefer a managed Postgres when one is provisioned, else a local SQLite file.

    Render exposes Postgres as DATABASE_URL using the legacy ``postgres://``
    scheme, which SQLAlchemy 2.x no longer registers; normalise it.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    return "sqlite:///" + os.path.join(INSTANCE_DIR, "bails_ledger.db")


def _secret_key() -> str:
    """Resolve a stable secret key.

    A key that changes per process would sign every worker's cookies
    differently and log everyone out on each restart, so a random value is
    never used for a real deployment:

    * ``SECRET_KEY`` set           -> use it (the only option in production).
    * running a real deployment    -> refuse to start without it.
    * running locally              -> persist one under ``instance/`` so it
      survives restarts and is shared by every worker.
    """
    from_env = os.environ.get("SECRET_KEY", "").strip()
    if from_env:
        return from_env

    # DATABASE_URL is set by the platform, so treat its presence as "deployed".
    if os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError(
            "SECRET_KEY is not set. Set it to a long random value "
            '(python -c "import secrets; print(secrets.token_hex(32))") '
            "so sessions stay valid across restarts and across workers."
        )

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    key_path = os.path.join(INSTANCE_DIR, "secret_key")
    try:
        with open(key_path) as handle:
            existing = handle.read().strip()
        if existing:
            return existing
    except OSError:
        pass

    generated = secrets.token_hex(32)
    try:
        # Create with owner-only permissions, and tolerate a concurrent writer.
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(generated)
        return generated
    except FileExistsError:
        with open(key_path) as handle:
            return handle.read().strip() or generated
    except OSError:
        return generated


class Config:
    SECRET_KEY = _secret_key()

    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Render's free Postgres drops idle connections; recycle before it does.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}

    # The admin gate password. Override in production via the ADMIN_PASSWORD env var.
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin123")

    # Partners sign in without a password by design, so anyone who can reach the
    # site can read the ledger. Set PARTNER_PASSCODE to put a shared code in
    # front of the partner (view-only) door without touching any code.
    PARTNER_PASSCODE = os.environ.get("PARTNER_PASSCODE", "").strip()

    # Session hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FORCE_HTTPS", "").lower() in {"1", "true", "yes"}
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 hours

    # The session cookie already bounds how long a form stays usable, so don't
    # also expire CSRF tokens after an hour and lose a half-typed entry to a 400.
    WTF_CSRF_TIME_LIMIT = None

    CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "₹")

    # Folder the Excel export is mirrored into. Point it at a Google Drive for
    # Desktop folder and Drive syncs the file to the cloud for you. Unset (or a
    # path that does not exist) simply disables the "Save to Drive" button.
    DRIVE_EXPORT_DIR = os.environ.get("DRIVE_EXPORT_DIR", "").strip()
    DRIVE_EXPORT_FILENAME = os.environ.get("DRIVE_EXPORT_FILENAME", "BailsLedgerBook.xlsx")

    # Cap upload size (the restore endpoint accepts a backup file). A ledger
    # backup is a few KB; 16 MB is far more than any real one and keeps a
    # runaway upload from exhausting memory.
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # How many reverse proxies sit in front of the app. Render uses one. Left at
    # 0, X-Forwarded-* headers are ignored entirely, because a client can forge
    # them and a forged value must never be able to reset the login throttle.
    TRUSTED_PROXY_COUNT = max(0, int(os.environ.get("TRUSTED_PROXY_COUNT", "0") or 0))

    # Login throttling
    MAX_LOGIN_ATTEMPTS = 8
    LOGIN_LOCKOUT_SECONDS = 300
    # Backstop for an attacker rotating source addresses: once this many
    # failures land inside one window, every further attempt is slowed.
    GLOBAL_FAILURE_THRESHOLD = 24
    GLOBAL_FAILURE_DELAY_SECONDS = 1.0
    MAX_THROTTLE_ENTRIES = 2048
