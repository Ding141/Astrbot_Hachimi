# 每日推送内容模块

每日早报的内容组合独立于 Todo、课表和提醒计划实现，入口位于 `personal_assistant/push_plugins/`。现有 `agenda` 模块汇总课程、个人日程、到期和逾期任务；天气地点只从项目私有 `.env` 读取，缺少配置时跳过天气栏目，不推测个人所在地。新闻是可选模块，未配置 RSS 时自动跳过，不会生成虚构内容。天气数据通过 Open-Meteo Forecast API 获取；微信天气工具和早报天气都会附上来源链接；新闻标题也会逐条附上原文链接。

## 可选天气与新闻

复制配置模板时，可在本项目自己的 `.env` 中填写：

- `WEATHER_LOCATION_NAME`：推送中显示的地点名称。
- `WEATHER_LATITUDE`、`WEATHER_LONGITUDE`：Open-Meteo 查询坐标。天气模块需要完整填写地点名称和坐标。
- `NEWS_RSS_URLS`：一个或多个 RSS/Atom 地址，用逗号分隔。每次最多读取 4 个来源、展示 4 条标题。

配置后运行 `./scripts/up.sh` 使 API 环境变量生效并加载新的 AstrBot 插件挂载。新闻未配置或某个来源暂时无法访问时，核心日程推送仍会继续。

## 增加自定义模块

模块提供 `name` 和 `build(target: date) -> str | None`。将模块加入 `registered_modules()` 即可在本项目中启用；若模块打包为 Python distribution，也可通过 `personal_assistant.push_modules` entry point 自动发现。内容生成失败会记录在 API 日志中并跳过该模块，不影响其他模块。

AstrBot 侧新增独立的“个人助手推送”插件，提供 `daily_brief_preview` 工具，预览网页/定时推送使用的同一份消息。发送调度和持久化状态仍由 API 服务统一负责，避免多个插件各自启动调度器。
