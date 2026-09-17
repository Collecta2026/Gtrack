# Deploying Gtrack — Neon, GitHub, Render, awspro.uk

The same pattern as Collecta: Neon holds the database, GitHub holds the code, Render runs
it, and a CNAME on awspro.uk points a subdomain at it.

Allow about an hour end to end. Everything below is done in your own accounts — the code
is already configured for it.

---

## Before you start

Have to hand: your Neon account, your GitHub account, your Render account, and access to
DNS for awspro.uk at Names.co.uk.

Decide the subdomain now, because it appears in a few places. `gtrack.awspro.uk` is the
obvious one and consistent with `collecta.awspro.uk`.

---

## 1. Create the Neon database

1. In Neon, create a project — name it `gtrack`.
2. Choose the region closest to your users. For Cairo and Preston, **AWS eu-central-1
   (Frankfurt)** is the sensible compromise; eu-west-2 (London) if most use is from the UK.
3. Once created, open **Connection Details** and copy the **pooled** connection string.
   It looks like:

   ```
   postgresql://gtrack_owner:XXXXXXXX@ep-something-pooler.eu-central-1.aws.neon.tech/gtrack?sslmode=require
   ```

   Use the **pooled** one (the host contains `-pooler`). Render runs multiple workers and
   Neon's pooler is what keeps connection counts sane.
4. Keep that string somewhere safe for step 3. It contains the password.

Gtrack is already configured for Neon's quirks: it adds `sslmode=require` if missing, and
uses connection pre-ping with a 280-second recycle so a suspended Neon endpoint doesn't
produce "server closed the connection unexpectedly" on the first request after an idle spell.

---

## 2. Put the code on GitHub

From the Gtrack folder on your machine:

```bash
git init
git add .
git commit -m "Gtrack — initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/gtrack.git
git push -u origin main
```

Create the `gtrack` repository on GitHub first (private), then run the commands above.

`.gitignore` already excludes `.env`, the SQLite database and uploaded files, so no
credentials or client documents are committed. Check with `git status` before that first
commit that nothing unexpected is staged.

---

## 3. Deploy on Render

1. Render dashboard → **New** → **Blueprint**.
2. Connect the GitHub repo. Render reads `render.yaml` and proposes a web service.
3. Before the first deploy, set the environment variables on the service:

   | Variable | Value |
   |---|---|
   | `GTRACK_DATABASE_URL` | the Neon pooled connection string from step 1 |
   | `GTRACK_SECRET_KEY` | let Render generate it, or paste your own |
   | `GTRACK_ORG_NAME` | `Scientific Gate Egypt` |
   | `GTRACK_UPLOAD_FOLDER` | `/var/data/uploads` |
   | `GTRACK_NOTIFICATIONS_LIVE` | `0` until email is wired up |

   **Important:** `render.yaml` as shipped also provisions a Render Postgres database.
   If you are using Neon instead, delete the `databases:` block at the bottom of
   `render.yaml` and the `fromDatabase` lines above it, then set `GTRACK_DATABASE_URL`
   by hand to the Neon string. Otherwise you will be paying for two databases and using
   one.

4. Keep the **Starter** plan so the service stays always-on, as with Collecta.
5. The disk mount at `/var/data` is what makes uploaded documents survive a redeploy.
   Don't remove it — without it, every document uploaded is lost on the next deploy.
6. Deploy. The build runs `pip install -r requirements-deploy.txt`, which is the file that
   includes gunicorn and the Postgres driver.

---

## 4. Build the database

The first deploy will start but have no tables. From Render's **Shell** tab on the service:

```bash
python check_db.py        # confirms it can reach Neon
python seed.py --force    # builds the schema and migrates the spreadsheet
```

`--force` is required because seeding drops and recreates every table, and Gtrack refuses
to do that to a non-SQLite database unless you say so explicitly. That guard is there on
purpose — read what it prints before you type the flag.

If you want an empty system rather than the migrated spreadsheet, run
`flask --app run init-db` instead, then create your first user through the shell.

**Change the demo passwords immediately.** Every seeded account uses `demo1234`. Sign in as
`zak@scientificgate.test`, go to Administration → Users, and reset them — or delete the
demo accounts entirely and create real ones.

---

## 5. Point gtrack.awspro.uk at it

1. In Render, open the service → **Settings** → **Custom Domains** → add
   `gtrack.awspro.uk`. Render shows you the target hostname, something like
   `gtrack-xxxx.onrender.com`.
2. At Names.co.uk, in the DNS for awspro.uk, add:

   | Type | Host | Points to |
   |---|---|---|
   | CNAME | `gtrack` | `gtrack-xxxx.onrender.com` |

   It must be a **CNAME**, not an A or AAAA record. (An AAAA record was the thing that
   caught you out on Collecta.)
3. Wait for propagation — usually minutes, occasionally an hour. Check with
   `nslookup gtrack.awspro.uk`.
4. Render issues the SSL certificate automatically once the CNAME resolves. The domain
   shows as "Certificate pending" until then, which is normal. Don't change anything while
   it is pending.

---

## 6. Check it over

- Sign in and confirm the dashboard loads with data.
- Upload a document to a shipment, redeploy, and confirm the document is still there —
  that proves the disk mount is working.
- Open the cost statement on a shipment and export it to PDF.
- Sign in as a sales account and confirm the scoping still holds.
- Leave it idle for ten minutes, then load a page. If Neon's pooling is right, it responds
  normally; if you see a connection error, check you used the **pooled** connection string.

---

## Ongoing

**Deploying a change:** push to `main` and Render rebuilds automatically.

**Backups:** Neon keeps point-in-time history on paid plans; check what your plan gives you
and set a retention you're comfortable with. The uploaded documents on Render's disk are
*not* part of that — back those up separately if they matter.

**The notification sweep** runs when someone presses the button on the dashboard. To have it
run by itself, add a Render **Cron Job** on the same repo running:

```bash
python -c "from app import create_app; from app.notifications import run_rule_sweep; \
app=create_app(); ctx=app.app_context(); ctx.push(); print(len(run_rule_sweep()), 'alerts')"
```

Daily at 07:00 UTC is a reasonable start.

**Turning on real emails:** set `GTRACK_NOTIFICATIONS_LIVE=1` and add an SMTP backend in
`app/notifications.py` at the `_deliver()` function. Until then every alert is written to
the notification log, which is visible in the interface.

---

## If something goes wrong

**"relation ... does not exist"** — the schema was never built. Run `python seed.py --force`
from the Render shell.

**"server closed the connection unexpectedly"** — you're using Neon's direct connection
string rather than the pooled one. Swap it in `GTRACK_DATABASE_URL`.

**Documents vanish after deploying** — the disk mount is missing or `GTRACK_UPLOAD_FOLDER`
doesn't point inside it.

**Certificate stuck pending** — the CNAME is wrong, or it's an A record. Verify with
`nslookup` that the subdomain resolves to the Render hostname.

**Build fails on psycopg2** — you're building `requirements.txt` instead of
`requirements-deploy.txt`. Check the build command in `render.yaml`.
