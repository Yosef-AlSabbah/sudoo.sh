"""The API: /api/v1, used by the panel's web app and by other systems alike.

Who may call (security.py): the web app with its session cookie (and X-CSRF-Token for changes), or another system
with an API token and a signature on every request (api_tokens.py, docs/PANEL_API.md). Either way the caller is an
role (roles.py), and the same permission checks apply.

    session.py     sign in (password, then a second factor when needed) and out, own password, contact
    account.py     own account and second factors
    instances.py   instances, jobs, versions
    settings.py    the panel's settings, changed while it runs
    server.py      the server's resource use, the panel's address and plugins
    users.py       roles, accounts and the audit log
    tokens.py      API tokens
    backups.py     backups
    github.py      deploy keys and repository checks
    docs.py        the documentation, for the web app's Help pages
    plugins.py     installed plugins and the marketplace (catalogue, purchases, linking)
    events.py      the live event stream (Server-Sent Events), served on the asyncio loop
Answers follow the conventions in responses.py.
"""

from __future__ import annotations

from flask import Blueprint, Flask

from sudoo.config import live
from sudoo.core import events as bus
from sudoo.core import jobs

from . import account, backups, docs, github, instances, plugins, server, session, settings, tokens, users
from . import events as stream
from .resources import instance_resource, job_resource
from .responses import PREFIX, add_request_id, problem

__all__ = ["PREFIX", "add_request_id", "problem", "register", "stream"]


def register(app: Flask) -> None:
    """Add the API to the Flask app, and tell the live events how to show instances and jobs."""
    api = Blueprint("api_v1", __name__, url_prefix=PREFIX)
    for module in (session, account, instances, settings, server, users, tokens, backups, github, docs, plugins):
        api.register_blueprint(module.blueprint)
    app.register_blueprint(api)
    bus.present("instance", instance_resource)
    bus.present("job", lambda job_id: job_resource(jobs.JOBS[job_id]))
    live.on_change(settings.publish_changes)
