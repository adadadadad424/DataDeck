"""RBAC, audit, monitoring and scenario regression tests."""

import datetime as dt
import calendar
import unittest
import uuid
from dataclasses import replace

from consulting.models import AnalysisSnapshot
from consulting.monitoring import evaluate_monitoring, reconcile_monitoring
from consulting.rbac import Permission, WorkspaceRole
from consulting.scenario import calculate_scenario
from consulting.store import InMemoryConsultingStore
from core.demo_data import DEMO_SEGMENTS, demo_financials


def snapshot(user_id, client_id, month, revenue, profit, margin, segments=None):
    return AnalysisSnapshot(
        str(uuid.uuid4()), user_id, client_id, f"{month:064x}",
        dt.date(2026, month, 1), dt.date(2026, month, calendar.monthrange(2026, month)[1]), {},
        {"revenue": revenue, "profit": profit, "margin": margin,
         "profit_available": True, "segments": segments or []}, "good",
    )


class EnterpriseTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryConsultingStore()
        self.owner = str(uuid.uuid4())
        self.partner = str(uuid.uuid4())
        self.consultant = str(uuid.uuid4())
        self.viewer = str(uuid.uuid4())
        self.outsider = str(uuid.uuid4())
        self.workspace = self.store.create_workspace(self.owner, "Beratung Nord")
        self.store.add_member(self.owner, self.workspace.workspace_id, self.partner, "PARTNER")
        self.store.add_member(self.owner, self.workspace.workspace_id, self.consultant, "CONSULTANT")
        self.store.add_member(self.owner, self.workspace.workspace_id, self.viewer, "VIEWER")

    def test_role_matrix_is_explicit(self):
        self.assertTrue(self.store.get_workspace_context(self.owner, self.workspace.workspace_id).can(Permission.BILLING_MANAGE))
        self.assertTrue(self.store.get_workspace_context(self.partner, self.workspace.workspace_id).can(Permission.REPORT_APPROVE))
        self.assertTrue(self.store.get_workspace_context(self.consultant, self.workspace.workspace_id).can(Permission.REPORT_EXPORT))
        self.assertFalse(self.store.get_workspace_context(self.viewer, self.workspace.workspace_id).can(Permission.REPORT_EXPORT))

    def test_viewer_cannot_write_client(self):
        with self.assertRaises(PermissionError):
            self.store.create_client(self.viewer, "Verboten", workspace_id=self.workspace.workspace_id)

    def test_viewer_cannot_save_analysis_or_export_report(self):
        client = self.store.create_client(self.owner, "Geschützt", workspace_id=self.workspace.workspace_id)
        report_source = self.store.save_analysis(snapshot(self.owner, client.client_id, 1, 100, 20, 20))
        with self.assertRaises(PermissionError):
            self.store.save_analysis(snapshot(self.viewer, client.client_id, 2, 100, 20, 20))
        with self.assertRaises(PermissionError):
            self.store.save_report_metadata(self.viewer, client.client_id,
                                            report_source.analysis_id, {"format": "PPTX"}, None)

    def test_consultant_cannot_manage_workspace_or_billing(self):
        context = self.store.get_workspace_context(self.consultant, self.workspace.workspace_id)
        self.assertFalse(context.can(Permission.BILLING_MANAGE))
        with self.assertRaises(PermissionError):
            self.store.add_member(self.consultant, self.workspace.workspace_id, self.outsider, "PARTNER")

    def test_consultant_can_write_but_not_approve(self):
        client = self.store.create_client(self.consultant, "Mandant", workspace_id=self.workspace.workspace_id)
        saved = self.store.save_analysis(snapshot(self.consultant, client.client_id, 1, 100, 20, 20))
        report = self.store.save_report_metadata(self.consultant, client.client_id, saved.analysis_id,
                                                 {"format": "PPTX"}, "a" * 64)
        with self.assertRaises(PermissionError):
            self.store.approve_report(self.consultant, report.report_id)
        self.store.approve_report(self.partner, report.report_id)

    def test_idor_is_denied(self):
        client = self.store.create_client(self.owner, "Privat", workspace_id=self.workspace.workspace_id)
        self.assertIsNone(self.store.get_client(self.outsider, client.client_id))

    def test_forged_owner_role_has_no_effect(self):
        forged = self.store.get_workspace_context(self.viewer, self.workspace.workspace_id)
        self.assertEqual(forged.role, WorkspaceRole.VIEWER)
        with self.assertRaises(PermissionError):
            self.store.add_member(self.viewer, self.workspace.workspace_id, self.outsider, "OWNER")

    def test_audit_is_anonymous_and_drops_sensitive_metadata(self):
        self.store.record_event(self.owner, "LOGIN", metadata={
            "email": "person@example.com", "result": "person@example.com",
            "provider": "person@example.com", "rows_processed": 12,
        },
                                workspace_id=self.workspace.workspace_id)
        events = self.store.list_audit_events(self.partner, self.workspace.workspace_id)
        self.assertRegex(events[0].anonymous_actor_id, r"^[0-9a-f]{32}$")
        self.assertNotIn("email", events[0].metadata)
        self.assertNotIn("person@example.com", str(events[0]))
        self.assertEqual(events[0].metadata, {"rows_processed": 12})
        with self.assertRaises(PermissionError):
            self.store.list_audit_events(self.viewer, self.workspace.workspace_id)

    def test_monitoring_rules_are_deterministic(self):
        client = self.store.create_client(self.owner, "Monitor", workspace_id=self.workspace.workspace_id)
        segments = [{"category": "Enterprise", "revenue": 80}]
        history = [
            snapshot(self.owner, client.client_id, 1, 120, 20, 16.7, segments),
            snapshot(self.owner, client.client_id, 2, 100, -5, -5, segments),
            snapshot(self.owner, client.client_id, 3, 70, -10, -14.3, segments),
        ]
        rules = {item.rule_id for item in evaluate_monitoring(history)}
        self.assertTrue({"negative_profit", "revenue_drop", "margin_drop",
                         "consecutive_negative_periods", "revenue_downtrend"}.issubset(rules))

    def test_scenario_is_math_not_forecast(self):
        result = calculate_scenario({"revenue": 1000, "profit": 200, "profit_available": True},
                                    revenue_change_pct=10, cost_change_pct=5)
        self.assertEqual(result.disclaimer, "Szenario, keine Prognose")
        self.assertAlmostEqual(result.scenario["revenue"], 1100)
        self.assertAlmostEqual(result.scenario["costs"], 840)
        self.assertAlmostEqual(result.scenario["profit"], 260)

    def test_revenue_only_scenario_does_not_invent_profit(self):
        result = calculate_scenario({"revenue": 1000, "profit_available": False}, revenue_change_pct=5)
        self.assertIsNone(result.scenario["profit"])
        self.assertIsNone(result.scenario["margin"])

    def test_monitoring_lifecycle(self):
        client = self.store.create_client(self.owner, "Lifecycle", workspace_id=self.workspace.workspace_id)
        history = [snapshot(self.owner, client.client_id, 1, 100, 10, 10),
                   snapshot(self.owner, client.client_id, 2, 70, -5, -7)]
        first = evaluate_monitoring(history)
        second = reconcile_monitoring(first, evaluate_monitoring(history))
        self.assertTrue(all(item.status == "ONGOING" for item in second))
        resolved = reconcile_monitoring(second, [])
        self.assertTrue(all(item.status == "RESOLVED" for item in resolved))
        stored = self.store.sync_monitoring_findings(self.owner, client.client_id, first)
        self.assertTrue(stored)
        self.assertTrue(any(item.evidence for item in stored))

    def test_monitoring_does_not_invent_trends_across_gaps_or_partial_months(self):
        client = self.store.create_client(self.owner, "Gaps", workspace_id=self.workspace.workspace_id)
        january = snapshot(self.owner, client.client_id, 1, 120, 20, 16.7)
        march = snapshot(self.owner, client.client_id, 3, 100, -5, -5)
        april = snapshot(self.owner, client.client_id, 4, 70, -10, -14.3)
        rules = {item.rule_id for item in evaluate_monitoring([january, march, april])}
        self.assertNotIn("revenue_downtrend", rules)
        self.assertIn("revenue_drop", rules)
        partial = replace(april, period_end=dt.date(2026, 4, 15))
        partial_rules = {item.rule_id for item in evaluate_monitoring([january, march, partial])}
        self.assertNotIn("revenue_drop", partial_rules)
        self.assertNotIn("revenue_downtrend", partial_rules)

    def test_monitoring_never_persists_segment_label_in_signal(self):
        client = self.store.create_client(self.owner, "Privacy", workspace_id=self.workspace.workspace_id)
        signal = evaluate_monitoring([snapshot(
            self.owner, client.client_id, 1, 100, 20, 20,
            [{"category": "person@example.com", "revenue": 80}],
        )])
        self.assertNotIn("person@example.com", str(signal))
        stored = self.store.sync_monitoring_findings(self.owner, client.client_id, signal)
        self.assertNotIn("person@example.com", str(stored))
        self.assertTrue(all(set(item.evidence) <= {"share_pct"} for item in stored))

    def test_monitoring_reads_complete_months_from_one_export(self):
        client = self.store.create_client(self.owner, "Year Export", workspace_id=self.workspace.workspace_id)
        source = snapshot(self.owner, client.client_id, 3, 290, 10, 3.4)
        source = replace(source, period_start=dt.date(2026, 1, 1), result={
            **source.result,
            "time_series": [
                {"period": "2026-01", "revenue": 120, "profit": 20, "margin": 16.7, "partial": False},
                {"period": "2026-02", "revenue": 100, "profit": -5, "margin": -5, "partial": False},
                {"period": "2026-03", "revenue": 70, "profit": -10, "margin": -14.3, "partial": False},
                {"period": "2026-04", "revenue": 30, "profit": -8, "margin": -26.7, "partial": True},
            ],
        })
        rules = {item.rule_id for item in evaluate_monitoring([source])}
        self.assertIn("revenue_downtrend", rules)
        self.assertIn("consecutive_negative_periods", rules)
        self.assertIn("revenue_drop", rules)

    def test_public_demo_financials_are_deterministic_and_balanced(self):
        overall = demo_financials("Gesamt", 12)
        parts = [demo_financials(segment, 12) for segment in DEMO_SEGMENTS[1:]]
        self.assertEqual(len(overall), 12)
        self.assertAlmostEqual(overall["Umsatz"].sum(), sum(part["Umsatz"].sum() for part in parts))
        self.assertAlmostEqual(overall["Kosten"].sum(), sum(part["Kosten"].sum() for part in parts))
        self.assertAlmostEqual(overall["Gewinn"].sum(), overall["Umsatz"].sum() - overall["Kosten"].sum())
        with self.assertRaises(ValueError):
            demo_financials("Fremddaten", 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
