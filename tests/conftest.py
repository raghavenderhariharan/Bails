"""Test isolation.

config.py loads a local .env so the operator's ADMIN_PASSWORD and
DRIVE_EXPORT_DIR are honoured when running the app. python-dotenv does not
overwrite variables that are already set, so pinning them here — before any test
module imports config — keeps a developer's real .env out of the test run.
"""
import os

_PINNED = {
    "ADMIN_PASSWORD": "Admin123",
    "SECRET_KEY": "test-secret",
    "PARTNER_PASSCODE": "",
    "DRIVE_EXPORT_DIR": "",
    "DRIVE_EXPORT_FILENAME": "BailsLedgerBook.xlsx",
    "TRUSTED_PROXY_COUNT": "0",
    "CURRENCY_SYMBOL": "₹",
    "FORCE_HTTPS": "",
    "FLASK_DEBUG": "",
}

for _key, _value in _PINNED.items():
    os.environ[_key] = _value
