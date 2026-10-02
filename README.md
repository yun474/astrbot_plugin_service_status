# 互联网服务状态

给群里发一张服务状态卡。当前接入 **OpenAI / GPT**、**Claude** 和 **SCP:SL / Northwood**，数据来自各自官方状态页；组件状态、事件和历史状态条放在同一张图片中。

云云把 GPT 和 Claude 状态查询整理成了一个可扩展的 AstrBot 插件，作者 `yun474`。项目仓库：[yun474/astrbot_plugin_service_status](https://github.com/yun474/astrbot_plugin_service_status)。

## 指令与开关

| 指令 | 用途 |
| --- | --- |
| `/gpt状态` | OpenAI 官方状态 |
| `/claude状态` | Claude 官方状态 |
| `/sl状态` | SCP:SL / Northwood 官方状态 |
| `/服务状态` | 列出已启用的服务 |
| `/服务状态 gpt` | 用服务 ID 查询，方便扩展新服务 |

不注册英文别名。指令由 AstrBot `@filter.command` 处理，遵循框架唤醒前缀和权限机制，不自行监听或截获普通聊天。

在配置页的 `enabled_services` 列表中保留需要的服务 ID，新安装默认开启 `gpt`、`claude`、`sl`。已有配置请手动加入 `sl`，不覆盖原有的启停选择。删除任意一项即可停用；空列表关闭全部查询。停用服务仍会礼貌回复“已停用”，不会发起状态请求、翻译或渲染。

`show_incidents`、`show_maintenance`、`show_history`、`show_uptime` 分别控制当前事件、维护、近期事件和历史状态条。`show_uptime` 关闭后不额外请求历史状态条数据；SCP:SL 的当前状态与历史探测共用接口，仍需获取心跳，但不展示状态条。

## 安装

1. 在 AstrBot 管理面板通过仓库链接 `https://github.com/yun474/astrbot_plugin_service_status` 安装；也可将插件放进 `data/plugins/astrbot_plugin_service_status`，或上传插件压缩包。
2. 由 AstrBot 安装 `requirements.txt`；手动部署也可在 AstrBot 的 Python 环境执行 `python -m pip install -r requirements.txt`。
3. 确保系统有中文字体。Windows 自动使用微软雅黑；Linux 推荐 `fonts-noto-cjk`，也可在 `font_path` 指定自己的字体文件。不附带商业字体。
4. 重载插件，在配置页启用服务，发送上述指令。若装有旧 GPT / Claude 插件，先停用旧插件，避免指令冲突。

使用 Pillow 本地生成 PNG，不需要 Chromium、浏览器驱动或外部图片渲染服务。图片是操作系统临时文件，发送后保留 180 秒，再由异步任务清理；插件卸载时也会清理。没有持久化业务数据。

## 数据与汉化

- OpenAI：[官网](https://status.openai.com)、[汇总接口](https://status.openai.com/api/v2/summary.json)、[事件接口](https://status.openai.com/api/v2/incidents.json)。公开汇总 API 的组件范围可能小于网页，当前组件以 API 返回结果为准；不补造未返回的当前状态。
- Claude：[官网](https://status.claude.com)、[汇总接口](https://status.claude.com/api/v2/summary.json)。逐日历史来自官网使用的 `/uptime_showcase` 接口。
- SCP:SL：[Northwood Studios Status Monitor](https://status.scpslgame.com/)，使用 Uptime Kuma 公开接口 `/api/status-page/nw` 与 `/api/status-page/heartbeat/nw`。覆盖中央服务器、Steam 登录验证、官方游戏服务器、自动验证与内部服务器，不代表所有社区服或个人线路。
- SCP:SL 状态条每格为一次官方探测，最多展示最近 100 次，不是天数；旁边的 `24h 可用` 是官方单独提供的 24 小时统计。当前状态取最新心跳，超过 15 分钟未更新、缺失或时间异常时标为未知。历史条不会补造未返回的检查。
- SCP:SL 公告使用“官方公告”标签，不根据公告颜色猜测是否已解决。公开接口仅列出置顶公告，空列表不代表没有未解决事件。当前维护来自官方 `maintenanceList`；该接口不提供完整已解决事件历史，对应区域明确提示数据不可用。
- OpenAI 的历史条来自官网页面内的完整历史窗口与组件影响区间，按 UTC 日展示最严重状态。新组件开始记录前及首个不完整日为灰色，不从有限的“近期事件列表”推算正常天数。不展示统计窗口无法明确对应的可用率数字。
- Claude 历史条使用官方逐日数据，显示官方 90 日可用率。缺失日期为灰色。历史日期按 UTC，查询时间和事件更新时间按 UTC+8，并在图片中标注。
- 官方接口缺少事件字段时，不显示“暂无事件”；请求历史失败不影响已获取的当前状态。状态查询失败不会拿过期缓存冒充实时结果。
- 状态标签和已知组件名始终中文显示；未知组件保留官方名称，未知状态明确标注。常见完整公告句子有固定译文，不对未知句子做生硬词语替换。
- `llm_translate_events` 可选调用当前会话模型，默认关闭。开启后仅翻译图片将展示的公告，按原文缓存，不写入聊天上下文；失败时保留原文。图片中的模型译文标注“机器翻译”。
- 公告很长时节选展示，当前事件和维护各最多 8 条；超出数量明确提示。完整公告请查看图片底部官网。

官方历史页面不是稳定承诺的公共 API，页面结构变化时可能暂时拿不到历史；此时显示“历史暂不可用”，不画全绿占位条。查询数据默认缓存 60 秒，图片时间是实际获取时间，命中缓存不会刷新成当前时间。

**SCP:SL 接入限制：** 2026-10-02 已在浏览器确认官方页面及 `nw` 标识，但本机程序请求被 Cloudflare 返回 403。`/sl状态` 遇到这种情况会说明无法自动读取并附官网链接，不将访问拦截解释成游戏故障。适配器依据 Uptime Kuma 官方源码实现并做离线测试；本机尚未完成实时接口成功获取的验证。普通浏览器能访问不代表机器人的 HTTP 请求也能访问，配置代理亦不保证通过验证。

## 框架与扩展

```text
main.py                AstrBot 注册、开关、调用编排、临时文件生命周期
_conf_schema.json      WebUI 配置
services/*.json        服务地址、组件汉化、主题和数据源选择
themes/*.json          颜色与品牌风格
core/models.py        统一数据结构
core/statuspage.py    Statuspage v2 兼容接口
core/uptime_kuma.py   Uptime Kuma 监控、公告与近期探测
core/client.py        请求、服务级缓存与并发合并
core/uptime.py        各官方历史数据解析
core/localization.py 中文状态与时间
core/translation.py  可选事件翻译
core/renderer.py     统一排版和本地图片生成
```

接入另一个 Statuspage 服务：复制一个 `services/*.json`，填写唯一 `id`、`command`、官方 HTTPS 地址和组件名称映射，再把 ID 加入 `enabled_services`。`uptime_source` 不支持时留空。新服务立即支持 `/服务状态 服务ID`；如需 `/xx状态`，在 `main.py` 增加标准指令入口：

```python
@filter.command("xx状态")
async def xx_status(self, event: AstrMessageEvent):
    yield await self._query(event, "xx")
```

这里有意保留显式装饰器，让 AstrBot 能正常发现、管理和重载指令。删除服务时，删除对应 JSON 与这几行入口，并从启用列表移除 ID。调整配色只改主题 JSON；接口不兼容 Statuspage 的服务，在 `core/client.py` 的 `ADAPTERS` 注册新适配器，返回 `Snapshot` 即可复用后续流程。

Uptime Kuma 服务可设置 `adapter: "uptime_kuma"` 和 `status_page_slug`；SCP:SL 的标识为 `nw`，来源是官方页面的 manifest 链接。`uptime_source` 留空，因为心跳接口同时返回当前状态和近期历史。

## 开发验证与兼容性

```shell
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python scripts/preview.py
```

预览脚本请求实时官方数据，输出到忽略提交的 `output/`，不会调用模型。

技术最低版本声明为 **AstrBot 3.4.34**：已核对该版本公开的配置、指令、Star 生命周期与 Provider API；保留类注册装饰器以支持该版本，当前 AstrBot 已将它标为弃用。测试版本与技术最低版本分开记录，不因为开发机的版本较新而抬高最低要求。

2026-10-02 验证记录：15 项自动测试通过；使用本机 AstrBot **4.28.2** 的真实 API 完成导入与三个指令注册、停用服务不发请求、生成图片结果、启用列表和卸载清理检查；两家实时官方数据均已生成图片并人工查看布局。完整机器人在 QQ 等平台的收发、真实模型翻译与旧版本加载仍需在实际部署环境验收，不把源码核对或模拟消息事件当成端到端验证。

当前版本为 `0.1.0`，尚未发布 Release。更新日志 `CHANGELOG.md` 由维护者补充。

SCP:SL 本地增量验证：30 项自动测试通过，另在 AstrBot 4.28.2 核对四个标准指令、`sl` 停用时不请求接口、Cloudflare 拒绝访问的回复以及卸载清理。图片仅用明确标注“非实时数据”的接口样例验证布局；SCP:SL 实时 API 当前受阻，不能将样例当成当前游戏状态。
