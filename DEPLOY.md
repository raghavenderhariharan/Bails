# Deploying to Render

Repository: <https://github.com/raghavenderhariharan/Bails>

Everything Render needs is already committed: `render.yaml` (the blueprint),
`requirements.txt`, and a `/healthz` endpoint for health checks.

---

## Read this first: pick your database

Render's **free** Postgres is **deleted 30 days after it is created** (plus a
14-day grace period to upgrade), and free databases get no backups. That is fine
for a trial, and wrong for a ledger you intend to keep.

| | Database | Cost | Your data |
|---|---|---|---|
| **A — recommended** | Neon free Postgres | free, no card | Permanent (0.5 GB) |
| **B — fastest** | Render free Postgres | free | **Deleted after ~30 days** |
| **C** | Render Postgres, paid plan | from ~$7/mo | Kept, with backups |

The app reads `DATABASE_URL`, so any Postgres works with no code change.

---

## Option A — Render web service + Neon Postgres (recommended)

### 1. Create the database

1. Sign up at <https://neon.com> (no card needed).
2. Create a project, e.g. `bails-ledger`.
3. Copy the **connection string**. It looks like:
   `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`

### 2. `render.yaml` is already set up for this

The committed blueprint uses an **external** database: there is no
Render-provisioned `databases:` block, and `DATABASE_URL` is marked
`sync: false`, so Render asks you for it in the dashboard (step 3).

```yaml
      - key: DATABASE_URL
        sync: false        # paste your Neon connection string in the dashboard
```

Nothing to change — go straight to step 3. (To use Render's own free Postgres
instead, see **Option B** below.)

### 3. Deploy

1. <https://dashboard.render.com> → **New +** → **Blueprint**.
2. Connect GitHub and pick **raghavenderhariharan/Bails**, branch `main`.
3. Render reads `render.yaml` and shows the `bails-ledger` service.
4. It will prompt for the variables marked `sync: false`:

   | Variable | What to enter |
   |---|---|
   | `ADMIN_PASSWORD` | A **new** strong password. Do not ship `Admin123`. |
   | `PARTNER_PASSCODE` | A shared code for partners — see the warning below. |
   | `DATABASE_URL` | The Neon connection string from step 1. |

   `SECRET_KEY` is generated for you. Leave `FORCE_HTTPS=true` and
   `TRUSTED_PROXY_COUNT=1` alone.
5. **Apply**. First build takes a few minutes.

Your URL will be `https://bails-ledger.onrender.com` (Render may add a suffix if
the name is taken).

### 4. Load your ledger into the database

Free Render services have no shell, so seed the database **from your laptop**,
pointing at the same Neon database you gave Render. Paste your own connection
string in place of the placeholder — the full string (`sslmode` and
`channel_binding` included) is on your Neon dashboard under **Connect**:

```bash
cd ~/Documents/BailsLedger
source .venv/bin/activate

# Your Neon connection string — keep it in the shell only, never in a file.
export DATABASE_URL='postgresql://USER:PASSWORD@ep-xxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
python import_excel.py BailsLedgerBook.xlsx --replace
unset DATABASE_URL
```

It prints what it imported (10 rows: ₹51,000 income, ₹7,000 expense) and seeds
the six partners. Reload the site and the figures appear. Re-run it any time you
want to reset the database to match the spreadsheet.

> **Never paste the real connection string into a tracked file** (this repo is
> public). Keep it in the shell, as above, or in your git-ignored `.env`.
>
> `unset DATABASE_URL` at the end matters — otherwise your next local run talks
> to the production database instead of `instance/bails_ledger.db`.

---

## Option B — using Render's own free Postgres

The blueprint ships with an external database (Option A), so to have Render
create and wire a Postgres for you, add this block back to the end of
`render.yaml` and change the `DATABASE_URL` entry to match:

```yaml
      - key: DATABASE_URL
        fromDatabase:
          name: bails-ledger-db
          property: connectionString

databases:
  - name: bails-ledger-db
    plan: free
    databaseName: bails_ledger
    user: bails
```

Commit, push, then **New +** → **Blueprint** → pick the repo → **Apply**. Render
creates both the service and the database and wires `DATABASE_URL` automatically;
you only enter `ADMIN_PASSWORD` and `PARTNER_PASSCODE`.

Load the data the same way as step 4 above, using the database's **External
Database URL** from its Render page. If the connection is refused, open the
database → **Access Control** → add your IP (or `0.0.0.0/0` temporarily).

**Set a calendar reminder for ~25 days out** to upgrade the database or migrate
to Neon, or the ledger goes with it.

---

## After it is live

**Change the admin password.** `Admin123` is in this public repo. Set a real one
in **Environment** → edit `ADMIN_PASSWORD` → save (the service restarts).

**Decide about partner access.** The Partner door has no password by design, so
on a public `.onrender.com` URL *anyone who finds the link can read the whole
ledger* — income, expenses and every partner's earnings. Set `PARTNER_PASSCODE`
to put a shared code in front of it. Leaving it blank is a deliberate choice, not
an oversight, but make it knowingly.

**Expect a slow first load.** Free services sleep after 15 minutes idle; the next
request takes 30–60 seconds while it wakes. Later requests are normal. A paid
instance removes this.

**"Save to Drive" will not appear.** It writes to a Google Drive folder on your
Mac, which does not exist on Render. Use it locally; **Export Excel** works
everywhere.

**Updating the app:** push to `main` and Render redeploys automatically. Your
data is in Postgres, so deploys do not touch it.

---

## Backing up the database

Signed in as **Admin**, the filter bar has an **Export / Backup** button. Pick
**All time** and **Download backup** for a single JSON file containing the entire database — every transaction, the
partners and their equity, watchmen, the ground-payment ledger, calendar bookings and settings.

It backs up **whatever database that site is connected to**:

- On the **Render** site, the button downloads your live **Neon** data.
- On your **laptop**, it downloads the local SQLite copy.

Keep that JSON somewhere safe. To restore it — into Neon, or a new database, or
your laptop — point `DATABASE_URL` at the target and run:

```bash
# Restore into Neon (your production database):
export DATABASE_URL='postgresql://...neon.tech/neondb?sslmode=require&channel_binding=require'
python restore_backup.py bails-ledger-backup-2026-10-06.json
unset DATABASE_URL

# ...or into the local SQLite copy (no DATABASE_URL):
python restore_backup.py bails-ledger-backup-2026-10-06.json
```

Pick a month, quarter or year instead for a **period backup**: just that
period's entries and calendar bookings. Restoring a period backup replaces only
that date range and leaves everything else alone.

A full restore **replaces all data** in the target database, so it asks you to confirm
first. Because Neon's free tier has no backups of its own, downloading this JSON
every so often is your safety net.

**In the browser (Admin):** the filter bar also has a **Restore** button next to
Backup. It opens a dialog to upload a backup `.json`, makes you type `RESTORE` to
enable the button, and then replaces everything — the same all-or-nothing restore
as the CLI, but without leaving the site. Use it to roll a Render/Neon database
back to a saved backup directly.

## Email ("Send mail")

Admin's **Send mail** button emails the Excel workbook for any month, quarter or
year. The subject and message are written for the period you pick, the
addresses are remembered, and you can add or remove addresses in the dialog at
any time. It starts with `bailscricketground@gmail.com` and `medallion76@gmail.com`.

**Render's free plan blocks outbound SMTP** (ports 25, 465 and 587), so the
usual "Gmail app password" route does not work there. The site sends through
the **Gmail API** instead, which uses ordinary HTTPS. One-time setup, about 10
minutes:

1. Go to <https://console.cloud.google.com>, signed in as the account that
   should send the mail (e.g. `bailscricketground@gmail.com`). Create a project,
   e.g. `bails-ledger`.
2. **APIs & Services → Library** → search **Gmail API** → **Enable**.
3. **APIs & Services → OAuth consent screen**: User type **External**, app name
   `Bails Ledger`, your email for the support/developer contacts. Add yourself
   under **Test users**. Then **Publish app** (set it to *In production*);
   without that, Google expires the token after 7 days. Google will show an
   "unverified app" warning when you sign in; that is expected for a private
   app, so click **Advanced → Go to Bails Ledger**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   type **Desktop app**. Copy the **client ID** and **client secret**.
5. On your laptop:

   ```bash
   cd ~/Documents/BailsLedger && source .venv/bin/activate
   python gmail_auth.py
   ```

   Paste the client ID and secret, sign in in the browser that opens, and allow
   **Send email on your behalf** (it cannot read your inbox). The script prints
   a refresh token.
6. Render → your service → **Environment** → add `GMAIL_CLIENT_ID`,
   `GMAIL_CLIENT_SECRET` and `GMAIL_REFRESH_TOKEN` → **Save** (the service
   restarts). The **Send** button now works.

Never put these three values in a tracked file: the repo is public. To revoke
access at any time, use <https://myaccount.google.com/permissions>.

**Without any setup**, the dialog's **Open in Gmail** button still works
everywhere: it downloads the workbook and opens a Gmail draft with the
addresses, subject and message filled in. You attach the file and press send.

**Locally (or on a paid Render instance)** you can use SMTP instead: set
`SMTP_USER` to the Gmail address and `SMTP_PASSWORD` to a Gmail
[app password](https://myaccount.google.com/apppasswords) in your `.env`.

## If something goes wrong

| Symptom | Cause and fix |
|---|---|
| Build fails on `psycopg` | `PYTHON_VERSION` must be 3.12.x. It is set in `render.yaml`. |
| `RuntimeError: SECRET_KEY is not set` | `SECRET_KEY` missing. The blueprint generates it; if you created the service by hand, add it: `python -c "import secrets; print(secrets.token_hex(32))"`. |
| Health check failing | Check **Logs**. `/healthz` returns 503 when the database is unreachable — usually a wrong `DATABASE_URL`. |
| Signed out on every page | `SECRET_KEY` is changing between restarts. Set it as a real env var. |
| Everyone locked out of login together | `TRUSTED_PROXY_COUNT` is not `1`, so every visitor shares one throttle bucket. |
| Site loads but has no data | The import in step 4 has not been run against this database. |
| Local run suddenly hits production | `DATABASE_URL` is still exported in that shell. `unset DATABASE_URL`. |
| Backup button missing | You are signed in as Partner, not Admin. It is admin-only. |
| **Send** is greyed out in Send mail | Email is not set up on this server. See **Email** above, or use **Open in Gmail**. |
| "Gmail refused the request (400/401)" | The refresh token was revoked or expired (an app still in *Testing* expires after 7 days). Publish the consent screen and re-run `gmail_auth.py`. |

Logs: service page → **Logs**. Env vars: **Environment**. Manual redeploy:
**Manual Deploy** → *Clear build cache & deploy*.
