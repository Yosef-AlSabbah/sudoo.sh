# Panel API

**Audience:** developers connecting other systems to the panel: CI pipelines, chat bots, scripts, dashboards.
**Covers:** API tokens, how to sign a request, every endpoint and the permission it needs, settings, live events,
and a ready-to-use client.

This is the API of the **panel** (create, change, restart, delete instances). To talk to the **Odoo** inside an
instance, see [API and webhooks](API.md).

It is the panel's only API: the panel's own web app uses it too (the internal API of earlier versions is removed).
Two kinds of callers are accepted, with the same checks:

| Caller | Authentication |
| :--- | :--- |
| Another system (CI, bot, script) | An API token and a signature on every request ([1](#1-getting-a-token), [2](#2-signing-a-request)) |
| The panel's web app in a browser | The session cookie set by `POST /api/v1/session`, plus `X-CSRF-Token` on every change |

Every endpoint needs a **permission** (for example `instances.create`). A person's role gives a set of permissions
([Security: roles](SECURITY.md#9-roles-and-the-audit-log)); an API token acts as a role: a `write` token as an
**Administrator**, a `read` token as a **Viewer**.

---

## Contents

1. [Getting a token](#1-getting-a-token)
2. [Signing a request](#2-signing-a-request)
3. [Endpoints](#3-endpoints)
4. [Examples](#4-examples)
5. [Errors](#5-errors)
6. [Security notes](#6-security-notes)
7. [Settings](#7-settings)
8. [Live events](#8-live-events)
9. [Metrics](#9-metrics)
10. [Signing in from a web app](#10-signing-in-from-a-web-app)
11. [Limits](#11-limits)

---

## 1. Getting a token

Someone with the permission `tokens.manage` (super admins and administrators) creates tokens in the panel:
**API tokens** in the sidebar, then **Create token**, with a name saying what will use it and a scope:

| Scope | Acts as | Allows |
| :--- | :--- | :--- |
| `read` | Viewer | Read instances, their figures, activity and logs, jobs and versions. Every change is refused with 403. |
| `write` | Administrator | Everything an Administrator may do: create, change, run actions on and delete instances, read Odoo passwords, manage accounts, tokens, backups and deploy keys. Not the panel's settings. |

The panel shows two values **once**: the **token** (`sudoo_...`) and the **signing secret**. Store both where the other
system keeps secrets. A token can be revoked at any time on the same page; it stops working at once.

On the server, a token can also be created from the command line:

```bash
docker exec sudoo-panel sudoo.sh create-token "CI pipeline" write
```

---

## 2. Signing a request

Every request carries four headers:

| Header | Value |
| :--- | :--- |
| `Authorization` | `Bearer <token>` |
| `X-Sudoo-Timestamp` | the current time, Unix seconds, for example `1794430123` |
| `X-Sudoo-Nonce` | 16 to 64 random letters, digits, `-` or `_`; new for every request |
| `X-Sudoo-Signature` | `sha256=` and the hex HMAC-SHA256 of the text below, with the signing secret as the key |

The signed text is five lines joined with `\n` (no newline at the end):

```
<X-Sudoo-Timestamp>
<X-Sudoo-Nonce>
<METHOD in capitals>
<path, with ?query if there is one>
<hex SHA-256 of the exact request body; of an empty body when there is none>
```

For example, `GET /api/v1/instances` at `1794430123` with nonce `p4Xq9mW2...`:

```
1794430123
p4Xq9mW2...
GET
/api/v1/instances
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Requests with a body send it as JSON (`Content-Type: application/json`) and sign the exact bytes sent.

What each part protects against:

| Part | Stops |
| :--- | :--- |
| Token | Unknown callers. Revoking it ends access at once. |
| Signature over method, path and body | A request being changed on the way, and anyone who only has the token (from a log, a proxy, a screenshot) |
| Timestamp (within 5 minutes) | Old requests being sent again later |
| Nonce (each one accepted once) | The same request being sent twice within those 5 minutes |

---

## 3. Endpoints

All paths start with `/api/v1`, and every answer follows the same conventions:

| Convention | Detail |
| :--- | :--- |
| Success | `{"data": <resource or list>}`, and `"meta"` for lists |
| Background work | **202 Accepted**, the job in `data`, and a `Location` header pointing to it (`/api/v1/jobs/<id>`) |
| Errors | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details, `Content-Type: application/problem+json` (see [Errors](#5-errors)) |
| Times | ISO 8601 in UTC: `2026-11-12T08:30:00Z` |
| Request id | Every answer has `X-Request-ID`; send your own (8 to 64 letters, digits, `-`, `_`, `.`) to find a call in both logs |
| Links | Each resource has `links.self`, the path to read it again |
| Secrets | Never in a resource: no Odoo passwords, no master password, no ports. They are only in `GET /instances/<name>/credentials` (permission `instances.credentials`) |

The **Permission** column names what the caller needs. Without it the answer is 403, and `detail` says what the
role is missing. "public" means no sign-in; "signed in" means any account or token.

### Instances, jobs and versions

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /instances?limit=100&offset=0` | `instances.view` | | 200, a list of instances; `meta`: `total`, `count`, `limit` (1 to 500), `offset` |
| `GET /instances/<name>` | `instances.view` | | 200, the instance with `disk`, `recent_commits`, `submodules`, `backups`, `restorable_backup` and `recent_jobs` ([below](#instances-jobs-and-actions-in-detail)) |
| `GET /instances/<name>/credentials` | `instances.credentials` | | 200, Odoo `login`, `admin_password`, `master_password`, `ports`; written to the audit log |
| `GET /instances/<name>/logs?lines=300` | `instances.logs` | | 200, `{"text"}`: the end of Odoo's log (1 to 5000 lines) |
| `POST /instances` | `instances.create` | as below | **202**, the job; `Content-Location` names the new instance |
| `PATCH /instances/<name>` | `instances.operate` | any of `auto_update`, `auto_upgrade`, `auto_pause` (true or false), `delete_after_days` (0 keeps it) | 200, the instance |
| `POST /instances/<name>/actions/<action>` | depends on the action (below) | `{}`, or the action's fields | **202**, the job |
| `DELETE /instances/<name>` | `instances.delete` | `{"confirm": "<name>"}` | **202**, the job; a backup is taken first |
| `GET /instance-plan?repo=&branch=&name=` | `instances.create` | | 200, the name and database a new instance would get, and the defaults |
| `GET /instance-quota` | `instances.view` | | 200, how many instances the caller may still create, and when ([Limits](#11-limits)) |
| `GET /jobs?instance=&limit=30&offset=0` | `instances.view` | | 200, recent jobs, newest first |
| `GET /jobs/<id>` | `instances.view` | | 200, the job; `?include=log` adds its technical log when the caller also has `instances.logs` |
| `GET /jobs/<id>/log?offset=0` | `instances.logs` | | 200, `{"text"}` from that line on; `meta.next_offset` is where to continue |
| `GET /versions` | `instances.view` | | 200, `[{"version": "19.0", "enterprise": true}, ...]` |

### Server, metrics and settings

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /server` | `instances.view` | | 200, the panel's version and address, the plugins in use, the server's figures, the number of live-event clients |
| `POST /server/restart` | `settings.manage` | `{}` | **202** `{"restarting": true}`: the backend stops and Docker starts it again within seconds; the web app, the connectors and the instances keep running. **409** while jobs run |
| `GET /metrics` | `instances.view` | | 200, the latest figures of the server and every instance ([Metrics](#9-metrics)) |
| `GET /metrics/history?minutes=60` | `instances.view` | | 200, up to one hour of figures, in columns |
| `GET /instances/<name>/metrics?minutes=60` | `instances.view` | | 200, one instance's latest figures and history |
| `GET /settings` | `settings.manage` | | 200, every setting ([Settings](#7-settings)) |
| `PATCH /settings` | `settings.manage` | `{"idle_hours": 4}` | 200, the settings |
| `DELETE /settings/<key>` | `settings.manage` | | **204**, back to the `.env` value |
| `POST /settings/test-email` | `settings.manage` | `{"to": "you@example.com"}` | 200 `{"sent_to"}`; 400 when e-mail is not set up, 502 with the mail server's answer when sending fails |
| `GET /events` | signed in | | the live event stream ([Live events](#8-live-events)) |

### Accounts, roles and the audit log

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /roles` | signed in | | 200, `{"roles": [{"name", "label", "description", "permissions"}], "permissions": {"<name>": "<what it allows>"}}` |
| `GET /users` | `accounts.manage` | | 200, accounts (below) |
| `POST /users` | `accounts.manage` | `{"email", "role"}` required; optional `first_name`, `last_name`, `phone`, `name` (made from the e-mail address when absent), `password` (generated when absent), `must_change_password` (default `true`) | **201**, the account with its `password`, shown once |
| `PATCH /users/<name>` | `accounts.manage` | any of `role`, `first_name`, `last_name`, `email`, `phone` (`""` clears one); also for your own account | 200, the account; a new role ends its sessions |
| `POST /users/<name>/password` | `accounts.manage` | `{}` to generate one, or `{"password", "must_change_password"}` | 200, `{"password"}`, shown once; the account's sessions end |
| `DELETE /users/<name>/second-factors` | `accounts.manage` | | **204**: removes the account's second factors (a lost phone) and signs it out |
| `DELETE /users/<name>` | `accounts.manage` | | **204** |
| `GET /audit?limit=200&user=&instance=` | `audit.view` | | 200, the latest audit-log entries, newest first (`limit` 1 to 2000) |

`role` is one of `super_admin`, `admin`, `maintainer`, `developer`, `viewer`. Only a super admin creates, changes,
resets or deletes super admins (403 otherwise).

| Rule | Answer when broken |
| :--- | :--- |
| `email` is required for a new account | 400 "Enter the person's e-mail address: they sign in with it." |
| No two accounts share an e-mail address (compared without case) | 400 "Another account already uses this e-mail address." |
| A typed `password` follows the [password rules](USER_MANUAL.md#password-rules) | 400, `detail` names the rule, for example "The password contains a sequence such as 12345 or qwerty. Choose another one." |
| The last super admin stays a super admin and cannot be deleted | 400 "The last super admin must stay a super admin." or "The last super admin cannot be deleted." |
| Nobody deletes their own account or sets their own password here | 400; use `PUT /session/password` for your own password |

`PATCH /users/<name>` works on your own account too, including your role; a new role ends your sessions as well,
so you sign in again. `name` is the account's user name: 3 to 32 lower-case letters, digits, dots, dashes and
underscores, starting with a letter. When it is left out, it is made from the e-mail address
(`yousef.sabbah@example.com` gives `yousef.sabbah`, then `yousef.sabbah-2` when that is taken).

The password: without `password` one is generated and `must_change_password` is always `true`. With a typed
`password`, `must_change_password: false` lets the owner keep it. While `must_change_password` is `true` the
owner's session is restricted until they choose their own ([10](#10-signing-in-from-a-web-app)).

```
POST /api/v1/users  {"email": "sam@example.com", "role": "maintainer", "first_name": "Sam", "last_name": "Lee"}
  -> 201 {"data": {"name": "sam", "email": "sam@example.com", "must_change_password": true, ...,
                   "password": "generated-and-shown-once"}}

POST /api/v1/users/sam/password  {"password": "green tea at 7 on the balcony", "must_change_password": false}
  -> 200 {"data": {"password": "green tea at 7 on the balcony"}}
```

An account:

```json
{
  "name": "sam", "display_name": "Sam Lee",
  "first_name": "Sam", "last_name": "Lee", "email": "sam@example.com", "phone": null,
  "role": "maintainer", "role_label": "Maintainer",
  "last_sign_in_at": "2026-11-12T08:01:10Z", "password_changed_at": "2026-11-01T09:12:44Z",
  "must_change_password": false, "second_factors": ["totp"],
  "links": {"self": "/api/v1/users/sam"}
}
```

### API tokens, backups and GitHub

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /tokens` | `tokens.manage` | | 200, API tokens (never their secrets) |
| `POST /tokens` | `tokens.manage` | `{"name", "scope"}` (`read` or `write`) | **201**, with `token` and `signing_secret`, shown once |
| `DELETE /tokens/<id>` | `tokens.manage` | | **204**, revoked |
| `GET /backups` | `backups.manage` | | 200, backups, newest first (below) |
| `GET /backups/<file>` | `backups.manage` | | the zip (`dump.sql`, the filestore, `manifest.json`) |
| `DELETE /backups/<file>` | `backups.manage` | | **204** |
| `GET /deploy-keys` | `github.manage` | | 200, deploy keys |
| `POST /deploy-keys` | `github.manage` | `{"repo"}` | **201**, the public key and the GitHub page to add it on |
| `DELETE /deploy-keys/<owner>/<repo>` | `github.manage` | | **204** |
| `GET /repositories/branches?url=` | `instances.view` | | 200, `{"branches", "default"}` |
| `GET /repositories/access?url=&branch=` | `instances.view` | | 200, whether the server can read the repository and each submodule; `meta.can_manage_keys` |

A backup in `GET /backups` (`created` in Unix seconds, `size` in bytes):

```json
{"file": "sales-main__sales_main__20261112-000012__daily.zip", "instance": "sales-main", "db": "sales_main",
 "kind": "daily", "size": 48213504, "created": 1794441612.4}
```

`kind` is one of:

| `kind` | Taken | Kept |
| :--- | :--- | :--- |
| `manual` | The `backup` action (**Back up now**); also every file of earlier versions, which have no kind in their name | Until deleted |
| `daily` | Once a day for each instance used since its last daily backup | Only the latest per instance; removed with the instance |
| `deletion` | Before an instance is deleted | Until deleted |
| `before-restore` | At the start of a `restore` action | Only the latest per instance; removed with the instance |

To restore a backup into its instance, use the `restore` action ([below](#instances-jobs-and-actions-in-detail)).

### Plugins and the marketplace

What the **Plugins** page uses ([Marketplace](MARKETPLACE.md)). The panel talks to the hub itself, with its own
signed requests; callers of these endpoints never need a hub account or key. When the hub cannot be reached, the
`/marketplace/...` endpoints answer **503** with a sentence saying so, and the `/plugins` endpoints keep working. A
hub refusal is passed on as **409** (404 for something that does not exist) with the hub's reason in plain words,
for example that the panel must be linked first. With `MARKETPLACE=off` the `/marketplace/...` endpoints and
installing answer **409**.

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /plugins` | `plugins.view` | | 200, the installed plugins: `id`, `name`, `version`, `tier`, `publisher`, `permissions`, `requires`, `enabled`, `status` (`active`, `disabled`, `modified`, `blocked`, `switched_off`, `unlicensed`), `loaded`, `restart_pending`, `licence` (`state`, `standing`, `expires_at`, `grace_until`, `phase`: `active`, `expiring`, `grace`, `ended`, `no_lease`, `unlicensed`; null for free plugins), `latest_version`, `update_available`; `meta.restart_pending` |
| `GET /plugins/notices` | `plugins.view` | | 200, banners: `[{"plugin", "kind", "level", "text", "date"}]` for licences ending, in grace or ended, changed files, and the hub refusing the panel |
| `POST /plugins` | `settings.manage` | `{"id": "com.sudoo.smtp", "version": "1.2.0"}` (version optional: the newest) | **202**, the job (kind `plugin-install`); the backend restarts when it has finished. **409** while jobs run or when that version is installed |
| `POST /plugins/<id>/update` | `settings.manage` | `{}` | **202**, the job installing the newest version |
| `POST /plugins/<id>/disable` | `settings.manage` | `{}` | 200, the plugin; the backend restarts without it. **409** when another installed plugin needs it |
| `POST /plugins/<id>/enable` | `settings.manage` | `{}` | 200, the plugin; the backend restarts with it. **409** when its files were changed |
| `DELETE /plugins/<id>` | `settings.manage` | `{"confirm": "<id>"}` | **202**, the job: backs up the panel's data, removes the plugin, restarts |
| `GET /marketplace` | `plugins.view` | | 200, the connection: `enabled`, `hub_url`, `installation_id`, `registered`, `reachable`, `error`, `hub_status`, `linked` (`account_name`, `linked_at`), `last_heartbeat_at`, `next_heartbeat_at`, `lease_expires_at`, `lease_valid`, `lease_ending_soon` |
| `POST /marketplace/link` | `settings.manage` | `{"code": "<one-time code from app.sudoo.sh>"}` | 200, `{"account_name", "linked_at"}`; 404 for a wrong or used code |
| `POST /marketplace/heartbeat` | `settings.manage` | `{}` | 200, the connection after a heartbeat sent now |
| `GET /marketplace/catalog?q=&type=&tier=&installed=&sort=&limit=50&offset=0` | `plugins.view` | | 200, the hub's catalogue for this panel (`tier`: `free` or `paid`; `installed`: `true` or `false`; `sort`: `popular`, `rating`, `newest`, `name`, `trusted`). Each plugin has `publisher` (`verified`, `official`), `plans` (cheapest first), `latest_version`, `compatible_version` (the newest that runs on this panel), `installed_version`, `license` and `action`: `install`, `update`, `installed`, `buy`, `renew` (a licence that ended) or `incompatible` |
| `GET /marketplace/catalog/<id>` | `plugins.view` | | 200, the plugin's public page: `permissions`, screenshots, plans, `installed_version` |
| `GET /marketplace/categories` | `plugins.view` | | 200, `[{"type", "count"}]` |
| `GET /marketplace/billing` | `plugins.view` | | 200, whether this server may buy: `payments_enabled`, `linked`, `account_name`, `purchases_allowed` (the account owner allows purchases from this server), `monthly_limit_cents`, `spent_this_month_cents`, `remaining_cents`, `currency`, `card` (`brand`, `last4`, `exp_month`, `exp_year`, `expired`: the card a purchase charges; null: Stripe Checkout), `manage_url` |
| `POST /marketplace/purchases` | `settings.manage` | `{"plugin_id", "plan_id", "idempotency_key"}` | Buys for this server; the caller's name and e-mail go with the purchase and onto the receipt. `idempotency_key` (16 to 64 of `A-Za-z0-9_-`) is new for each press of Buy and the same when that request is retried: the hub answers the same purchase and never charges twice. **202** `{"purchase", "job"}` when the saved card was charged (`status` `succeeded`; the install job has started); 200 `{"purchase", "job": null}` otherwise, with `status` `checkout_required` (open `checkout_url`, https on Stripe), `processing`, `failed` or `expired` (`reason`) |
| `GET /marketplace/purchases/<id>` | `settings.manage` | | 200, the purchase; follow it until `succeeded` (then `POST /plugins`), `failed` or `expired` |
| `GET /marketplace/purchases` | `plugins.view` | | 200, purchases asked for from this server, newest first: `id`, `plugin_id`, `plugin_name`, `plan_kind`, `amount_cents`, `currency`, `status`, `method` (`saved_card` or `checkout`), `reason`, `receipt_number`, `requested_by` (`name`, `email`), `created_at`, `completed_at`; `?format=csv` answers a CSV file |
| `GET /marketplace/receipts` | `plugins.view` | | 200, receipts and credit notes of this server's plugins: `number`, `kind` (`receipt` or `credit_note`), `issued_at`, `plugin_name`, `plan_kind`, `payment_kind` (`purchase` or `renewal`), `total_cents`, `currency`, `requested_by_name`; `?format=csv` answers a CSV file |

No endpoint returns a plugin's files or its package.

### Documentation

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /docs` | `instances.view` | | 200, `{"index", "sections": [{"title", "pages": [{"path", "title"}]}]}`: the table of contents |
| `GET /docs/<path>` | `instances.view` | | 200, `{"path", "title", "html", "headings": [{"level", "id", "text"}]}`, for example `GET /docs/docs/PANEL_API.md` |

These are the same Markdown files as in the repository's `docs/`, rendered on the server. Links between pages point
to `/help/<path>`, the web app's Help pages.

### First run, session and own account (the web app)

| Method and path | Permission | Body | Answer |
| :--- | :--- | :--- | :--- |
| `GET /setup` | public | | 200, `{"needed", "contact"}`: whether the panel still has no account |
| `POST /setup` | public | `{"setup_code", "password", "first_name", "email"}` required; `last_name`, `phone`, `username` optional (made from `email` when absent) | **201**, signed in as the first account, a super admin ([10](#10-signing-in-from-a-web-app)) |
| `GET /contact` | public | | 200, who to contact |
| `POST /session` | public | `{"username", "password"}`; `username` is the e-mail address (up to 254 characters) or the user name | **201**, the session (as `GET /session`); sets the session cookie. Or **200** with `second_factor` when a code is needed. **401** "Wrong e-mail address or password." |
| `POST /session/second-factor` | public | `{"method", "code"}` | **201**, signed in |
| `POST /session/second-factor/<method>` | public | `{}` | 200, a new code was sent (`email`) |
| `GET /session` | signed in | | 200, the signed-in account (below) |
| `DELETE /session` | signed in | | **204**, signed out |
| `PUT /session/password` | signed in | `{"current", "new"}` | **204**; other sessions of the account end, and a `password` restriction is lifted |
| `GET /account` | signed in | | 200, own account: profile, role, second factors, whether one is required |
| `PATCH /account` | signed in | any of `first_name`, `last_name`, `email`, `phone` | 200, the account. The e-mail address cannot change while it receives sign-in codes |
| `POST /account/second-factors/<name>` | signed in | `email`: `{"email"}`; `totp`: `{}` | 200: a code was sent, or `{"secret", "otpauth_uri"}` for the app |
| `PUT /account/second-factors/<name>` | signed in | `{"code"}` | 200, the factors; it is set up |
| `DELETE /account/second-factors/<name>` | signed in | `{"password"}` | **204**; the account's other sessions end |

`GET /session`:

```json
{
  "data": {
    "user": "sam", "display_name": "Sam Lee",
    "first_name": "Sam", "last_name": "Lee", "email": "sam@example.com", "phone": null,
    "role": "maintainer", "role_label": "Maintainer",
    "permissions": ["github.manage", "instances.create", "instances.credentials", "instances.logs", "..."],
    "csrf_token": "...",
    "restricted": null,
    "must_set_up_second_factor": false,
    "brand_color": "#714B67"
  }
}
```

`permissions` is what the web app uses to show or hide buttons; the server checks again on every call.
`restricted` is `"password"` (choose your own password first), `"second_factor"` (set one up first) or `null`.
While it is set, only `/session`, `/account` and `/contact` answer; every other call is refused with 403.

### Instances, jobs and actions in detail

An instance:

```json
{
  "data": {
    "name": "sales-main",
    "status": "online",
    "url": "https://river-stone-apple.trycloudflare.com",
    "odoo": {"version": "19.0", "edition": "enterprise", "database": "sales_main"},
    "git": {
      "repository": "https://github.com/acme-co/sales",
      "branch": "main",
      "branch_deleted_on_github": false,
      "commit": {"sha": "4f2a9c1", "subject": "Add delivery report", "author": "Sam", "age": "2 hours ago"}
    },
    "settings": {"auto_update": true, "auto_upgrade": true, "auto_pause": true, "delete_after_days": 30},
    "usage": {
      "cpu_percent": 3.2, "memory_bytes": 905969664, "memory_limit_bytes": 3011510272, "memory_percent": 30.1,
      "requests_per_minute": 42.0, "error_rate_percent": 0.0, "response_ms_avg": 38.5, "response_ms_p95": 120.4,
      "uptime_seconds": 7260, "disk_bytes": 412090368
    },
    "created_at": "2026-11-11T10:16:47Z",
    "last_visit_at": "2026-11-12T08:01:10Z",
    "pauses_at": "2026-11-12T14:01:10Z",
    "expires_at": "2026-12-11T10:16:47Z",
    "current_job": null,
    "links": {"self": "/api/v1/instances/sales-main"}
  }
}
```

`GET /instances/<name>` adds, among others, the instance's backups, newest first, and the one the `restore` action
would use without a `file` (`null` when there is none):

```json
"backups": [
  {"file": "sales-main__sales_main__20261112-000012__daily.zip", "kind": "daily", "database": "sales_main",
   "size_bytes": 48213504, "created_at": "2026-11-12T00:00:12Z"},
  {"file": "sales-main__sales_main__20261110-153001__manual.zip", "kind": "manual", "database": "sales_main",
   "size_bytes": 47120384, "created_at": "2026-11-10T15:30:01Z"}
],
"restorable_backup": "sales-main__sales_main__20261112-000012__daily.zip"
```

`status` is one of `online`, `starting`, `busy` (a job is running), `paused`, `switched_off`, `stopped`, `unknown`.

A job (the answer to every 202, and to `GET /jobs/<id>`):

```json
{
  "data": {
    "id": "a12fff66a05d",
    "instance": "sales-main",
    "action": "Restart",
    "status": "running",
    "progress_percent": 50,
    "requested_by": "api:CI pipeline",
    "started_at": "2026-11-12T08:31:02Z",
    "finished_at": null,
    "steps": [{"title": "Restarting Odoo", "status": "running"}],
    "notes": [],
    "error": null,
    "links": {"self": "/api/v1/jobs/a12fff66a05d", "instance": "/api/v1/instances/sales-main"}
  }
}
```

`status` goes from `queued` to `running` to `success` or `failed`; when it failed, `error` explains why in plain words.
`progress_percent` is the share of steps done (below 100 until the job has finished), or `null` for jobs whose
number of steps is not known in advance.

Creating an instance takes the same fields as the **New instance** form:

```json
{
  "repo": "https://github.com/acme-co/sales",
  "branch": "main",
  "version": "19.0",
  "edition": "community",
  "name": "",
  "install_modules": true,
  "demo": false,
  "delete_after_days": 30
}
```

Actions (`POST /instances/<name>/actions/<action>`); each needs its own permission:

| Action | Does | Permission | Body |
| :--- | :--- | :--- | :--- |
| `update` | Get latest code | `instances.update` | `{}` |
| `update-submodules` | Update submodules | `instances.update` | `{}` |
| `restart` | Restart | `instances.update` | `{}` |
| `start` | Start a paused or switched-off instance | `instances.update` | `{}` |
| `add-submodule` | Add a submodule | `instances.update` | `{"url": "https://github.com/OCA/web", "path": "oca/web", "branch": "19.0"}` (`path` and `branch` optional) |
| `pause` | Pause | `instances.operate` | `{}` |
| `switch-off` | Switch off (stays off until started) | `instances.operate` | `{}` |
| `upgrade` | Upgrade modules | `instances.operate` | `{"modules": "sale_custom,stock_custom"}` or `{"modules": "all"}` |
| `remove-submodule` | Remove a submodule | `instances.operate` | `{"path": "oca/web"}` |
| `switch-branch` | Switch branch | `instances.operate` | `{"branch": "main"}` |
| `backup` | Back up now | `instances.operate` | `{}` |
| `restore` | Restore a backup: replaces the database and the filestore | `instances.restore` | `{}` for the latest, or `{"file": "<backup file name>"}` |
| `delete` | Delete, after a backup (same as `DELETE /instances/<name>`) | `instances.delete` | `{"confirm": "<name>"}` |

By role: a Developer may run the `instances.update` actions, a Maintainer every action except `delete`, a Super
admin or Administrator all of them.

`restore` without `file` puts back the newest `manual`, `daily` or `deletion` backup of a database the instance has
(`restorable_backup` in `GET /instances/<name>`). With `file`, it must be one of the instance's own `backups`. The
job (`"action": "Restore a backup"`) saves the current state as a `before-restore` backup, stops Odoo, replaces the
database and the filestore, sets the instance's public address again and starts Odoo. When there is no backup to
restore, or the backup is of a database the instance does not have, the job fails and `error` says so.

```
POST /api/v1/instances/sales-main/actions/restore  {"file": "sales-main__sales_main__20261110-153001__manual.zip"}
  -> 202 {"data": {"id": "c3d41e0b7a92", "action": "Restore a backup", "status": "queued", ...}}
```

---

## 4. Examples

**Python**: [`examples/panel_api_client.py`](../examples/panel_api_client.py) is a complete client using only the
standard library. Copy it into your project:

```python
from panel_api_client import PanelAPI

api = PanelAPI("https://panel.example.com", token="sudoo_...", signing_secret="...")
for instance in api.instances():                    # follows the pages of the list
    print(instance["name"], instance["status"], instance["url"])

job = api.action("sales-main", "update")           # waits until the update is finished
print(job["status"], job["error"])                  # success None, or failed and the reason

job = api.create(repo="https://github.com/acme-co/sales", branch="feature-x", version="19.0",
                 edition="community", install_modules=True, delete_after_days=7)
print(job["status"], job["instance"])
```

**Shell** (bash with openssl):

```bash
URL=https://panel.example.com TOKEN=sudoo_... SECRET=...
call() {  # call METHOD PATH [JSON]
  local body="${3:-}" ts nonce sig
  ts=$(date +%s); nonce=$(openssl rand -hex 16)
  sig=$(printf '%s\n%s\n%s\n%s\n%s' "$ts" "$nonce" "$1" "$2" "$(printf '%s' "$body" | sha256sum | cut -d' ' -f1)" \
        | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $NF}')
  curl -s -X "$1" "$URL$2" -H "Authorization: Bearer $TOKEN" -H "X-Sudoo-Timestamp: $ts" \
       -H "X-Sudoo-Nonce: $nonce" -H "X-Sudoo-Signature: sha256=$sig" \
       ${body:+-H "Content-Type: application/json" --data "$body"}
}
call GET /api/v1/instances
call POST /api/v1/instances/sales-main/actions/restart '{}'
```

**A CI pipeline** that gives every pull request its own instance: create an instance from the pull request's branch
with `delete_after_days: 7`, post its `url` as a comment, and delete it when the pull request is closed.

---

## 5. Errors

Errors follow [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) ("problem details"), with
`Content-Type: application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "detail": "Choose an Odoo version from the list.",
  "instance": "/api/v1/instances",
  "request_id": "5f0c9a3e2b8d4e7a9c1d0b6f3e2a1c4d"
}
```

`detail` says what is wrong and what to do; quote `request_id` when asking for help.

| Status | Meaning |
| :--- | :--- |
| 400 | A field is missing or not valid; `detail` says which and what to send |
| 401 | Token, timestamp, nonce or signature not accepted, the session has ended, or a wrong e-mail address or password at `POST /session`; `detail` says which |
| 403 | The caller's role lacks the permission; `detail` names what is missing, for example "Your role cannot do this (delete instances)." A `read` token sending a change, a restricted session, a wrong setup code, and a reached instance limit (`MAX_INSTANCES`, `MAX_INSTANCES_PER_USER`) are also 403, each with its own `detail` |
| 404 | No such instance, job, account, action or documentation page |
| 405 | The method is not allowed on this path |
| 409 | `POST /server/restart` while jobs are running |
| 415 | The body is not sent as JSON |
| 429 | Too many requests per minute, too many refused calls, wrong passwords or wrong setup codes from this address (5 in 15 minutes), or a creation within `CREATE_COOLDOWN_MINUTES`; `Retry-After` says how many seconds to wait |
| 500 | Something unexpected on the server; quote the `request_id` |
| 502 | `POST /settings/test-email`: the mail server refused the message; `detail` has its answer |
| 503 | An e-mail code could not be sent |

---

## 6. Security notes

* The token is stored only as a SHA-256 hash, and the signing secret encrypted with the vault key. Neither is ever
  shown again; a lost one means creating a new token.
* A `write` token acts as an Administrator: it can do everything an administrator can, including deleting instances,
  reading Odoo passwords and managing accounts (but not the panel's settings). A `read` token acts as a Viewer.
  Give each system its own token, with the `read` scope where reading is enough, and revoke tokens that are no
  longer used.
* Every call is in the audit log as `api:<token name>`, and every refused call with its reason and address.
* Resources never contain passwords (Odoo admin, master password) or the server's ports; only
  `GET /instances/<name>/credentials` returns them, to callers with `instances.credentials`, and each read is in the
  audit log.
* API tokens do not open the panel's pages. The browser's session opens the API only from the panel's own
  address, and every change also needs the session's CSRF token, so another website cannot use a visitor's session.

---

## 7. Settings

The settings in `.env` are the defaults. A super admin (permission `settings.manage`) can change almost all of them
while the panel runs, on the **Settings** page or through the API; the change is kept in
`/opt/odoo/manager/settings.json` on top of `.env`. Each setting says when a change takes effect, in `applies`:

| `applies` | When | Which |
| :--- | :--- | :--- |
| `now` | At once, without a restart | Almost every setting: limits, sessions, e-mail, daily backups (`daily_backups`, `daily_backup_time`, `timezone`), Odoo images and versions, Enterprise paths, contact, accent colour (marked **live** in [Configuration](CONFIGURATION.md)) |
| `restart` | After the panel restarts (`POST /api/v1/server/restart`, or **Restart the panel** on the Settings page) | The settings that choose plugins: `mailer`, `second_factors`, `update_triggers`, `enterprise_source`, `auth`, `rate_limiter` |
| `env` | Only in `.env`; the API refuses a change with 400 | Folders, ports, exposure, storage |

```json
GET /api/v1/settings
{
  "data": [
    {
      "key": "idle_hours", "env": "IDLE_HOURS",
      "value": 4, "env_value": 6, "changed_in_panel": true,
      "editable": true, "applies": "now", "pending_restart": false,
      "secret": false, "type": "number", "minimum": 0,
      "description": "Pause an instance after this many hours without visits; 0: never."
    },
    ...
  ]
}
```

`pending_restart` is `true` for a `restart` setting whose new value is not in use yet. `editable` is `true` for
`now` and `restart` settings.

| Request | Effect |
| :--- | :--- |
| `PATCH /api/v1/settings` `{"idle_hours": 4, "auto_pause": false}` | Change several at once; all are checked before any is kept |
| `PATCH /api/v1/settings` `{"idle_hours": null}` | Back to the `.env` value |
| `DELETE /api/v1/settings/idle_hours` | The same |
| `POST /api/v1/settings/test-email` `{"to": "you@example.com"}` | Send a test e-mail with the current mail settings |
| `POST /api/v1/server/restart` | Apply the `restart` settings; refused with 409 while jobs run |

A wrong value is refused with 400 and the setting's name (`IDLE_HOURS: Input should be greater than or equal to
0.`); a setting that can only be set in `.env` is refused with 400. Secrets (`smtp_password`,
`odoo_admin_password`, `github_webhook_secret`) are write-only: `value` and `env_value` only say whether they are
set, and they are stored encrypted with the vault key. Every change sends the `settings` [live event](#8-live-events).

---

## 8. Live events

`GET /api/v1/events` keeps the connection open and sends every change the moment it happens, as
[Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html), a standard every browser
reads with `EventSource`. Nothing needs to ask "anything new?" again and again: a job's progress, an instance going
online, new resource figures arrive by themselves.

```
id: 4182
event: job
data: {"key": "a12fff66a05d", "data": {"id": "a12fff66a05d", "status": "running", "steps": [...], ...}}

id: 4183
event: metrics
data: {"key": "", "data": {"server": {"cpu": 12.5, ...}, "instances": {"sales-main": {"cpu_percent": 3.1, ...}}}}
```

| Event | When | `data` |
| :--- | :--- | :--- |
| `instance` | An instance changed: status, code, address, settings, a job started or ended | The instance, as `GET /instances/<name>` |
| `instance.deleted` | An instance was deleted | `{"name"}` |
| `job` | A job started, moved to another step, added a note or ended | The job, as `GET /jobs/<id>` |
| `job.output` | New log text of a running job (at most twice a second) | `{"job", "offset", "text"}` |
| `metrics` | Every `METRICS_INTERVAL_SECONDS` (5 by default) | The new figures, as `GET /metrics` ([Metrics](#9-metrics)) |
| `settings` | A setting was changed | `{"changed": ["idle_hours", ...]}` |
| `reset` | After a reconnection, when more was missed than the panel keeps | `{}`: reload everything |

* `?topics=job,instance` sends only those events.
* A line starting with `:` is sent every 20 seconds to keep the connection open through proxies; ignore it.
* When the connection drops, `EventSource` reconnects by itself and sends the last `id` it received
  (`Last-Event-ID`); the stream starts with what was missed, only the latest state of each instance and job.
  Other clients can send `?last_event_id=` instead.

In a browser (the session cookie is sent by itself):

```js
const events = new EventSource("/api/v1/events?topics=job,instance");
events.addEventListener("job", (message) => {
  const { data: job } = JSON.parse(message.data);
  console.log(job.action, job.status);
});
```

From another system, sign `GET /api/v1/events` like any other request; the signature's 5-minute window applies to
opening the stream, which then stays open. With the [Python client](../examples/panel_api_client.py):

```python
for event in api.events(topics=["job"]):
    print(event["event"], event["data"]["status"])
```

---

## 9. Metrics

The panel measures the server and every instance every `METRICS_INTERVAL_SECONDS` (5 seconds by default, 2 to 60,
changeable on the Settings page) and keeps one hour of figures in memory (they start again empty when the panel
restarts). Container figures come from a continuous `docker stats` stream.

| Figure | Meaning |
| :--- | :--- |
| `cpu_percent` | Share of the whole server's processor (all cores); for an instance, Odoo and its database together |
| `memory_percent`, `memory_bytes`, `memory_limit_bytes` | Memory in use, of the containers' limit (the server's memory when they have none) |
| `requests_per_minute` | Requests the gateway forwarded to Odoo: pages, RPC and API calls (the background traffic of open tabs is left out) |
| `error_rate_percent` | Share of those requests answered with a 5xx error; `null` without requests |
| `response_ms_avg`, `response_ms_p95` | Time until Odoo started answering: average, and the time 95 % of requests stayed under |
| `uptime_seconds` | Since Odoo's container started; `null` when it is not running |
| `disk_bytes` | Database and files, measured every 5 minutes while running |
| Server only: `memory_*_bytes`, `disk_percent`, `disk_*_bytes`, `load_1m`, `cores`, `uptime_seconds`, `instances_running`, `instances_total` | `instances_running`: how many instances run now |

`GET /api/v1/metrics` returns the latest sample:

```json
{
  "data": {
    "at": 1794430123,
    "interval_seconds": 5,
    "server": {"cpu_percent": 12.5, "memory_percent": 61.2, "disk_percent": 48.0, "load_1m": 0.42, ...},
    "instances": {"sales-main": {"running": true, "cpu_percent": 3.2, "memory_percent": 30.1, ...}}
  }
}
```

`GET /api/v1/metrics/history?minutes=60` returns the history in **columns**, one list per figure, the shape chart
libraries draw from directly; `t` holds the times (Unix seconds):

```json
{
  "data": {
    "server": {"t": [1794426523, ...], "cpu_percent": [11.0, ...], "memory_percent": [...], "disk_percent": [...], "load_1m": [...],
               "instances_running": [3, ...]},
    "instances": {"sales-main": {"t": [...], "cpu_percent": [...], "memory_percent": [...], "requests_per_minute": [...], ...}}
  },
  "meta": {"minutes": 60, "interval_seconds": 5}
}
```

A dashboard loads the history once, then appends the sample of every `metrics` [live event](#8-live-events).

---

## 10. Signing in from a web app

On a new server there is no account yet. `GET /api/v1/setup` answers `{"needed": true}`, and the first account is
created with the setup code the installer printed (`docker exec sudoo-panel sudoo.sh setup-code` shows it again):

```
POST /api/v1/setup  {"setup_code": "K7QH-3MXP-9TAD", "password": "...",
                     "first_name": "Sam", "last_name": "Lee", "email": "sam@example.com", "phone": ""}
  -> 201 {"data": {"user": "sam", "role": "super_admin", "csrf_token": "...", ...}}    signed in
```

`email` and `first_name` are required. Without `username`, the user name is made from the e-mail address (here
`sam`); it is the account's key in `user` and in `/users/<name>`. The password follows the
[password rules](USER_MANUAL.md#password-rules). The code works once. A wrong one is 403; 5 wrong ones from an address in 15 minutes block it (429). Once an account
exists, `POST /api/v1/setup` is refused with 400.

The panel's own web app then signs in with a session cookie. Without a second factor it is one call; with one, two:

```
POST /api/v1/session            {"username": "sam@example.com", "password": "..."}
  -> 201 {"data": {"user": "sam", "csrf_token": "...", ...}}                 signed in
  -> 200 {"data": {"second_factor": {
            "methods": [{"name": "totp", "label": "Authenticator app"}, {"name": "email", "label": "E-mail code"}],
            "sent_to": "s***@example.com"}}}                                   a code is needed

POST /api/v1/session/second-factor/email          (only to send a new e-mail code)
POST /api/v1/session/second-factor  {"method": "totp", "code": "123456"}
  -> 201 {"data": {"user": "sam", "csrf_token": "...", ...}}
```

`username` takes the e-mail address or the user name. A wrong e-mail address and a wrong password give the same
**401** "Wrong e-mail address or password.", in the same time.

Between the two calls the session opens nothing, for 5 minutes at most.

A signed-in session can be **restricted** (`"restricted"` in the answer). Only `/api/v1/session`,
`/api/v1/account` and `/api/v1/contact` answer until the task is done:

| `restricted` | Why | Done with |
| :--- | :--- | :--- |
| `"password"` | The password was set by someone else (a new account, or `POST /users/<name>/password`) with `must_change_password` | `PUT /api/v1/session/password` `{"current", "new"}` |
| `"second_factor"` | `REQUIRE_SECOND_FACTOR` applies and the account has no second factor (`"must_set_up_second_factor": true`) | setting one up, as below |

Setting up an authenticator app:

```
POST /api/v1/account/second-factors/totp   {}      -> {"secret": "JBSW...", "otpauth_uri": "otpauth://totp/..."}
                                                       (show the URI as a QR code)
PUT  /api/v1/account/second-factors/totp   {"code": "123456"}
```

API tokens are not affected: a token already is something only its system has.

`GET /api/v1/session` returns the same document at any time; read `permissions` from it to decide which controls
to show.

---

## 11. Limits

**Requests per minute.** Every caller (signed-in user, API token, or address before signing in) may send
`RATE_LIMIT_READS_PER_MINUTE` reading requests (600) and `RATE_LIMIT_CHANGES_PER_MINUTE` changing ones (60). Answers
carry the standard fields:

```
RateLimit-Limit: 60
RateLimit-Remaining: 57
RateLimit-Reset: 41          seconds until the window has moved on
```

Over the limit: `429 Too Many Requests` and `Retry-After`. Well-behaved clients wait that long.

**Instances.** `MAX_INSTANCES` (server), `MAX_INSTANCES_PER_USER` and `CREATE_COOLDOWN_MINUTES` limit creation; all
are off (0) unless set, and can be changed on the Settings page. Before offering **New instance**, ask:

```json
GET /api/v1/instance-quota
{"data": {"instances": 4, "max_instances": 10, "own_instances": 2, "max_instances_per_user": 3,
          "cooldown_minutes": 60, "next_creation_at": 1794433723}}
```

`next_creation_at` (Unix time) is set while the caller has to wait. A creation that breaks a limit is refused with
403 (a number is reached) or 429 with `Retry-After` (wait).
