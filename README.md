# 互联网服务状态

给群里发一张服务状态卡。当前接入 **OpenAI / GPT**、**Claude** 和 **DeepSeek**，数据来自各自官方状态页；组件状态、事件和支持的数据源历史状态条放在同一张图片中。

云云把 GPT 和 Claude 状态查询整理成了一个可扩展的 AstrBot 插件，作者 `yun474`。项目仓库：[yun474/astrbot_plugin_service_status](https://github.com/yun474/astrbot_plugin_service_status)。

## 指令与开关

| 指令 | 用途 |
| --- | --- |
| `/gpt状态` | OpenAI 官方状态 |
| `/claude状态` | Claude 官方状态 |
| `/ds状态` | DeepSeek 官方状态，也支持 `/服务状态 ds` |
| `/服务状态` | 列出已启用的服务 |
| `/服务状态 gpt` | 用服务 ID 查询，方便扩展新服务 |

不注册英文别名。指令由 AstrBot `@filter.command` 处理，遵循框架唤醒前缀和权限机制，不自行监听或截获普通聊天。

在配置页的 `enabled_services` 列表中保留需要的服务 ID，新安装默认开启 `gpt`、`claude`、`ds`。已有配置需要手动加入 `ds` 才会启用 DeepSeek。删除任意一项即可停用；空列表关闭全部查询。停用服务仍会礼貌回复“已停用”，不会发起状态请求、翻译或渲染。

`show_incidents`、`show_maintenance`、`show_history`、`show_uptime` 分别控制当前事件、维护、近期事件和历史状态条。`show_uptime` 关闭后不额外请求历史状态条数据。

## 安装

1. 在 AstrBot 管理面板通过仓库链接 `https://github.com/yun474/astrbot_plugin_service_status` 安装；也可将插件放进 `data/plugins/astrbot_plugin_service_status`，或上传插件压缩包。
2. 由 AstrBot 安装 `requirements.txt`；手动部署也可在 AstrBot 的 Python 环境执行 `python -m pip install -r requirements.txt`。
3. 确保系统有中文字体。Windows 自动使用微软雅黑；Linux 推荐 `fonts-noto-cjk`，也可在 `font_path` 指定自己的字体文件。不附带商业字体。
4. 重载插件，在配置页启用服务，发送上述指令。若装有旧 GPT / Claude 插件，先停用旧插件，避免指令冲突。

使用 Pillow 本地生成 PNG，图片渲染不需要 Chromium、浏览器驱动或外部图片渲染服务。每次保存结束（包括失败）显式关闭 Pillow 图片，释放像素内存。临时图片生成后保留至少 180 秒供平台发送，由一个异步任务每 60 秒扫描并删除过期图片（通常在生成后 180～240 秒清理）；文件被占用时下次扫描重试，插件卸载时立即清空临时目录。没有持久化业务数据。

插件最多同时处理 4 个查询、2 个图片渲染；超过查询上限会回复繁忙。渲染放在线程执行，卸载时取消网络和翻译任务，等待已经开始的图片写入完成后再删除临时目录。异常长的文字和过高的图片会受到限制，避免异常官方数据长时间占用 CPU 或大量内存。

## 数据与汉化

- OpenAI：[官网](https://status.openai.com)、[汇总接口](https://status.openai.com/api/v2/summary.json)、[事件接口](https://status.openai.com/api/v2/incidents.json)。公开汇总 API 的组件范围可能小于网页，当前组件以 API 返回结果为准；不补造未返回的当前状态。
- Claude：[官网](https://status.claude.com)、[汇总接口](https://status.claude.com/api/v2/summary.json)。逐日历史来自官网使用的 `/uptime_showcase` 接口。
- DeepSeek：[官网](https://status.deepseek.com)，通过官网 CNAME 指向的 `statuspage.flashduty.com` 托管域名读取同一状态页的公开接口。支持组件状态、当前事件、维护与最近 90 日内已解决事件，使用蓝色主题；暂未接入逐日历史条。配置中的 `page_id` 标识官方页面，返回页面的 ID 和域名会校验，不使用旧 `deepseek.statuspage.io` 数据。
- OpenAI 的历史条来自官网页面内的完整历史窗口与组件影响区间，按 UTC 日展示最严重状态。新组件开始记录前及首个不完整日为灰色，不从有限的“近期事件列表”推算正常天数。不展示统计窗口无法明确对应的可用率数字。
- Claude 历史条使用官方逐日数据，显示官方 90 日可用率。缺失日期为灰色。历史日期按 UTC，查询时间和事件更新时间按 UTC+8，并在图片中标注。
- 官方接口缺少事件字段时，不显示“暂无事件”；请求历史失败不影响已获取的当前状态。状态查询失败不会拿过期缓存冒充实时结果。
- 状态标签和已知组件名始终中文显示；未知组件保留官方名称，未知状态明确标注。常见完整公告句子有固定译文，不对未知句子做生硬词语替换。
- `llm_translate_events` 可选调用当前会话模型，默认关闭。开启后仅翻译图片将展示的公告，按原文缓存，不写入聊天上下文；失败时保留原文。图片中的模型译文标注“机器翻译”。
- 公告很长时节选展示，当前事件和维护各最多 8 条；超出数量明确提示。完整公告请查看图片底部官网。

官方历史页面不是稳定承诺的公共 API，页面结构变化时可能暂时拿不到历史；此时显示“历史暂不可用”，不画全绿占位条。查询数据默认缓存 60 秒，图片时间是实际获取时间，命中缓存不会刷新成当前时间。

## 框架与扩展

```text
main.py                AstrBot 注册、开关、调用编排、临时文件生命周期
_conf_schema.json      WebUI 配置
services/*.json        服务地址、组件汉化、主题和数据源选择
themes/*.json          颜色与品牌风格
core/models.py        统一数据结构
core/statuspage.py    Statuspage v2 兼容接口
core/flashduty.py     DeepSeek / Flashduty 状态与事件解析
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

当前版本为 `0.1.2`，更新内容见 [CHANGELOG.md](CHANGELOG.md)。

本次安全检查补充了查询并发限制、网络取消、渲染取消后清理和保存失败释放图片内存的回归测试。指令继续使用框架标准装饰器，用户参数只能选择已登记的服务 ID，不能指定请求 URL、字体或输出路径；没有执行远端脚本或系统命令。可选翻译只提交官方公告，使用空会话上下文，不传入群聊历史或模型工具。

本次复验：25 项自动测试通过，GPT 与 Claude 实时接口和图片生成通过；新增测试覆盖周期清理、未过期图片保留及文件占用后的重试。

DeepSeek 接入验证（2026-10-02）：34 项自动测试通过，Ruff 检查通过；实际请求 Flashduty 托管接口取得 5 项组件及近期事件，已生成并查看图片。新增测试覆盖异常状态、页面身份校验、事件缺失、维护、历史请求失败以及 `/ds状态` 的启停行为；新指令尚未在 QQ 等实际平台收发验收。
