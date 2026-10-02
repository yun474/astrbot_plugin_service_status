from datetime import datetime, timedelta, timezone

STATES = {
    "unavailable": ("不可用", "bad"),
    "pending": ("等待确认", "warn"),
    "notice": ("官方公告", "info"),
    "operational": ("运行正常", "ok"),
    "degraded_performance": ("性能下降", "warn"),
    "partial_outage": ("部分中断", "bad"),
    "major_outage": ("严重中断", "bad"),
    "under_maintenance": ("维护中", "info"),
    "investigating": ("调查中", "warn"),
    "identified": ("已定位", "warn"),
    "monitoring": ("观察恢复", "info"),
    "resolved": ("已解决", "ok"),
    "postmortem": ("事后复盘", "ok"),
    "scheduled": ("计划维护", "info"),
    "in_progress": ("维护中", "info"),
    "verifying": ("验证中", "info"),
    "completed": ("维护完成", "ok"),
}
INDICATORS = {
    "partial_down": ("部分监控报告异常", "warn"),
    "all_down": ("全部监控报告异常", "bad"),
    "none": ("所有系统运行正常", "ok"),
    "minor": ("部分服务出现异常", "warn"),
    "major": ("服务出现较大故障", "bad"),
    "critical": ("服务出现严重故障", "bad"),
    "maintenance": ("服务正在维护", "info"),
}
PHRASES = {
    "This incident has been resolved.": "此事件已解决。",
    "This issue has been resolved.": "此问题已解决。",
    "All impacted services have now fully recovered.": "所有受影响的服务现已完全恢复。",
    "We are continuing to monitor for any further issues.": "我们正在持续观察，确认是否仍有问题。",
    "We are continuing to investigate this issue.": "我们正在继续调查此问题。",
}


def state(value):
    return STATES.get(value, ("状态未知", "unknown"))


def overall(snapshot):
    label, tone = INDICATORS.get(snapshot.indicator, ("总体状态未知", "unknown"))
    # 官方指标与组件/事件存在更新时差时，不能给出全绿结论。
    if snapshot.indicator == "none":
        if any(c.status != "operational" for c in snapshot.components):
            return "部分组件需要关注", "warn"
        if snapshot.incidents:
            return "仍有事件正在跟进", "warn"
        if not snapshot.components:
            return "组件状态暂不可用", "unknown"
    return label, tone


def display_time(value):
    if not value:
        return "时间未提供"
    try:
        dt = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return "时间格式未知"
