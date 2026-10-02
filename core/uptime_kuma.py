"""Uptime Kuma 公开接口：监控列表 + 最近心跳，不使用管理员接口。"""

import asyncio
from datetime import datetime, timedelta, timezone

from .localization import display_time, state
from .models import Component, Notice, Snapshot, Uptime

HEARTBEAT_STATES = {
    0: "unavailable",
    1: "operational",
    2: "pending",
    3: "under_maintenance",
}


class StatusAccessError(Exception):
    """官方接口要求浏览器验证或拒绝访问。"""


def _time(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _incident(row):
    # Kuma 公告的 style 是外观，不代表调查/解决阶段。
    return Notice(
        id=f"incident-{row['id']}",
        title=str(row.get("title") or "官方公告"),
        body=str(row.get("content") or ""),
        status="notice",
        updated_at=str(row.get("lastUpdatedDate") or row.get("createdDate") or ""),
    )


def parse_uptime_kuma(service, page, heartbeat, checked_at=None):
    if not isinstance(page, dict) or not isinstance(page.get("publicGroupList"), list):
        raise ValueError("官方状态页缺少 publicGroupList")
    if not isinstance(heartbeat, dict) or not isinstance(heartbeat.get("heartbeatList"), dict):
        raise ValueError("官方状态页缺少 heartbeatList")
    now = checked_at or datetime.now(timezone.utc)
    components, uptime, stale = [], {}, False
    for group in page["publicGroupList"]:
        group_name = str(group.get("name") or "")
        group_name = service.component_names.get(group_name, group_name)
        for monitor in group["monitorList"]:
            key = str(monitor["id"])
            rows = heartbeat["heartbeatList"].get(key, [])
            samples = sorted(
                ((_time(row["time"]), row.get("status")) for row in rows), key=lambda s: s[0]
            )
            status = "unknown"
            if samples:
                last_time, last_status = samples[-1]
                status = HEARTBEAT_STATES.get(last_status, "unknown")
                # 暂停更新的监控不能凭最后一个绿点一直宣称在线。
                age = now - last_time
                if age > timedelta(minutes=15) or age < -timedelta(minutes=5):
                    status, stale = "unknown", True
                points = tuple(
                    (stamp.isoformat(), state(HEARTBEAT_STATES.get(code, "unknown"))[1])
                    for stamp, code in samples[-100:]
                )
                ratio = heartbeat.get("uptimeList", {}).get(f"{key}_24")
                percent = (
                    f"{ratio * 100:.2f}" if type(ratio) in (float, int) and 0 <= ratio <= 1 else ""
                )
                period = f"最近 {len(points)} 次 · 截至 {display_time(last_time)} UTC+8"
                uptime[key] = Uptime(points, percent, group_name, period, "24h 可用")
            components.append(Component(key, str(monitor["name"]), status, group_name))

    statuses = {c.status for c in components}
    if "unavailable" in statuses:
        indicator = "all_down" if statuses == {"unavailable"} else "partial_down"
    elif not statuses or "unknown" in statuses:
        indicator = "unknown"
    elif "pending" in statuses:
        indicator = "minor"
    elif "under_maintenance" in statuses:
        indicator = "maintenance"
    else:
        indicator = "none"

    # 2.0 使用单条 incident，新版本支持 incidents 数组。
    incidents_known = isinstance(page.get("incidents"), list) or (
        "incident" in page and (page["incident"] is None or isinstance(page["incident"], dict))
    )
    incident_rows = page.get("incidents")
    if not isinstance(incident_rows, list):
        incident_rows = [page["incident"]] if isinstance(page.get("incident"), dict) else []
    incidents = tuple(_incident(row) for row in incident_rows)
    maintenance_known = isinstance(page.get("maintenanceList"), list)
    maintenance = tuple(
        Notice(
            id=f"maintenance-{row['id']}",
            title=str(row.get("title") or "官方维护"),
            body=str(row.get("description") or ""),
            status="under_maintenance",
            updated_at="",
        )
        for row in (page.get("maintenanceList") or [])
    )
    warnings = ["状态条为近期探测记录；24h 可用率是官方单独统计，不是逐日历史"]
    if stale:
        warnings.append("部分监控超过 15 分钟未更新或时间异常，当前状态标为未知")
    return Snapshot(
        service,
        indicator,
        tuple(components),
        incidents,
        maintenance,
        (),
        now,
        incidents_known,
        maintenance_known,
        False,
        tuple(warnings),
        uptime,
    )


class UptimeKumaAdapter:
    async def fetch(self, service, session, proxy):
        async def get(path):
            async with session.get(service.url.rstrip("/") + path, proxy=proxy or None) as response:
                if response.status == 403 or response.headers.get("cf-mitigated") == "challenge":
                    raise StatusAccessError("官方状态接口需要浏览器验证或拒绝程序访问")
                response.raise_for_status()
                return await response.json()

        slug = service.status_page_slug
        page, heartbeat = await asyncio.gather(
            get(f"/api/status-page/{slug}"),
            get(f"/api/status-page/heartbeat/{slug}"),
            return_exceptions=True,
        )
        for result in (page, heartbeat):
            if isinstance(result, BaseException):
                raise result
        return parse_uptime_kuma(service, page, heartbeat)
