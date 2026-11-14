"""The `sudoo.sh` command (also available as `sudoo`), run inside the panel container by the server administrator:

docker exec sudoo-panel sudoo.sh setup-code              the one-time code for the first-run page
docker exec sudoo-panel sudoo.sh create-user NAME ROLE   ROLE: super_admin, admin, maintainer, developer, viewer
docker exec sudoo-panel sudoo.sh reset-password NAME     print a new password
docker exec sudoo-panel sudoo.sh list-users
docker exec sudoo-panel sudoo.sh urls                    current public addresses
docker exec sudoo-panel sudoo.sh config                  effective settings and installed plugins
docker exec sudoo-panel sudoo.sh create-token NAME SCOPE  SCOPE is read or write; prints the secrets once
docker exec sudoo-panel sudoo.sh test-email ADDRESS       send a test e-mail, to check the SMTP settings
docker exec sudoo-panel sudoo.sh marketplace [status|heartbeat|repin]   the connection to the Sudoo.sh hub
sudoo.sh serve                                       start the web panel (the container does this)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from sudoo import accounts, api_tokens, exposure, plugins
from sudoo.config import settings
from sudoo.core import audit
from sudoo.instances import store


def setup_code(_: argparse.Namespace) -> None:
    code = accounts.setup_code()
    if code is None:
        print("The panel is already set up: accounts exist. Use reset-password if a password is lost.")
    else:
        print(f"Setup code: {code}\nOpen the panel's address and create the first account with it.")


def create_user(args: argparse.Namespace) -> None:
    password = accounts.create(args.name.lower(), args.role)
    audit.record("command line", None, "account created", detail=args.name)
    print(f"Account {args.name.lower()} created. Password (shown once): {password}")


def reset_password(args: argparse.Namespace) -> None:
    if not accounts.get(args.name):
        sys.exit(f"No account called {args.name!r}.")
    password = accounts.generate_password()
    accounts.set_password(args.name, password, must_change=True)
    audit.record("command line", None, "password reset", detail=args.name)
    print(f"New password for {args.name}: {password}\nAll existing sessions of this account were signed out.")


def list_users(_: argparse.Namespace) -> None:
    for name, user in sorted(accounts.all_users().items()):
        last = user.get("last_login")
        when = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M") if last else "never"
        print(f"{name:<16} {accounts.ROLES[user['role']]:<16} last sign-in: {when}")


def urls(_: argparse.Namespace) -> None:
    print(f"Panel: {exposure.address(exposure.PANEL) or 'not ready yet'}")
    for name in store.names():
        print(f"{name}: {exposure.address(name) or 'not ready yet'}")


def create_token(args: argparse.Namespace) -> None:
    token, signing_secret = api_tokens.create(args.name, args.scope, "command line")
    audit.record("command line", None, "API token created", detail=f"{args.name} ({args.scope})")
    print(f"Token (shown once):          {token}\nSigning secret (shown once): {signing_secret}")


def show_config(_: argparse.Namespace) -> None:
    """Every setting with its effective value (secrets hidden), then the installed plugins."""
    hidden = {"odoo_admin_password", "github_webhook_secret"}
    for key, value in settings.model_dump().items():
        print(f"{key.upper():<32} {'(set)' if key in hidden and value else value}")
    print(f"\nExposure plugins:   {', '.join(plugins.available(plugins.EXPOSURE_GROUP))}")
    print(f"Add-on sources:     {', '.join(plugins.available(plugins.ADDON_SOURCE_GROUP))}, none")
    print(f"Update triggers:    {', '.join(plugins.available(plugins.UPDATE_TRIGGER_GROUP))}")


def test_email(args: argparse.Namespace) -> None:
    """Send the test e-mail; says what went wrong when it cannot."""
    from sudoo.mail import MailError, mailer, send_template

    if not mailer().ready:
        sys.exit(
            "E-mail is not set up: fill in SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD in .env (docs/CONFIGURATION.md)."
        )
    server = f"{settings.smtp_host}:{settings.smtp_port} ({settings.smtp_security}) as {settings.smtp_username or '-'}"
    try:
        send_template(args.address, "test", "Sudoo.sh e-mail works", preheader="Your mail settings work.",
                      kicker="E-mail settings", title="It works", server=server)  # fmt: skip
    except MailError as error:
        sys.exit(f"{error}\nCheck SMTP_* in .env; for Gmail, SMTP_PASSWORD must be an app password.")
    audit.record("command line", None, "test e-mail sent", detail=args.address)
    print(f"Sent to {args.address} through {server}. Check the inbox (and the spam folder).")


def marketplace(args: argparse.Namespace) -> None:
    """status: the connection to the hub and the installed plugins; heartbeat: send one now; repin: forget the
    pinned hub keys so the next heartbeat fetches and pins them again (after the hub changed its key)."""
    from sudoo import plugin_manager
    from sudoo.hub import HubRefused, HubUnavailable, client
    from sudoo.hub import marketplace as hub

    if args.action == "repin":
        client.update_identity(hub_keys={}, hub_url=None, registered_at=None)
        audit.record("command line", None, "marketplace keys forgotten (repin)")
        print("The hub's keys are forgotten; the next heartbeat fetches and pins them again.")
    if args.action in ("heartbeat", "repin"):
        try:
            hub.heartbeat()
        except (HubRefused, HubUnavailable) as error:
            sys.exit(f"Heartbeat failed: {error}")
    status = hub.status()
    for key, value in status.items():
        if key.endswith("_at") and isinstance(value, int | float):
            value = datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
        print(f"{key:<20} {value}")
    for plugin_id, rec in sorted(plugin_manager.records().items()):
        print(f"plugin {plugin_id:<32} {rec['version']:<10} {plugin_manager.allowed(rec)[1]}")


def serve(_: argparse.Namespace) -> None:
    """Start gunicorn: one process (jobs, monitor and gateway share its memory), on 127.0.0.1:API_PORT. Visitors
    reach it through the web service (web/, container sudoo-web), which listens on PANEL_PORT."""
    bind = f"127.0.0.1:{settings.api_port}"
    os.execvp("gunicorn", ["gunicorn", "--workers", "1", "--threads", "32", "--timeout", "120",
                           "--bind", bind, "sudoo.wsgi:app"])  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sudoo.sh", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup-code", help="show the code that creates the first account").set_defaults(run=setup_code)
    create = commands.add_parser("create-user", help="create an account and print its password")
    create.add_argument("name")
    create.add_argument("role", choices=sorted(accounts.ROLES))
    create.set_defaults(run=create_user)
    reset = commands.add_parser("reset-password", help="set and print a new password")
    reset.add_argument("name")
    reset.set_defaults(run=reset_password)
    commands.add_parser("list-users", help="list accounts").set_defaults(run=list_users)
    commands.add_parser("urls", help="print the current public addresses").set_defaults(run=urls)
    commands.add_parser("config", help="print the effective settings and plugins").set_defaults(run=show_config)
    token = commands.add_parser("create-token", help="create an API token and print its secrets")
    token.add_argument("name")
    token.add_argument("scope", choices=sorted(api_tokens.SCOPES))
    token.set_defaults(run=create_token)
    mail = commands.add_parser("test-email", help="send a test e-mail to check the SMTP settings")
    mail.add_argument("address")
    mail.set_defaults(run=test_email)
    hub = commands.add_parser("marketplace", help="the connection to the Sudoo.sh hub")
    hub.add_argument("action", nargs="?", default="status", choices=("status", "heartbeat", "repin"))
    hub.set_defaults(run=marketplace)
    commands.add_parser("serve", help="start the web panel").set_defaults(run=serve)
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except ValueError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
