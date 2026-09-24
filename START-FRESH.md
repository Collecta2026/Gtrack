# Starting fresh — erase everything and deploy clean

Follow these in order. Nothing here needs a terminal, a shell, or any command typing.
Expect about twenty minutes, most of it waiting for the build.

---

## 1. Delete the old Render services

In Render, you currently have more than one Gtrack web service, which is a large part of
why this has been confusing — the URL you were visiting and the one you were configuring
were not always the same service.

1. Go to **dashboard.render.com**
2. For **every** service named Gtrack: open it → **Settings** → scroll to the bottom →
   **Delete Web Service**
3. Confirm. Do this until no Gtrack service remains in the list.

Leave your other services (sgcash, time-hr, collecta, Collecta-Test) alone.

---

## 2. Empty the database

Your Postgres lives at Neon, not Render.

1. Sign in at **console.neon.tech**
2. Open the Gtrack project
3. Either delete the database and create a new empty one with the same name, or use
   **SQL Editor** and run:

   ```sql
   DROP SCHEMA public CASCADE;
   CREATE SCHEMA public;
   ```

4. Copy the **connection string** — you need it in step 4. It looks like
   `postgresql://user:password@ep-something.eu-central-1.aws.neon.tech/dbname?sslmode=require`

The app rebuilds every table itself on first start, so an empty database is exactly what
it wants.

---

## 3. Replace the code on GitHub

The existing repository has accumulated 78 stray files from uploads — duplicate copies
that sit in the root doing nothing, and two old databases with the demo accounts still
inside them. Rather than delete those one at a time, start a clean repository.

1. Go to **github.com/new**
2. Name it `Gtrack-Live` (any name; just not the old one)
3. **Private**, no README, no .gitignore — create it empty
4. On the new repository's page, click **uploading an existing file**
5. Unzip the package I sent you, open the unzipped folder, select **everything inside
   it**, and drag it all into the browser window in one go — folders included. GitHub
   keeps the folder structure when you drag them together.
6. Check the file list shows `app`, `data`, `seed.py`, `Dockerfile`, `wsgi.py` and the
   rest, then **Commit changes**

---

## 4. Create the Render service

1. Render → **New** → **Web Service**
2. Connect it to your new **Gtrack-Live** repository
3. Set:
   - **Language / Runtime**: Docker
   - **Branch**: main
   - **Instance type**: whatever you were on before is fine
4. Under **Environment Variables**, add these two:

   | Key | Value |
   |---|---|
   | `GTRACK_DATABASE_URL` | the Neon connection string from step 2 |
   | `GTRACK_SECRET_KEY` | any long random string of your own |

5. **Create Web Service**

The first build takes a few minutes. When it finishes, the container seeds the database
automatically — 116 shipments, the purchase orders, costs, documents and equipment
history — and creates **no accounts at all**.

---

## 5. Create your admin account

1. Open the URL Render shows at the top of the service page — it will be something like
   `https://gtrack-xxxx.onrender.com`
2. You'll get a **setup screen**, not a login form
3. Enter your name, your email and a password of your choosing
4. You're signed in immediately

That account has full access. Nobody else knows the password, and there is no other way
in — there are no other accounts.

---

## 6. Add your team

**Admin → Users → Add a user**, one per person:

- Give them a name, email and the role their position needs
- Leave the password field blank and the system generates a temporary one
- Hand that temporary password to them; the first time they sign in they're made to
  replace it with their own before they can reach anything else
- If anyone forgets theirs, **Reset password** on their row issues a fresh one

Roles available: CFO (full access, including Admin), MD (read everything plus reports),
Finance (costs, payments, bank registration, financial analysis), Sales (only their own
customers' shipments), Sales Admin (all customers' allocations), Logistics Admin (POs,
suppliers, shipments, stages, Form 4, warehouse receipt). You can add more roles and set
exactly what each can reach from **Admin → Authorisation matrix**.

---

## If something goes wrong

**The setup screen doesn't appear and you get a login form instead** — the database
already has an account in it. That's expected on the second visit onwards; sign in with
the account you made in step 5.

**"Application failed to respond"** — check the service's **Logs** tab. Nine times out of
ten it's `GTRACK_DATABASE_URL` being wrong or missing.

**Build fails** — check the repository has `Dockerfile` at the top level, not inside a
subfolder. That happens if the folder itself got dragged in rather than its contents.
