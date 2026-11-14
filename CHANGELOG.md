# Changelog

All notable changes to this project are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Plugin store:** a new **Plugins** page (super admins install and buy; administrators can look) with the
  Sudoo.sh marketplace's catalogue (search, categories, Official and Verified publishers, prices), the installed
  plugins (versions, updates, licence dates, switch off and on, uninstall after a backup) and the receipts and
  purchases of this server, each with a CSV export. A free plugin installs with one click: the package is
  downloaded with a signed request, its SHA-256 and the hub's Ed25519 signature are checked, it is unpacked into a
  private folder and the backend restarts by itself. Paid plugins are bought with the account's saved card or
  through a Stripe page (each press carries its own idempotency key, so nothing is charged twice); their licences
  are followed offline (reminder 7 days before, grace period, backup and switch-off keeping the data, switch-on
  after a renewal). The panel registers with the hub, sends a signed heartbeat every 6 hours and keeps the signed
  lease; everything keeps working when the hub cannot be reached. New settings `MARKETPLACE` and `HUB_URL`,
  permission `plugins.view`, command `sudoo.sh marketplace`, and [Marketplace](docs/MARKETPLACE.md).

- **Daily backups:** once a day (`DAILY_BACKUP_TIME`, default 00:00, in `TIMEZONE`), every instance that was used
  since its last daily backup is backed up. Each instance keeps only its latest daily backup; they go when the
  instance is deleted. Settings: `DAILY_BACKUPS`, `DAILY_BACKUP_TIME`, `TIMEZONE` (Settings, Backups).
- **Restore from the instance's page:** a Backups card with "Back up now", "Restore the latest" (with its date) and
  every backup of the instance. A restore saves the current state first ("before a restore"), then replaces the
  database and the filestore and starts Odoo. New permission `instances.restore` (maintainers and up) and action
  `POST /api/v1/instances/<name>/actions/restore`.
- **Dashboard charts:** a one-hour line inside every figure card, and charts for what the cards do not show:
  requests and errors of all instances, instances by state, response time, and the instances using the most
  processor, memory or disk.
- **Passwords typed by an administrator:** new accounts and password resets can generate a password or take one typed
  by the administrator, checked live with a strength meter; optionally without asking the person to change it.
- **A new logo,** the same everywhere: Odoo's round "o" followed by a text cursor.

### Changed

- **The logo is redrawn:** a plum ring with a dot and a text cursor on a white tile (light plum on graphite in dark
  mode), in the app, favicon, status pages, e-mails and README; the README shows it with a blinking cursor. The
  repository moved to the Sudoo-sh organization and every link points there.
- **Sign in with the e-mail address.** Every account has a unique e-mail address; the user name is made from it and
  still works. First-run setup no longer asks for a user name.
- **Super admins can be edited,** including your own account; the last super admin stays one.
- **Stronger password rules** (NIST SP 800-63B): sequences such as 12345 or qwerty, repeated characters and the
  person's own name or address are refused, in the browser and on the server.
- **Menus open above the page,** so a list never cuts them off, and upwards near the bottom of the window.
- **The unsaved-changes bar on the Settings page follows the theme.**
- **The web app builds with Node.js 26, the current LTS release** (image, CI and `engines`). Dependabot proposes
  only LTS (even-numbered) Node majors.
- **The interface follows Apple's design and motion principles** ([docs/DESIGN.md](docs/DESIGN.md)):
  - the system font with size-specific tracking;
  - graphite neutrals with Odoo's plum as the single accent;
  - a translucent sidebar and top bar;
  - presses that answer at once; menus that grow from their trigger; dialogs that materialize in the centre;
  - a job drawer and toasts that leave the way they came; a sliding segmented control; quick cross-fades
    between pages;
  - themes that fade instead of flashing;
  - support for reduced motion, reduced transparency and higher contrast.
- **The live charts use Chart.js,** updated in place as each sample arrives.
- **Faster measurements:** every 5 seconds (`METRICS_INTERVAL_SECONDS`), from a continuous `docker stats` stream.
  Git details are read at most once a minute and right after a job.
- **No status badge:** a small "Reconnecting" notice appears only when the connection is lost.
- **Five roles** replace administrator and sync operator: super admin, administrator, maintainer, developer and
  viewer, each a set of named permissions checked on every request. Existing accounts are renamed automatically
  (administrator to super admin, sync operator to developer).
- **No default accounts:** the installer prints a one-time setup code, and the first visit creates your own
  account (name, e-mail, phone, password).
- **Generated passwords** (new accounts, resets) must be replaced at the first sign-in.
- **Almost every setting can be changed on the Settings page,** including the e-mail account:
  - secrets are stored encrypted;
  - settings that choose plugins apply after **Restart the panel**;
  - folders, ports, the exposure and the storage stay in `.env`.
- **The documentation is shown on the web app's Help pages,** from the same files as on GitHub.
- **The previous pages and the internal `/api/*` are removed;** everything uses `/api/v1`.

### Added

- **One-command install:** `curl -fsSL https://raw.githubusercontent.com/Sudoo-sh/sudoo.sh/main/get.sh | sudo bash`
  installs Docker if needed, downloads the latest release and runs the installer.
- **Account profiles** (first and last name, e-mail, phone), editable on My account and by administrators.
- **New endpoints:**
  - `GET/POST /api/v1/setup`, `GET /api/v1/roles`, `PATCH /api/v1/users/<name>`, `PATCH /api/v1/account`;
  - `GET /api/v1/docs` and `GET /api/v1/docs/<path>`;
  - `POST /api/v1/server/restart` and `POST /api/v1/settings/test-email`;
  - `sudoo.sh setup-code`.
- **Sign-in codes in e-mails** can be selected with one tap.
- **A design guide** (`docs/DESIGN.md`) explaining the tokens, type, materials and motion, and how to restyle
  Sudoo.sh.

### Renamed

- The project is now **Sudoo** (`sudo` + `Odoo`), the self-hosted counterpart of Odoo.sh: repository
  `sudoo.sh`, Python package and command `sudoo`, containers `sudoo-panel` and `sudoo-connector-<name>`,
  API tokens `sudoo_...`, signature headers `X-Sudoo-*`.
- New sudoo.sh logo (light and dark) and social preview in `docs/images/brand/`, shown at the top of the
  README; the remaining `odoo-sudoo` folder names in the README, CONTRIBUTING and the Administrator guide now say
  `sudoo.sh`.

### Added

- **A new web app** (`web/`): React, TypeScript and SCSS, built with Vite and served by Caddy as its own container
  (`sudoo-web`) on the panel's port, using only `/api/v1`. Every page is new:
  - sign-in with the second step (six-box code entry, e-mail resend);
  - instances with live status, resource figures, sparklines and job progress;
  - each instance with live charts for the last hour, activity with a live log, code, Odoo log, settings and
    credentials;
  - a guided **New instance** with repository checks, branch list, name preview and quota warnings;
  - **Settings** with save and reset, accounts, API tokens, backups, GitHub access, audit log, and **My account**
    with authenticator-app setup by QR code.

  It has light and dark themes, page transitions, and an accent colour from `BRAND_COLOR`. The backend moves to
  `127.0.0.1:API_PORT` (9002); the panel's link does not change.
- E-mails in HTML, in the style of Odoo's own (white card, title and product name, code box, button, footer), with
  a plain-text version. Sign-in codes say when, from which address and browser they were asked for. Templates can
  be replaced with `MAIL_TEMPLATES_DIR`; `BRAND_COLOR` sets the accent colour (also on the Settings page).
- `sudoo.sh test-email ADDRESS` checks the mail settings; Gmail setup in docs/CONFIGURATION.md.
- The pages, documentation and installer say **Sudoo.sh**; the command is `sudoo.sh` (`sudoo` still works).
- The panel's own data (accounts, API tokens, audit log, instance state) is kept in SQLite
  (`/opt/odoo/manager/sudoo.db`) through a storage plugin (`STORAGE`); the JSON files of earlier versions are moved
  in on the first start and kept as `*.migrated`.
- Second factors at sign-in: authenticator apps (`totp`) and e-mail codes sent from your own mailbox over SMTP
  (`email`, `SMTP_*`, `MAIL_FROM`). `REQUIRE_SECOND_FACTOR` (`none`, `admins` by default, `everyone`, also on the
  Settings page) makes one compulsory. New API: two-step `POST /api/v1/session`, `/api/v1/account` and its second
  factors, and `DELETE /api/v1/users/<name>/second-factors` for a lost phone.
- Plugin interfaces for sign-in (`sudoo.auth`, e.g. LDAP), second factors (`sudoo.second_factors`, e.g. SMS),
  e-mail (`sudoo.mailers`), storage (`sudoo.storage`) and rate limiting (`sudoo.rate_limiters`).
- Request limits per user, token or address (`RATE_LIMIT_READS_PER_MINUTE`, `RATE_LIMIT_CHANGES_PER_MINUTE`) with
  IETF `RateLimit-*` headers and `Retry-After`.
- Instance limits: `MAX_INSTANCES`, `MAX_INSTANCES_PER_USER` and `CREATE_COOLDOWN_MINUTES`, also on the Settings
  page; `GET /api/v1/instance-quota`; instances record who created them (`CREATED_BY`).
- `LICENSE.md` carries the copyright holder's Required Notice; the README explains commercial licences.
- Metrics for the server and every instance, with one hour of history: CPU and memory (as a share of the limit),
  requests per minute, error rate and response times (average and 95th percentile) measured by the gateway,
  uptime and disk use; `GET /api/v1/metrics`, `/metrics/history` and `/instances/<name>/metrics`, and in every
  `metrics` live event. Instances show them under `usage`.
- Jobs show their progress as a percentage (`progress_percent`) when the number of steps is known (creating,
  deleting, restarting and starting instances).
- One API for everything: every function of the panel is now in `/api/v1` (sessions, accounts, API tokens, backups,
  deploy keys, repository checks, job logs, instance credentials, server figures). The panel's web app can use it
  with its session cookie and CSRF token; other systems keep using tokens and signatures.
- Live events: `GET /api/v1/events` pushes every change (job progress and log, instance status, resource figures,
  settings) as Server-Sent Events, and resumes after a lost connection with what was missed.
- Settings page support: administrators change behaviour settings (pause, lifetime, polling, sessions, contact,
  versions) while the panel runs, through `GET/PATCH /api/v1/settings`; changes take effect at once and are kept on
  top of `.env`, and a reset brings back the `.env` value.
- `AUTO_PAUSE`, `AUTO_UPDATE` and `AUTO_UPGRADE` set the automation switches of new instances (all on, as before);
  the create request can set each one.
- `EVENTS_PORT` (9001): local port of the live event stream.
- The example client follows live events (`api.events()`).

- API answers follow common conventions: `{"data", "meta"}` envelopes, RFC 9457 problem details for errors
  (`application/problem+json`), `202 Accepted` with `Location` for background jobs, ISO 8601 times, pagination
  (`limit`, `offset`), `X-Request-ID` on every answer, and `links` on every resource.

- Plugins for what differs between servers, loaded through Python entry points and chosen in `.env`
  ([docs/PLUGINS.md](docs/PLUGINS.md)):
  - exposure: `cloudflare-quick` (as before) or `host-ports` (open ports, fixed addresses), set by `EXPOSURE`;
  - Enterprise add-on source: `folder` with any naming (`ENTERPRISE_PATH=/data/ent-{major}`), `git` with one branch
    per version, or `none`, set by `ENTERPRISE_SOURCE`.
- Any Odoo version: `ODOO_VERSIONS=auto` offers every published version from `ODOO_MIN_VERSION`.
- New settings for the Odoo and PostgreSQL images and all ports; full reference in
  [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
- `sudoo` command (replaces `manage.py`), with `config` to show the effective settings and plugins.
- Update triggers as plugins (`UPDATE_TRIGGERS`, several at once): `polling` (as before) and `github-webhook`
  (updates within seconds of a push, verified with GitHub's signature).
- API for other systems at `/api/v1`: list, read, create, change, run actions on and delete instances, follow jobs.
  Each request needs an API token and an HMAC-SHA256 signature (timestamp, nonce, method, path, body); read and
  write scopes; tokens managed under **API tokens** or with `sudoo create-token`
  ([docs/PANEL_API.md](docs/PANEL_API.md)). A reference client is in `examples/`.
- Test suite (pytest), pre-commit hooks (black, ruff, mypy, shellcheck, uv.lock) and CI running them on every pull
  request.

### Changed

- Dependencies are installed with uv from `uv.lock` instead of Alpine packages; the image is based on
  `python:3.12-alpine`.
- Settings are typed and checked at start-up (pydantic-settings): a wrong value stops the panel with a clear message.
- Code moved to a `src/` layout with subpackages (`core`, `instances`, `repos`, `exposure`, `addons`, `web`), type
  hints on every function, formatted with black.
- `ADMIN_CONTACT_NAME` defaults to "the administrator".

### Upgrading

Run `install.sh` as usual. It replaces the old `manager/` files, adds the new settings to `.env` with their
defaults and keeps your values. `ODOO_VERSIONS` keeps its current value; set it to `auto` to offer every version.
Use `sudoo` instead of `python3 manage.py` in commands.

### Fixed

- **Live container figures work with Docker 29:** the `docker stats` stream ends its lines with a terminal code
  that stopped the reader, so per-instance processor and memory figures were missing. A line it cannot read is now
  skipped instead of restarting the stream.

## [0.1.0] - 2026-11-11

### Added

- Web panel that runs many independent Odoo 18, 19 and 20 instances (Community and Enterprise) on one Docker server.
- Instance creation from a GitHub repository and branch, with generated names, databases, ports and passwords.
- One public https link per instance through Cloudflare quick tunnels, with no open incoming port.
- GitHub sync every 2 minutes, upgrading only changed modules; submodule update, add and remove.
- Read-only deploy keys per private repository, stored encrypted with AES-256-GCM.
- Auto-pause after 6 hours without visits, and wake-up on the next visit.
- Instance lifetime with automatic Odoo-format backups before any deletion.
- Administrator and sync operator roles, sign-in throttling and an audit log.
- Server and per-instance resource monitoring.
- Documentation in `docs/`, also shown inside the panel.
- Contributor files: contributing guide, security policy, code of conduct, issue and pull request templates, continuous integration and Dependabot.

[Unreleased]: https://github.com/Sudoo-sh/sudoo.sh/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Sudoo-sh/sudoo.sh/releases/tag/v0.1.0
