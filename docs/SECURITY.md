# Security

**Audience:** administrators, and anyone reviewing the panel's security.
**Covers:** what is protected, against whom, how, and what is deliberately not protected.

---

## Contents

1. [What we protect, and from whom](#1-what-we-protect-and-from-whom)
2. [Reachability](#2-reachability)
3. [Panel passwords](#3-panel-passwords)
4. [Stored secrets: the vault](#4-stored-secrets-the-vault)
5. [Sessions and the browser](#5-sessions-and-the-browser)
6. [Checking every input](#6-checking-every-input)
7. [What is not protected](#7-what-is-not-protected)
8. [API tokens and webhooks](#8-api-tokens-and-webhooks)
9. [Roles and the audit log](#9-roles-and-the-audit-log)
10. [Marketplace plugins: keys, signatures, licences](#10-marketplace-plugins-keys-signatures-licences)
11. [Checklist for the administrator](#11-checklist-for-the-administrator)

---

## 1. What we protect, and from whom

| What | Why it matters |
| :--- | :--- |
| The panel | It controls Docker on the server: a super admin or administrator account can do anything on the server. |
| Panel passwords | People reuse passwords; a leaked one could open other doors. |
| GitHub deploy keys | They read the customers' private code. |
| The server | It runs every instance. |

| From whom | Typical attempt | Main defence |
| :--- | :--- | :--- |
| Anyone on the internet | Guessing passwords on the sign-in page, or taking over a new server before its owner | Slow hashes, sign-in lockout, strong generated passwords, no default accounts, a one-time setup code |
| A website the user visits | Making the user's browser send requests to the panel | Same-origin check, CSRF token, JSON-only, `SameSite=Strict` cookie |
| Somebody typing into a form | Text that becomes a command, a path or a script | Allow-list checks, no shell, escaping, Content-Security-Policy |
| A person with a smaller role | Doing what their role does not allow | A permission checked on the server for every request |
| Someone with a copy of the files (a backup, a copied folder) | Reading passwords and keys | Hashes and encryption with a key kept apart |

Examples of each attempt, and how the panel stops it, are in [Web attacks](concepts/WEB_ATTACKS.md).

---

## 2. Reachability

* The panel is two containers. The web service (`sudoo-web`, Caddy) serves the web app on `PANEL_PORT` and forwards
  `/api`, `/hooks` and `/docs` to the backend (`sudoo-panel`). The backend's API (`API_PORT`) and its live event
  stream (`EVENTS_PORT`) listen on `127.0.0.1` only, with every exposure: nothing reaches them except through the
  web service.
* With the default exposure plugin (`cloudflare-quick`), the web service, every gateway and every Odoo
  listen on `127.0.0.1` only. Nothing is reachable from the internet except through the Cloudflare connectors that
  the server opened itself, and SSH for administrators.
* With `host-ports`, the web service and the gateways listen on every interface, on purpose; Odoo itself and the
  databases still listen on `127.0.0.1` only. Use a firewall to limit who can reach the ports, and https in front of
  them on any network you do not fully trust (see [Plugins](PLUGINS.md#host-ports)).
* Cloudflare carries the traffic over https and decrypts it at its edge (that is how quick tunnels work); between
  Cloudflare and the server it travels inside the connector's own encrypted connection. See
  [Tunneling](concepts/TUNNELING.md#6-is-it-safe).
* The panel and every instance have different addresses (different browser origins), so an instance's pages can never read
  the panel's cookie. The gateway also removes the panel's cookie from requests to Odoo and stops Odoo from setting
  one with the same name.

### The visitor's address

Sign-in lockout, rate limits and the audit log count by the visitor's address, so it must not be something a
visitor can make up:

| Source | Trusted when |
| :--- | :--- |
| `CF-Connecting-IP` | Only with the `cloudflare-quick` exposure, where Cloudflare sets it (the exposure plugin's `client_ip_header`). With `host-ports` it is ignored. |
| `X-Forwarded-For` | Only when the request reaches the backend from `127.0.0.1`, that is from the web service, which replaces any value sent by the visitor with the address it received the request from. |
| The connection's own address | In every other case. |

---

## 3. Panel passwords

Passwords are **never stored**. The panel only needs to *check* a password, so it keeps a one-way **hash**:

```
stored = scrypt( HMAC-SHA256(pepper, password), salt )      salt: 16 random bytes per password
                                                             pepper: derived from vault.key
                                                             scrypt: N = 2^15, r = 8, p = 1 (32 MB, about 0.1 s)
```

| Measure | Effect |
| :--- | :--- |
| **scrypt** | Slow and memory-hungry on purpose: a stolen hash costs an attacker about 0.1 s and 32 MB per guess, so millions of guesses become impractical. |
| **Salt** | Two people with the same password have different hashes; precomputed tables are useless. |
| **Pepper** | A secret mixed in before hashing, taken from `vault.key`, which is not in the database (`sudoo.db`). A stolen database alone cannot even be attacked. |
| **Constant-time comparison** | Checking a password takes the same time whether it is almost right or completely wrong, and for unknown accounts too: timing reveals nothing. |
| **Generated passwords** | When an administrator chooses **Generate** for a new account or a new password, the panel makes 24 random characters (144 bits), shown once. They must be replaced at the first sign-in (see below). |
| **Passwords typed by an administrator** | Checked against the same rules as any chosen password. By default they must also be replaced at the first sign-in; the administrator can turn that off. |
| **Rules for chosen passwords** | Follow NIST SP 800-63B: length and a blocklist, no composition rules ([below](#password-rules)). Checked on the server and, as you type, in the browser. |
| **Sign-in by e-mail address** | People sign in with their e-mail address (or their user name). Each e-mail address belongs to one account at most. A wrong address and a wrong password give the same answer, "Wrong e-mail address or password.", and take as long: an unknown address still runs a full password check. |
| **Sign-in lockout** | 5 failures for an account from one address, or 20 from one address, block sign-in for 15 minutes. An e-mail address counts as its account, so switching between the address and the user name does not give more tries. |
| **Changing or resetting a password** | Ends every other session of that account. |
| **Upgrade on sign-in** | Hashes made before the pepper existed are replaced with the current kind the next time their owner signs in. |

Why a hash and not encryption is explained in [Passwords and encryption](concepts/PASSWORDS_AND_ENCRYPTION.md).

### Password rules

The rules follow NIST SP 800-63B (Digital Identity Guidelines, memorized secrets): a long password that is not on a
list of known ones protects better than forced mixes of characters, which lead to predictable patterns such as
`Password1!`. The same rules apply on the setup page, for new accounts, for passwords set by an administrator and
in **My account**, on the server and in the browser.

| Rule | Detail |
| :--- | :--- |
| Length | 12 to 128 characters. |
| Characters | Any printable character, spaces included. No control characters. |
| No composition rules | Capitals, digits and symbols are never required. Passwords never expire. |
| Blocklist | Refused when it contains a common password or word: `password`, `qwerty`, `admin`, `odoo`, `sudoo`, `welcome` and others. |
| Sequences | Refused when it contains five characters in a row of the alphabet, the digits or a keyboard row, in either direction (`abcde`, `12345`, `54321`, `qwerty`, `asdfg`, `zxcvb`). |
| Repeats | Refused when one character appears four times in a row. |
| Variety | At least 6 different characters. |
| Personal details | Refused when it contains the person's first name, last name, user name or the part of the e-mail address before `@`, each counted from 3 characters. |
| Paste and password managers | Allowed. |

The browser shows a strength meter of four bars (**Acceptable**, **Good**, **Strong**, **Very strong**); it only
guides, the server decides. The full list of rules for people is in the
[User manual](USER_MANUAL.md#password-rules).

### First-run setup

There are **no default accounts**: a new server has no account at all, so there is no known password to try.

* While no account exists, the panel makes a one-time **setup code** (three groups of four letters and digits, for
  example `K7QH-3MXP-9TAD`) and keeps it in `/opt/odoo/manager/setup_code`, mode 600 (root only). The installer
  prints it; `docker exec sudoo-panel sudoo.sh setup-code` shows it again.
* The **Set up Sudoo.sh** page (`POST /api/v1/setup`) creates the first account, a **Super admin**, only with that
  code, and signs in. It asks for an e-mail address (the user name is made from it) and a password that follows
  the [password rules](#password-rules). The code is compared in constant time and deleted once the account exists; after that the
  setup page refuses every request.
* Wrong codes are throttled: 5 from one address in 15 minutes block that address for 15 minutes, and each one is
  written to the audit log.
* Someone who reaches the address before you still needs the code, which only a person with root on the server can
  read.

### Generated passwords must be replaced

A password chosen by someone else (a new account, or a new password set by an administrator) is known to two
people. The account is therefore marked (always for a generated password; for a typed one unless the administrator
turned off **Ask them to choose their own password when they first sign in**): after signing in with it, the session is **restricted**. It opens only the session
and **My account** endpoints (`/api/v1/session`, `/api/v1/account`, `/api/v1/contact`); everything else answers
403 "Choose your own password first." until the person has chosen a new password. The same restriction, with "Set
up a second factor first.", applies when `REQUIRE_SECOND_FACTOR` requires a factor the account does not have yet.

### Second factors

A password can leak; a second factor means a leaked password alone does not open the panel.

| Factor | How it works |
| :--- | :--- |
| **Authenticator app** (`totp`) | The app and the panel share a secret (stored encrypted with the vault key) and both compute a 6-digit code every 30 seconds (RFC 6238). Each code works once; codes of the step before and after are accepted for clocks that are slightly off. |
| **E-mail code** (`email`) | A 6-digit code sent from the panel's mailbox (`SMTP_*`), valid 10 minutes, used once, kept only as a hash; 5 wrong tries use it up; a new one can be asked for once a minute. Setting it up confirms the address with a code. |

* After the password, the session only remembers who passed the first step, for 5 minutes; it opens nothing.
* Wrong codes count like wrong passwords (5 per account and address in 15 minutes, then blocked).
* `REQUIRE_SECOND_FACTOR` (`admins` by default) makes it compulsory: such an account without a factor can only set
  one up after signing in. Removing a factor needs the password and ends the account's other sessions.
* A lost phone: an administrator removes the account's factors (**Accounts**, or
  `DELETE /api/v1/users/<name>/second-factors`), which signs it out everywhere.
* More factors (SMS, hardware keys) can be added as plugins ([Plugins](PLUGINS.md#8-more-plugin-types)).

---

## 4. Stored secrets: the vault

Some secrets must be **read back** by the panel, so they cannot be hashed. They are **encrypted**:

| Secret | Stored as | Read when |
| :--- | :--- | :--- |
| GitHub deploy keys (`keys/deploy/*.key`) | AES-256-GCM, label `deploy-key:<owner>/<repo>` | For the length of one git connection, decrypted into a memory-only file readable by root, then deleted |
| Odoo master password of each instance (`MASTER_PASSWORD` in its `.env`) | AES-256-GCM, label `master-password:<name>` | When someone with the permission `instances.credentials` opens an instance's **Access** tab (and the audit log records it) |
| Secret settings changed in the panel (`smtp_password`, `odoo_admin_password`, `github_webhook_secret`) | AES-256-GCM in `/opt/odoo/manager/settings.json`, label `setting:<key>` | When the panel starts, and when a setting is changed |
| API tokens' signing secrets | AES-256-GCM | On every signed API call |

Backups (`/opt/odoo/backups`) contain whole databases, so they are mode 600 (root only), listed and downloaded only
with the permission `backups.manage` (super admins and administrators), and only by their file name from the
listing, never by a path. An instance's page lists its own backups to everyone who may see the instance, without
the download link.

Restoring a backup replaces an instance's database and files, so it has its own permission, `instances.restore`
(super admins, administrators and maintainers). A restore only takes a backup of that same instance, chosen by
file name from its own list, and first saves the current state as a `before-restore` backup: a restore by mistake
can be undone by restoring that one ([Administrator guide: Backups](ADMIN_GUIDE.md#10-backups)).

* **AES-256-GCM** is authenticated encryption: besides hiding the value, it detects any change to it. A modified
  value is refused, never decrypted into garbage.
* Every value is encrypted together with a **label** saying what it is. A value copied to another place (for
  example one repository's key renamed as another's) fails to decrypt.
* The key is `/opt/odoo/manager/vault.key`: 32 random bytes, created on first use, mode 600. It is kept apart from
  the data: a copy of the instance folders or of the deploy keys alone is useless. Back it up **separately**
  ([Administrator guide: Backups](ADMIN_GUIDE.md#10-backups)).
* Odoo itself receives only a **hash** of its master password in `odoo.conf` (Odoo's own `pbkdf2-sha512` format).
  Odoo can check it but nobody can read it from that file.
* The cookie-signing key (`secret_key`) and the vault key are generated on the server and never leave it.

### Settings changed in the panel

Super admins change almost every setting on the **Settings** page (`PATCH /api/v1/settings`, permission
`settings.manage`). The changes are kept in `/opt/odoo/manager/settings.json` (mode 600) on top of `.env`.

* The three secret settings (`SMTP_PASSWORD`, `ODOO_ADMIN_PASSWORD`, `GITHUB_WEBHOOK_SECRET`) are **write-only**: the
  page and the API only say whether they are set, never their value. In `settings.json` they are encrypted with the
  vault key; without `vault.key` they cannot be read back.
* Folders, ports, the exposure and the storage can only be set in `.env`, which only root on the server can edit.
* Every change is in the audit log with the names of the settings (secret values are not written there).

---

## 5. Sessions and the browser

| Measure | Effect |
| :--- | :--- |
| Signed session cookie `sudoo_session` | `HttpOnly` (scripts cannot read it), `Secure` (https only), `SameSite=Strict` (never sent with requests started by another site). |
| Session limits | Ends after 60 minutes without activity and after 12 hours in any case. |
| Session version | Each account has a version number in its record; a password change, reset or deletion raises it, and every older session stops working at once. |
| CSRF token | Every change must carry the session's secret token in a header, which another site cannot know. |
| Same-origin check | Every change must come from the panel's own address (`Origin` header). |
| JSON only | Every change must be sent as `application/json`; a form posted from another site cannot do that. |
| Content-Security-Policy | Set by the web service (`web/Caddyfile`) on the web app, and by the backend on its own answers: only the panel's own scripts and styles run; no inline scripts or styles, no outside resources, no framing. An injected `<script>` would not run. |
| Other headers | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, `Permissions-Policy` (no camera, microphone, location or payment); on API answers also `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store`, and `Strict-Transport-Security` when the exposure uses https. |
| Escaping | The web app is built with React, which inserts every value as text, never as HTML. The only HTML it shows is the documentation, rendered on the server from the project's own Markdown files. |
| One API | The web app uses only `/api/v1`, the same API as other systems, with the same checks. The pages and internal API of earlier versions are removed. |

---

## 6. Checking every input

Every value received from a browser or API client goes through `sudoo/web/validation.py` before it is used:

| Rule | Example of what is refused |
| :--- | :--- |
| The request body is a JSON object, at most 64 KB | A form post, a JSON list, a 1 MB body |
| Every field has the expected type | `"instance": "yes"` instead of `true`; a number where text is expected |
| Text is trimmed, limited in length, without control characters | A name of 500 characters; a NUL byte or a line break inside a branch name |
| Names, addresses and branches match an allow-list pattern | `https://evil.example/x` as a GitHub address; `../../etc` as a folder |
| Branch names cannot look like command options or path tricks | `--upload-pack=...`, `-rf`, `a..b`, `x.lock` |
| Choices must be one of the offered values | Odoo version `99.0`; role `superuser` |
| Instance and user names in addresses are checked before any file is touched | `/api/v1/instances/..%2F..%2Fetc` |

After checking, values are only passed to commands as **separate arguments, never through a shell**
(`core/shell.py`, `core/jobs.py`), and git commands put `--` before addresses, so nothing typed can become a command or an
option. Refused input gets HTTP 400 with a sentence saying what to enter instead.

---

## 7. What is not protected

Being clear about limits is part of security.

| Not protected | Why, and what to do |
| :--- | :--- |
| **Instance contents** | Every instance opens with `admin` / `admin` and anyone with its link can sign in. Instances must not hold real customer data. |
| **Someone with root on the server** | Root can read `vault.key` as well as the encrypted values, and controls Docker. The vault protects copies and backups, not a compromised server. Keep SSH access to the server limited. |
| **A super admin or administrator account** | The panel controls Docker, so these roles can do anything on the server. Give them only to people who would be trusted with the server. |
| **Plain http with `host-ports`** | With `PUBLIC_SCHEME=http`, passwords and session cookies travel unencrypted (the cookie is then not marked Secure). Put a TLS proxy in front, or keep it to trusted networks. |
| **Traffic inside Cloudflare** | Quick tunnels end https at Cloudflare's edge. For a server this is acceptable; Tailscale Funnel is the end-to-end alternative ([Tunneling](concepts/TUNNELING.md#7-other-ways-and-why-we-chose-this-one)). |
| **Each instance's database password** | Stored readable in the instance's `.env` and `odoo.conf` (folder mode 700, root only). The database is reachable only from that instance's Odoo container, on a private Docker network, so the password is of no use to anyone who could not already read the whole server. |
| **Sign-in lockout after a restart** | Failed attempts are counted in memory; a panel restart resets the counters. The slow hash still limits guessing. |
| **Odoo's own security** | Odoo inside an instance is the official image, unchanged; its own security is Odoo's. |
| **A plugin's files, from root** | Installed plugins are in `/opt/odoo/manager/plugins/` (root only, never served, no API returns them), but root on the server can read them. Their code is protected by the panel never exposing it and by the licence forbidding copies, not by encryption ([Marketplace plugins](#10-marketplace-plugins-keys-signatures-licences)). |
| **What a plugin does once loaded** | A plugin runs inside the panel's process with the panel's rights. The marketplace's review, the permissions it must declare and the hub's signature are the safeguards; install only the plugins you need. |

---

## 8. API tokens and webhooks

| Entry point | Who can use it | How it is checked |
| :--- | :--- | :--- |
| `/api/v1` (other systems) | holders of an API token **and** its signing secret | token (SHA-256 hash), HMAC-SHA256 signature over timestamp, nonce, method, path and body; timestamp within 5 minutes; each nonce accepted once; scope `write` acts as an Administrator, `read` as a Viewer; 5 refused calls from an address block it for 15 minutes |
| `/hooks/github` (when enabled) | GitHub | `X-Hub-Signature-256`: HMAC-SHA256 of the body with `GITHUB_WEBHOOK_SECRET` |

Every caller is also limited in requests per minute (`RATE_LIMIT_READS_PER_MINUTE`, `RATE_LIMIT_CHANGES_PER_MINUTE`,
per user, token or address), and instance creation can be limited in number and frequency (`MAX_INSTANCES`,
`MAX_INSTANCES_PER_USER`, `CREATE_COOLDOWN_MINUTES`); see [Configuration](CONFIGURATION.md#limits).

The signing secret is stored encrypted (vault), the token only as a hash; both are shown once. API tokens do not open the
panel's pages; the panel's session opens the API only from the panel's own address, with its CSRF token. Details: [Panel API](PANEL_API.md#6-security-notes).

---

## 9. Roles and the audit log

Every account has one of five roles. A role is only a named set of **permissions**, and every check on the server
asks for a permission, never for a role: each endpoint, and each action on an instance, names the permission it
needs ([Panel API](PANEL_API.md#3-endpoints)). Hiding a button in the web app is only a convenience; the server
refuses the call anyway, with 403 naming the missing permission, and the refusal is in the audit log.

| Permission | Allows | Super admin | Administrator | Maintainer | Developer | Viewer |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `instances.view` | See instances, their figures and activity | yes | yes | yes | yes | yes |
| `instances.logs` | Read Odoo's log and jobs' technical logs | yes | yes | yes | yes | yes |
| `instances.update` | Get new code, update submodules, restart, start, add submodules | yes | yes | yes | yes | |
| `instances.operate` | Pause, switch off, upgrade modules, switch branch, back up, remove submodules, change automation and lifetime | yes | yes | yes | | |
| `instances.create` | Create instances | yes | yes | yes | | |
| `instances.restore` | Restore an instance from a backup (replaces its database and files) | yes | yes | yes | | |
| `instances.delete` | Delete instances | yes | yes | | | |
| `instances.credentials` | See Odoo passwords and ports | yes | yes | yes | | |
| `backups.manage` | Download and delete backups | yes | yes | | | |
| `github.manage` | Manage deploy keys | yes | yes | yes | | |
| `accounts.manage` | Create, change and delete accounts | yes | yes | | | |
| `tokens.manage` | Create and revoke API tokens | yes | yes | | | |
| `audit.view` | Read the audit log | yes | yes | | | |
| `plugins.view` | See installed plugins, the marketplace and purchases | yes | yes | | | |
| `settings.manage` | Change the panel's settings, install and buy plugins, and restart it | yes | | | | |

* Only a **super admin** creates, changes, resets or deletes super admin accounts. The last super admin cannot be
  deleted or given another role, so there is always at least one.
* An administrator may edit their own account on the Accounts page, role included, but cannot delete it or set its
  password there (that needs the current password, in **My account**).
* Changing an account's role ends its sessions, your own included; the new permissions apply from the next sign-in.
* No two accounts share an e-mail address, so an address always signs in as exactly one account.
* **API tokens** have no account: a `write` token acts as an **Administrator**, a `read` token as a **Viewer**.
* Roles without `instances.credentials` never receive passwords, master passwords or ports, even in API answers.
* Accounts of earlier versions were renamed once, when the panel started: `admin` became Super admin, the sync
  operator became Developer.
* The audit log (in `/opt/odoo/manager/sudoo.db`, shown under **Audit log**) records sign-ins, failed sign-ins,
  lockouts, wrong setup codes, refused actions, every action on an instance, viewed credentials, settings changes,
  and account and key changes, with time, account, address and result. Passwords are never written to it.

---

## 10. Marketplace plugins: keys, signatures, licences

Plugins from the Sudoo.sh marketplace are checked by the panel itself before they run
([Marketplace](MARKETPLACE.md)).

| Key or value | Kind | Where it is kept | What it does |
| :--- | :--- | :--- | :--- |
| Installation key | Ed25519 private key, made on the server | The panel's database, encrypted with the vault key (label `hub-identity:<id>`) | Signs every request to the hub (method, path, installation id, time, single-use nonce, body hash), so the hub knows which panel asks and nobody can replay or alter a request |
| Hub keys | Ed25519 public keys | Pinned in the panel's database the first time the panel registers with a hub | Verify leases and plugin signatures; a key that was not pinned is refused (`sudoo.sh marketplace repin` pins again, on purpose only) |
| Lease | JWT signed by the hub (EdDSA only; `none` and HMAC algorithms are refused), for this installation, 7 days | The panel's database | Says which plugins may run and the licence dates of the paid ones; only verified claims are used |
| Package signature | Ed25519 over `sudoo-plugin-v1`, id, version and SHA-256 | Sent with the package | Binds a package to one plugin and one version; checked with a pinned key before anything is unpacked |
| Plugin file hashes | SHA-256 over every unpacked file | The plugin's record | Checked at every start and every 10 minutes; a changed plugin is not loaded and the super admins are e-mailed |

* Downloads use a signed request; a redirect to a storage link is followed only over https, without the signature.
* Packages with links, special files, absolute or `..` paths, compiled code, archive bombs or Python dependencies are
  refused; plugins are unpacked into `/opt/odoo/manager/plugins/` (folders 700, files 600) and the package file is
  deleted. The web container does not mount that folder.
* No endpoint returns a plugin's files or package. Purchase links and receipts reach the browser only when they are
  https.
* Paid plugins stop when the lease expires (7 days without a heartbeat that passed) or when the licence's grace ends.
  The panel never counts a time earlier than one it saw before or than the last lease's signed issue time, so
  turning the clock back does not extend a licence. When the hub reports an integrity violation or a suspension,
  every plugin is switched off.
* The heartbeat sends the version, the hash of the panel's Python files and the installed plugins; nothing about
  instances, accounts or their data. A purchase also sends the name and e-mail address of the super admin who
  pressed **Buy**, for the receipt. Card details never pass through the panel: cards are entered only on Stripe's
  pages.
* Each press of **Buy** carries a single-use idempotency key, so a retried request never charges twice.
* Root on the server can read plugin files and the vault key; see [What is not protected](#7-what-is-not-protected).

---

## 11. Checklist for the administrator

- [ ] Create the first account with the setup code right after installing, so nobody else can.
- [ ] Turn on a second factor for your own account; keep `REQUIRE_SECOND_FACTOR` at `admins` or `everyone`.
- [ ] Back up `vault.key` separately from other backups (without it, encrypted settings and keys cannot be read).
- [ ] Give the Super admin and Administrator roles only to people trusted with the server; give everyone else the
      smallest role that is enough (Viewer, Developer, Maintainer).
- [ ] Delete accounts of people who no longer need them; reset a password when in doubt.
- [ ] Look at the audit log from time to time for refused actions and failed sign-ins.
- [ ] Keep real customer data out of instances.
- [ ] Remove deploy keys of repositories that are no longer used, in the panel and on GitHub.
- [ ] Give each system its own API token, `read` where reading is enough; revoke tokens no longer used.
- [ ] With `host-ports`, put https in front of the panel and limit who can reach its port.
- [ ] Install only the plugins you need, preferably from Official or Verified publishers; read what each asks
      permission to do.
