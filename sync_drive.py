"""Write the Excel export into a folder (typically Google Drive for Desktop).

    python sync_drive.py                      # uses DRIVE_EXPORT_DIR
    python sync_drive.py --dir "/path/to/My Drive/BAILS"
    python sync_drive.py --period all
    python sync_drive.py --dir ... --name "BailsLedgerBook.xlsx"

The destination file is replaced in place, so the folder always holds the latest
ledger. Google Drive uploads it and keeps the previous copy in version history.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import os as _os

# These scripts only touch the database; they never serve a request, so they do
# not need a real session key. Set a placeholder before importing the app so the
# "SECRET_KEY is required in deployment" guard does not block a CLI run against
# a remote DATABASE_URL.
_os.environ.setdefault("SECRET_KEY", "cli-no-sessions")

from app import app
from exporter import build_workbook
from finance import parse_period


def main():
    parser = argparse.ArgumentParser(description="Export the ledger to a sync folder.")
    parser.add_argument("--dir", dest="folder", default=os.environ.get("DRIVE_EXPORT_DIR", ""),
                        help="destination folder (default: $DRIVE_EXPORT_DIR)")
    parser.add_argument("--name", default=os.environ.get("DRIVE_EXPORT_FILENAME", "BailsLedgerBook.xlsx"),
                        help="file name to write (default: BailsLedgerBook.xlsx)")
    parser.add_argument("--period", default="all",
                        choices=["all", "month", "quarter", "year"],
                        help="how much of the ledger to include (default: all)")
    parser.add_argument("--month", help="YYYY-MM, with --period month")
    parser.add_argument("--year", help="YYYY, with --period quarter or year")
    parser.add_argument("--quarter", help="1-4, with --period quarter")
    args = parser.parse_args()

    if not args.folder:
        sys.exit("No destination. Pass --dir or set DRIVE_EXPORT_DIR.")
    folder = os.path.abspath(os.path.expanduser(args.folder))
    if not os.path.isdir(folder):
        sys.exit(f"Not a folder: {folder}")

    filters = {"period": args.period}
    for key in ("month", "year", "quarter"):
        value = getattr(args, key)
        if value:
            filters[key] = value

    name = os.path.basename(args.name)
    if not name.endswith(".xlsx"):
        name += ".xlsx"
    destination = os.path.join(folder, name)

    with app.app_context():
        period = parse_period(filters)
        workbook = build_workbook(period, generated_at=datetime.now(timezone.utc))
        temporary = destination + ".part"
        workbook.save(temporary)
        os.replace(temporary, destination)

    size = os.path.getsize(destination)
    print(f"Wrote {destination}")
    print(f"  period: {period.label}")
    print(f"  size:   {size:,} bytes")
    print("  Google Drive will upload it shortly (check the Drive menu-bar icon).")


if __name__ == "__main__":
    main()
