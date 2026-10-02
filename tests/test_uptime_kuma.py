import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from core.client import StatusClient
from core.localization import overall
from core.registry import load_services
from core.uptime_kuma import StatusAccessError, UptimeKumaAdapter, parse_uptime_kuma

SERVICE = load_services(Path(__file__).resolve().parents[1] / "services")["sl"]
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
PAGE = {
    "publicGroupList": [
        {"name": "Central Servers", "monitorList": [{"id": 1, "name": "Roubaix 1"}]}
    ],
    "incident": None,
    "maintenanceList": [],
}


def beats(*statuses):
    return {
        "heartbeatList": {
            "1": [
                {
                    "time": (NOW - timedelta(minutes=len(statuses) - i - 1)).isoformat(),
                    "status": code,
                }
                for i, code in enumerate(statuses)
            ]
        },
        "uptimeList": {"1_24": 0.9993},
    }


class KumaParsingTests(unittest.TestCase):
    def test_states_and_separate_percent_window(self):
        data = parse_uptime_kuma(SERVICE, PAGE, beats(0, 2, 3, 1), NOW)
        self.assertEqual(data.indicator, "none")
        self.assertEqual(data.components[0].group, "中央服务器")
        self.assertEqual([tone for _, tone in data.uptime["1"].days], ["bad", "warn", "info", "ok"])
        self.assertEqual(data.uptime["1"].percent, "99.93")
        self.assertEqual(data.uptime["1"].percent_label, "24h 可用")
        self.assertIn("最近 4 次", data.uptime["1"].period_label)

    def test_missing_heartbeat_is_unknown_not_green(self):
        data = parse_uptime_kuma(SERVICE, PAGE, beats(), NOW)
        self.assertEqual(data.components[0].status, "unknown")
        self.assertEqual(data.indicator, "unknown")
        self.assertEqual(data.uptime, {})

    def test_all_down_pending_and_maintenance(self):
        for status, indicator in (
            (0, "all_down"),
            (2, "minor"),
            (3, "maintenance"),
            (99, "unknown"),
        ):
            data = parse_uptime_kuma(SERVICE, PAGE, beats(status), NOW)
            self.assertEqual(data.indicator, indicator)
            self.assertNotEqual(overall(data)[1], "ok")

    def test_stale_and_future_heartbeats_are_unknown(self):
        for offset in (16, -6):
            payload = beats(1)
            payload["heartbeatList"]["1"][0]["time"] = (NOW - timedelta(minutes=offset)).isoformat()
            data = parse_uptime_kuma(SERVICE, PAGE, payload, NOW)
            self.assertEqual(data.components[0].status, "unknown")
            self.assertTrue(any("15 分钟" in warning for warning in data.warnings))

    def test_sorting_and_naive_utc_time(self):
        payload = beats(0, 1)
        payload["heartbeatList"]["1"].reverse()
        payload["heartbeatList"]["1"][0]["time"] = "2026-10-02 12:00:00.000"
        data = parse_uptime_kuma(SERVICE, PAGE, payload, NOW)
        self.assertEqual(data.components[0].status, "operational")

    def test_unknown_monitor_does_not_hide_known_outage(self):
        page = copy.deepcopy(PAGE)
        page["publicGroupList"][0]["monitorList"].append({"id": 2, "name": "Strasbourg 1"})
        data = parse_uptime_kuma(SERVICE, page, beats(0), NOW)
        self.assertEqual(data.indicator, "partial_down")

    def test_recent_samples_are_not_filled_into_daily_history(self):
        payload = beats(*(1 for _ in range(120)))
        payload["heartbeatList"]["1"].pop(-2)
        data = parse_uptime_kuma(SERVICE, PAGE, payload, NOW)
        self.assertEqual(len(data.uptime["1"].days), 100)
        self.assertEqual(data.uptime["1"].days[-1][0], NOW.isoformat())
        self.assertEqual(data.uptime["1"].days[-2][0], (NOW - timedelta(minutes=2)).isoformat())

    def test_invalid_percent_is_omitted(self):
        for ratio in (None, "100%", 2, -1, True, float("nan")):
            payload = beats(1)
            payload["uptimeList"]["1_24"] = ratio
            self.assertEqual(parse_uptime_kuma(SERVICE, PAGE, payload, NOW).uptime["1"].percent, "")

    def test_announcements_are_not_assumed_resolved_by_color(self):
        notice = {
            "id": 1,
            "title": "Notice",
            "content": "Body",
            "style": "primary",
            "createdDate": "2026-10-02 11:00:00",
        }
        for field, value in (("incident", notice), ("incidents", [notice])):
            page = {**PAGE, field: value}
            data = parse_uptime_kuma(SERVICE, page, beats(1), NOW)
            self.assertEqual(data.incidents[0].status, "notice")
            self.assertTrue(data.incidents_known)
            self.assertFalse(data.history_known)

    def test_empty_vs_unavailable_notice_fields(self):
        data = parse_uptime_kuma(SERVICE, PAGE, beats(1), NOW)
        self.assertTrue(data.incidents_known)
        self.assertTrue(data.maintenance_known)
        page = {"publicGroupList": PAGE["publicGroupList"]}
        data = parse_uptime_kuma(SERVICE, page, beats(1), NOW)
        self.assertFalse(data.incidents_known)
        self.assertFalse(data.maintenance_known)

    def test_maintenance_ids_cannot_collide_with_announcements(self):
        page = {
            **PAGE,
            "incident": {"id": 1},
            "maintenanceList": [{"id": 1, "title": "Work", "description": "Restart"}],
        }
        data = parse_uptime_kuma(SERVICE, page, beats(3), NOW)
        self.assertNotEqual(data.incidents[0].id, data.maintenance[0].id)
        self.assertEqual(data.maintenance[0].status, "under_maintenance")

    def test_invalid_payload_rejected(self):
        for page, heartbeat in (({}, beats(1)), (PAGE, {}), ([], beats(1))):
            with self.assertRaises(ValueError):
                parse_uptime_kuma(SERVICE, page, heartbeat, NOW)


def response(payload=None, status=200, headers=None):
    result = Mock(status=status, headers=headers or {})
    result.json = AsyncMock(return_value=payload)
    context = AsyncMock()
    context.__aenter__.return_value = result
    return context, result


class KumaAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_endpoints_and_proxy(self):
        page, _ = response(PAGE)
        heartbeat, _ = response(beats(1))
        session = Mock(get=Mock(side_effect=[page, heartbeat]))
        data = await UptimeKumaAdapter().fetch(SERVICE, session, "http://proxy.example:8080")
        self.assertEqual(len(data.components), 1)
        self.assertEqual(
            [c.args[0] for c in session.get.call_args_list],
            [
                "https://status.scpslgame.com/api/status-page/nw",
                "https://status.scpslgame.com/api/status-page/heartbeat/nw",
            ],
        )
        self.assertTrue(
            all(
                c.kwargs["proxy"] == "http://proxy.example:8080" for c in session.get.call_args_list
            )
        )

    async def test_challenge_never_parsed_as_status(self):
        for status, headers in ((403, {}), (503, {"cf-mitigated": "challenge"})):
            blocked, result = response(status=status, headers=headers)
            session = Mock(get=Mock(return_value=blocked))
            with self.assertRaises(StatusAccessError):
                await UptimeKumaAdapter().fetch(SERVICE, session, "")
            result.json.assert_not_awaited()

    async def test_disable_history_retains_current_state(self):
        data = parse_uptime_kuma(SERVICE, PAGE, beats(1), NOW)
        with patch("core.client.UptimeKumaAdapter.fetch", AsyncMock(return_value=data)):
            result = await StatusClient().fetch(SERVICE, show_uptime=False)
        self.assertEqual(result.components[0].status, "operational")
        self.assertFalse(result.uptime)


if __name__ == "__main__":
    unittest.main()
