# 个人 AI 助手

个人使用的 AI 助手项目，以 AstrBot 连接微信和大语言模型，以本项目的 FastAPI 服务、SQLite 和网页管理端管理 Todo、课表、日程与提醒。当前发布版本为 **v0.5.0**，可本地或私有服务器运行。

## 功能

- 微信自然语言管理 Todo：新增、查询、修改、完成、删除、搜索、分类、重要/紧急四象限、截止日期、每日/每周/每月重复和多个提醒。
- 支持一层子任务与重复任务子任务模板；父任务需等子任务完成后才能完成。
- 支持 Todo 日/周/月日历；每月任务按月末自动收敛，并要求新重复规则设置停止日期。
- 按学期查看课程与个人安排；支持学期日期范围、整学期课程修改、单日调课/停课/恢复、课前提醒批量预览和确认。
- 导入 `.xlsx` 课表前先预览；兼容标准字段表和星期列合并单元格周历。
- 统一管理 Todo 提醒、课前提醒、每日早报与周复盘；可从网页或微信进行周复盘和下一周安排。
- 结构化的中文工具结果；可选天气与 RSS 新闻模块会标出事实来源。
- JSON/CSV 导出、SQLite 一致性备份与恢复，以及面向 Ubuntu 服务器的迁移步骤。

## 架构

```text
微信 ── AstrBot + 项目插件 ── 项目私有 Docker 网络 ── FastAPI ── SQLite
网页 ── 127.0.0.1:8080 ────────────────────────────────┘
获准电脑浏览器 ── Tailscale Serve HTTPS ── tailnet ── 服务器 127.0.0.1:8080/6185
```

- `personal_assistant/api/` 按功能提供版本化 API，`personal_assistant/services/domain.py` 集中共享业务逻辑；入口仍是 `personal_assistant.app:app`。
- `web/js/` 使用浏览器原生 ES 模块，无 npm 或前端构建步骤。
- AstrBot 插件只调用业务 API；不直接访问数据库。
- 数据库 schema 当前为 v4；旧数据库会自动备份后迁移。API 路径保持兼容，已存在的旧版无限重复任务和个人安排继续保留。
- Compose 只把 Todo 网页绑定到宿主机 `127.0.0.1:8080`；AstrBot WebUI 绑定到 `127.0.0.1:6185`。数据库没有宿主机端口映射。

详细结构见[架构说明](docs/architecture.md)。

## 新机器部署

支持 Ubuntu 22.04 或更新的 Ubuntu 主机。安装 Docker Engine 与 Compose Plugin 时请使用 [Docker 官方 Ubuntu 安装指南](https://docs.docker.com/engine/install/ubuntu/)。本项目不要求安装系统级 Python 依赖；开发依赖仅用于项目内虚拟环境。

从本机连接 DeepSeek、启用插件和个人微信，到迁移数据并在服务器上安全运行的完整步骤，见[本机测试与服务器部署指南](docs/setup-guide.md)。

新增的学期、课程、批量提醒和 Todo 功能用法见[新版功能操作说明](docs/features-and-usage.md)。

```bash
git clone <公开仓库地址>
cd <仓库目录>
./scripts/init-local.sh
./scripts/up.sh
```

初始化脚本会在项目目录生成仅当前用户可读写的 `.env`、随机网页登录密码和内部会话/服务密钥，并创建 `data/`、`backups/`。**请在首次运行时保存脚本显示的网页登录密码。**脚本不会配置模型 API Key，也不会连接微信。

- Todo 管理页：<http://127.0.0.1:8080>
- AstrBot WebUI：<http://127.0.0.1:6185>

常用命令：

```bash
sudo docker compose ps
sudo docker compose logs -f assistant-api astrbot
./scripts/backup.sh
sudo docker compose down
```

如果当前用户已具备 Docker daemon 访问权限，可去掉 `sudo`。获得该权限通常相当于主机 root；本项目不会修改 Docker 组成员或系统权限。

## 配置微信和模型

1. 打开 AstrBot WebUI，添加支持函数调用的模型服务商，配置模型并为 Agent 启用函数工具。
2. 在 AstrBot 插件页启用项目挂载的 Todo、课表与日程、提醒与复盘、推送和共享桥接插件。
3. 添加“个人微信”平台适配器并完成扫码。按 [AstrBot 个人微信文档](https://docs.astrbot.app/platform/weixin_oc.html)确认当前 AstrBot、微信客户端和手机侧插件要求。
4. 微信发出消息后，机器人会绑定最近使用的会话，网页创建的提醒可以发到该会话。
5. 主动提醒还需要在 AstrBot 创建仅含 `im` scope 的 OpenAPI Key，填入项目 `.env` 的 `ASTRBOT_API_KEY`，然后重建 API 服务。它与模型提供商 API Key 不同。

操作步骤和人工验收清单见[手动连接与验收](docs/manual-checklist.md)。天气地点和 RSS 地址等个性配置仅写在私有 `.env`；模板不包含个人位置。

已有服务器的安全更新顺序是：先确认 `git status --short`，再运行 `./scripts/backup.sh`，使用 `git pull --ff-only origin main` 拉取代码，运行 `./scripts/up.sh` 构建并启动服务，然后运行 `sudo docker compose restart astrbot` 重新加载插件。检查 `/healthz`、容器日志和网页后再继续使用。完整回滚提示见[部署与数据运维](docs/operations.md#更新与回滚)。

## 服务器上的私有网页访问

远程网页访问使用 **Tailscale Serve**：服务器在 tailnet 内为两个网页提供 HTTPS 地址，授权电脑登录同一 tailnet 后即可用浏览器访问。管理页仍只绑定服务器 `127.0.0.1`，不会映射到公网；可以用 Tailscale 设备审批和访问策略把权限限于指定电脑。无需配置网页 SSH 隧道。服务器 `.env` 设置 `COOKIE_SECURE=true`。分步配置见 [Tailscale 远程访问操作指南](docs/remote-access.md)。

## 备份、恢复与迁移

```bash
./scripts/backup.sh
ls -lh backups/
./scripts/restore.sh assistant-YYYYMMDDTHHMMSSZ.sqlite3
```

`backups/` 中是 SQLite online backup API 创建的一致性快照。迁移服务器时还要私密转移 AstrBot 的 `data/astrbot/`；该目录可能含微信会话登录态和服务商密钥。新机器用 `./scripts/init-local.sh` 生成独立 `.env`，更新 `APP_UID`、`APP_GID`，恢复数据后运行 `./scripts/up.sh`。完整流程见[部署与数据运维](docs/operations.md)。

## 安全与隐私

- 不要提交 `.env`、`data/`、`backups/`、SQLite 文件、课表工作簿、导出文件、AstrBot 会话数据或日志。
- 导出的 Todo、课表、提醒、复盘和操作记录可能包含个人信息；即使 JSON/CSV 不含 API Key，也应按私密数据保管。
- AstrBot WebUI 和 API 不直接映射到公网；Tailscale Serve 只向 tailnet 提供网页，并可通过访问策略限制到获准设备。这两个网页仍保留各自的登录认证。不要使用 Funnel 发布到公网。
- 上传的 `.xlsx` 限制压缩文件大小、条目数、单文件及总解压大小和压缩率。
- 发布前使用 `python3 scripts/check-public-release.py` 检查暂存文件白名单和敏感内容。

安全说明见[安全与隐私](docs/security.md)。

## 本地开发与检查

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
.venv/bin/ruff check personal_assistant tests
```

测试服务器只绑定临时 `127.0.0.1` 端口，使用 `/tmp` 下的临时数据库和专门的测试凭据，不读取项目 `.env` 或真实微信会话。

## 文档与许可证

- [架构说明](docs/architecture.md)
- [部署、备份和迁移](docs/operations.md)
- [本机测试与服务器部署](docs/setup-guide.md)
- [Tailscale 远程访问操作指南](docs/remote-access.md)
- [安全与隐私](docs/security.md)
- [每日推送模块扩展](docs/push-content-modules.md)
- [联网搜索与来源说明](docs/web-search.md)
- [手动连接与验收](docs/manual-checklist.md)
- [Apache-2.0 许可证](LICENSE)
