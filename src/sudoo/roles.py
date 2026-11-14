"""Roles and what each may do.

Every check in the panel asks for a permission, never for a role (security.require, security.can), so a role is
only a named set of permissions:

    super_admin   Super admin     everything, including the panel's settings and the other super admins
    admin         Administrator   everything except the panel's settings (sees plugins, cannot install them)
    maintainer    Maintainer      creates instances and does everything on them except deleting (restoring backups
                                  too); GitHub access
    developer     Developer       follows instances: gets new code, restarts, starts, adds submodules
    viewer        Viewer          sees instances, their activity and logs

Accounts of earlier versions are renamed once when the panel starts (storage/migrate.py): "admin" becomes a super
admin, "operator" (the sync operator) a developer. API tokens act as an administrator (write scope) or a viewer
(read scope).
"""

from __future__ import annotations

from dataclasses import dataclass

PERMISSIONS: dict[str, str] = {
    "instances.view": "See instances, their figures and activity",
    "instances.logs": "Read Odoo's log and jobs' technical logs",
    "instances.update": "Get new code, restart, start, add submodules",
    "instances.operate": "Pause, switch off, upgrade, switch branch, back up, change automation",
    "instances.create": "Create instances",
    "instances.restore": "Restore an instance from a backup (replaces its database and files)",
    "instances.delete": "Delete instances",
    "instances.credentials": "See Odoo passwords and ports",
    "backups.manage": "Download and delete backups",
    "github.manage": "Manage deploy keys",
    "accounts.manage": "Create, change and delete accounts",
    "tokens.manage": "Create and revoke API tokens",
    "audit.view": "Read the audit log",
    "plugins.view": "See installed plugins, the marketplace and purchases",
    "settings.manage": "Change the panel's settings, install and buy plugins, and restart it",
}


@dataclass(frozen=True, slots=True)
class Role:
    label: str
    description: str
    permissions: frozenset[str]


_VIEW = frozenset({"instances.view", "instances.logs"})
_DEVELOP = _VIEW | {"instances.update"}
_MAINTAIN = _DEVELOP | {
    "instances.operate",
    "instances.restore",
    "instances.create",
    "instances.credentials",
    "github.manage",
}
_ADMIN = frozenset(PERMISSIONS) - {"settings.manage"}

ROLES: dict[str, Role] = {
    "super_admin": Role("Super admin", "Everything, including the panel's settings.", frozenset(PERMISSIONS)),
    "admin": Role("Administrator", "Everything except the panel's settings.", _ADMIN),
    "maintainer": Role("Maintainer", "Creates instances and runs every action on them except deleting.", _MAINTAIN),
    "developer": Role("Developer", "Gets new code, restarts and starts instances, adds submodules.", _DEVELOP),
    "viewer": Role("Viewer", "Sees instances, their activity and logs.", _VIEW),
}
LABELS = {name: role.label for name, role in ROLES.items()}
ADMINISTRATORS = frozenset({"super_admin", "admin"})  # "admins" in REQUIRE_SECOND_FACTOR


def normalize(role: str) -> str:
    """A known role, or the role with the fewest permissions."""
    return role if role in ROLES else "viewer"


def permissions(role: str) -> frozenset[str]:
    return ROLES[normalize(role)].permissions
