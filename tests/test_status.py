import asyncio
import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.client import StatusClient
from core.localization import display_time, overall, state
from core.models import Notice
from core.registry import load_services
from core.statuspage import parse_statuspage
from core.translation import EventTranslator
from core.uptime import parse_incident_io_uptime, parse_statuspage_uptime

ROOT = Path(__file__).resolve().parents[1]
SERVICES = load_services(ROOT / "services")
SUMMARY = {
    "status": {"indicator": "none"},
    "components": [
        {"id": "a", "name": "API", "status": "operational", "position": 1},
    ],
}


def snapshot(**changes):
    return replace(parse_statuspage(SERVICES["gpt"], copy.deepcopy(SUMMARY), None), **changes)


class ParsingTests(unittest.TestCase):
    def test_missing_incidents_are_unknown(self):
        data = snapshot()
        self.assertFalse(data.incidents_known)
        self.assertFalse(data.maintenance_known)
        self.assertTrue(data.warnings)

    def test_openai_active_events_are_taken_from_event_api(self):
        data = parse_statuspage(
            SERVICES["gpt"],
            SUMMARY,
            {
                "incidents": [
                    {"id": "active", "status": "investigating", "name": "Active"},
                    {"id": "done", "status": "resolved", "name": "Done"},
                ]
            },
        )
        self.assertEqual([n.id for n in data.incidents], ["active"])
        self.assertEqual([n.id for n in data.history], ["done"])
        self.assertNotEqual(overall(data)[1], "ok")

    def test_summary_events_override_older_history(self):
        summary = {**SUMMARY, "incidents": []}
        data = parse_statuspage(
            SERVICES["claude"], summary, {"incidents": [{"id": "old", "status": "investigating"}]}
        )
        self.assertEqual(data.incidents, ())

    def test_latest_update_and_unknown_status(self):
        summary = {
            **SUMMARY,
            "incidents": [
                {
                    "id": "1",
                    "status": "new_status",
                    "incident_updates": [
                        {"created_at": "2026-01-01T00:00:00Z", "body": "old"},
                        {"created_at": "2026-01-02T00:00:00Z", "body": "new"},
                    ],
                }
            ],
        }
        data = parse_statuspage(SERVICES["gpt"], summary, None)
        self.assertEqual(data.incidents[0].body, "new")
        self.assertEqual(state("new_status")[1], "unknown")

    def test_component_fault_overrides_green_indicator(self):
        summary = copy.deepcopy(SUMMARY)
        summary["components"][0]["status"] = "major_outage"
        self.assertNotEqual(overall(parse_statuspage(SERVICES["gpt"], summary, None))[1], "ok")

    def test_groups_not_counted_as_components(self):
        summary = copy.deepcopy(SUMMARY)
        summary["components"][0]["group_id"] = "group"
        summary["components"].append({"id": "group", "name": "APIs", "group": True})
        data = parse_statuspage(SERVICES["gpt"], summary, None)
        self.assertEqual(len(data.components), 1)
        self.assertEqual(data.components[0].group, "APIs")

    def test_maintenance_preserves_window(self):
        summary = {
            **SUMMARY,
            "scheduled_maintenances": [
                {
                    "id": "m",
                    "status": "scheduled",
                    "scheduled_for": "2026-01-01T00:00:00Z",
                    "scheduled_until": "2026-01-01T01:00:00Z",
                },
                {"id": "done", "status": "completed"},
            ],
        }
        data = parse_statuspage(SERVICES["gpt"], summary, None)
        self.assertEqual(len(data.maintenance), 1)
        self.assertEqual(display_time(data.maintenance[0].scheduled_for), "01-01 08:00")

    def test_invalid_summary_rejected(self):
        for payload in ([], {}, {"status": {}, "components": "invalid"}):
            with self.assertRaises(ValueError):
                parse_statuspage(SERVICES["gpt"], payload, None)

    def test_claude_history_gaps_and_not_started_are_unknown(self):
        data = {
            "timelines": {
                "a": {
                    "component": {"startDate": "2026-01-02"},
                    "days": [
                        {"date": "2026-01-01", "outages": {}},
                        {"date": "2026-01-02", "outages": {"d": 50}},
                        {"date": "2026-01-04", "outages": {"m": 100}},
                    ],
                }
            }
        }
        self.assertEqual(
            [tone for _, tone in parse_statuspage_uptime(data)["a"].days],
            ["unknown", "warn", "unknown", "bad"],
        )

    def test_openai_history_intervals_and_partial_first_day(self):
        obj = {
            "summary": {"history_window_days": 3, "components": []},
            "initialNow": {"isoDate": "2026-01-03T12:00:00Z"},
            "data": {
                "component_uptimes": [
                    {"component_id": "a", "data_available_since": "2026-01-01T12:00:00Z"}
                ],
                "component_impacts": [
                    {
                        "component_id": "a",
                        "start_at": "2026-01-02T23:00:00Z",
                        "end_at": "2026-01-03T00:00:00Z",
                        "status": "major_outage",
                    }
                ],
            },
        }
        html = (
            "<script>self.__next_f.push("
            + json.dumps([1, "a:" + json.dumps(obj) + "\n"])
            + ")</script>"
        )
        data = parse_incident_io_uptime(html)
        self.assertEqual([tone for _, tone in data["a"].days], ["unknown", "bad", "ok"])
        self.assertEqual(parse_incident_io_uptime("page changed"), {})


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_requests_share_cache(self):
        client = StatusClient()
        fetch = AsyncMock(return_value=snapshot())
        with patch("core.client.StatuspageAdapter.fetch", fetch):
            results = await asyncio.gather(
                *(client.fetch(SERVICES["gpt"], show_uptime=False) for _ in range(6))
            )
        self.assertEqual(fetch.await_count, 1)
        self.assertTrue(all(r is results[0] for r in results))

    async def test_no_cache_and_expired_failure_does_not_return_old_green(self):
        client = StatusClient()
        fetch = AsyncMock(side_effect=[snapshot(), RuntimeError("offline")])
        with patch("core.client.StatuspageAdapter.fetch", fetch):
            await client.fetch(SERVICES["gpt"], cache_seconds=0, show_uptime=False)
            with self.assertRaises(RuntimeError):
                await client.fetch(SERVICES["gpt"], cache_seconds=0, show_uptime=False)

    async def test_history_failure_keeps_current_snapshot(self):
        fetch = AsyncMock(return_value=snapshot())
        with (
            patch("core.client.StatuspageAdapter.fetch", fetch),
            patch("core.client.fetch_uptime", AsyncMock(side_effect=ValueError("changed"))),
        ):
            data = await StatusClient().fetch(SERVICES["gpt"])
        self.assertEqual(len(data.components), 1)
        self.assertEqual(data.uptime, {})

    async def test_translation_cache_does_not_mutate_input(self):
        translator = EventTranslator()
        source = Notice("a", "Error", "Something failed", "investigating", "")
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(
                    completion_text='[{"index":0,"title":"发生错误","body":"部分请求失败"}]'
                )
            )
        )
        result = await translator.translate((source,), provider, 5)
        await translator.translate((source,), provider, 5)
        self.assertTrue(result[0].translated)
        self.assertEqual(source.title, "Error")
        self.assertEqual(provider.text_chat.await_count, 1)
        self.assertEqual(provider.text_chat.call_args.kwargs["contexts"], [])

    async def test_invalid_translation_not_cached(self):
        translator = EventTranslator()
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(
                    completion_text='[{"index":0,"title":"标题","body":""}]'
                )
            )
        )
        with self.assertRaises(ValueError):
            await translator.translate(
                (Notice("a", "Error", "Important details", "", ""),), provider, 5
            )
        self.assertFalse(translator.cache)


if __name__ == "__main__":
    unittest.main()
