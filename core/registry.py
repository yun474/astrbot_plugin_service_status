import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .models import Service


def load_services(directory: Path) -> dict[str, Service]:
    services = {}
    commands = {"服务状态", "状态列表"}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text("utf-8"))
        data["aliases"] = tuple(data.get("aliases", []))
        service = Service(**data)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", service.id):
            raise ValueError(f"{path.name}: 服务 ID 必须为小写字母、数字或下划线")
        if service.id in services:
            raise ValueError(f"重复服务 ID: {service.id}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", service.theme):
            raise ValueError(f"{path.name}: 主题名无效")
        url = urlsplit(service.url)
        if url.scheme != "https" or not url.netloc or url.query or url.fragment:
            raise ValueError(f"{path.name}: 请填写官方 HTTPS 状态页地址")
        for command in (service.command, *service.aliases):
            if not command or command.startswith("/") or any(c.isspace() for c in command):
                raise ValueError(f"{path.name}: 指令不应带斜杠或空格")
            if command in commands:
                raise ValueError(f"重复状态指令: {command}")
            commands.add(command)
        services[service.id] = service
    return services
