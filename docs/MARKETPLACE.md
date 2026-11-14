# Marketplace

**Audience:** super admins and administrators who add plugins to the panel, and administrators of the server.
**Covers:** the Plugins page, installing free and paid plugins, licences and what happens when one ends, linking
the panel to an account, how the panel talks to the hub, and what is and is not protected.

---

## Contents

1. [What the marketplace is](#1-what-the-marketplace-is)
2. [Who can do what](#2-who-can-do-what)
3. [The Plugins page](#3-the-plugins-page)
4. [Installing a free plugin](#4-installing-a-free-plugin)
5. [Buying a paid plugin](#5-buying-a-paid-plugin)
6. [Licences: reminders, grace period, switching off](#6-licences-reminders-grace-period-switching-off)
7. [Updating, switching off and uninstalling](#7-updating-switching-off-and-uninstalling)
8. [When the hub cannot be reached](#8-when-the-hub-cannot-be-reached)
9. [How the panel talks to the hub](#9-how-the-panel-talks-to-the-hub)
10. [How a package is checked](#10-how-a-package-is-checked)
11. [Where plugins are kept, and what is protected](#11-where-plugins-are-kept-and-what-is-protected)
12. [Settings and commands](#12-settings-and-commands)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What the marketplace is

The Sudoo.sh marketplace (marketplace.sudoo.sh) lists plugins that add features to the panel: other sign-in
methods, mailers, backup destinations, notifications and more. Its server, the **hub** (hub.sudoo.sh), keeps the
catalogue, sells paid plugins and **signs every package** after a person at Sudoo.sh has reviewed it. Your panel
installs plugins only from the hub, and only after checking that signature.

| Badge | Meaning |
| :--- | :--- |
| **Official** | Made by Sudoo.sh itself |
| **Verified** | Sudoo.sh checked who the publisher is (person or company) and that their support works |
| none | A registered developer whose identity is not confirmed yet; the plugin was still reviewed |

Free plugins need nothing but the panel. Paid plugins need the panel to be **linked** to an account on
app.sudoo.sh, which pays for them ([Buying a paid plugin](#5-buying-a-paid-plugin)).

---

## 2. Who can do what

| Role | Plugins page | Install, buy, update, switch off, uninstall, link |
| :--- | :--- | :--- |
| Super admin | yes | yes (permission `settings.manage`) |
| Administrator | yes, to look (permission `plugins.view`) | no |
| Maintainer, developer, viewer | no | no |

Uninstalling is a super admin's explicit action and always takes a backup of the panel's data first.

---

## 3. The Plugins page

Open **Plugins** in the sidebar (under Administration). It has three tabs:

| Tab | Shows |
| :--- | :--- |
| **Marketplace** | The catalogue: search, a category list, Free or Paid, and the order (official and verified first, most installed, best rated, newest, name). Each card shows the publisher and its badge, the price (the cheapest plan), the rating, how many panels run it, and whether it is installed, has an update, needs a newer Sudoo.sh, or its licence ended. Click a card for its details: what it asks permission to do, which other plugins it needs, its plans and price. |
| **Installed** | Each installed plugin with its version, whether a newer one exists (**Update to vX**), whether it runs, and for a paid plugin its licence: the date it ends and the date it stops. **Manage** switches it off or on, or uninstalls it. |
| **Purchases** | **Receipts**: every payment and renewal of this server's plugins (number, date, plugin, plan, who asked, total) and credit notes for refunds. **Purchases**: every purchase asked for from this server and how it ended (paid, waiting for payment, failed and why). Each list has **Export CSV** for your accounting; the full receipts (with tax and the invoice) are on app.sudoo.sh. |

When a licence ends soon, is in its grace period or has ended, or when a plugin's files were changed, a banner says
so at the top of every page for super admins and administrators.

---

## 4. Installing a free plugin

1. On **Marketplace**, open the plugin and choose **Install**.
2. A card follows the work: asking the hub, downloading, checking the signature, checking that it suits this
   panel, installing. Nothing else is asked of you.
3. The panel then restarts its backend by itself, which takes a few seconds; the web app, the links and every
   instance keep running. A message says when the plugin is ready.

Installing is refused while other jobs run (a restart would cut them off): wait until they finish. If a step fails,
the card says why in plain words; **Details** shows the technical log.

---

## 5. Buying a paid plugin

**Link the panel once.** Paid plugins belong to an account, which is billed and receives the e-mails about them.

1. On app.sudoo.sh, open **Servers** and choose **Link a server**. You get a one-time code, valid 15 minutes.
2. In the panel, open **Settings**, section **Marketplace** (or the plugin's details), paste the code and choose
   **Link**. The panel sends it to the hub signed with its own key, so the hub knows which panel it was typed into.

**Allow purchases.** On app.sudoo.sh, Servers, the account owner turns on *Allow purchases from this server* (off
by default) and may set a monthly limit. Until then the plugin's details show a link there instead of the buy
button.

**Buy.** Open the plugin, choose a plan (monthly, yearly or a fixed term) and **Buy & install**. The plugin's
details say which card will be charged, or that you will pay on Stripe's page, and how much is left of the monthly
limit.

* When the account has a saved card, the hub charges it and the plugin installs at once, as a free one does.
* Otherwise (or when the bank asks to confirm the payment) a Stripe payment page opens in a new tab. Pay there; the
  Plugins page checks every few seconds, and when you come back to its tab, and installs the plugin as soon as the
  payment arrives. If you close the plugin's details meanwhile, the licence is not lost: once paid, the plugin's
  button becomes **Install**.
* If the payment fails or the page expires (after 24 hours), the details say why; nothing is charged, and a new
  press starts a new purchase.

Pressing **Buy & install** twice, or a network error while buying, never charges twice: each press carries its own
key, and the hub answers the same purchase for the same key. The purchase records who pressed the button (name and
e-mail of your panel account), and the receipt shows it.

Subscriptions renew by themselves until they are cancelled on app.sudoo.sh. Uninstalling a plugin does not cancel
its subscription.

---

## 6. Licences: reminders, grace period, switching off

Each paid plugin has a licence for this server. Its dates come from the hub in every heartbeat, signed, and are kept
by the panel, so it knows them even while it cannot reach the hub.

| When | What happens |
| :--- | :--- |
| 7 days before the licence ends | A banner, and an e-mail to every super admin (through the panel's mailer, when e-mail is set up). The hub e-mails the account too. |
| The licence ends without renewal | The plugin keeps running during the grace period (7 days by default); a banner gives the date it stops. |
| The grace period ends | The panel backs up its own data (and every instance, when the plugin may change instances), **then switches the plugin off, keeping its data and settings**, restarts, and e-mails the super admins. If a backup failed, the e-mail says so; the plugin is switched off anyway. |
| The licence is renewed later | The next heartbeat brings the new dates; the plugin is switched back on by itself and the super admins are told. |

Nothing is deleted when a licence ends. Turning the server's clock back does not extend a licence: the panel never
counts a time earlier than one it has already seen, nor earlier than the last lease it received.

---

## 7. Updating, switching off and uninstalling

| Action | Where | What happens |
| :--- | :--- | :--- |
| Update | **Installed**, **Update to vX** | The new version is downloaded and checked like a new plugin, replaces the old one, and the panel restarts. |
| Switch off | **Manage**, **Switch off** | The plugin's files and data stay; the panel restarts without it. Refused while another installed plugin needs it. |
| Switch on | **Manage**, **Switch on** | The panel restarts with it. Not possible for a plugin whose files were changed: install it again. |
| Uninstall | **Manage**, **Uninstall**, then type the plugin's id | A backup of the panel's data first (`/opt/odoo/backups/panel/`), then its files and its record are removed and the panel restarts. Refused while another installed plugin needs it. |

---

## 8. When the hub cannot be reached

The panel keeps working without the hub:

* Instances, accounts, backups and every installed **free** plugin work as before.
* **Paid** plugins keep running until the lease the panel holds expires, **7 days** after the last heartbeat that
  passed, or until their licence's grace period ends, whichever comes first. Then they are switched off the same
  way as at the end of a licence, and switched on again by the next heartbeat that passes.
* The Plugins page says that the marketplace cannot be reached; the catalogue and the purchases cannot be shown,
  the Installed tab still can. The panel tries again every 15 minutes.

The hub can also **refuse** the panel: when its core files differ from the released version
(`integrity_violation`), or when the installation is suspended. Every plugin is then switched off, and a banner
says why.

---

## 9. How the panel talks to the hub

| What | How |
| :--- | :--- |
| Identity | On first use the panel makes an installation id and an **Ed25519 key pair**. The private key is stored in the panel's database, encrypted with the vault key; it never leaves the server. |
| Registration | Once per hub: the panel fetches the hub's public keys (`GET /api/v1/keys`) and **pins** them, then registers its own public key, its version and the hash of its core files. |
| Signed requests | Every request that says which panel sends it (heartbeat, link, download, purchase) is signed with the installation key over the method, path, installation id, time, a single-use nonce and the body's SHA-256. The hub refuses old, replayed or altered requests. |
| Heartbeat | Every 6 hours: the version, the **core hash** (SHA-256 over the panel's Python files) and the installed plugins with their versions. Nothing about instances, accounts or your data is sent. |
| Lease | The hub answers with a lease signed by its key (a JWT, EdDSA), for this installation only, valid 7 days: the standing of each plugin and the licence dates of the paid ones. The panel verifies it with a pinned key and keeps only verified values. |

The heartbeat is also what lets the hub tell a released panel from a modified one: the core hash is compared with
the hash of the released version.

---

## 10. How a package is checked

Before anything is unpacked:

1. The package is downloaded with a signed request into a private folder.
2. Its **SHA-256** must equal the one the hub states.
3. The hub's **Ed25519 signature** over `sudoo-plugin-v1`, the plugin id, the version and that SHA-256 must verify
   with a **pinned** hub key. A signature therefore binds the package to one plugin and one version: an old
   release cannot be passed off as an update, nor one plugin as another.
4. Its `manifest.json` must name the same plugin and version; this panel's version must be within its
   `min_sudoo_version` and `max_sudoo_version`, and its `sdk_version` must accept this panel's SDK version (0.1.0).
5. Every plugin it `requires` must be installed and switched on, in a matching version.
6. It must not need **other Python packages**. This version of the panel has no dependency installer, so packages
   that declare dependencies (in `pyproject.toml` or a `requirements*.txt`) are refused; publishers ship plugins
   that use only the Python standard library and what the panel already provides.
7. It must not contain compiled code (`.so`, `.pyd`, `.pyc` ...), links, special files, absolute paths or `..`,
   and must stay within 25 MB, 200 MB unpacked and 5,000 files (no archive bombs).
8. Its entry points must be in `sudoo.*` groups, must not take a name another plugin already uses, and its modules
   must not clash with the panel's own or with its libraries. Storage plugins cannot come from the marketplace (the
   installed plugins are recorded in storage).

A package that fails any check is deleted and nothing is installed.

---

## 11. Where plugins are kept, and what is protected

Installed plugins are unpacked into `/opt/odoo/manager/plugins/<id>/<version>/` (folders mode 700, files mode 600,
owned by root). The package file is deleted after unpacking. A hash of every unpacked file is recorded; at every
start, and every 10 minutes, the files are hashed again, and a plugin whose files changed is **not loaded**, is shown
as "Files changed" and the super admins are e-mailed. Installing it again repairs it.

What the panel guarantees:

* **No API returns a plugin's code or package.** The panel lists plugins (name, version, status, licence) and
  nothing else.
* The web container (`sudoo-web`) does not mount `/opt/odoo`, so it cannot read plugin files, and no web path serves
  them.
* Plugins run only from packages the hub signed, checked as above.

What it does **not** protect, said plainly:

* **An administrator with root on the server can read the files** in `/opt/odoo/manager/plugins/`. The panel cannot
  hide files from root. The protection of a plugin's code is that the panel never exposes it, and that the licence
  forbids copying it.
* A plugin runs inside the panel's process, with the panel's rights. The review on the marketplace, the permissions
  a plugin must declare, and the signature are what make that acceptable; install only plugins you need.

---

## 12. Settings and commands

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `MARKETPLACE` | `on` | `off`: the panel never contacts the hub. Installed free plugins keep working; paid ones stop when the last lease ends. Also on the Settings page. |
| `HUB_URL` | `https://hub.sudoo.sh` | The hub's address (`.env` only). A new address registers the panel with that hub and pins its keys. |

See [Configuration](CONFIGURATION.md#marketplace). On the server:

```bash
docker exec sudoo-panel sudoo.sh marketplace            # the connection, the lease, the installed plugins
docker exec sudoo-panel sudoo.sh marketplace heartbeat  # send a heartbeat now
docker exec sudoo-panel sudoo.sh marketplace repin      # forget the pinned hub keys and pin them again
```

Use `repin` only when Sudoo.sh announces a new hub key: until then, a lease or package signed with another key is
refused on purpose.

The API behind the page is described in [Panel API](PANEL_API.md#plugins-and-the-marketplace).

---

## 13. Troubleshooting

| Message | What to do |
| :--- | :--- |
| The marketplace cannot be reached | Check that the server can open `https://hub.sudoo.sh` (firewall, DNS). The panel retries every 15 minutes; **Send a heartbeat now** under Settings, Marketplace tries at once. |
| Link this panel to your Sudoo.sh account first | Make a code on app.sudoo.sh, Servers, Link a server, and paste it under Settings, Marketplace. |
| This panel has no licence for this plugin yet | Buy it first, or wait for the payment to arrive. |
| The account owner has not allowed purchases from this server | On app.sudoo.sh, Servers, turn on *Allow purchases from this server*. |
| This server's monthly spending limit is reached | Raise the limit on app.sudoo.sh, Servers, or wait for next month. |
| Your account has no e-mail address | Add one under **My account**: the purchase and the receipt name who asked. |
| Jobs are running | Wait until they finish: installing restarts the backend. |
| The package's signature is not valid / SHA-256 does not match | The download was changed on the way or is not from the marketplace. Nothing was installed; try again, and tell Sudoo.sh if it repeats. |
| Signed with a key this panel does not trust | The hub uses a key this panel has not pinned. Run `sudoo.sh marketplace repin` only if Sudoo.sh announced a new key. |
| This plugin needs other Python packages | Not supported yet; ask the publisher for a version without dependencies. |
| Files changed | Someone or something changed the plugin's files on the server. Find out why, then install the plugin again. |
| The marketplace refuses this panel (integrity violation) | The panel's own files differ from the released version. Reinstall the released version with `install.sh`. |
