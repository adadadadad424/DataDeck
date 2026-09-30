"""Server-side workspace roles and permissions.

The UI may hide unavailable controls, but this module is the authority. Store
methods must call ``require_permission`` before touching workspace resources.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkspaceRole(StrEnum):
    OWNER = "OWNER"
    PARTNER = "PARTNER"
    CONSULTANT = "CONSULTANT"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    WORKSPACE_MANAGE = "workspace.manage"
    BILLING_MANAGE = "billing.manage"
    BRANDING_MANAGE = "branding.manage"
    CLIENT_READ = "client.read"
    CLIENT_WRITE = "client.write"
    ANALYSIS_READ = "analysis.read"
    ANALYSIS_WRITE = "analysis.write"
    REPORT_READ = "report.read"
    REPORT_EXPORT = "report.export"
    REPORT_APPROVE = "report.approve"
    ACTIVITY_READ = "activity.read"
    MONITORING_READ = "monitoring.read"
    MONITORING_WRITE = "monitoring.write"


ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[Permission]] = {
    WorkspaceRole.OWNER: frozenset(Permission),
    WorkspaceRole.PARTNER: frozenset({
        Permission.CLIENT_READ, Permission.CLIENT_WRITE,
        Permission.ANALYSIS_READ, Permission.ANALYSIS_WRITE,
        Permission.REPORT_READ, Permission.REPORT_EXPORT, Permission.REPORT_APPROVE,
        Permission.ACTIVITY_READ, Permission.MONITORING_READ, Permission.MONITORING_WRITE,
    }),
    WorkspaceRole.CONSULTANT: frozenset({
        Permission.CLIENT_READ, Permission.CLIENT_WRITE,
        Permission.ANALYSIS_READ, Permission.ANALYSIS_WRITE,
        Permission.REPORT_READ, Permission.REPORT_EXPORT,
        Permission.MONITORING_READ, Permission.MONITORING_WRITE,
    }),
    WorkspaceRole.VIEWER: frozenset({
        Permission.CLIENT_READ, Permission.ANALYSIS_READ, Permission.REPORT_READ,
        Permission.MONITORING_READ,
    }),
}


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    user_id: str
    role: WorkspaceRole

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


def parse_role(value: str | WorkspaceRole) -> WorkspaceRole:
    try:
        return value if isinstance(value, WorkspaceRole) else WorkspaceRole(str(value).upper())
    except ValueError as exc:
        raise ValueError("Unbekannte Workspace-Rolle") from exc


def require_permission(context: WorkspaceContext, permission: Permission) -> None:
    if not context.can(permission):
        raise PermissionError("Für diese Aktion fehlt die Workspace-Berechtigung")
