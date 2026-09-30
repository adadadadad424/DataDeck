"""Workspace-scoped aggregate persistence with server-side authorization."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import uuid
from dataclasses import replace

import psycopg

from core.database import connect_postgres
from .models import AnalysisSnapshot, AuditEvent, Client, MonitoringFinding, ReportMetadata, Workspace
from .rbac import Permission, WorkspaceContext, WorkspaceRole, parse_role, require_permission


_AUDIT_ENUMS = {
    "role": {"OWNER", "PARTNER", "CONSULTANT", "VIEWER"},
    "format": {"PDF", "PPTX"},
    "provider": {"local", "gemini"},
    "quality_status": {"GOOD", "WARNING", "POOR", "good", "warning", "poor"},
}
_AUDIT_COUNTS = {"version", "active_findings", "rows_processed", "columns_detected"}
_MONITORING_EVIDENCE = {
    "profit", "change_pct", "change_pp", "periods", "share_pct",
    "current_share_pct", "previous_share_pct", "refund_rate_pct",
}


def _personal_workspace_id(user_id: str) -> str:
    value = hashlib.md5(f"datadeck-personal-workspace:{user_id}".encode(), usedforsecurity=False).hexdigest()
    return str(uuid.UUID(value))


def _anonymous_actor(workspace_id: str, user_id: str) -> str:
    return hashlib.sha256(f"{workspace_id}:{user_id}".encode()).hexdigest()[:32]


def _safe_metadata(metadata: dict | None) -> dict:
    result = {}
    for key, value in (metadata or {}).items():
        if key in _AUDIT_ENUMS and isinstance(value, str) and value in _AUDIT_ENUMS[key]:
            result[key] = value
        elif key in _AUDIT_COUNTS and type(value) is int and 0 <= value <= 1_000_000_000:
            result[key] = value
    return result


def _safe_monitoring_evidence(evidence: dict | None) -> dict:
    result = {}
    for key, value in (evidence or {}).items():
        if key in _MONITORING_EVIDENCE and type(value) in (int, float) and math.isfinite(value):
            result[key] = value
    return result


def _json_payload(value, label: str, max_bytes: int) -> str:
    payload = json.dumps(value, ensure_ascii=False)
    if len(payload.encode()) > max_bytes:
        raise ValueError(f"{label} überschreitet das Speicherlimit")
    return payload


def _client(row):
    return Client(**row) if row else None


def _snapshot(row):
    if not row:
        return None
    row = dict(row)
    row["result"] = row.pop("analysis_result")
    return AnalysisSnapshot(**row)


def _report(row):
    return ReportMetadata(**row) if row else None


def _event(row):
    return AuditEvent(**row) if row else None


class PostgresConsultingStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        return connect_postgres(self.database_url)

    @staticmethod
    def _list_limit() -> int:
        try:
            return max(10, min(int(os.getenv("MAX_HISTORY_ITEMS", "200")), 1_000))
        except ValueError:
            return 200

    @staticmethod
    def _user(user_id: str) -> str:
        value = str(user_id or "").strip()
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise PermissionError("Anmeldung erforderlich") from exc
        return value

    def _ensure_personal(self, cursor, user_id: str) -> WorkspaceContext:
        user_id = self._user(user_id)
        workspace_id = _personal_workspace_id(user_id)
        cursor.execute(
            "INSERT INTO workspace_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO UPDATE SET last_seen_at=NOW()",
            (user_id,),
        )
        cursor.execute(
            """INSERT INTO workspaces (workspace_id,name,created_by)
               VALUES (%s,'Persönlicher Workspace',%s) ON CONFLICT (workspace_id) DO NOTHING""",
            (workspace_id, user_id),
        )
        cursor.execute(
            """INSERT INTO workspace_members (workspace_id,user_id,role)
               VALUES (%s,%s,'OWNER') ON CONFLICT (workspace_id,user_id) DO NOTHING""",
            (workspace_id, user_id),
        )
        return WorkspaceContext(workspace_id, user_id, WorkspaceRole.OWNER)

    def _context(self, cursor, user_id: str, workspace_id: str | None = None) -> WorkspaceContext:
        user_id = self._user(user_id)
        if workspace_id is None:
            return self._ensure_personal(cursor, user_id)
        cursor.execute(
            "SELECT role FROM workspace_members WHERE workspace_id=%s AND user_id=%s",
            (workspace_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            raise PermissionError("Kein Zugriff auf diesen Workspace")
        return WorkspaceContext(str(workspace_id), user_id, parse_role(row["role"]))

    @staticmethod
    def _audit(cursor, context: WorkspaceContext, event_type: str, resource_type: str,
               resource_id: str | None = None, metadata: dict | None = None) -> None:
        cursor.execute(
            """INSERT INTO audit_events (event_id,workspace_id,anonymous_actor_id,event_type,resource_type,resource_id,metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""",
            (str(uuid.uuid4()), context.workspace_id,
             _anonymous_actor(context.workspace_id, context.user_id), event_type[:80],
             resource_type[:80], resource_id,
             _json_payload(_safe_metadata(metadata), "Audit-Metadaten", 8_000)),
        )

    def ensure_personal_workspace(self, user_id: str) -> WorkspaceContext:
        with self._connect() as connection, connection.cursor() as cursor:
            return self._ensure_personal(cursor, user_id)

    def get_workspace_context(self, user_id: str, workspace_id: str | None = None) -> WorkspaceContext:
        with self._connect() as connection, connection.cursor() as cursor:
            return self._context(cursor, user_id, workspace_id)

    def create_workspace(self, user_id: str, name: str) -> Workspace:
        clean = str(name or "").strip()
        if not clean or len(clean) > 160:
            raise ValueError("Workspace-Name muss zwischen 1 und 160 Zeichen lang sein")
        workspace_id = str(uuid.uuid4())
        with self._connect() as connection, connection.cursor() as cursor:
            self._ensure_personal(cursor, user_id)
            cursor.execute(
                "INSERT INTO workspaces (workspace_id,name,created_by) VALUES (%s,%s,%s) RETURNING *",
                (workspace_id, clean, user_id),
            )
            workspace = Workspace(**cursor.fetchone())
            cursor.execute(
                "INSERT INTO workspace_members (workspace_id,user_id,role) VALUES (%s,%s,'OWNER')",
                (workspace_id, user_id),
            )
            self._audit(cursor, WorkspaceContext(workspace_id, user_id, WorkspaceRole.OWNER),
                        "WORKSPACE_CREATED", "workspace", workspace_id)
            return workspace

    def add_member(self, actor_user_id: str, workspace_id: str, user_id: str,
                   role: str | WorkspaceRole) -> None:
        role = parse_role(role)
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, actor_user_id, workspace_id)
            require_permission(context, Permission.WORKSPACE_MANAGE)
            self._user(user_id)
            cursor.execute("INSERT INTO workspace_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            cursor.execute(
                """INSERT INTO workspace_members (workspace_id,user_id,role) VALUES (%s,%s,%s)
                   ON CONFLICT (workspace_id,user_id) DO UPDATE SET role=EXCLUDED.role""",
                (workspace_id, user_id, role.value),
            )
            self._audit(cursor, context, "MEMBER_ROLE_CHANGED", "workspace", workspace_id, {"role": role.value})

    def record_event(self, user_id: str, event_type: str, resource_type: str = "session",
                     resource_id: str | None = None, metadata: dict | None = None,
                     workspace_id: str | None = None) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            self._audit(cursor, self._context(cursor, user_id, workspace_id), event_type,
                        resource_type, resource_id, metadata)

    def list_audit_events(self, user_id: str, workspace_id: str | None = None,
                          limit: int = 100) -> list[AuditEvent]:
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, user_id, workspace_id)
            require_permission(context, Permission.ACTIVITY_READ)
            cursor.execute(
                "SELECT * FROM audit_events WHERE workspace_id=%s ORDER BY created_at DESC LIMIT %s",
                (context.workspace_id, max(1, min(int(limit), 500))),
            )
            return [_event(row) for row in cursor.fetchall()]

    def create_client(self, owner_user_id: str, name: str, internal_reference: str | None = None,
                      *, workspace_id: str | None = None) -> Client:
        clean_name = str(name or "").strip()
        clean_reference = (internal_reference or "").strip() or None
        if not clean_name or len(clean_name) > 160:
            raise ValueError("Mandantenname muss zwischen 1 und 160 Zeichen lang sein")
        if clean_reference and len(clean_reference) > 120:
            raise ValueError("Interne Referenz darf maximal 120 Zeichen lang sein")
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, owner_user_id, workspace_id)
            require_permission(context, Permission.CLIENT_WRITE)
            cursor.execute(
                """INSERT INTO consulting_clients (client_id,owner_user_id,workspace_id,name,internal_reference)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (workspace_id,name) DO UPDATE SET
                   internal_reference=COALESCE(EXCLUDED.internal_reference,consulting_clients.internal_reference),updated_at=NOW()
                   RETURNING *""",
                (str(uuid.uuid4()), context.user_id, context.workspace_id, clean_name, clean_reference),
            )
            client = _client(cursor.fetchone())
            self._audit(cursor, context, "CLIENT_SAVED", "client", client.client_id)
            return client

    def list_clients(self, owner_user_id: str, *, workspace_id: str | None = None) -> list[Client]:
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, owner_user_id, workspace_id)
            require_permission(context, Permission.CLIENT_READ)
            cursor.execute("SELECT * FROM consulting_clients WHERE workspace_id=%s ORDER BY name LIMIT %s",
                           (context.workspace_id, self._list_limit()))
            return [_client(row) for row in cursor.fetchall()]

    def get_client(self, owner_user_id: str, client_id: str) -> Client | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM consulting_clients WHERE client_id=%s", (client_id,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                context = self._context(cursor, owner_user_id, str(row["workspace_id"]))
                require_permission(context, Permission.CLIENT_READ)
            except PermissionError:
                return None
            return _client(row)

    def delete_client(self, owner_user_id: str, client_id: str) -> bool:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            return False
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, owner_user_id, client.workspace_id)
            require_permission(context, Permission.CLIENT_WRITE)
            self._audit(cursor, context, "CLIENT_DELETED", "client", client_id)
            cursor.execute("DELETE FROM consulting_clients WHERE workspace_id=%s AND client_id=%s",
                           (context.workspace_id, client_id))
            return cursor.rowcount == 1

    def save_analysis(self, snapshot: AnalysisSnapshot) -> AnalysisSnapshot:
        mapping = _json_payload(snapshot.mapping, "Spaltenzuordnung", 32_000)
        result = _json_payload(snapshot.result, "Analyseergebnis", 512_000)
        insights = _json_payload(snapshot.insights, "Insights", 32_000)
        if len(snapshot.executive_summary) > 2_000 or len(snapshot.consultant_comment) > 2_000:
            raise ValueError("Berichtstext überschreitet das Speicherlimit")
        client = self.get_client(snapshot.owner_user_id, snapshot.client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                context = self._context(cursor, snapshot.owner_user_id, client.workspace_id)
                require_permission(context, Permission.ANALYSIS_WRITE)
                cursor.execute(
                    """INSERT INTO analysis_snapshots (
                       analysis_id,owner_user_id,workspace_id,client_id,dataset_hash,period_start,period_end,
                       mapping,analysis_result,quality_status,insights,executive_summary,consultant_comment,
                       analysis_version,analysis_engine_version,analysis_schema_version,uploaded_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,COALESCE(%s,NOW()))
                       ON CONFLICT (analysis_id) DO NOTHING RETURNING *""",
                    (snapshot.analysis_id, context.user_id, context.workspace_id, snapshot.client_id,
                     snapshot.dataset_hash, snapshot.period_start, snapshot.period_end, mapping, result,
                     snapshot.quality_status, insights, snapshot.executive_summary, snapshot.consultant_comment,
                     snapshot.analysis_version, snapshot.analysis_engine_version,
                     snapshot.analysis_schema_version, snapshot.uploaded_at),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute("SELECT * FROM analysis_snapshots WHERE workspace_id=%s AND analysis_id=%s",
                                   (context.workspace_id, snapshot.analysis_id))
                    existing = _snapshot(cursor.fetchone())
                    if not existing or existing.dataset_hash != snapshot.dataset_hash:
                        raise PermissionError("Analyse-ID gehört nicht zu diesem Workspace")
                    return existing
                saved = _snapshot(row)
                self._audit(cursor, context, "ANALYSIS_SAVED", "analysis", saved.analysis_id,
                            {"quality_status": saved.quality_status})
                return saved
        except psycopg.errors.UniqueViolation as exc:
            if str(getattr(exc.diag, "constraint_name", "")) in {
                "analysis_snapshots_owner_user_id_client_id_dataset_hash_key",
                "analysis_snapshots_workspace_dataset_key",
            }:
                raise ValueError("Dieser Datenstand wurde für den Mandanten bereits gespeichert") from exc
            raise

    def list_analyses(self, owner_user_id: str, client_id: str) -> list[AnalysisSnapshot]:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, owner_user_id, client.workspace_id)
            require_permission(context, Permission.ANALYSIS_READ)
            cursor.execute(
                """SELECT * FROM analysis_snapshots WHERE workspace_id=%s AND client_id=%s
                   ORDER BY period_start DESC LIMIT %s""",
                (context.workspace_id, client_id, self._list_limit()),
            )
            return [_snapshot(row) for row in cursor.fetchall()]

    def get_analysis(self, owner_user_id: str, analysis_id: str) -> AnalysisSnapshot | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM analysis_snapshots WHERE analysis_id=%s", (analysis_id,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                context = self._context(cursor, owner_user_id, str(row["workspace_id"]))
                require_permission(context, Permission.ANALYSIS_READ)
            except PermissionError:
                return None
            return _snapshot(row)

    def _analysis_context(self, cursor, user_id: str, analysis_id: str,
                          permission: Permission) -> tuple[WorkspaceContext, AnalysisSnapshot]:
        cursor.execute("SELECT * FROM analysis_snapshots WHERE analysis_id=%s", (analysis_id,))
        analysis = _snapshot(cursor.fetchone())
        if not analysis:
            raise PermissionError("Analyse ist nicht verfügbar")
        context = self._context(cursor, user_id, analysis.workspace_id)
        require_permission(context, permission)
        return context, analysis

    def next_report_version(self, owner_user_id: str, client_id: str, analysis_id: str) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            context, analysis = self._analysis_context(cursor, owner_user_id, analysis_id, Permission.REPORT_EXPORT)
            if analysis.client_id != client_id:
                raise PermissionError("Analyse gehört nicht zu diesem Mandanten")
            cursor.execute("SELECT COALESCE(MAX(report_version),0)+1 AS n FROM report_versions WHERE workspace_id=%s AND analysis_id=%s",
                           (context.workspace_id, analysis_id))
            return int(cursor.fetchone()["n"])

    def save_report_metadata(self, owner_user_id: str, client_id: str, analysis_id: str,
                             settings: dict, report_hash: str | None) -> ReportMetadata:
        payload = _json_payload(settings, "Report-Einstellungen", 16_000)
        with self._connect() as connection, connection.cursor() as cursor:
            context, analysis = self._analysis_context(cursor, owner_user_id, analysis_id, Permission.REPORT_EXPORT)
            if analysis.client_id != client_id:
                raise PermissionError("Analyse gehört nicht zu diesem Mandanten")
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                           (f"report:{context.workspace_id}:{analysis_id}",))
            cursor.execute("SELECT COALESCE(MAX(report_version),0)+1 AS n FROM report_versions WHERE workspace_id=%s AND analysis_id=%s",
                           (context.workspace_id, analysis_id))
            version = int(cursor.fetchone()["n"])
            cursor.execute(
                """INSERT INTO report_versions (report_id,owner_user_id,workspace_id,client_id,analysis_id,report_version,settings,report_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING *""",
                (str(uuid.uuid4()), context.user_id, context.workspace_id, client_id, analysis_id,
                 version, payload, report_hash),
            )
            report = _report(cursor.fetchone())
            self._audit(cursor, context, "REPORT_EXPORTED", "report", report.report_id,
                        {"format": str(settings.get("format", "PDF"))[:20], "version": version})
            return report

    def get_report(self, owner_user_id: str, report_id: str) -> ReportMetadata | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM report_versions WHERE report_id=%s", (report_id,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                context = self._context(cursor, owner_user_id, str(row["workspace_id"]))
                require_permission(context, Permission.REPORT_READ)
            except PermissionError:
                return None
            return _report(row)

    def approve_report(self, owner_user_id: str, report_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT workspace_id FROM report_versions WHERE report_id=%s", (report_id,))
            row = cursor.fetchone()
            if not row:
                raise PermissionError("Report ist nicht verfügbar")
            context = self._context(cursor, owner_user_id, str(row["workspace_id"]))
            require_permission(context, Permission.REPORT_APPROVE)
            cursor.execute(
                """INSERT INTO report_approvals (approval_id,workspace_id,report_id,anonymous_approver_id)
                   VALUES (%s,%s,%s,%s) ON CONFLICT (workspace_id,report_id) DO NOTHING""",
                (str(uuid.uuid4()), context.workspace_id, report_id,
                 _anonymous_actor(context.workspace_id, context.user_id)),
            )
            self._audit(cursor, context, "REPORT_APPROVED", "report", report_id)

    def sync_monitoring_findings(self, owner_user_id: str, client_id: str, signals) -> list[MonitoringFinding]:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, owner_user_id, client.workspace_id)
            require_permission(context, Permission.MONITORING_WRITE)
            cursor.execute("SELECT * FROM monitoring_findings WHERE workspace_id=%s AND client_id=%s",
                           (context.workspace_id, client_id))
            existing = {row["fingerprint"]: row for row in cursor.fetchall()}
            active = set()
            for signal in signals:
                active.add(signal.fingerprint)
                old = existing.get(signal.fingerprint)
                status = "ONGOING" if old and old["status"] in {"NEW", "ONGOING"} else "NEW"
                cursor.execute(
                    """INSERT INTO monitoring_findings (
                       finding_id,workspace_id,client_id,rule_id,fingerprint,severity,status,title,detail,evidence)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT (workspace_id,client_id,rule_id,fingerprint) DO UPDATE SET
                       severity=EXCLUDED.severity,status=EXCLUDED.status,title=EXCLUDED.title,
                       detail=EXCLUDED.detail,evidence=EXCLUDED.evidence,last_seen_at=NOW()""",
                    (str(uuid.uuid4()), context.workspace_id, client_id, signal.rule_id,
                     signal.fingerprint, signal.severity, status, signal.title, signal.detail,
                     _json_payload(_safe_monitoring_evidence(signal.evidence), "Monitoring-Evidenz", 8_000)),
                )
            for fingerprint, row in existing.items():
                if fingerprint not in active and row["status"] != "RESOLVED":
                    cursor.execute("UPDATE monitoring_findings SET status='RESOLVED',last_seen_at=NOW() WHERE finding_id=%s",
                                   (row["finding_id"],))
            self._audit(cursor, context, "MONITORING_UPDATED", "client", client_id,
                        {"active_findings": len(active)})
            cursor.execute("SELECT * FROM monitoring_findings WHERE workspace_id=%s AND client_id=%s ORDER BY last_seen_at DESC",
                           (context.workspace_id, client_id))
            return [MonitoringFinding(**row) for row in cursor.fetchall()]

    def list_monitoring_findings(self, owner_user_id: str, client_id: str) -> list[MonitoringFinding]:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        with self._connect() as connection, connection.cursor() as cursor:
            context = self._context(cursor, owner_user_id, client.workspace_id)
            require_permission(context, Permission.MONITORING_READ)
            cursor.execute("SELECT * FROM monitoring_findings WHERE workspace_id=%s AND client_id=%s ORDER BY last_seen_at DESC",
                           (context.workspace_id, client_id))
            return [MonitoringFinding(**row) for row in cursor.fetchall()]


class InMemoryConsultingStore:
    """Behavioral test double with the same workspace permission model."""

    def __init__(self):
        self.clients: dict[str, Client] = {}
        self.analyses: dict[str, AnalysisSnapshot] = {}
        self.reports: dict[str, ReportMetadata] = {}
        self.workspaces: dict[str, Workspace] = {}
        self.members: dict[tuple[str, str], WorkspaceRole] = {}
        self.audit_events: list[AuditEvent] = []
        self.monitoring_findings: dict[tuple[str, str, str], MonitoringFinding] = {}

    def ensure_personal_workspace(self, user_id: str) -> WorkspaceContext:
        user_id = str(user_id or "").strip()
        if not user_id:
            raise PermissionError("Anmeldung erforderlich")
        workspace_id = _personal_workspace_id(user_id)
        self.workspaces.setdefault(workspace_id, Workspace(workspace_id, "Persönlicher Workspace", user_id))
        self.members.setdefault((workspace_id, user_id), WorkspaceRole.OWNER)
        return WorkspaceContext(workspace_id, user_id, self.members[(workspace_id, user_id)])

    def get_workspace_context(self, user_id: str, workspace_id: str | None = None) -> WorkspaceContext:
        if workspace_id is None:
            return self.ensure_personal_workspace(user_id)
        role = self.members.get((workspace_id, user_id))
        if role is None:
            raise PermissionError("Kein Zugriff auf diesen Workspace")
        return WorkspaceContext(workspace_id, user_id, role)

    def create_workspace(self, user_id: str, name: str) -> Workspace:
        self.ensure_personal_workspace(user_id)
        clean = str(name or "").strip()
        if not clean or len(clean) > 160:
            raise ValueError("Workspace-Name muss zwischen 1 und 160 Zeichen lang sein")
        workspace = Workspace(str(uuid.uuid4()), clean, user_id)
        self.workspaces[workspace.workspace_id] = workspace
        self.members[(workspace.workspace_id, user_id)] = WorkspaceRole.OWNER
        self.record_event(user_id, "WORKSPACE_CREATED", "workspace", workspace.workspace_id,
                          workspace_id=workspace.workspace_id)
        return workspace

    def add_member(self, actor_user_id: str, workspace_id: str, user_id: str,
                   role: str | WorkspaceRole) -> None:
        context = self.get_workspace_context(actor_user_id, workspace_id)
        require_permission(context, Permission.WORKSPACE_MANAGE)
        parsed = parse_role(role)
        self.members[(workspace_id, user_id)] = parsed
        self.record_event(actor_user_id, "MEMBER_ROLE_CHANGED", "workspace", workspace_id,
                          {"role": parsed.value}, workspace_id)

    def record_event(self, user_id: str, event_type: str, resource_type: str = "session",
                     resource_id: str | None = None, metadata: dict | None = None,
                     workspace_id: str | None = None) -> None:
        context = self.get_workspace_context(user_id, workspace_id)
        self.audit_events.append(AuditEvent(
            str(uuid.uuid4()), context.workspace_id,
            _anonymous_actor(context.workspace_id, context.user_id), event_type[:80],
            resource_type[:80], resource_id, _safe_metadata(metadata), dt.datetime.now(dt.timezone.utc),
        ))

    def list_audit_events(self, user_id: str, workspace_id: str | None = None,
                          limit: int = 100) -> list[AuditEvent]:
        context = self.get_workspace_context(user_id, workspace_id)
        require_permission(context, Permission.ACTIVITY_READ)
        return [event for event in reversed(self.audit_events)
                if event.workspace_id == context.workspace_id][:limit]

    def create_client(self, owner_user_id: str, name: str, internal_reference: str | None = None,
                      *, workspace_id: str | None = None) -> Client:
        context = self.get_workspace_context(owner_user_id, workspace_id)
        require_permission(context, Permission.CLIENT_WRITE)
        clean = str(name or "").strip()
        reference = (internal_reference or "").strip() or None
        if not clean or len(clean) > 160:
            raise ValueError("Mandantenname muss zwischen 1 und 160 Zeichen lang sein")
        if reference and len(reference) > 120:
            raise ValueError("Interne Referenz darf maximal 120 Zeichen lang sein")
        existing = next((client for client in self.clients.values()
                         if client.workspace_id == context.workspace_id and client.name == clean), None)
        if existing:
            return existing
        client = Client(str(uuid.uuid4()), owner_user_id, clean, reference,
                        workspace_id=context.workspace_id)
        self.clients[client.client_id] = client
        self.record_event(owner_user_id, "CLIENT_SAVED", "client", client.client_id,
                          workspace_id=context.workspace_id)
        return client

    def list_clients(self, owner_user_id: str, *, workspace_id: str | None = None) -> list[Client]:
        context = self.get_workspace_context(owner_user_id, workspace_id)
        require_permission(context, Permission.CLIENT_READ)
        return sorted((client for client in self.clients.values()
                       if client.workspace_id == context.workspace_id), key=lambda item: item.name)[:200]

    def get_client(self, owner_user_id: str, client_id: str) -> Client | None:
        client = self.clients.get(client_id)
        if not client:
            return None
        try:
            context = self.get_workspace_context(owner_user_id, client.workspace_id)
            require_permission(context, Permission.CLIENT_READ)
        except PermissionError:
            return None
        return client

    def delete_client(self, owner_user_id: str, client_id: str) -> bool:
        client = self.clients.get(client_id)
        if not client:
            return False
        try:
            context = self.get_workspace_context(owner_user_id, client.workspace_id)
            require_permission(context, Permission.CLIENT_WRITE)
        except PermissionError:
            return False
        self.record_event(owner_user_id, "CLIENT_DELETED", "client", client_id,
                          workspace_id=context.workspace_id)
        del self.clients[client_id]
        self.analyses = {key: value for key, value in self.analyses.items() if value.client_id != client_id}
        self.reports = {key: value for key, value in self.reports.items() if value.client_id != client_id}
        return True

    def save_analysis(self, snapshot: AnalysisSnapshot) -> AnalysisSnapshot:
        client = self.get_client(snapshot.owner_user_id, snapshot.client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        context = self.get_workspace_context(snapshot.owner_user_id, client.workspace_id)
        require_permission(context, Permission.ANALYSIS_WRITE)
        _json_payload(snapshot.mapping, "Spaltenzuordnung", 32_000)
        _json_payload(snapshot.result, "Analyseergebnis", 512_000)
        _json_payload(snapshot.insights, "Insights", 32_000)
        if len(snapshot.executive_summary) > 2_000 or len(snapshot.consultant_comment) > 2_000:
            raise ValueError("Berichtstext überschreitet das Speicherlimit")
        if any(item.workspace_id == context.workspace_id and item.client_id == snapshot.client_id
               and item.dataset_hash == snapshot.dataset_hash for item in self.analyses.values()):
            raise ValueError("Dieser Datenstand wurde für den Mandanten bereits gespeichert")
        saved = replace(snapshot, workspace_id=context.workspace_id)
        self.analyses[saved.analysis_id] = saved
        self.record_event(snapshot.owner_user_id, "ANALYSIS_SAVED", "analysis", saved.analysis_id,
                          {"quality_status": saved.quality_status}, context.workspace_id)
        return saved

    def list_analyses(self, owner_user_id: str, client_id: str) -> list[AnalysisSnapshot]:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        context = self.get_workspace_context(owner_user_id, client.workspace_id)
        require_permission(context, Permission.ANALYSIS_READ)
        return sorted((item for item in self.analyses.values()
                       if item.workspace_id == context.workspace_id and item.client_id == client_id),
                      key=lambda item: item.period_start, reverse=True)[:200]

    def get_analysis(self, owner_user_id: str, analysis_id: str) -> AnalysisSnapshot | None:
        analysis = self.analyses.get(analysis_id)
        if not analysis:
            return None
        try:
            context = self.get_workspace_context(owner_user_id, analysis.workspace_id)
            require_permission(context, Permission.ANALYSIS_READ)
        except PermissionError:
            return None
        return analysis

    def next_report_version(self, owner_user_id: str, client_id: str, analysis_id: str) -> int:
        analysis = self.get_analysis(owner_user_id, analysis_id)
        if not analysis or analysis.client_id != client_id:
            raise PermissionError("Analyse gehört nicht zu diesem Mandanten")
        context = self.get_workspace_context(owner_user_id, analysis.workspace_id)
        require_permission(context, Permission.REPORT_EXPORT)
        return 1 + max((report.report_version for report in self.reports.values()
                        if report.workspace_id == context.workspace_id and report.analysis_id == analysis_id), default=0)

    def save_report_metadata(self, owner_user_id: str, client_id: str, analysis_id: str,
                             settings: dict, report_hash: str | None) -> ReportMetadata:
        analysis = self.get_analysis(owner_user_id, analysis_id)
        if not analysis or analysis.client_id != client_id:
            raise PermissionError("Analyse gehört nicht zu diesem Mandanten")
        context = self.get_workspace_context(owner_user_id, analysis.workspace_id)
        require_permission(context, Permission.REPORT_EXPORT)
        _json_payload(settings, "Report-Einstellungen", 16_000)
        version = self.next_report_version(owner_user_id, client_id, analysis_id)
        report = ReportMetadata(str(uuid.uuid4()), owner_user_id, client_id, analysis_id,
                                version, settings, report_hash, workspace_id=context.workspace_id)
        self.reports[report.report_id] = report
        self.record_event(owner_user_id, "REPORT_EXPORTED", "report", report.report_id,
                          {"format": str(settings.get("format", "PDF"))[:20], "version": version},
                          context.workspace_id)
        return report

    def get_report(self, owner_user_id: str, report_id: str) -> ReportMetadata | None:
        report = self.reports.get(report_id)
        if not report:
            return None
        try:
            context = self.get_workspace_context(owner_user_id, report.workspace_id)
            require_permission(context, Permission.REPORT_READ)
        except PermissionError:
            return None
        return report

    def approve_report(self, owner_user_id: str, report_id: str) -> None:
        report = self.get_report(owner_user_id, report_id)
        if not report:
            raise PermissionError("Report ist nicht verfügbar")
        context = self.get_workspace_context(owner_user_id, report.workspace_id)
        require_permission(context, Permission.REPORT_APPROVE)
        self.record_event(owner_user_id, "REPORT_APPROVED", "report", report_id,
                          workspace_id=context.workspace_id)

    def sync_monitoring_findings(self, owner_user_id: str, client_id: str, signals) -> list[MonitoringFinding]:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        context = self.get_workspace_context(owner_user_id, client.workspace_id)
        require_permission(context, Permission.MONITORING_WRITE)
        now = dt.datetime.now(dt.timezone.utc)
        active = {signal.fingerprint for signal in signals}
        for signal in signals:
            key = (context.workspace_id, client_id, signal.fingerprint)
            old = self.monitoring_findings.get(key)
            status = "ONGOING" if old and old.status in {"NEW", "ONGOING"} else "NEW"
            self.monitoring_findings[key] = MonitoringFinding(
                old.finding_id if old else str(uuid.uuid4()), context.workspace_id, client_id,
                signal.rule_id, signal.fingerprint, signal.severity, status, signal.title,
                signal.detail, _safe_monitoring_evidence(signal.evidence), old.first_seen_at if old else now, now,
            )
        for key, old in list(self.monitoring_findings.items()):
            if key[:2] == (context.workspace_id, client_id) and key[2] not in active and old.status != "RESOLVED":
                self.monitoring_findings[key] = replace(old, status="RESOLVED", last_seen_at=now)
        self.record_event(owner_user_id, "MONITORING_UPDATED", "client", client_id,
                          {"active_findings": len(active)}, context.workspace_id)
        return self.list_monitoring_findings(owner_user_id, client_id)

    def list_monitoring_findings(self, owner_user_id: str, client_id: str) -> list[MonitoringFinding]:
        client = self.get_client(owner_user_id, client_id)
        if not client:
            raise PermissionError("Mandant gehört nicht zu diesem Workspace")
        context = self.get_workspace_context(owner_user_id, client.workspace_id)
        require_permission(context, Permission.MONITORING_READ)
        return [item for key, item in self.monitoring_findings.items()
                if key[:2] == (context.workspace_id, client_id)]
