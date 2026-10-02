"""Statuspage v2 以及兼容接口；缺失字段不等于没有事故。"""

import asyncio
from datetime import datetime, timezone

from .models import Component, Notice, Service, Snapshot


def _notices(rows: list) -> tuple[Notice, ...]:
    result = []
    for row in rows:
        updates = row.get("incident_updates") or []
        latest = max(
            updates, key=lambda u: u.get("display_at") or u.get("created_at") or "", default={}
        )
        result.append(
            Notice(
                id=str(row["id"]),
                title=str(row.get("name") or "未命名事件"),
                body=str(latest.get("body") or ""),
                status=str(row.get("status") or "unknown"),
                updated_at=str(
                    latest.get("display_at")
                    or latest.get("created_at")
                    or row.get("updated_at")
                    or ""
                ),
                scheduled_for=str(row.get("scheduled_for") or ""),
                scheduled_until=str(row.get("scheduled_until") or ""),
            )
        )
    return tuple(sorted(result, key=lambda n: n.updated_at, reverse=True))


def parse_statuspage(service: Service, summary: dict, history: dict | None) -> Snapshot:
    if not isinstance(summary, dict) or not isinstance(summary.get("status"), dict):
        raise ValueError("官方汇总接口缺少 status 字段")
    rows = summary.get("components")
    if not isinstance(rows, list):
        raise ValueError("官方汇总接口缺少 components 列表")
    if any(not isinstance(row, dict) or "id" not in row or "name" not in row for row in rows):
        raise ValueError("官方组件数据格式异常")
    groups = {row["id"]: row["name"] for row in rows if row.get("group")}
    components = tuple(
        Component(
            str(row["id"]),
            str(row["name"]),
            str(row.get("status") or "unknown"),
            groups.get(row.get("group_id"), ""),
        )
        for row in sorted(rows, key=lambda row: row.get("position") or 0)
        if not row.get("group")
    )
    history_known = isinstance(history, dict) and isinstance(history.get("incidents"), list)
    history_rows = history["incidents"] if history_known else []
    incidents_known = isinstance(summary.get("incidents"), list) or history_known
    # summary 的活动事件为权威来源；OpenAI 未提供该字段时从事件接口提取。
    incident_rows = summary.get("incidents", history_rows)
    if not isinstance(incident_rows, list):
        incident_rows = history_rows
    incidents = _notices(
        [r for r in incident_rows if r.get("status") not in {"resolved", "postmortem", "completed"}]
    )
    maintenance_known = isinstance(summary.get("scheduled_maintenances"), list)
    maintenance = _notices(
        [r for r in (summary.get("scheduled_maintenances") or []) if r.get("status") != "completed"]
    )
    recent = _notices([r for r in history_rows if r.get("status") in {"resolved", "postmortem"}])
    warnings = []
    if not incidents_known:
        warnings.append("事件详情暂不可用，请以官方状态页为准")
    if not components:
        warnings.append("官方暂未返回组件数据")
    return Snapshot(
        service,
        str(summary["status"].get("indicator") or "unknown"),
        components,
        incidents,
        maintenance,
        recent,
        datetime.now(timezone.utc),
        incidents_known,
        maintenance_known,
        history_known,
        tuple(warnings),
    )


class StatuspageAdapter:
    async def fetch(self, service, session, proxy):
        async def get(path):
            async with session.get(service.url.rstrip("/") + path, proxy=proxy or None) as response:
                response.raise_for_status()
                return await response.json()

        summary, history = await asyncio.gather(
            get("/api/v2/summary.json"),
            get("/api/v2/incidents.json"),
            return_exceptions=True,
        )
        if isinstance(summary, BaseException):
            raise summary
        return parse_statuspage(
            service, summary, None if isinstance(history, Exception) else history
        )
