# 架构说明

## 进程和信任边界

```text
微信个人号
    │
    ▼
AstrBot + Todo / 课表 / 提醒 / 推送插件 ── private Compose network ── Python API
                                                                      │
                                                    SQLite + reminder scheduler
                                                                      │
                                                             AstrBot OpenAPI

Browser ── 127.0.0.1:8080 ── authenticated UI and versioned API ──────┘
Authorized computers ── SSH local forwarding ── server loopback :8080/:6185
```

- AstrBot 管理微信适配器、LLM 和 Agent 工具调用；Todo、课表/日程、提醒/复盘和推送预览插件把结构化参数发给个人助手 API。
- `personal_assistant/api/` 按系统/认证、Todo、提醒、课程导入、个人日程、周复盘和导出拆分路由；跨资源查询、渲染和重复任务等共用操作位于 `personal_assistant/services/domain.py`。
- API 是业务数据的唯一写入入口，管理网页也经由 API 工作，不能绕过 API 直接打开数据库。
- `web/js/` 将状态与公共请求、Todo、提醒、复盘、课表和操作记录拆成原生 ES 模块；页面无需前端构建器。
- 插件将 API 结构化结果渲染为中文文本后交给模型；课表文本包含日期、星期、教学周、课程节次、时间、地点和教师。
- API 通过容器内网络调用 AstrBot OpenAPI 发送主动提醒。无 OpenAPI Key 时提醒保留为待发送，不发出外部请求。
- SQLite 使用 WAL 和外键；schema 版本用 `PRAGMA user_version` 管理。旧 schema 升级到 v3 前会在 `backups/` 中生成 SQLite 一致性快照。
- Compose 项目名为 `personal-assistant-astrbot`，没有固定容器名，网络、服务名和数据卷/绑定目录均由本项目 Compose 管理。

## 核心数据

- `todos`：任务文本、分类、优先级、日期/时刻级截止时间、状态和软删除时间。
- `reminders`：任务关联、提醒时间、收件会话 UMO、发送状态、尝试次数和错误信息。
- `terms` / `courses`：学期第 1 周周一、课程周几/节次/时间、周次范围、单双周、地点和教师。
- `todo_series`：每日/每周重复规则；每次发生会建立独立 Todo 记录，完成历史不会覆盖。
- `schedule_events`：单次或每周个人安排；按节次映射校历时间，并提示与课程/其他安排的冲突。
- `weekly_reviews`：每周复盘文字；下周 Todo 与安排分别保存到 Todo 和个人日程资源。
- `period_times`：图片提供的 14 节开始/结束时刻表。
- `settings`：默认微信会话 UMO 等非凭据设置。
- `audit_log`：关键变更前后的结构化记录。

截止日期允许只有日期，不补时刻。重复任务每期保存独立记录，父任务必须等所有子任务完成后才能完成。提醒按 `Asia/Shanghai` 解释未附时区的时刻，并以 UTC 存储。发送超时或服务在发送中重启时记为 `uncertain`，不会自动重发；确定的网络连接失败最多自动重试三次。

统一服务端调度器生成重复 Todo 提醒、课前提醒、每日早报和周复盘提醒。默认早报为每日 08:00、周复盘为周日 20:00、课前提醒提前 10 分钟（按课程逐门启用）。所有待发送状态保存在 SQLite 中。

早报正文由独立的推送内容模块组合；天气、RSS 新闻等可选模块与核心日程模块隔离。可选模块失败时只记录日志并跳过，不会中断提醒发送。具体配置见 `docs/push-content-modules.md`。

## HTTP 接口和权限

- 浏览器 API 使用 HMAC 签名的短期 HttpOnly、SameSite Strict Cookie。
- AstrBot 插件用 `SERVICE_API_TOKEN` Bearer 令牌调用 API。
- `ASTRBOT_API_KEY` 仅供提醒调度器调用 AstrBot `POST /api/v1/im/message`，与 LLM 提供商密钥分开。
- `/healthz` 不要求认证，只返回服务存活状态；业务端点均需浏览器会话或插件令牌。
- 管理页和 AstrBot WebUI 默认只映射到 `127.0.0.1`。
- 远程访问通过 SSH 本地端口转发到服务器回环地址 `127.0.0.1:8080` 和 `127.0.0.1:6185`；网页端口不直接映射到公网。可用专用 SSH 账号、独立设备密钥和 `PermitOpen` 将权限限制为这两个服务，两个网页继续要求各自的登录认证。
- 公共发布文件使用白名单检查；私有 `.env`、SQLite、课表、备份、导出和 AstrBot 登录态不在发布内容中。

## 课表处理

预览 API 返回工作簿信息、解析到的课程和行/列错误。既支持标准表头行映射，也支持项目内星期列合并单元格周历和同格多课程。确认导入需要填写学期名和第 1 周周一；替换同名学期需要 `replace_existing=true`，网页会再次确认，并取消旧课程对应的待发送课前提醒。
