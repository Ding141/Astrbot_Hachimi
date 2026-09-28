# 本机测试与服务器部署操作指南

本文按“先在本机验证，再部署到 Ubuntu 服务器”的顺序说明本项目。命令从仓库根目录运行。当前 Compose 默认使用 AstrBot `v4.28.1`，应用数据保存在项目目录的 `data/` 和 `backups/` 中。

## 运行结构

```text
微信 ── AstrBot ── HTTPS 出站 ── DeepSeek API
          │
          ├── 项目插件 ── 私有 Compose 网络 ── 助手 API ── SQLite
          └── 管理台 127.0.0.1:6185

浏览器 ── 127.0.0.1:8080 ── 助手网页与 API
```

AstrBot 管理模型、会话和微信平台；挂载的项目插件通过内部网络调用助手 API。DeepSeek API Key 在 AstrBot 的模型提供商配置中保存。项目 `.env` 中的 `ASTRBOT_API_KEY` 是 AstrBot OpenAPI Key，用于助手 API 主动发提醒，**不是 DeepSeek Key**。

Compose 将宿主机端口绑定到 `127.0.0.1`，因此同一台机器以外的设备不能直接连接 `8080` 或 `6185`。个人微信适配器使用扫码登录与长轮询，不需要为本项目开放公网 Webhook 端口。

## 一、本机启动与验证

### 1. 准备环境

需要 Git、Docker Engine 和 Docker Compose Plugin。Ubuntu 安装方式参见 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)；Windows/macOS 可使用 Docker Desktop，并在 Bash、WSL2 或终端中运行下列脚本。

进入项目目录后初始化私有配置并启动：

```bash
./scripts/init-local.sh
./scripts/up.sh
```

`init-local.sh` 会生成权限为当前用户可读写的 `.env`、网页登录密码和内部密钥。它不会覆盖已有 `.env`；若提示文件已存在，继续使用当前凭据即可。首次生成时请把命令显示的网页登录密码存到密码管理器。不要把 `.env` 或 API Key 发到聊天、Issue 或代码仓库。

启动后检查服务：

```bash
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

如 Docker 需要提权，仓库脚本会尝试使用 `sudo`。Todo 网页地址为 <http://127.0.0.1:8080>；AstrBot 管理台地址为 <http://127.0.0.1:6185>。AstrBot 首次登录的临时密码可从日志查找：

```bash
docker compose logs --tail=200 astrbot
```

用户名通常是 `astrbot`。如果当前用户没有 Docker daemon 权限，上述 `docker compose` 查询命令前加 `sudo`。

### 2. 在 AstrBot 中接入 DeepSeek

先在 [DeepSeek 开放平台](https://platform.deepseek.com/)创建 API Key。接着进入 AstrBot 管理台：

1. 打开“模型提供商 → 对话”，选择“新增 → OpenAI Compatible”。
2. 提供商名称可填写 `DeepSeek`；API Base URL 填 `https://api.deepseek.com`，不要在末尾加 `/v1`；API Key 填刚创建的 DeepSeek Key。
3. 保存并获取模型，在列表中添加并启用一个模型。官方 API 文档当前示例使用 `deepseek-flash`；如果模型列表已更新，以管理台成功获取的模型列表和 DeepSeek 当前模型文档为准。
4. 打开“配置”，选择实际使用的人格配置，在“AI → 模型”中将“对话模型”设为刚添加的 DeepSeek 模型，然后保存。
5. 点击提供商中的“测试模型”，确认连接成功，再用 AstrBot 的聊天窗口发一条普通问候。

官方参考：[DeepSeek API 首次调用](https://api-docs.deepseek.com/zh-cn/)、[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)、[AstrBot 模型提供商](https://docs.astrbot.app/providers/llm.html)。DeepSeek 模型名称会随 API 更新；不要照搬旧教程中的 `deepseek-chat` 或 `deepseek-reasoner`，优先用 AstrBot“获取模型”显示的有效模型。

### 3. 启用项目插件和工具调用

Compose 已把仓库内的四个项目插件挂载进 AstrBot。打开 AstrBot 的插件管理页，启用：

- 个人助手 Todo
- 个人助手课表与日程
- 个人助手提醒与复盘
- 个人助手推送

`assistant_pa_common` 是这些插件共用的内部桥接代码，不需要单独启用。进入“扩展 → 处理器 → 函数工具”检查工具调用已启用，并在当前人格可用工具范围内允许相应插件工具。项目插件工具、人格和函数工具的入口可能随 AstrBot 小版本调整；官方说明见 [函数调用](https://docs.astrbot.app/use/function-calling.html)。

先验证单轮工具调用：

1. 对 AstrBot 发送“创建一个名为本机部署测试的待办，没有截止时间”，确认机器人调用工具并返回成功。
2. 打开 <http://127.0.0.1:8080>，用初始化生成的网页登录密码登录，确认该待办出现在列表中。
3. 让机器人查询并删除该测试待办，确认网页列表同步更新。

如果模型能聊天但不调用工具，先确认使用的模型支持函数调用、工具已对当前人格启用，然后新开一轮对话重试。AstrBot 的函数调用通过模型请求工具，工具实际执行由 AstrBot 和插件完成。

### 4. 连接个人微信（可选）

在 AstrBot 左侧打开“机器人”，点击“创建机器人”，选择“个人微信”，用手机微信扫描页面二维码并在手机端确认，登录成功后保存。项目固定的 AstrBot 版本高于个人微信适配器所需的 v4.22.0。手机微信版本和 ClawBot 插件要求可能变化，按 [AstrBot 个人微信接入文档](https://docs.astrbot.app/platform/weixin_oc.html)核对当前要求。

从微信发消息验证回复。再发送一条明确调用项目工具的消息，例如创建测试 Todo；工具成功调用后会绑定该聊天会话，网页创建的提醒才能发送到对应会话。

普通聊天和工具调用不需要 `ASTRBOT_API_KEY`。如果要启用 Todo、课前或定时主动提醒：

1. 在 AstrBot “设置 → OpenAPI”创建 API Key，只授予 `im` scope。
2. 将该 Key 写入项目 `.env` 的 `ASTRBOT_API_KEY`。
3. 重启助手 API 使变量生效：

```bash
docker compose up -d assistant-api
```

这把 Key 与 DeepSeek 提供商 Key 分开保管。AstrBot OpenAPI 入口和 Key 权限见 [AstrBot HTTP API 文档](https://docs.astrbot.app/dev/openapi.html)。

### 5. 本机验收完成后

手动核对清单见[手动连接与验收](manual-checklist.md)。如本机只是试跑，请先删除测试 Todo 和导入的测试课表；确认要带到服务器的数据后再做备份。

## 二、部署到 Ubuntu 服务器

### 1. 准备服务器

本项目文档按 Ubuntu 22.04 或更新版本编写。使用普通登录用户操作，不要以 root 运行 `init-local.sh`；脚本会按当前用户 UID/GID 配置 API 容器的数据目录权限。先按 [Docker 官方说明](https://docs.docker.com/engine/install/ubuntu/)安装 Docker Engine 与 Compose Plugin，并确保普通用户可通过 Docker 或 `sudo docker` 使用 Docker。

服务器需要出站连接 DeepSeek API 和 Tailscale。远程网页访问使用 Tailscale Serve；不要在云安全组或系统防火墙开放 `8000`、`8080`、`6185`、`6199`、`443` 或 `8443` 等项目/Tailscale Serve 端口。Tailscale Serve 从 tailnet 内接收请求，不需要开放服务器公网入站端口。仓库 Compose 已将 `8080` 和 `6185` 绑定到服务器回环地址。服务器的 SSH 管理方式是独立设置，本指南不要求为网页访问安装或配置 SSH 隧道。

### 2. 获取代码并生成服务器专用配置

在服务器上：

```bash
git clone <仓库地址> Astrbot
cd Astrbot
./scripts/init-local.sh
```

记录脚本显示的**服务器网页登录密码**。服务器生成自己的 `.env`、`SESSION_SECRET` 和 `SERVICE_API_TOKEN`；不要从测试电脑复制 `.env` 到服务器。检查 `APP_UID`、`APP_GID` 与服务器运行 `init-local.sh` 的普通用户一致。

首次部署与本机测试保持 `.env` 中的 `COOKIE_SECURE=false`。按后文配置好 Tailscale Serve HTTPS 后，再将服务器 `.env` 改为 `COOKIE_SECURE=true` 并重启 `assistant-api`；本机测试配置继续保持 `false`。

### 3. 选择是否迁移本机试跑数据

若要从空白实例开始，跳过此节，在服务器运行 `./scripts/up.sh` 后重新配置 DeepSeek、个人微信和项目插件即可。

若要保留本机 SQLite 数据、AstrBot 提供商/平台配置或微信登录态：

1. 本机清理不需要的测试数据，再生成数据库备份：

   ```bash
   ./scripts/backup.sh
   sudo docker compose down
   ```

   备份文件位于 `backups/assistant-*.sqlite3`。`docker compose down` 只停止本项目，不会删除 `data/` 或 `backups/`。

2. 通过 SSH 私密传输所需数据到服务器仓库的对应目录。示例中的用户名、主机名和服务器路径替换为实际值：

   ```bash
   scp backups/assistant-<备份时间>.sqlite3 <用户>@<服务器>:/<服务器仓库路径>/backups/
   rsync -a data/astrbot/ <用户>@<服务器>:/<服务器仓库路径>/data/astrbot/
   ```

   `data/astrbot/` 可能包含 DeepSeek Key、AstrBot 配置、插件数据和微信登录态，应像密码一样通过可信的加密连接传输和保管。若使用 SSH/SCP，需另行确认服务器管理 SSH 与 tailnet 策略允许你的管理电脑连接；本指南的网页访问策略只开放 HTTPS 网页端口，不会自动开放 SSH。若不迁移该目录，就在服务器重新输入模型 Key、重新配置平台并扫码登录。

3. 不迁移 `.env`。服务器保留刚生成的独立网页登录密码、会话密钥和服务令牌。如需提醒，在服务器 AstrBot 中新建 `im` scope Key，写入服务器 `.env` 的 `ASTRBOT_API_KEY`。

### 4. 启动并检查服务器服务

```bash
./scripts/up.sh
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

若迁移了 SQLite 备份，在服务启动后恢复：

```bash
./scripts/restore.sh assistant-<备份时间>.sqlite3
```

恢复完成后访问 `http://127.0.0.1:8080` 和 `http://127.0.0.1:6185` 验收服务，并在 AstrBot 中重新检查模型、插件、函数工具和机器人连接状态。配置未迁移或密钥无效时，请按本机步骤重新输入 DeepSeek Key 并点击“测试模型”。

### 5. 从自己的电脑管理服务器

Tailscale Serve 必须配置在**真正运行项目的服务器**上。此前在本机/WSL 测试环境中配置成功，不会自动把 Serve 路由复制到新服务器；每台 Tailscale 设备有自己的 Serve 配置，新服务器也会有自己的设备名和 HTTPS 地址。

按 [Tailscale 远程访问操作指南](remote-access.md)完成账号、设备审批、访问策略、MagicDNS 和 HTTPS 证书设置。部署到真实服务器时，按以下顺序操作：

1. 确认生产服务器和 Windows 客户端都加入同一个 tailnet；在管理控制台批准生产服务器和授权电脑。访问策略中的服务器 Tailscale IP 要替换为生产服务器的实际 IP，允许已授权电脑连接服务器 TCP `443` 和 `8443`。
2. 在生产服务器项目目录确认容器正常，并且两个网页在服务器本机可用：

   ```bash
   sudo docker compose ps
   curl -fsS http://127.0.0.1:8080/healthz
   curl -sS -o /dev/null -w 'AstrBot HTTP %{http_code}\n' http://127.0.0.1:6185/
   ```

3. 在生产服务器编辑 `.env`，将 `COOKIE_SECURE=false` 改为 `COOKIE_SECURE=true`，然后重启 API：

   ```bash
   sudo nano .env
   sudo docker compose up -d assistant-api
   ```

4. 仍在生产服务器上检查 Serve 状态；确认没有要保留的其他 Serve 路由后，配置两个网页：

   ```bash
   sudo tailscale serve status
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
   sudo tailscale serve --bg --https=8443 http://127.0.0.1:6185
   sudo tailscale serve status
   ```

5. 从最后一条命令复制实际显示的 HTTPS 地址，在 Windows 浏览器中分别打开。Todo 通常使用 `https://生产服务器名.你的tailnet.ts.net/`；AstrBot WebUI 通常使用 `https://生产服务器名.你的tailnet.ts.net:8443/`。实际名称以生产服务器的 Serve 输出为准，不能沿用测试机显示的名称。
6. 两个页面都能打开并成功登录后，日常只需在 Windows 上连接 Tailscale，再访问这两个 HTTPS 地址。不要访问 `http://生产服务器Tailscale-IP:8080` 或 `:6185`；也不要开放公网应用端口或启用 Funnel。

若 Windows 上的 `tailscale serve status` 显示 `No serve config`，这是 Windows 自己没有托管 Serve 路由的状态；网页路由应在生产 Ubuntu 服务器上查看。详细排查步骤见 [Tailscale 远程访问操作指南](remote-access.md)。

## 三、日常维护

```bash
# 状态和日志
docker compose ps
docker compose logs --tail=100 assistant-api astrbot

# 数据库备份
./scripts/backup.sh

# 正常停止本项目
docker compose down
```

服务器升级前先备份数据库，再在仓库目录获取代码更新并重建服务：

```bash
git pull
./scripts/up.sh
```

AstrBot 镜像默认固定版本；升级 AstrBot 前先检查兼容性，再显式修改服务器 `.env` 中的 `ASTRBOT_IMAGE`。不要运行 `docker system prune`、清空共享 volume 或删除 `data/`。更完整的备份恢复说明见[部署与数据运维](operations.md)，安全边界见[安全与隐私](security.md)。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| DeepSeek 提供商无法连接 | 核对 API Key、账户可用额度和 `https://api.deepseek.com` 地址；确认服务器可出站访问 DeepSeek。 |
| 模型能答话但不调用项目工具 | 核对模型支持函数调用；启用四个项目插件，确认当前配置文件的人格允许相应函数工具。 |
| 插件提示无法连接个人助手服务 | 查看 `docker compose logs --tail=100 assistant-api astrbot`；确认 Compose 服务健康并由项目 `up.sh` 启动，不要把容器间地址改成宿主机 `localhost`。 |
| 本机可用，服务器网页打不开 | `8080` 与 `6185` 是服务器回环端口；确认服务器和客户端 Tailscale 在线、设备已批准、访问策略允许 443/8443，并在服务器检查 `sudo tailscale serve status`。 |
| 主动提醒未发送 | 检查 `.env` 的 `ASTRBOT_API_KEY` 是否为 AstrBot 的 `im` scope Key、最近是否有插件工具成功绑定会话，并查看 API 与 AstrBot 日志。 |
| 个人微信扫码失败或适配器离线 | 按 AstrBot 当前个人微信文档核对手机微信版本、ClawBot 插件、扫码确认和适配器日志。 |
