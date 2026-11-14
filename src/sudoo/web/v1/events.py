"""GET /api/v1/events: the live event stream (Server-Sent Events).

A client opens one long-lived request and receives every change as it happens:

    id: 4182
    event: job
    data: {"key": "a12fff66a05d", "data": {<the job, as GET /api/v1/jobs/<id> shows it>}}

Topics: "instance" (an instance changed; data is the instance), "instance.deleted", "job" (a job started, moved to
another step or ended), "job.output" (new log text of a job), "metrics" (resource use, every METRICS_INTERVAL_SECONDS),
"settings", "plugins" (an installed plugin changed) and "marketplace" (the connection to the hub changed); the last
two carry no details, only that something changed. `?topics=job,instance` limits the stream to some topics. A
comment line is sent every 20 seconds so proxies keep the connection open.

After a lost connection, the browser's EventSource reconnects by itself and sends Last-Event-ID; the stream then
starts with what was missed (the latest state of each instance and job). When too much was missed, the first
event is "reset": the client reloads its data.

The stream runs on the asyncio event loop shared with the gateway, not in the web server's threads, so a thousand
open tabs cost a thousand small coroutines, not a thousand threads. It listens on 127.0.0.1:EVENTS_PORT; the web
service forwards /api/v1/events to it. It accepts the same callers as the rest of the API: the panel's session
cookie (the browser), or an API token with a signature (other systems).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web
from flask import Flask

from sudoo.config import settings
from sudoo.core.events import BUS, Event
from sudoo.instances import gateway

from ..security import api_caller, client_ip_of, user_of_session

PATH = "/api/v1/events"
FLASK_APP = web.AppKey("flask", Flask)
TOPICS = frozenset(
    {"instance", "instance.deleted", "job", "job.output", "metrics", "settings", "plugins", "marketplace"}
)
HEARTBEAT_SECONDS = 20
MAX_CLIENTS = 500
_RECHECK_SECONDS = 60  # how often a long stream checks that its session is still valid


def start(flask_app: Flask) -> None:
    """Serve the stream on the gateway's event loop (called when the panel starts)."""
    gateway.submit(_serve(make_app(flask_app)))


async def _serve(app: web.Application) -> None:
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", settings.events_port, reuse_address=True).start()


def make_app(flask_app: Flask) -> web.Application:
    app = web.Application()
    app[FLASK_APP] = flask_app
    app.router.add_get(PATH, stream)
    return app


# ---------------------------------------------------------------- who is calling


def _problem(status: int, title: str, detail: str) -> web.Response:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, "instance": PATH}
    return web.json_response(body, status=status, content_type="application/problem+json")


def _session_of(request: web.Request) -> dict[str, Any] | None:
    """The panel's session cookie, verified with the panel's own key (as Flask reads it)."""
    flask_app = request.app[FLASK_APP]
    cookie = request.cookies.get(flask_app.config["SESSION_COOKIE_NAME"])
    serializer = flask_app.session_interface.get_signing_serializer(flask_app)  # type: ignore[attr-defined]
    if not cookie or serializer is None:
        return None
    try:
        data = serializer.loads(cookie, max_age=int(flask_app.permanent_session_lifetime.total_seconds()))
    except Exception:  # noqa: BLE001 - a forged, old or damaged cookie is simply not a session
        return None
    return data if isinstance(data, dict) else None


def _caller(request: web.Request) -> tuple[dict[str, str] | None, dict[str, Any] | None, web.Response | None]:
    """(user, session, refusal). Exactly one of user and refusal is set."""
    ip = client_ip_of(request.headers, request.remote or "")
    if "Authorization" in request.headers:
        try:
            return api_caller(request.headers, "GET", request.path_qs, b"", ip), None, None
        except PermissionError as error:
            status = error.args[1]
            return None, None, _problem(status, {401: "Unauthorized", 429: "Too Many Requests"}[status], error.args[0])
    origin = request.headers.get("Origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("X-Forwarded-Host", request.host):
        return None, None, _problem(403, "Forbidden", "Request blocked: it did not come from this panel.")
    session = _session_of(request)
    user = user_of_session(session) if session else None
    if user is None:
        return None, None, _problem(401, "Unauthorized", "Your session has ended. Please sign in again.")
    return user, session, None


# ---------------------------------------------------------------- the stream


def _frame(event: Event, data: Any) -> bytes:
    payload = json.dumps({"key": event.key, "data": data}, separators=(",", ":"), default=str)
    return f"id: {event.id}\nevent: {event.topic}\ndata: {payload}\n\n".encode()


def _topics(request: web.Request) -> frozenset[str] | None:
    asked = {t.strip() for t in request.query.get("topics", "").split(",") if t.strip()}
    return frozenset(asked & TOPICS) if asked else None


def _last_id(request: web.Request) -> int | None:
    given = request.headers.get("Last-Event-ID") or request.query.get("last_event_id", "")
    return int(given) if given.isdigit() else None


async def stream(request: web.Request) -> web.StreamResponse:
    user, session, refusal = _caller(request)
    if refusal is not None:
        return refusal
    if BUS.subscriber_count >= MAX_CLIENTS:
        return _problem(503, "Service Unavailable", "Too many open live connections. Try again in a minute.")

    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",  # proxies must pass each event on at once
            "X-Content-Type-Options": "nosniff",
        }
    )
    await response.prepare(request)
    topics = _topics(request)
    subscription, last_before = BUS.subscribe(topics)
    loop = asyncio.get_running_loop()
    try:
        await response.write(f"retry: 3000\n: hello {user and user['name']}\n\n".encode())
        after = _last_id(request)
        if after is not None:
            missed = BUS.missed(after, last_before, topics)
            if missed is None:
                await response.write(f"id: {last_before}\nevent: reset\ndata: {{}}\n\n".encode())
            else:
                for old in missed:
                    data = await loop.run_in_executor(None, BUS.data_of, old)
                    if data is not None:
                        await response.write(_frame(old, data))
        checked = loop.time()
        while True:
            try:
                event = await asyncio.wait_for(subscription.queue.get(), HEARTBEAT_SECONDS)
            except TimeoutError:
                await response.write(b": ping\n\n")
            else:
                if event is None:  # too slow: closed; the browser reconnects with Last-Event-ID
                    break
                data = event.data if event.data is not None else await loop.run_in_executor(None, BUS.data_of, event)
                if data is not None:
                    await response.write(_frame(event, data))
            if session is not None and loop.time() - checked > _RECHECK_SECONDS:
                checked = loop.time()
                if user_of_session(session, check_idle=False) is None:  # signed out elsewhere, password changed
                    break
    except ConnectionResetError:
        pass  # the client went away
    finally:
        BUS.unsubscribe(subscription)
    return response
