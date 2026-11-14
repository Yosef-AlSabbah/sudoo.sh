"""Finding and loading plugins.

A plugin is a class registered under an entry-point group in a package's pyproject.toml, the standard Python way
(also used by pytest, Flask and Sphinx extensions):

    [project.entry-points."sudoo.exposure"]
    cloudflare-quick = "sudoo.exposure.cloudflare:CloudflareQuickTunnel"

A setting names the plugin to use (`EXPOSURE=cloudflare-quick`). The class is created once with the settings
(dependency injection: plugins never read the environment themselves), and every caller gets that one object.
Plugins from other installed packages are found the same way, so new ones need no change in this code. Plugins
installed from the marketplace (plugin_manager.py) are put on the path, with their entry points, the first time a
plugin is loaded; the storage plugin is loaded before that, because the installed plugins are recorded in storage.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from sudoo.config import Settings

EXPOSURE_GROUP = "sudoo.exposure"
ADDON_SOURCE_GROUP = "sudoo.addon_sources"
UPDATE_TRIGGER_GROUP = "sudoo.update_triggers"
STORAGE_GROUP = "sudoo.storage"
AUTH_GROUP = "sudoo.auth"
SECOND_FACTOR_GROUP = "sudoo.second_factors"
MAILER_GROUP = "sudoo.mailers"
RATE_LIMITER_GROUP = "sudoo.rate_limiters"


class PluginError(RuntimeError):
    """A setting names a plugin that is not installed."""


def _with_installed(group: str) -> None:
    """Before the first plugin other than storage is loaded: put the marketplace plugins on the path."""
    if group != STORAGE_GROUP:
        from sudoo import plugin_manager

        plugin_manager.activate()


def available(group: str) -> list[str]:
    """Names of the plugins installed for `group`."""
    _with_installed(group)
    return sorted(entry.name for entry in entry_points(group=group))


def load(group: str, name: str, settings: Settings) -> Any:
    """Create the plugin `name` of `group`, giving it the settings."""
    _with_installed(group)
    for entry in entry_points(group=group):
        if entry.name == name:
            return entry.load()(settings)
    raise PluginError(f'No plugin "{name}" for {group}. Installed: {", ".join(available(group)) or "none"}.')
