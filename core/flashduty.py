"""DeepSeek 当前官方状态页使用的 Flashduty 公开数据接口。"""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .statuspage import parse_statuspage

STATES = {
    "operational": "operational",
    "degraded": "degraded_performance",
    "partial_outage": "partial_outage",
    "full_outage": "major_outage",
    "maintenance": "under_maintenance",
    "under_maintenance": "under_maintenance",
}
PRIORITY = {
    "operational": 0,
    "under_maintenance": 1,
    "degraded_performance": 2,
    "partial_outage": 3,
    "major_outage": 4,
    "unknown": 5,
}
INDICATORS = {
    "operational": "none",
    "under_maintenance": "maintenance",
    "degraded_performance": "minor",
    "partial_outage": "major",
    "major_outage": "critical",
    "unknown": "unknown",
}


def _time(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat() if seconds else ""


def _notice(row):
    return {
        "id": str(row["change_id"]),
        "name": row.get("title"),
        "status": {"ongoing": "in_progress"}.get(row.get("status"), row.get("status")),
        "updated_at": _time(row.get("close_at_seconds") or row.get("start_at_seconds")),
        "incident_updates": [
            {"created_at": _time(u.get("at_seconds")), "body": u.get("description")}
            for u in row.get("updates", [])
        ]
        or [{"body": row.get("description")}],
        "scheduled_for": _time(row.get("start_at_seconds"))
        if row.get("type") == "maintenance"
        else "",
        "scheduled_until": _time(row.get("end_at_seconds"))
        if row.get("type") == "maintenance"
        else "",
    }


def parse_flashduty(service, active, history=None):
    if not isinstance(active, dict) or not isinstance(active.get("page"), dict):
        raise ValueError("官方汇总接口缺少 page 字段")
    page = active["page"]
    if (
        str(page.get("page_id")) != service.page_id
        or page.get("custom_domain") != urlsplit(service.url).hostname
    ):
        raise ValueError("官方状态页身份与服务配置不匹配")
    rows, changes = page.get("components"), active.get("active_changes")
    if not isinstance(rows, list) or not isinstance(changes, list):
        raise ValueError("官方汇总接口缺少组件或活动事件列表")
    changes = [r for r in changes if r.get("status") not in {"resolved", "completed", "cancelled"}]
    groups = {r["section_id"]: r for r in page.get("sections", [])}
    components = []
    for row in rows:
        group = groups.get(row.get("section_id"), {})
        if row.get("hide_all") or group.get("hide_all"):
            continue
        status = "operational"
        # 与官网一致：当前组件状态取自活动事件，而非历史事故。
        for change in changes:
            if change.get("status") == "scheduled":
                continue
            affected = change.get("affected_components")
            if not isinstance(affected, list):
                status = "unknown"
                continue
            for impact in affected:
                if impact.get("component_id") == row["component_id"]:
                    candidate = STATES.get(impact.get("status"), "unknown")
                    if PRIORITY[candidate] > PRIORITY[status]:
                        status = candidate
        components.append(
            {
                "id": row["component_id"],
                "name": row["name"],
                "status": status,
                "group_id": row.get("section_id"),
            }
        )
    worst = max((c["status"] for c in components), key=PRIORITY.get, default="unknown")
    summary = {
        "status": {"indicator": INDICATORS[worst]},
        "components": components
        + [{"id": key, "name": row["name"], "group": True} for key, row in groups.items()],
        "incidents": [_notice(r) for r in changes if r.get("type") != "maintenance"],
        "scheduled_maintenances": [_notice(r) for r in changes if r.get("type") == "maintenance"],
    }
    recent = None
    if isinstance(history, dict) and isinstance(history.get("items"), list):
        recent = {
            "incidents": [_notice(r) for r in history["items"] if r.get("type") == "incident"]
        }
    return parse_statuspage(service, summary, recent)


class FlashdutyAdapter:
    async def fetch(self, service, session, proxy):
        # 使用官网 CNAME 指向的托管域名；不依赖固定 IP 或旧 Statuspage 数据。
        base = f"https://statuspage.flashduty.com/api/status-page/{service.page_id}"

        async def get(path, params=None):
            async with session.get(base + path, params=params, proxy=proxy or None) as response:
                response.raise_for_status()
                payload = await response.json()
                if payload.get("error") or not isinstance(payload.get("data"), dict):
                    raise ValueError("Flashduty 接口未返回有效数据")
                return payload["data"]

        now = datetime.now(timezone.utc)
        active, history = await asyncio.gather(
            get("/summary/active"),
            get(
                "/change/list",
                {
                    "start_at_seconds": int((now - timedelta(days=90)).timestamp()),
                    "end_at_seconds": int(now.timestamp()),
                },
            ),
            return_exceptions=True,
        )
        if isinstance(active, BaseException):
            raise active
        return parse_flashduty(service, active, None if isinstance(history, Exception) else history)
