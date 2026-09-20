"""Central owner checks for every persistent consultant object."""

from __future__ import annotations


def require_authenticated_user(owner_user_id: str) -> str:
    user_id = str(owner_user_id or "").strip()
    if not user_id:
        raise PermissionError("Anmeldung erforderlich")
    return user_id


def require_client_access(store, owner_user_id: str, client_id: str):
    user_id = require_authenticated_user(owner_user_id)
    client = store.get_client(user_id, client_id)
    if client is None:
        raise PermissionError("Mandant gehört nicht zu diesem Nutzer")
    return client


def require_analysis_access(store, owner_user_id: str, analysis_id: str):
    user_id = require_authenticated_user(owner_user_id)
    analysis = store.get_analysis(user_id, analysis_id)
    if analysis is None:
        raise PermissionError("Analyse gehört nicht zu diesem Nutzer")
    return analysis


def require_report_access(store, owner_user_id: str, report_id: str):
    user_id = require_authenticated_user(owner_user_id)
    report = store.get_report(user_id, report_id)
    if report is None:
        raise PermissionError("Report gehört nicht zu diesem Nutzer")
    return report
