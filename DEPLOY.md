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

### 2. Edit `render.yaml`

Delete the `databases:` block at the bottom, and replace the `DATABASE_URL`
entry so you supply the value yourself:

```yaml
      - key: DATABASE_URL
        sync: false        # paste the Neon connection string in the dashboard
```

Commit and push:

```bash
git add render.yaml && git commit -m "Use external Postgres" && git push
```

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

### 4. Load your ledger

Free Render services have no shell, so run the import **from your laptop**
against the same database:

```bash
cd ~/Documents/BailsLedger
source .venv/bin/activate

export DATABASE_URL='postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require'
python import_excel.py BailsLedgerBook.xlsx --replace
unset DATABASE_URL
```

It prints what it imported. Reload the site and the figures appear.

> `unset DATABASE_URL` matters — otherwise your next local run talks to the
> production database instead of `instance/bails_ledger.db`.

---

## Option B — one-click, using Render's own free Postgres

Change nothing. **New +** → **Blueprint** → pick the repo → **Apply**. The
blueprint creates both the service and `bails-ledger-db`, and wires
`DATABASE_URL` automatically. You only enter `ADMIN_PASSWORD` and
`PARTNER_PASSCODE`.

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

Logs: service page → **Logs**. Env vars: **Environment**. Manual redeploy:
**Manual Deploy** → *Clear build cache & deploy*.
