import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core.client import ADAPTERS, StatusClient
from .core.registry import load_services
from .core.renderer import render, visible_notices
from .core.translation import EventTranslator
from .core.uptime_kuma import StatusAccessError


@register(
    "astrbot_plugin_service_status",
    "yun474",
    "互联网服务官方状态查询",
    "0.1.0",
    "https://github.com/yun474/astrbot_plugin_service_status",
)
class ServiceStatusPlugin(Star):
    """指令入口仅负责编排；数据与渲染模块可独立测试。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.services = load_services(Path(__file__).parent / "services")
        for service in self.services.values():
            if service.adapter not in ADAPTERS:
                raise ValueError(f"未注册的数据适配器: {service.adapter}")
        self.client = StatusClient()
        self.translator = EventTranslator()
        self._render_limit = asyncio.Semaphore(2)
        self._cleanup_tasks = set()
        self._render_tasks = set()
        self._closing = False
        self._temp_dir = tempfile.TemporaryDirectory(prefix="astrbot_service_status_")

    def _number(self, key, default, low, high):
        return max(low, min(high, int(self.config.get(key, default))))

    def _enabled(self, key):
        return key in self.config.get("enabled_services", ["gpt", "claude", "sl"])

    async def _cleanup(self, path):
        try:
            await asyncio.sleep(180)
        finally:
            path.unlink(missing_ok=True)

    async def _translate(self, snapshot, event):
        if not self.config.get("llm_translate_events", False):
            return snapshot
        notices = tuple(n for _, rows, _, _ in visible_notices(snapshot, self.config) for n in rows)
        if not notices:
            return snapshot
        try:
            # 3.4.34 尚不支持会话参数；只为这个已确认的 API 差异做兼容。
            try:
                provider = self.context.get_using_provider(event.unified_msg_origin)
            except TypeError:
                provider = self.context.get_using_provider()
            translated = await self.translator.translate(
                notices, provider, self._number("translation_timeout", 25, 5, 60)
            )
            by_id = {n.id: n for n in translated}
            return replace(
                snapshot,
                **{
                    field: tuple(by_id.get(n.id, n) for n in getattr(snapshot, field))
                    for field in ("incidents", "maintenance", "history")
                },
            )
        except Exception:
            logger.warning("服务状态：事件翻译失败，保留官方原文", exc_info=True)
            return snapshot

    async def _query(self, event, key):
        service = self.services.get(key)
        if service is None:
            return event.plain_result("未找到这个状态服务，请使用 /服务状态 查看列表。")
        if not self._enabled(key):
            return event.plain_result(f"{service.name} 状态查询已停用。")
        try:
            snapshot = await self.client.fetch(
                service,
                timeout=self._number("request_timeout", 15, 3, 60),
                cache_seconds=self._number("cache_seconds", 60, 0, 3600),
                proxy=str(self.config.get("proxy_url", "")).strip(),
                show_uptime=bool(self.config.get("show_uptime", True)),
            )
            snapshot = await self._translate(snapshot, event)
            async with self._render_limit:
                if self._closing:
                    return event.plain_result("状态插件正在重载，请稍后重试。")
                with tempfile.NamedTemporaryFile(
                    suffix=".png", dir=self._temp_dir.name, delete=False
                ) as file:
                    path = Path(file.name)
                worker = asyncio.create_task(asyncio.to_thread(render, snapshot, path, self.config))
                self._render_tasks.add(worker)
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    # to_thread 无法中断；等写入结束再删文件，避免卸载后留下文件。
                    await asyncio.gather(worker, return_exceptions=True)
                    path.unlink(missing_ok=True)
                    raise
                except BaseException:
                    path.unlink(missing_ok=True)
                    raise
                finally:
                    self._render_tasks.discard(worker)
            if self._closing:
                path.unlink(missing_ok=True)
                return event.plain_result("状态插件正在重载，请稍后重试。")
            task = asyncio.create_task(self._cleanup(path))
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)
            return event.image_result(str(path))
        except StatusAccessError:
            return event.plain_result(
                f"{service.name} 官方状态接口需要浏览器验证或暂时拒绝访问，无法自动读取。"
                f"这不代表游戏服务故障。\n请打开官方状态页：{service.url}"
            )
        except Exception:
            logger.exception("服务状态：%s 查询或渲染失败", service.name)
            return event.plain_result(
                f"{service.name} 状态查询暂时失败，请稍后重试。\n官方状态页：{service.url}"
            )

    @filter.command("gpt状态")
    async def gpt_status(self, event: AstrMessageEvent):
        """查看 OpenAI 官方服务状态。"""
        yield await self._query(event, "gpt")

    @filter.command("claude状态")
    async def claude_status(self, event: AstrMessageEvent):
        """查看 Claude 官方服务状态。"""
        yield await self._query(event, "claude")

    @filter.command("sl状态")
    async def sl_status(self, event: AstrMessageEvent):
        """查看 SCP:SL / Northwood 官方服务状态。"""
        yield await self._query(event, "sl")

    @filter.command("服务状态")
    async def service_status(self, event: AstrMessageEvent, name: str = ""):
        """查看启用列表，或使用 /服务状态 服务ID 查询。"""
        if name:
            yield await self._query(event, name.lower())
        else:
            lines = [
                f"/服务状态 {s.id}  ·  {s.name}"
                for s in self.services.values()
                if self._enabled(s.id)
            ]
            yield event.plain_result(
                "已启用的状态服务：\n" + "\n".join(lines) if lines else "暂未启用任何状态服务。"
            )

    async def terminate(self):
        self._closing = True
        await asyncio.gather(*self._render_tasks, return_exceptions=True)
        for task in tuple(self._cleanup_tasks):
            task.cancel()
        await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
        self._cleanup_tasks.clear()
        self.client.clear()
        self.translator.cache.clear()
        self._temp_dir.cleanup()
