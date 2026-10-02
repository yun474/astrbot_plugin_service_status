from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    subtitle: str
    command: str
    aliases: tuple[str, ...]
    url: str
    adapter: str
    theme: str
    uptime_source: str = ""
    component_names: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    status: str
    group: str = ""


@dataclass(frozen=True)
class Notice:
    id: str
    title: str
    body: str
    status: str
    updated_at: str
    translated: bool = False
    scheduled_for: str = ""
    scheduled_until: str = ""


@dataclass(frozen=True)
class Uptime:
    days: tuple[tuple[str, str], ...]
    percent: str = ""
    group: str = ""
    period_label: str = ""
    percent_label: str = "可用"


@dataclass(frozen=True)
class Snapshot:
    service: Service
    indicator: str
    components: tuple[Component, ...]
    incidents: tuple[Notice, ...]
    maintenance: tuple[Notice, ...]
    history: tuple[Notice, ...]
    checked_at: datetime
    incidents_known: bool
    maintenance_known: bool
    history_known: bool
    warnings: tuple[str, ...] = ()
    uptime: dict[str, Uptime] = field(default_factory=dict)
