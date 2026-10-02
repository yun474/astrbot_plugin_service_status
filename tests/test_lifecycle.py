"""用最小框架替身检查插件自身的查询、渲染和卸载生命周期。"""

import asyncio
import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from core.renderer import Canvas

ROOT = Path(__file__).resolve().parents[1]


def plugin_class():
    api = ModuleType("astrbot.api")
    api.AstrBotConfig = dict
    api.logger = Mock()
    event = ModuleType("astrbot.api.event")
    event.AstrMessageEvent = object
    event.filter = SimpleNamespace(command=lambda *args: lambda method: method)
    star = ModuleType("astrbot.api.star")
    star.Context = object
    star.Star = type("Star", (), {"__init__": lambda self, context: None})
    star.register = lambda *args: lambda cls: cls
    spec = importlib.util.spec_from_file_location(
        "lifecycle_plugin", ROOT / "main.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"astrbot.api": api, "astrbot.api.event": event, "astrbot.api.star": star},
    ):
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


PLUGIN = plugin_class()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = PLUGIN.ServiceStatusPlugin(Mock(), {})
        self.event = SimpleNamespace(plain_result=lambda text: text, image_result=lambda path: path)

    async def asyncTearDown(self):
        await self.plugin.terminate()

    async def test_disabled_and_unloaded_queries_do_not_start_requests(self):
        self.plugin.client.fetch = AsyncMock()
        self.plugin.config["enabled_services"] = []
        self.assertIn("已停用", await self.plugin._query(self.event, "gpt"))
        await self.plugin.terminate()
        self.assertIn("重载", await self.plugin._query(self.event, "gpt"))
        self.plugin.client.fetch.assert_not_awaited()

    async def test_terminate_cancels_active_fetch_and_removes_directory(self):
        started = asyncio.Event()

        async def fetch(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        self.plugin.client.fetch = fetch
        query = asyncio.create_task(self.plugin._query(self.event, "gpt"))
        await started.wait()
        directory = Path(self.plugin._temp_dir.name)
        await self.plugin.terminate()
        with self.assertRaises(asyncio.CancelledError):
            await query
        self.assertFalse(directory.exists())
        self.assertFalse(self.plugin._query_tasks)

    async def test_busy_queries_do_not_grow_waiting_queue(self):
        started = asyncio.Event()
        count = 0

        async def fetch(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 4:
                started.set()
            await asyncio.Event().wait()

        self.plugin.client.fetch = fetch
        queries = [asyncio.create_task(self.plugin._query(self.event, "gpt")) for _ in range(4)]
        await started.wait()
        self.assertIn("繁忙", await self.plugin._query(self.event, "gpt"))
        self.assertEqual(count, 4)
        await self.plugin.terminate()
        await asyncio.gather(*queries, return_exceptions=True)

    async def test_image_is_retained_for_sending_then_removed_on_unload(self):
        self.plugin.client.fetch = AsyncMock(return_value=object())
        with patch.object(
            PLUGIN, "render", lambda snapshot, path, config: path.write_bytes(b"png")
        ):
            path = Path(await self.plugin._query(self.event, "gpt"))
        self.assertTrue(path.exists())
        await self.plugin.terminate()
        self.assertFalse(path.exists())

    async def test_periodic_cleanup_preserves_fresh_images_and_retries_locked_files(self):
        directory = Path(self.plugin._temp_dir.name)
        old, fresh = directory / "old.png", directory / "fresh.png"
        old.write_bytes(b"old")
        fresh.write_bytes(b"fresh")
        self.plugin._images = {old: 0, fresh: 150}
        with patch.object(PLUGIN.time, "monotonic", return_value=200):
            with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
                self.plugin._cleanup_expired()
            self.assertIn(old, self.plugin._images)
            self.plugin._cleanup_expired()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(self.plugin._images, {fresh: 150})

    async def test_multiple_images_share_one_periodic_task(self):
        self.plugin.client.fetch = AsyncMock(return_value=object())
        with patch.object(
            PLUGIN, "render", lambda snapshot, path, config: path.write_bytes(b"png")
        ):
            await self.plugin._query(self.event, "gpt")
            cleanup = self.plugin._cleanup_task
            await self.plugin._query(self.event, "gpt")
        self.assertIs(self.plugin._cleanup_task, cleanup)
        self.assertEqual(len(self.plugin._images), 2)
        await self.plugin.terminate()
        self.assertTrue(cleanup.done())
        self.assertFalse(self.plugin._images)

    async def test_cancelled_render_finishes_before_file_cleanup(self):
        started = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        self.plugin.client.fetch = AsyncMock(return_value=object())

        def render(snapshot, path, config):
            loop.call_soon_threadsafe(started.set)
            if not finish.wait(5):
                raise TimeoutError("test render did not finish")
            path.write_bytes(b"png")

        with patch.object(PLUGIN, "render", render):
            query = asyncio.create_task(self.plugin._query(self.event, "gpt"))
            await started.wait()
            query.cancel()
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await query
        self.assertEqual(list(Path(self.plugin._temp_dir.name).iterdir()), [])
        self.assertFalse(self.plugin._render_tasks)

    async def test_render_failure_removes_partial_file(self):
        self.plugin.client.fetch = AsyncMock(return_value=object())
        with patch.object(PLUGIN, "render", side_effect=OSError("disk full")):
            self.assertIn("暂时失败", await self.plugin._query(self.event, "gpt"))
        self.assertEqual(list(Path(self.plugin._temp_dir.name).iterdir()), [])


class RenderResourceTests(unittest.TestCase):
    def test_pixel_buffer_closed_on_success_and_save_failure(self):
        canvas = Canvas.__new__(Canvas)
        canvas.theme, canvas.ops = {"background": "white"}, []
        for error in (None, OSError("disk full")):
            image = Image.new("RGB", (1000, 100))
            with (
                patch("core.renderer.Image.new", return_value=image),
                patch.object(image, "save", side_effect=error),
            ):
                if error:
                    with self.assertRaises(OSError):
                        canvas.save("unused.png", 100)
                else:
                    canvas.save("unused.png", 100)
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_excessive_image_height_rejected_before_allocation(self):
        canvas = Canvas.__new__(Canvas)
        with patch("core.renderer.Image.new") as new:
            with self.assertRaises(ValueError):
                canvas.save("unused.png", 30001)
            new.assert_not_called()


if __name__ == "__main__":
    unittest.main()
