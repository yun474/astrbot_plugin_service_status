"""本地 Pillow 渲染：主题独立，中文字体明确，不依赖网页截图服务。"""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .localization import PHRASES, display_time, overall, state

ROOT = Path(__file__).resolve().parent.parent
COLORS = {
    "ok": "#348A64",
    "warn": "#D9A032",
    "bad": "#D36457",
    "info": "#688CB1",
    "unknown": "#BEC3C0",
}
MAX_ACTIVE = 8


def find_font(custom=""):
    if custom:
        if not Path(custom).is_file():
            raise ValueError("配置的中文字体文件不存在")
        return custom
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    raise ValueError("未找到中文字体，请安装 Noto Sans CJK 或配置 font_path")


class Canvas:
    def __init__(self, theme, font_path):
        self.theme = theme
        self.font_path = find_font(font_path)
        self.fonts = {}
        self.ops = []

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = ImageFont.truetype(self.font_path, size)
        return self.fonts[size]

    def text(self, xy, text, size=22, color=None):
        self.ops.append(
            (
                "text",
                (xy, str(text)),
                {"font": self.font(size), "fill": color or self.theme["ink"], "anchor": "lt"},
            )
        )

    def rect(self, box, fill, radius=16, outline=None):
        self.ops.append(
            ("rounded_rectangle", (box,), {"radius": radius, "fill": fill, "outline": outline})
        )

    def fit(self, text, width, size=22):
        font = self.font(size)
        if font.getlength(text) <= width:
            return text
        while text and font.getlength(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def wrap(self, text, width, size=22, limit=5):
        lines, current = [], ""
        for char in text.replace("\r", ""):
            if char == "\n" or self.font(size).getlength(current + char) > width:
                lines.append(current)
                current = "" if char == "\n" else char
            else:
                current += char
        if current:
            lines.append(current)
        if len(lines) > limit:
            lines = lines[:limit]
            lines[-1] = self.fit(lines[-1] + "…", width, size)
        return lines

    def save(self, path, height):
        image = Image.new("RGB", (1000, height), self.theme["background"])
        draw = ImageDraw.Draw(image)
        for method, args, kwargs in self.ops:
            getattr(draw, method)(*args, **kwargs)
        image.save(path, "PNG", optimize=True)


def visible_notices(snapshot, config):
    sections = []
    if config.get("show_incidents", True):
        sections.append(
            (
                "当前事件",
                snapshot.incidents[:MAX_ACTIVE],
                snapshot.incidents_known,
                len(snapshot.incidents),
            )
        )
    if config.get("show_maintenance", True) and (
        snapshot.maintenance or not snapshot.maintenance_known
    ):
        sections.append(
            (
                "计划维护",
                snapshot.maintenance[:MAX_ACTIVE],
                snapshot.maintenance_known,
                len(snapshot.maintenance),
            )
        )
    if config.get("show_history", True):
        count = max(1, min(5, int(config.get("history_count", 2))))
        sections.append(
            (
                "近期已解决",
                snapshot.history[:count],
                snapshot.history_known,
                min(count, len(snapshot.history)),
            )
        )
    return sections


def render(snapshot, path, config):
    theme = json.loads((ROOT / "themes" / f"{snapshot.service.theme}.json").read_text("utf-8"))
    c = Canvas(theme, config.get("font_path", ""))
    ink, muted, accent = theme["ink"], theme["muted"], theme["accent"]
    service = snapshot.service
    c.rect((0, 0, 1000, 9), accent, 0)
    if theme["brand_style"] == "serif":
        # 用几何放射线呼应 Claude 的品牌图形，不加载外部图片。
        for i in range(12):
            angle = i * math.pi / 6
            x, y = 78 + 23 * math.cos(angle), 76 + 23 * math.sin(angle)
            c.ops.append(("line", ((78, 76, x, y),), {"fill": accent, "width": 5}))
    else:
        c.rect((53, 53, 101, 101), ink, 14)
        c.text((65, 59), "O", 32, "#FFFFFF")
    c.text((119, 49), service.name, 42)
    c.text((120, 104), service.subtitle, 18, muted)
    c.text((756, 57), "服务运行报告", 21, accent)
    c.text((756, 91), display_time(snapshot.checked_at), 19, muted)
    c.rect((48, 151, 952, 297), theme["surface"], 24)
    title, tone = overall(snapshot)
    c.rect((74, 184, 88, 198), COLORS[tone], 7)
    c.text((102, 174), title, 32)
    normal = sum(item.status == "operational" for item in snapshot.components)
    c.text((76, 233), f"{normal} / {len(snapshot.components)} 项组件正常", 21, muted)
    c.text((566, 236), "来自官方状态页 · 非本地连通性测试", 18, muted)
    y = 327
    c.text((50, y), "系统状态", 26)
    c.text((742, y + 5), "组件状态 / 官方历史", 18, muted)
    y += 49
    columns = 2 if len(snapshot.components) > 8 else 1
    width = (904 - (columns - 1) * 16) // columns
    row_heights = []
    for index, component in enumerate(snapshot.components):
        column = index % columns
        x = 48 + column * (width + 16)
        uptime = snapshot.uptime.get(component.id) if config.get("show_uptime", True) else None
        height = 144 if uptime else 95
        row_heights.append(height)
        label = service.component_names.get(component.name, component.name)
        c.rect((x, y, x + width, y + height - 10), theme["surface"], 16)
        c.text((x + 20, y + 19), c.fit(label, width - 154, 22), 22)
        text, tone = state(component.status)
        c.rect((x + width - 119, y + 25, x + width - 110, y + 34), COLORS[tone], 4)
        c.text((x + width - 101, y + 20), text, 18, COLORS[tone])
        group = component.group or (uptime.group if uptime else "")
        sub = group + " · " + component.name if group else component.name
        if sub == label:
            sub = "官方组件"
        c.text((x + 20, y + 50), c.fit(sub, width - 40, 15), 15, muted)
        if uptime:
            days = uptime.days
            step = (width - 40) / len(days)
            for i, (_, day_tone) in enumerate(days):
                left = x + 20 + i * step
                c.rect((left, y + 79, left + max(1, step - 2), y + 99), COLORS[day_tone], 1)
            period = f"{days[0][0][5:]} — {days[-1][0][5:]} · UTC"
            c.text((x + 20, y + 109), period, 14, muted)
            if uptime.percent:
                text = f"{uptime.percent}% 可用"
                c.text((x + width - 20 - c.font(14).getlength(text), y + 109), text, 14, muted)
        elif config.get("show_uptime", True):
            c.text((x + width - 135, y + 53), "历史暂不可用", 15, muted)
        if column == columns - 1 or index == len(snapshot.components) - 1:
            y += max(row_heights)
            row_heights = []
    if config.get("show_uptime", True) and snapshot.uptime:
        y += 8
        for i, (key, label) in enumerate(
            (
                ("ok", "正常"),
                ("warn", "性能下降"),
                ("bad", "中断"),
                ("info", "维护"),
                ("unknown", "无数据"),
            )
        ):
            x = 53 + i * 150
            c.rect((x, y, x + 10, y + 10), COLORS[key], 2)
            c.text((x + 19, y - 3), label, 16, muted)
        y += 40
    for warning in snapshot.warnings:
        c.text((52, y), c.fit(warning, 890, 18), 18, COLORS["warn"])
        y += 32
    for heading, notices, known, total in visible_notices(snapshot, config):
        y += 20
        c.text((52, y), heading, 25)
        y += 46
        if not notices:
            text = "暂无未解决事件" if heading == "当前事件" else "暂无记录"
            if not known:
                text = "官方未提供此数据或接口暂不可用"
            c.rect((48, y, 952, y + 62), theme["surface"], 14)
            c.text((70, y + 20), text, 20, muted)
            y += 76
            continue
        for notice in notices:
            title_lines = c.wrap(notice.title, 840, 23, 3)
            body = PHRASES.get(notice.body.strip(), notice.body.strip())
            body_lines = c.wrap(body, 840, 19, 4)
            height = 73 + 32 * len(title_lines) + 28 * len(body_lines)
            schedule = ""
            if notice.scheduled_for:
                schedule = f"维护窗口：{display_time(notice.scheduled_for)} — {display_time(notice.scheduled_until)} UTC+8"
                height += 32
            c.rect((48, y, 952, y + height), theme["surface"], 16)
            label, tone = state(notice.status)
            c.text((70, y + 19), label, 17, COLORS[tone])
            c.text((182, y + 19), display_time(notice.updated_at), 17, muted)
            c.text((757, y + 19), "机器翻译" if notice.translated else "官方公告", 16, muted)
            pos = y + 53
            for line in title_lines:
                c.text((70, pos), line, 23)
                pos += 32
            for line in body_lines:
                c.text((70, pos + 3), line, 19, muted)
                pos += 28
            if schedule:
                c.text((70, pos + 6), schedule, 17, accent)
            y += height + 14
        if total > len(notices):
            c.text((54, y), f"另有 {total - len(notices)} 条，请前往官方状态页查看", 18, muted)
            y += 31
    y += 25
    c.rect((48, y, 952, y + 1), theme["line"], 0)
    c.text((52, y + 23), service.url.removeprefix("https://"), 19, accent)
    c.text((677, y + 25), "查询 / 事件时间：UTC+8", 17, muted)
    c.text((52, y + 59), "官方汇总数据不代表每位用户体验 · 长公告节选，完整内容见官网", 16, muted)
    c.save(path, y + 108)
