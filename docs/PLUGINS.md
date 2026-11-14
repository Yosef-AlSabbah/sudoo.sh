# Plugins

**Audience:** administrators choosing how the panel works on their server, and developers extending it.
**Covers:** the plugin types, the built-in plugins and their settings, and how to write and install your own.

---

## Contents

1. [Why plugins](#1-why-plugins)
2. [How it works](#2-how-it-works)
3. [Exposure: how instances are reached](#3-exposure-how-instances-are-reached)
4. [Add-on sources: where Enterprise comes from](#4-add-on-sources-where-enterprise-comes-from)
5. [Update triggers: what starts a code update](#5-update-triggers-what-starts-a-code-update)
6. [Writing a plugin](#6-writing-a-plugin)
7. [Rules for plugins](#7-rules-for-plugins)
8. [More plugin types](#8-more-plugin-types)
9. [Plugins from the marketplace](#9-plugins-from-the-marketplace)

---

## 1. Why plugins

Servers differ. One server accepts no incoming connection and needs a tunnel; another has a public address and can
simply open ports; a third sits behind the company's reverse proxy. Some teams keep Odoo Enterprise in a folder,
others in a git repository with one branch per version, others do not use Enterprise at all.

Instead of building one of these into the panel, each is a **plugin** chosen by a setting. The panel's core does
not know which one runs: it calls a small, typed interface, and the plugin does the work. Changing how instances are
reached is a change of one line in `.env`, and new ways can be added without touching the panel's code.

---

## 2. How it works

Plugins use **Python entry points**, the standard mechanism also used by pytest, Flask and Sphinx extensions. A
package declares in its `pyproject.toml` which classes it provides, under a group name:

```toml
[project.entry-points."sudoo.exposure"]
cloudflare-quick = "sudoo.exposure.cloudflare:CloudflareQuickTunnel"
host-ports = "sudoo.exposure.ports:HostPorts"
```

A setting names the plugin (`EXPOSURE=host-ports`). When the panel starts, `plugins.py` finds the class registered
under that name, creates it **once** with the panel's settings (dependency injection: plugins never read the
environment themselves), and every part of the panel uses that object.

| Plugin type | Entry-point group | Setting | Interface | Built-in plugins |
| :--- | :--- | :--- | :--- | :--- |
| Exposure | `sudoo.exposure` | `EXPOSURE` | `exposure/base.py`: `Exposure` | `cloudflare-quick`, `host-ports` |
| Add-on source | `sudoo.addon_sources` | `ENTERPRISE_SOURCE` | `addons/base.py`: `AddonSource` | `folder`, `git` (and `none`) |
| Update trigger | `sudoo.update_triggers` | `UPDATE_TRIGGERS` (a list) | `triggers/base.py`: `UpdateTrigger` | `polling`, `github-webhook` |
| Storage | `sudoo.storage` | `STORAGE` | `storage/base.py`: `Storage` | `sqlite` |
| Authenticator | `sudoo.auth` | `AUTH` | `auth/base.py`: `Authenticator` | `local` |
| Second factor | `sudoo.second_factors` | `SECOND_FACTORS` (a list) | `auth/base.py`: `SecondFactor` | `email`, `totp` |
| Mailer | `sudoo.mailers` | `MAILER` | `mail/base.py`: `Mailer` | `smtp`, `none` |
| Rate limiter | `sudoo.rate_limiters` | `RATE_LIMITER` | `limits/base.py`: `RateLimiter` | `memory` |

See which plugins are installed and which are in use:

```bash
docker exec sudoo-panel sudoo.sh config
```

A setting that names a plugin that is not installed stops the panel at start-up with the list of installed ones.

Plugins can also come from the **Sudoo.sh marketplace**, installed from the panel's **Plugins** page without touching
the server: see [Plugins from the marketplace](#9-plugins-from-the-marketplace).

**Changing a plugin.** Plugins are created when the panel starts, so a new choice takes effect after a restart of the
panel:

| Setting | Where to change it |
| :--- | :--- |
| `ENTERPRISE_SOURCE`, `UPDATE_TRIGGERS`, `AUTH`, `SECOND_FACTORS`, `MAILER`, `RATE_LIMITER` | On the **Settings** page (super admins), section **Plugins**, then **Restart the panel**; or in `.env`. The page marks a changed setting until the restart. The restart stops only the backend for a few seconds (the web app, the connectors and the instances keep running) and is refused while jobs run. |
| `EXPOSURE`, `STORAGE` | In `.env` only, then `cd /opt/odoo/manager && docker compose up -d`: the web service and the containers depend on them too. |

The settings of a plugin (for example `ENTERPRISE_PATH`, `POLL_MINUTES`, `SMTP_HOST`) mostly apply at once when
changed on the Settings page; [Configuration](CONFIGURATION.md) says which.

---

## 3. Exposure: how instances are reached

The panel and each instance's gateway listen on a local port. The exposure plugin makes those ports reachable and
says what the public address is.

### `cloudflare-quick` (default)

A free Cloudflare quick tunnel per instance and one for the panel. No open port, no account, no domain; https
included. Addresses look like `https://<words>.trycloudflare.com` and change when the server restarts. See
[Tunneling](concepts/TUNNELING.md).

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `CLOUDFLARED_IMAGE` | `cloudflare/cloudflared:latest` | The connector image |
| `CONNECTOR_PREFIX` | `sudoo-connector-` | Container name prefix of the connectors |
| `CONNECTOR_STATUS_PORT_START` | `20300` | First status port; each instance gets one (`CONNECTOR_METRICS_PORT` in its `.env`) |
| `PANEL_CONNECTOR_STATUS_PORT` | `20242` | Status port of the panel's connector |

### `host-ports`

Visitors connect straight to the server: the panel on `PANEL_PORT`, each instance on its `GATEWAY_PORT`, on every
network interface. Addresses never change. For servers with a public address, or on an office network.

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `PUBLIC_HOST` | (required) | The server's public name or address, for example `demo.example.com` |
| `PUBLIC_SCHEME` | `http` | `https` only when a TLS proxy in front of the server handles https on those ports |

```
EXPOSURE=host-ports
PUBLIC_HOST=demo.example.com
```

Then open the ports in the firewall: `PANEL_PORT` (9000) and the gateway range from `GATEWAY_PORT_START` (8069). With
`PUBLIC_SCHEME=http` passwords travel unencrypted: use it only on networks you trust.

---

## 4. Add-on sources: where Enterprise comes from

The add-on source provides the Odoo Enterprise add-ons of a version. The **Edition** field in the panel offers
Enterprise for exactly the versions the source can provide. `ENTERPRISE_SOURCE=none` turns Enterprise off.

### `folder` (default)

The add-ons are already on the server, in a folder per version. `ENTERPRISE_PATH` gives the place, with `{version}`
(for example `19.0`) and `{major}` (`19`) replaced, so any existing naming works:

| `ENTERPRISE_PATH` | Folder for Odoo 19 |
| :--- | :--- |
| `/opt/odoo/enterprise/{version}` (default) | `/opt/odoo/enterprise/19.0` |
| `/data/odoo-enterprise-{major}` | `/data/odoo-enterprise-19` |
| `/srv/ent/v{major}/addons` | `/srv/ent/v19/addons` |

A version counts as available when its folder contains the module named by `ENTERPRISE_MARKER` (`web_enterprise`).
The folder must be readable by the Odoo containers (`chmod -R a+rX <folder>`).

### `git`

The add-ons come from a git repository with one branch per Odoo version; the panel downloads the branch when an
Enterprise instance of that version is created (latest commit only) and refreshes it the next time.

| Setting | Example | Meaning |
| :--- | :--- | :--- |
| `ENTERPRISE_GIT_URL` | `git@github.com:my-company/odoo-enterprise.git` | The repository |
| `ENTERPRISE_GIT_BRANCH` | `{version}` or `enterprise-{major}` | Branch name of a version |

Use a private repository you control, and give the server read-only access with a deploy key (**GitHub access** in
the panel). Downloads are kept in `<ODOO_ROOT>/enterprise-git/<version>`.

---

## 5. Update triggers: what starts a code update

An update trigger notices new code and asks the panel to update the instances concerned. The panel itself still
decides: an instance is only updated when its **Update automatically** switch is on and it is not busy. Several
triggers can work together, for example `UPDATE_TRIGGERS=github-webhook,polling` (the webhook for speed, polling as
a safety net).

| Trigger | How it notices | Delay after a push | Needs |
| :--- | :--- | :--- | :--- |
| `polling` (default) | Asks GitHub every `POLL_MINUTES` whether each instance's branch has new commits | up to `POLL_MINUTES` (2) | nothing; works behind changing tunnel addresses |
| `github-webhook` | GitHub calls `<panel address>/hooks/github` on every push | seconds | a panel address that does not change, and `GITHUB_WEBHOOK_SECRET` |

### `github-webhook`

1. Generate a secret, for example `openssl rand -hex 32`, and set it on the server:

   ```
   UPDATE_TRIGGERS=github-webhook,polling
   GITHUB_WEBHOOK_SECRET=<the secret>
   ```

   Both can also be set on the panel's **Settings** page; the new trigger starts after **Restart the panel**.

2. On GitHub, in each repository: **Settings, Webhooks, Add webhook**:

   | Field | Value |
   | :--- | :--- |
   | Payload URL | `<panel address>/hooks/github` |
   | Content type | `application/json` |
   | Secret | the same secret |
   | Events | Just the push event |

GitHub then sends a test call (a "ping"), and the panel answers it. Every call is checked with GitHub's signature
(`X-Hub-Signature-256`, an HMAC-SHA256 of the body made with the secret): a call without the right signature is
refused, so only GitHub can trigger updates. A push updates every instance that follows the pushed repository and
branch.

With `EXPOSURE=cloudflare-quick` the panel's address changes when the server restarts, so the webhook address would
have to be edited on GitHub each time: use it with `host-ports` or with your own domain.

---

## 6. Writing a plugin

A plugin is a class that implements one of the interfaces and is registered under the group's entry point. Here is
a complete exposure plugin that gives every instance an address on a wildcard domain served by a reverse proxy you
already run (Traefik, Caddy, nginx):

```python
# my_exposure/wildcard.py
from sudoo.config import Settings
from sudoo.exposure.base import Target


class WildcardDomain:
    """https://<instance>.<domain>; the reverse proxy forwards each name to the instance's gateway port."""

    listen_host = "127.0.0.1"   # the proxy runs on the same server
    https = True
    client_ip_header = None     # or the header your proxy sets with the visitor's address, e.g. "X-Real-IP"

    def __init__(self, settings: Settings) -> None:
        self.domain = "odoo.example.com"   # or read your own environment variable here

    def instance_ports(self) -> dict[str, int]:
        return {}

    def panel_env(self) -> dict[str, str]:
        return {}

    def ensure(self, target: Target) -> None:
        pass   # e.g. write a route file for the proxy: <target.name>.<domain> -> 127.0.0.1:<target.port>

    def remove(self, target: Target) -> None:
        pass   # delete that route

    def address(self, target: Target) -> str | None:
        name = "panel" if target.name == "panel" else target.name
        return f"https://{name}.{self.domain}"
```

```toml
# pyproject.toml of your package
[project]
name = "my-exposure"
version = "0.1.0"
dependencies = ["sudoo"]

[project.entry-points."sudoo.exposure"]
wildcard-domain = "my_exposure.wildcard:WildcardDomain"
```

Install it into the panel's environment, for example by adding it to `pyproject.toml` of the panel and running
`uv lock`, then set `EXPOSURE=wildcard-domain` and run `install.sh`.

`client_ip_header` names a request header that carries the visitor's real address and that only the service in
front can set (the built-in `cloudflare-quick` uses Cloudflare's `CF-Connecting-IP`; `host-ports` uses `None`). The
panel trusts it for sign-in lockout, rate limits and the audit log, so name a header only when visitors cannot
reach the panel without passing through that service, which replaces any value they send. An add-on source works the same way: implement
`available(version)` and `prepare(version, log)` from `addons/base.py` and register it under
`sudoo.addon_sources`. An update trigger implements `start(request_update)` and `blueprint()` from
`triggers/base.py` and is registered under `sudoo.update_triggers`; a webhook's endpoints are served under
`/hooks/` and must check their sender's signature themselves.

---

## 7. Rules for plugins

| Rule | Why |
| :--- | :--- |
| Take everything from the `Settings` object passed to the constructor. | One place for configuration; tests can create a plugin with any settings. |
| Refuse bad configuration in the constructor, with a sentence naming the setting (`raise ValueError(...)`). | The panel stops at start-up with a clear message instead of failing later. |
| `ensure()` must be safe to call again and again. | It runs when the panel starts, and after every restart of an instance. |
| Never restart something that would change an existing address without being asked. | People have shared those links. |
| Run commands as argument lists, never through a shell (`core/shell.py`). | Nothing typed by a user can become a command. |
| Add type hints; the project's mypy and tests must pass. | The interfaces are the contract between the panel and the plugin. |

---

## 8. More plugin types

Everything that one server may want differently is a plugin, written the same way as in
[Writing a plugin](#6-writing-a-plugin). The interfaces are short typed `Protocol` classes; read them for the
details.

### Storage: where the panel keeps its data

`storage/base.py`. Documents in named collections (`get`, `all`, `put`, `delete`, an atomic `change`) and the audit
log (`log`, `logs`). The built-in `sqlite` keeps everything in one file and needs no server. A `postgres` plugin
would implement the same methods, for example to keep the panel's data in a database that is already backed up.

### Authenticator: who may sign in

`auth/base.py`. `authenticate(username, password)` returns an `Identity` or `None`. Built in: `local`. A company
directory plugin, for example LDAP:

```python
class Ldap:
    manages_passwords = False   # passwords are changed in the directory, not in the panel

    def __init__(self, settings: Settings) -> None:
        self.server = "ldaps://ldap.example.com"

    def authenticate(self, username: str, password: str) -> Identity | None:
        if not ldap_bind(self.server, f"uid={username},ou=people,dc=example,dc=com", password):
            return None
        return Identity(username, role="admin" if username in ADMINS else "developer", email=f"{username}@example.com")
```

The first time someone signs in this way, the panel creates the account with that role (one of `super_admin`,
`admin`, `maintainer`, `developer`, `viewer`; `viewer` when none is given); second factors, sessions
and the audit log work as for local accounts.

### Second factors: proving it is really that person

`auth/base.py`, `SecondFactor`: `challenge` (send a code), `verify`, and `begin_setup` / `finish_setup` / `remove`
for the account page. Built in: `email` and `totp`. An SMS plugin works like `email` with a phone number; the
one-time codes helper (`auth/codes.py`: `new`, `check`, with expiry, tries and resend delay) does the hard part:

```python
class Sms:
    name, label, available = "sms", "Text message", True

    def challenge(self, username, account):
        code = codes.new((username, "sign-in"))
        sms_provider.send(account["phone"], f"Your Sudoo.sh code: {code}")
        return {"sent_to": account["phone"][-4:].rjust(10, "*")}

    def verify(self, username, account, code):
        return codes.check((username, "sign-in"), code)[0]
    ...
```

Register it under `sudoo.second_factors` and add it to `SECOND_FACTORS=email,totp,sms`.

### Mailer: how e-mail is sent

`mail/base.py`: `ready` and `send(to, subject, text, html)`. Built in: `smtp` (any mailbox, such as your website's
`no-reply@` address) and `none`. An e-mail service's HTTP API (SendGrid, Amazon SES, Postmark) fits the same
interface.

### Rate limiter: where request counts are kept

`limits/base.py`: `hit(key, limit, window_seconds)` returns a `Decision`. The built-in `memory` counts in the
panel's process, which is exact for one panel. Several panels behind one address would share counts through a
Redis plugin: the same method, with Redis's `INCR` and `EXPIRE`.

---

## 9. Plugins from the marketplace

Besides the built-in plugins and the ones you add to the panel's own package, a super admin can install plugins
from the Sudoo.sh marketplace on the **Plugins** page. The page, buying, licences and troubleshooting are described in
[Marketplace](MARKETPLACE.md); this section says how such a plugin fits the mechanism above.

| Step | What the panel does (`src/sudoo/plugin_manager.py`) |
| :--- | :--- |
| Download | A signed request to the hub; the package goes to a private folder |
| Verify | SHA-256 as stated by the hub, the hub's Ed25519 signature over id, version and SHA-256, with a pinned hub key |
| Check | `manifest.json` names the same plugin and version; `min_sudoo_version`, `max_sudoo_version`, `sdk_version` (the panel offers SDK 0.1.0) and `requires` fit; no Python dependencies, compiled files, links or unsafe paths |
| Unpack | `/opt/odoo/manager/plugins/<id>/<version>/package/` (root only); the package file is deleted |
| Register | The manifest's `entry_points` are written as a small `dist-info` folder next to the package, and both folders are added to the **end** of Python's path when the backend starts. `plugins.load(group, name, settings)` then finds the plugin exactly like a built-in one: an installed mailer named `sendgrid` is chosen with `MAILER=sendgrid` |
| Restart | The backend restarts by itself once no job runs; instances and links keep running |
| Keep honest | Every file is hashed at install; the hashes are checked at each start and every 10 minutes. A changed plugin is not loaded |

Rules for a marketplace plugin, on top of [Rules for plugins](#7-rules-for-plugins):

* **Standard library only, for now.** Packages that declare dependencies (`[project] dependencies` in
  `pyproject.toml`, or a `requirements*.txt` with entries) are refused, because this version of the panel has no
  dependency installer.
* **Python source only.** No `.so`, `.pyd`, `.pyc` or other compiled files.
* **Your own names.** Entry-point names must not be taken by another plugin of the same group, and top-level module
  names must not clash with the panel's (`sudoo`) or its libraries (`flask`, `cryptography`...). A storage plugin
  (`sudoo.storage`) cannot be installed from the marketplace.
* **Declare what you need.** The manifest's `permissions` are shown before installing and checked by the
  marketplace's reviewers.

The plugin SDK (`sudoo-plugin-sdk`) builds, checks and packs plugins in this format.
