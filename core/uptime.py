"""仅解析官方页面提供的历史，不用近期事件列表补出正常日期。"""

import json
import re
from datetime import datetime, time, timedelta, timezone

from .models import Uptime


def _datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_statuspage_uptime(data):
    values = {
        row["component"]: str(row["ninety"]) for row in data.get("values", []) if "ninety" in row
    }
    result = {}
    for key, timeline in data.get("timelines", {}).items():
        start = timeline.get("component", {}).get("startDate") or "9999-12-31"
        rows = {row["date"]: row for row in timeline.get("days", [])}
        if not rows:
            continue
        first, last = min(rows), max(rows)
        day, end = datetime.fromisoformat(first).date(), datetime.fromisoformat(last).date()
        if (end - day).days > 366:
            raise ValueError("官方历史时间范围异常")
        days = []
        while day <= end:
            date = day.isoformat()
            row = rows.get(date)
            if not row or date < start or not isinstance(row.get("outages"), dict):
                tone = "unknown"
            else:
                outages = {key for key, value in row["outages"].items() if value}
                if outages & {"m", "p"}:
                    tone = "bad"
                elif "d" in outages:
                    tone = "warn"
                elif outages:
                    tone = "unknown"
                else:
                    tone = "ok"
            days.append((date, tone))
            day += timedelta(days=1)
        result[key] = Uptime(tuple(days), values.get(key, ""))
    return result


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def parse_incident_io_uptime(html):
    # Next.js Flight 数据是 JSON 文本，绝不执行页面脚本。
    chunks = []
    for match in re.finditer(r"self\.__next_f\.push\((\[.*?\])\)</script>", html):
        payload = json.loads(match.group(1))
        if len(payload) == 2 and payload[0] == 1 and isinstance(payload[1], str):
            chunks.append(payload[1])
    objects = []
    for line in "".join(chunks).splitlines():
        try:
            objects.extend(_objects(json.loads(line.split(":", 1)[1])))
        except (ValueError, IndexError):
            continue
    summary = next((o for o in objects if "history_window_days" in o and "components" in o), None)
    now = next((o["isoDate"] for o in objects if "isoDate" in o), None)
    data = next((o for o in objects if "component_impacts" in o and "component_uptimes" in o), None)
    if not summary or not data or not now:
        return {}
    count = int(summary["history_window_days"])
    if not 1 <= count <= 366:
        return {}
    # 官网提供完整窗口的组件影响区间；按 UTC 日相交计算每日最严重状态。
    today = _datetime(now).astimezone(timezone.utc).date()
    first = today - timedelta(days=count - 1)
    tones = {
        "operational": "ok",
        "degraded_performance": "warn",
        "partial_outage": "bad",
        "major_outage": "bad",
        "under_maintenance": "info",
    }
    priority = {"ok": 0, "info": 1, "warn": 2, "bad": 3, "unknown": 4}
    groups = {}
    for item in summary.get("structure", {}).get("items", []):
        group = item.get("group")
        if isinstance(group, dict):
            for component in group.get("components", []):
                groups[component["component_id"]] = group.get("name", "")
    result = {}
    for row in data["component_uptimes"]:
        key = row.get("component_id")
        since = row.get("data_available_since")
        if not key or not since or since == "$undefined":
            continue
        available = _datetime(since)
        impacts = [i for i in data["component_impacts"] if i.get("component_id") == key]
        days = []
        for offset in range(count):
            day = first + timedelta(days=offset)
            start = datetime.combine(day, time(), timezone.utc)
            end = start + timedelta(days=1)
            tone = "unknown" if start < available else "ok"
            for impact in impacts:
                finish = impact.get("end_at")
                finish = _datetime(finish) if finish and finish != "$undefined" else _datetime(now)
                if _datetime(impact["start_at"]) < end and finish > start:
                    candidate = tones.get(impact.get("status"), "unknown")
                    if priority[candidate] > priority[tone]:
                        tone = candidate
            days.append((day.isoformat(), tone))
        # 不把不明统计周期的百分比搬到逐日条上，避免与窗口口径不一致。
        result[key] = Uptime(tuple(days), group=groups.get(key, ""))
    return result


async def fetch_uptime(service, snapshot, session, proxy):
    if service.uptime_source == "statuspage":
        ids = ",".join(c.id for c in snapshot.components)
        async with session.get(
            service.url + "/uptime_showcase", params={"components": ids}, proxy=proxy or None
        ) as response:
            response.raise_for_status()
            return parse_statuspage_uptime(await response.json())
    if service.uptime_source == "incident_io":
        async with session.get(
            service.url, proxy=proxy or None, headers={"Accept": "text/html"}
        ) as response:
            response.raise_for_status()
            return parse_incident_io_uptime(await response.text())
    return {}
