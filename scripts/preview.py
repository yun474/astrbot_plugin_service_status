"""从实时官方数据生成预览：python scripts/preview.py。"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.client import StatusClient  # noqa: E402
from core.registry import load_services  # noqa: E402
from core.renderer import render  # noqa: E402
from core.uptime_kuma import StatusAccessError  # noqa: E402


async def main():
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    client = StatusClient()
    for service in load_services(ROOT / "services").values():
        try:
            snapshot = await client.fetch(service, timeout=25)
        except StatusAccessError as exc:
            print(f"{service.name}: 未生成实时预览，{exc}；官网 {service.url}")
            continue
        target = output / f"{service.id}.png"
        await asyncio.to_thread(render, snapshot, target, {})
        print(
            f"{service.name}: {len(snapshot.components)} components, {len(snapshot.uptime)} histories -> {target}"
        )


if __name__ == "__main__":
    asyncio.run(main())
