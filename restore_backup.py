"""Restore a Bails ledger from a backup produced by the website's Download backup.

    python restore_backup.py bails-ledger-backup-2026-10-06.json

Restores into whatever DATABASE_URL points at (local SQLite by default, or a
remote Postgres when DATABASE_URL is exported). This REPLACES all existing data,
so it asks for confirmation unless --yes is given.
"""
import argparse
import json
import os as _os
import sys

_os.environ.setdefault("SECRET_KEY", "cli-no-sessions")

from app import app
from backup import restore_backup


def main():
    parser = argparse.ArgumentParser(description="Restore a ledger backup JSON file.")
    parser.add_argument("path", help="the backup .json file downloaded from the site")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    try:
        with open(args.path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.exit(f"Could not read {args.path}: {exc}")

    summary = data.get("summary", {})
    target = app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1] or "local SQLite"
    print(f"Backup: {summary.get('transactions', '?')} transactions, "
          f"{summary.get('partners', '?')} partners, net {summary.get('net', '?')}")
    print(f"Restoring INTO: {target}")
    print("This replaces ALL existing data in that database.")

    if not args.yes:
        if input("Type 'restore' to continue: ").strip().lower() != "restore":
            sys.exit("Cancelled.")

    with app.app_context():
        counts = restore_backup(data)
    print(f"Restored {counts['transactions']} transactions, {counts['partners']} partners, "
          f"{counts['settings']} settings.")


if __name__ == "__main__":
    main()
