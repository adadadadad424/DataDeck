"""Owner-scoped persistence. No method accepts or stores uploaded raw files."""

from __future__ import annotations

import json
import os
import uuid

from core.database import connect_postgres

from .authorization import require_analysis_access, require_client_access
from .models import AnalysisSnapshot, Client, ReportMetadata


def _client(row) -> Client | None:
    return Client(**row) if row else None


def _snapshot(row) -> AnalysisSnapshot | None:
    if not row:
        return None
    row = dict(row)
    row["result"] = row.pop("analysis_result")
    return AnalysisSnapshot(**row)


def _report(row) -> ReportMetadata | None:
    return ReportMetadata(**row) if row else None


def _json_payload(value, label: str, max_bytes: int) -> str:
    payload = json.dumps(value, ensure_ascii=False)
    if len(payload.encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} überschreitet das Speicherlimit")
    return payload


class PostgresConsultingStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        return connect_postgres(self.database_url)

    @staticmethod
    def _list_limit() -> int:
        try:
            value = int(os.getenv("MAX_HISTORY_ITEMS", "200"))
        except ValueError:
            value = 200
        return max(10, min(value, 1_000))

    def create_client(self, owner_user_id: str, name: str, internal_reference: str | None = None) -> Client:
        if not owner_user_id:
            raise PermissionError("Anmeldung erforderlich")
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 160:
            raise ValueError("Mandantenname muss zwischen 1 und 160 Zeichen lang sein")
        clean_reference = (internal_reference or "").strip() or None
        if clean_reference and len(clean_reference) > 120:
            raise ValueError("Interne Referenz darf maximal 120 Zeichen lang sein")
        client_id = str(uuid.uuid4())
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO consulting_clients (client_id, owner_user_id, name, internal_reference)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (client_id, owner_user_id, clean_name, clean_reference),
            )
            return _client(cursor.fetchone())  # type: ignore[return-value]

    def list_clients(self, owner_user_id: str) -> list[Client]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM consulting_clients WHERE owner_user_id = %s ORDER BY name LIMIT %s",
                (owner_user_id, self._list_limit()),
            )
            return [_client(row) for row in cursor.fetchall()]  # type: ignore[misc]

    def get_client(self, owner_user_id: str, client_id: str) -> Client | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM consulting_clients WHERE owner_user_id = %s AND client_id = %s",
                (owner_user_id, client_id),
            )
            return _client(cursor.fetchone())

    def delete_client(self, owner_user_id: str, client_id: str) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM consulting_clients WHERE owner_user_id = %s AND client_id = %s",
                (owner_user_id, client_id),
            )
            return cursor.rowcount == 1

    def save_analysis(self, snapshot: AnalysisSnapshot) -> AnalysisSnapshot:
        require_client_access(self, snapshot.owner_user_id, snapshot.client_id)
        mapping_json = _json_payload(snapshot.mapping, "Spaltenzuordnung", 32_000)
        result_json = _json_payload(snapshot.result, "Analyseergebnis", 512_000)
        insights_json = _json_payload(snapshot.insights, "Insights", 32_000)
        if len(snapshot.executive_summary) > 2_000 or len(snapshot.consultant_comment) > 2_000:
            raise ValueError("Berichtstext überschreitet das Speicherlimit")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO analysis_snapshots (
                       analysis_id, owner_user_id, client_id, dataset_hash, period_start, period_end,
                       mapping, analysis_result, quality_status, insights, executive_summary,
                       consultant_comment, analysis_version, uploaded_at
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s,COALESCE(%s,NOW()))
                   RETURNING *""",
                (
                    snapshot.analysis_id, snapshot.owner_user_id, snapshot.client_id,
                    snapshot.dataset_hash, snapshot.period_start, snapshot.period_end,
                    mapping_json, result_json, snapshot.quality_status,
                    insights_json, snapshot.executive_summary,
                    snapshot.consultant_comment, snapshot.analysis_version, snapshot.uploaded_at,
                ),
            )
            return _snapshot(cursor.fetchone())  # type: ignore[return-value]

    def list_analyses(self, owner_user_id: str, client_id: str) -> list[AnalysisSnapshot]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM analysis_snapshots
                   WHERE owner_user_id = %s AND client_id = %s ORDER BY period_start DESC LIMIT %s""",
                (owner_user_id, client_id, self._list_limit()),
            )
            return [_snapshot(row) for row in cursor.fetchall()]  # type: ignore[misc]

    def get_analysis(self, owner_user_id: str, analysis_id: str) -> AnalysisSnapshot | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM analysis_snapshots WHERE owner_user_id = %s AND analysis_id = %s",
                (owner_user_id, analysis_id),
            )
            return _snapshot(cursor.fetchone())

    def save_report_metadata(
        self, owner_user_id: str, client_id: str, analysis_id: str,
        settings: dict, report_hash: str | None,
    ) -> ReportMetadata:
        analysis = require_analysis_access(self, owner_user_id, analysis_id)
        if analysis.client_id != client_id:
            raise PermissionError("Analyse gehört nicht zu diesem Nutzer")
        settings_json = _json_payload(settings, "Report-Einstellungen", 16_000)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT COALESCE(MAX(report_version), 0) + 1 AS next_version
                   FROM report_versions WHERE owner_user_id = %s AND analysis_id = %s""",
                (owner_user_id, analysis_id),
            )
            version = int(cursor.fetchone()["next_version"])
            cursor.execute(
                """INSERT INTO report_versions (
                       report_id, owner_user_id, client_id, analysis_id, report_version, settings, report_hash
                   ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING *""",
                (str(uuid.uuid4()), owner_user_id, client_id, analysis_id, version, settings_json, report_hash),
            )
            return _report(cursor.fetchone())  # type: ignore[return-value]

    def next_report_version(self, owner_user_id: str, client_id: str, analysis_id: str) -> int:
        analysis = require_analysis_access(self, owner_user_id, analysis_id)
        if analysis.client_id != client_id:
            raise PermissionError("Analyse gehört nicht zu diesem Nutzer")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT COALESCE(MAX(report_version), 0) + 1 AS next_version
                   FROM report_versions WHERE owner_user_id = %s AND analysis_id = %s""",
                (owner_user_id, analysis_id),
            )
            return int(cursor.fetchone()["next_version"])

    def get_report(self, owner_user_id: str, report_id: str) -> ReportMetadata | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM report_versions WHERE owner_user_id = %s AND report_id = %s",
                (owner_user_id, report_id),
            )
            return _report(cursor.fetchone())


class InMemoryConsultingStore:
    """Behavioral test double with the same owner-isolation rules."""

    def __init__(self):
        self.clients: dict[str, Client] = {}
        self.analyses: dict[str, AnalysisSnapshot] = {}
        self.reports: dict[str, ReportMetadata] = {}

    def create_client(self, owner_user_id: str, name: str, internal_reference: str | None = None) -> Client:
        if not owner_user_id:
            raise PermissionError("Anmeldung erforderlich")
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 160:
            raise ValueError("Mandantenname muss zwischen 1 und 160 Zeichen lang sein")
        clean_reference = (internal_reference or "").strip() or None
        if clean_reference and len(clean_reference) > 120:
            raise ValueError("Interne Referenz darf maximal 120 Zeichen lang sein")
        client = Client(str(uuid.uuid4()), owner_user_id, clean_name, clean_reference)
        self.clients[client.client_id] = client
        return client

    def list_clients(self, owner_user_id: str) -> list[Client]:
        return sorted(
            (item for item in self.clients.values() if item.owner_user_id == owner_user_id),
            key=lambda item: item.name,
        )[:200]

    def get_client(self, owner_user_id: str, client_id: str) -> Client | None:
        client = self.clients.get(client_id)
        return client if client and client.owner_user_id == owner_user_id else None

    def delete_client(self, owner_user_id: str, client_id: str) -> bool:
        if self.get_client(owner_user_id, client_id) is None:
            return False
        del self.clients[client_id]
        self.analyses = {key: value for key, value in self.analyses.items() if value.client_id != client_id}
        self.reports = {key: value for key, value in self.reports.items() if value.client_id != client_id}
        return True

    def save_analysis(self, snapshot: AnalysisSnapshot) -> AnalysisSnapshot:
        require_client_access(self, snapshot.owner_user_id, snapshot.client_id)
        _json_payload(snapshot.mapping, "Spaltenzuordnung", 32_000)
        _json_payload(snapshot.result, "Analyseergebnis", 512_000)
        _json_payload(snapshot.insights, "Insights", 32_000)
        if len(snapshot.executive_summary) > 2_000 or len(snapshot.consultant_comment) > 2_000:
            raise ValueError("Berichtstext überschreitet das Speicherlimit")
        if any(
            item.owner_user_id == snapshot.owner_user_id
            and item.client_id == snapshot.client_id
            and item.dataset_hash == snapshot.dataset_hash
            for item in self.analyses.values()
        ):
            raise ValueError("Dieser Datenstand wurde für den Mandanten bereits gespeichert")
        self.analyses[snapshot.analysis_id] = snapshot
        return snapshot

    def list_analyses(self, owner_user_id: str, client_id: str) -> list[AnalysisSnapshot]:
        return sorted(
            (item for item in self.analyses.values() if item.owner_user_id == owner_user_id and item.client_id == client_id),
            key=lambda item: item.period_start,
            reverse=True,
        )[:200]

    def get_analysis(self, owner_user_id: str, analysis_id: str) -> AnalysisSnapshot | None:
        snapshot = self.analyses.get(analysis_id)
        return snapshot if snapshot and snapshot.owner_user_id == owner_user_id else None

    def save_report_metadata(
        self, owner_user_id: str, client_id: str, analysis_id: str,
        settings: dict, report_hash: str | None,
    ) -> ReportMetadata:
        analysis = require_analysis_access(self, owner_user_id, analysis_id)
        if analysis.client_id != client_id:
            raise PermissionError("Analyse gehört nicht zu diesem Nutzer")
        version = 1 + max(
            (item.report_version for item in self.reports.values() if item.owner_user_id == owner_user_id and item.analysis_id == analysis_id),
            default=0,
        )
        report = ReportMetadata(
            str(uuid.uuid4()), owner_user_id, client_id, analysis_id, version, settings, report_hash
        )
        self.reports[report.report_id] = report
        return report

    def get_report(self, owner_user_id: str, report_id: str) -> ReportMetadata | None:
        report = self.reports.get(report_id)
        return report if report and report.owner_user_id == owner_user_id else None

    def next_report_version(self, owner_user_id: str, client_id: str, analysis_id: str) -> int:
        analysis = require_analysis_access(self, owner_user_id, analysis_id)
        if analysis.client_id != client_id:
            raise PermissionError("Analyse gehört nicht zu diesem Nutzer")
        return 1 + max(
            (
                item.report_version for item in self.reports.values()
                if item.owner_user_id == owner_user_id and item.analysis_id == analysis_id
            ),
            default=0,
        )
