import copy
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from core.flashduty import FlashdutyAdapter, parse_flashduty
from core.localization import overall
from core.registry import load_services

SERVICE = load_services(Path(__file__).resolve().parents[1] / "services")["ds"]
ACTIVE = {
    "page": {
        "page_id": int(SERVICE.page_id),
        "custom_domain": "status.deepseek.com",
        "components": [{"component_id": "api", "name": "API"}],
    },
    "active_changes": [],
}


def change(status="investigating", impact="degraded", **values):
    return {
        "change_id": 1,
        "type": "incident",
        "title": "API 性能下降",
        "status": status,
        "affected_components": [{"component_id": "api", "status": impact}],
        "description": "正在调查",
        "start_at_seconds": 1790883605,
        **values,
    }


class FlashdutyTests(unittest.TestCase):
    def test_empty_active_list_is_healthy_but_missing_list_is_rejected(self):
        data = parse_flashduty(SERVICE, ACTIVE)
        self.assertEqual(overall(data)[1], "ok")
        self.assertTrue(data.incidents_known)
        self.assertFalse(data.history_known)
        missing = copy.deepcopy(ACTIVE)
        del missing["active_changes"]
        with self.assertRaises(ValueError):
            parse_flashduty(SERVICE, missing)

    def test_wrong_page_identity_is_rejected(self):
        for key, value in (("page_id", 1), ("custom_domain", "example.com")):
            data = copy.deepcopy(ACTIVE)
            data["page"][key] = value
            with self.assertRaises(ValueError):
                parse_flashduty(SERVICE, data)

    def test_worst_current_impact_wins_and_latest_update_is_shown(self):
        changes = [
            change(impact="full_outage"),
            change(
                change_id=2,
                updates=[
                    {"at_seconds": 1790890475, "description": "最新进展"},
                    {"at_seconds": 1790883605, "description": "早期进展"},
                ],
            ),
        ]
        data = parse_flashduty(SERVICE, {**ACTIVE, "active_changes": changes})
        self.assertEqual(data.components[0].status, "major_outage")
        self.assertEqual(data.indicator, "critical")
        self.assertEqual(data.incidents[0].body, "最新进展")

    def test_unknown_impact_and_missing_impacts_do_not_claim_healthy(self):
        for row in (change(impact="new_status"), change(affected_components=None)):
            data = parse_flashduty(SERVICE, {**ACTIVE, "active_changes": [row]})
            self.assertEqual(data.components[0].status, "unknown")
            self.assertNotEqual(overall(data)[1], "ok")

    def test_resolved_history_cannot_override_current_status(self):
        data = parse_flashduty(SERVICE, ACTIVE, {"items": [change("resolved", "full_outage")]})
        self.assertEqual(data.components[0].status, "operational")
        self.assertEqual(len(data.history), 1)
        self.assertFalse(data.incidents)

    def test_scheduled_maintenance_is_separate_from_current_outage(self):
        row = change("scheduled", "maintenance", type="maintenance", end_at_seconds=1790890475)
        data = parse_flashduty(SERVICE, {**ACTIVE, "active_changes": [row]})
        self.assertEqual(data.components[0].status, "operational")
        self.assertFalse(data.incidents)
        self.assertTrue(data.maintenance[0].scheduled_until)
        row["status"] = "ongoing"
        data = parse_flashduty(SERVICE, {**ACTIVE, "active_changes": [row]})
        self.assertEqual(data.indicator, "maintenance")
        self.assertEqual(data.maintenance[0].status, "in_progress")

    def test_hidden_sections_are_not_displayed(self):
        active = copy.deepcopy(ACTIVE)
        active["page"]["components"][0]["section_id"] = "hidden"
        active["page"]["sections"] = [{"section_id": "hidden", "name": "Hidden", "hide_all": True}]
        data = parse_flashduty(SERVICE, active)
        self.assertFalse(data.components)
        self.assertNotEqual(overall(data)[1], "ok")


class FlashdutyFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_failure_keeps_current_status_and_passes_proxy(self):
        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                response = AsyncMock()
                if url.endswith("/summary/active"):
                    response.__aenter__.return_value = response
                    response.raise_for_status = lambda: None
                    response.json.return_value = {"data": ACTIVE}
                else:
                    response.__aenter__.side_effect = TimeoutError()
                return response

        session = Session()
        data = await FlashdutyAdapter().fetch(SERVICE, session, "http://localhost:7890")
        self.assertEqual(overall(data)[1], "ok")
        self.assertFalse(data.history_known)
        self.assertTrue(all(k["proxy"] == "http://localhost:7890" for _, k in session.calls))
