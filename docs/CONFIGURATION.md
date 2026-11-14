# Configuration

**Audience:** administrators of the server.
**Covers:** every setting of the panel, with its type, default, meaning, and where and when it can be changed.

The defaults are environment variables, kept in `/opt/odoo/manager/.env` on the server
([.env.example](../.env.example) is the template). **Almost every setting can also be changed on the panel's
Settings page** by a super admin (or with `PATCH /api/v1/settings`, see [Panel API](PANEL_API.md#7-settings)). Such
a change is kept in `/opt/odoo/manager/settings.json` on top of `.env`; **Use .env** on the page brings back the
`.env` value.

The **Applies** column of each table says how a change takes effect:

| Applies | Changed where | Takes effect |
| :--- | :--- | :--- |
| **live** | Settings page or `.env` | On the Settings page: at once, without a restart. |
| **restart** | Settings page or `.env` | These settings choose plugins. On the Settings page: after **Restart the panel** (Settings, Plugins), which stops only the backend for a few seconds and is refused while jobs run. |
| `.env` only | `.env` only | Folders, ports, the exposure and the storage, which the web service and the containers read too. The Settings page lists them, read-only, under **Server**. |

A change made in `.env` itself (any class) applies when the containers are recreated:
`cd /opt/odoo/manager && docker compose up -d`. A value changed on the Settings page wins over `.env` until it is
reset with **Use .env**.

* Names are not case sensitive. A wrong value (for example `IDLE_HOURS=soon`) stops the panel at start-up with a
  message naming the setting; on the Settings page it is refused with the same message.
* See what the panel actually uses: `docker exec sudoo-panel sudoo.sh config`.
* The settings are defined in `src/sudoo/config.py` (the lists `EDITABLE`, `RESTART` and `SECRET`); a test fails when
  one of them is missing here.
* Secret settings (`SMTP_PASSWORD`, `ODOO_ADMIN_PASSWORD`, `GITHUB_WEBHOOK_SECRET`) are write-only on the Settings
  page: it only shows whether they are set. Changed there, they are stored encrypted with the vault key
  ([Security](SECURITY.md#4-stored-secrets-the-vault)).

---

## Contents

1. [Contact](#contact)
2. [Odoo](#odoo)
3. [Enterprise add-ons (plugin)](#enterprise-add-ons-plugin)
4. [Exposure (plugin)](#exposure-plugin)
5. [Code updates (plugins)](#code-updates-plugins)
6. [Storage, sign-in and e-mail (plugins)](#storage-sign-in-and-e-mail-plugins)
7. [Limits](#limits)
8. [Ports](#ports)
9. [Behaviour](#behaviour)
10. [Marketplace](#marketplace)
11. [Locations](#locations)

---

## Contact

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `ADMIN_CONTACT_NAME` | str | `the administrator` | **live** | Who users are told to contact. |
| `ADMIN_CONTACT_PHONE` | str | empty | **live** | Phone number added to that message. |
| `ADMIN_CONTACT_EMAIL` | str | empty | **live** | E-mail address added to that message. |
| `BRAND_COLOR` | str | `#714B67` | **live** | Accent colour of the web app and of e-mails (title mark, buttons), as `#RRGGBB`. |

---

## Odoo

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `ODOO_VERSIONS` | str | `auto` | **live** | Versions offered: "auto" (every published version of the official image from odoo_min_version) or a comma-separated list such as 17.0,18.0,saas-18.2. |
| `ODOO_MIN_VERSION` | str | `16.0` | **live** | Oldest version offered when odoo_versions is "auto". |
| `ODOO_IMAGE` | str | `odoo` | **live** | Docker image of Odoo; the tag is the Odoo version. Used for instances created after the change. |
| `POSTGRES_IMAGE` | str | `postgres:16` | **live** | Docker image of each instance's database. Used for instances created after the change. |
| `ODOO_ADMIN_PASSWORD` | str | `admin` | **live** | Password of the Odoo user "admin" in new instances. Secret: write-only on the Settings page. |

---

## Enterprise add-ons (plugin)

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `ENTERPRISE_SOURCE` | str | `folder` | **restart** | Where Enterprise add-ons come from: "folder", "git" or "none". |
| `ENTERPRISE_PATH` | str | `/opt/odoo/enterprise/{version}` | **live** | folder source: where the add-ons of a version are; {version} (19.0) and {major} (19) are replaced. |
| `ENTERPRISE_GIT_URL` | str | empty | **live** | git source: repository holding one branch per Odoo version. |
| `ENTERPRISE_GIT_BRANCH` | str | `{version}` | **live** | git source: branch name of a version, e.g. {version}. |
| `ENTERPRISE_MARKER` | str | `web_enterprise` | **live** | Module whose presence proves the add-ons are there. |

---

## Exposure (plugin)

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `EXPOSURE` | str | `cloudflare-quick` | `.env` only | How instances are reached: "cloudflare-quick" or "host-ports". |
| `PUBLIC_HOST` | str | empty | `.env` only | host-ports: the server's public name or address. |
| `PUBLIC_SCHEME` | `http` or `https` | `http` | `.env` only | host-ports: scheme of the public addresses. |
| `CLOUDFLARED_IMAGE` | str | `cloudflare/cloudflared:latest` | **live** | cloudflare-quick: connector image, used for connectors started after the change. |
| `CONNECTOR_PREFIX` | str | `sudoo-connector-` | `.env` only | cloudflare-quick: container name prefix. |
| `CONNECTOR_STATUS_PORT_START` | int | `20300` | `.env` only | cloudflare-quick: first status port of a connector. |
| `PANEL_CONNECTOR_STATUS_PORT` | int | `20242` | `.env` only | cloudflare-quick: status port of the panel connector. |

---

## Code updates (plugins)

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `UPDATE_TRIGGERS` | str | `polling` | **restart** | What starts code updates, comma-separated: "polling", "github-webhook" or both. See [Plugins](PLUGINS.md#5-update-triggers-what-starts-a-code-update). |
| `GITHUB_WEBHOOK_SECRET` | str | empty | **live** | github-webhook: the secret entered on GitHub (20 or more random characters). Secret: write-only on the Settings page. |
| `POLL_MINUTES` | float | `2` | **live** | polling: check GitHub for new commits this often. |

---

## Storage, sign-in and e-mail (plugins)

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `STORAGE` | str | `sqlite` | `.env` only | Where the panel keeps its own data (accounts, tokens, audit log, instance state): `sqlite`, the file `/opt/odoo/manager/sudoo.db`. |
| `AUTH` | str | `local` | **restart** | How user names and passwords are checked: `local`, the panel's own accounts. |
| `SECOND_FACTORS` | str | `email,totp` | **restart** | Second factors offered, comma-separated: `email` (a code by e-mail; only when e-mail is set up) and `totp` (an authenticator app). |
| `REQUIRE_SECOND_FACTOR` | str | `admins` | **live** | Who must use a second factor: `none`, `admins` (super admins and administrators) or `everyone`. Such accounts without one can only set one up after signing in. |
| `SESSION_IDLE_MINUTES` | float | `60` | **live** | Panel sign-out after this long without activity. |
| `SESSION_MAX_HOURS` | float | `12` | **live** | Longest panel session. |
| `MAILER` | str | `smtp` | **restart** | How the panel sends e-mail: `smtp` or `none`. |
| `MAIL_FROM` | str | empty | **live** | Sender, for example `Sudoo.sh <no-reply@your-site.com>`; empty: `SMTP_USERNAME`. |
| `SMTP_HOST` | str | empty | **live** | The mail server, for example `mail.your-site.com`. Empty: no e-mail, and no e-mail codes. |
| `SMTP_PORT` | int | `587` | **live** | `587` with `starttls`, `465` with `ssl`. |
| `SMTP_SECURITY` | str | `starttls` | **live** | `starttls`, `ssl` or `none` (only for a mail server on the same machine). |
| `SMTP_USERNAME` | str | empty | **live** | Usually the full address of the mailbox. |
| `SMTP_PASSWORD` | str | empty | **live** | Its password (often an "app password"). Secret: write-only on the Settings page. |
| `MAIL_TEMPLATES_DIR` | str | empty | **live** | A folder with e-mail templates (`layout.html`, `code.html`, `code.txt`, ...) that replace the built-in ones of the same name (`src/sudoo/mail/templates/`). |

E-mails are HTML in the style of Odoo's own (a white card, the title on the left, the product name on the right,
a button and a footer), with a plain-text version for mail programs that show text only. Sign-in codes also say
when, from which address and which browser they were asked for. The code can be selected with one tap; Gmail's
apps also offer their own **Copy code** button.

### Gmail

1. On the Google account that will send the e-mails, turn on **2-Step Verification**
   (myaccount.google.com, Security).
2. Create an **app password**: myaccount.google.com/apppasswords, name it `Sudoo.sh`. Google shows 16 letters once.
3. In the panel, open **Settings**, then **E-mail**, and enter:

   | Field | Value |
   | :--- | :--- |
   | Mail server | `smtp.gmail.com` |
   | Port | `587` |
   | Encryption | STARTTLS |
   | User name | your Gmail address |
   | Password | the app password |
   | Sender | `Sudoo.sh <your.address@gmail.com>` |

   Click **Save**, then **Send a test** and enter an address to send the test e-mail to. The changes apply at
   once.

4. Or put the same values in `/opt/odoo/manager/.env`:

   ```
   MAILER=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls
   SMTP_USERNAME=your.address@gmail.com
   SMTP_PASSWORD=the16letterapppassword
   MAIL_FROM=Sudoo.sh <your.address@gmail.com>
   ```

   and apply and test them on the server:

   ```
   cd /opt/odoo/manager && docker compose up -d
   docker exec sudoo-panel sudoo.sh test-email you@example.com
   ```

Gmail sends from the signed-in address (or an alias added under Gmail's **Send mail as**), at most about 500
messages a day for a personal account. With Google Workspace on your own domain, use the domain's address. When
the test fails, the message shows the mail server's answer; for Gmail the password must be an app password, not
the account's password.

### Your website's mailbox

The same fields on the Settings page, or in `.env`:

```
MAIL_FROM=Sudoo.sh <no-reply@your-site.com>
SMTP_HOST=mail.your-site.com
SMTP_USERNAME=no-reply@your-site.com
SMTP_PASSWORD=...
```

---

## Limits

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `RATE_LIMITER` | str | `memory` | **restart** | Where request counts are kept: `memory`. |
| `RATE_LIMIT_READS_PER_MINUTE` | int | `600` | **live** | Requests that read, per minute, per signed-in user or API token (per address before signing in); 0: no limit. |
| `RATE_LIMIT_CHANGES_PER_MINUTE` | int | `60` | **live** | Requests that change something, per minute, counted the same way; 0: no limit. |
| `MAX_INSTANCES` | int | `0` | **live** | Instances on this server at most; 0: no limit. |
| `MAX_INSTANCES_PER_USER` | int | `0` | **live** | Instances one person or API token may have created and not yet deleted; 0: no limit. |
| `CREATE_COOLDOWN_MINUTES` | float | `0` | **live** | Minutes one person or token must wait between two creations, for example `60`; 0: no wait. |

Answers over a request limit are `429 Too Many Requests` with `Retry-After`; every limited answer carries
`RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`.

---

## Ports

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `PANEL_PORT` | int | `9000` | `.env` only | Port of the panel: the web app (container `sudoo-web`) listens here. |
| `API_PORT` | int | `9002` | `.env` only | Port of the backend (container `sudoo-panel`), on 127.0.0.1 only; the web app forwards `/api`, `/hooks` and `/docs` to it. |
| `EVENTS_PORT` | int | `9001` | `.env` only | Port of the live event stream (`/api/v1/events`), on 127.0.0.1 only. |
| `GATEWAY_PORT_START` | int | `8069` | `.env` only | First gateway port (one per instance). |
| `ODOO_PORT_START` | int | `28069` | `.env` only | First Odoo port (one per instance, 127.0.0.1 only). |

---

## Behaviour

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `IDLE_HOURS` | float | `6` | **live** | Pause an instance after this many hours without visits; 0: never. |
| `AUTO_PAUSE` | bool | `true` | **live** | New instances pause when idle (each instance can change it). |
| `AUTO_UPDATE` | bool | `true` | **live** | New instances get new code from their branch automatically. |
| `AUTO_UPGRADE` | bool | `true` | **live** | New instances upgrade changed modules after an update. |
| `DELETE_AFTER_DAYS` | int | `30` | **live** | Lifetime offered for new instances, in days; 0: keep. |
| `METRICS_INTERVAL_SECONDS` | float | `5` | **live** | Seconds between two measurements of the server and the instances (2 to 60). One hour of figures is kept. |
| `DAILY_BACKUPS` | bool | `true` | **live** | Once a day, back up every instance that was used since its last daily backup. Each instance keeps only its latest daily backup; they are removed when the instance is deleted. |
| `DAILY_BACKUP_TIME` | text | `00:00` | **live** | When the daily backups run, `HH:MM` on a 24-hour clock, in `TIMEZONE`. |
| `TIMEZONE` | text | `UTC` | **live** | Time zone of `DAILY_BACKUP_TIME` and of the times in backup names shown in the panel, for example `Africa/Cairo`. |

---

## Marketplace

How the panel talks to the Sudoo.sh hub, which lists plugins, sells paid ones and signs every package. See
[Marketplace](MARKETPLACE.md).

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `MARKETPLACE` | bool | `on` | **live** | `on`: register with the hub, send a signed heartbeat every 6 hours (version, core hash, installed plugins) and install plugins from the Plugins page. `off`: the panel never contacts the hub; installed free plugins keep working, paid ones stop when the last lease ends (7 days). |
| `HUB_URL` | text | `https://hub.sudoo.sh` | `.env` only | The hub's address: `https://` (`http://` only for `localhost` while testing). The panel registers with each hub it is pointed at and pins that hub's keys the first time. |

---

## Locations

| Setting | Type | Default | Applies | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `ODOO_ROOT` | Path | `/opt/odoo` | `.env` only | Folder that holds instances, backups and panel data. |
| `DOCS_DIR` | Path | `/app/documentation` | `.env` only | README.md and docs/ shown in the panel. |
| `MEMORY_DIR` | Path | `/dev/shm` | `.env` only | Memory-backed folder for secrets needed briefly as files. |
