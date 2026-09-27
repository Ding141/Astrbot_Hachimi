# 安全与隐私说明

## 私有数据边界

本仓库发布代码和无密钥模板。以下内容始终留在机器本地并由 Git/Docker 忽略规则排除：

- `.env`：网页登录密码、会话签名密钥、AstrBot API Key、内部服务令牌和私有天气地点。
- `data/`：Todo/课表数据库，以及 AstrBot 提供商配置、平台登录态和微信会话信息。
- `backups/`、`exports/`：数据库备份和生成的个人信息导出。
- `.xlsx`/`.xls` 课表、CSV/JSON 导出、日志、本地说明文件和 Codex 工作目录。

公开仓库的加入采用文件白名单；提交前还要运行发布检查脚本。即使已忽略，也不要在命令行参数、聊天记录、Issue 或截图中粘贴密钥、微信会话 ID 或私人导出。

导出内容可能包括 Todo 文字、课程名称与地点、教师、个人安排、提醒接收 UMO、操作历史和周总结。JSON/CSV“不包含密钥”不等于“没有隐私信息”。应加密备份并仅分享给可信设备。

## 访问控制

- Docker Compose 使用本项目独立命名的网络、服务和绑定数据目录；API 和数据库不开放宿主机端口。
- Todo 网页仅映射至 `127.0.0.1:8080`，AstrBot WebUI 仅映射至 `127.0.0.1:6185`。
- 浏览器会话使用签名的 HttpOnly、SameSite Strict Cookie。登录最多接受 5 次连续失败，15 分钟内限制重试；Cookie 写操作和网页登录要求来源校验。
- 远程网页访问使用 SSH 本地端口转发。每台获准电脑使用独立密钥；建议用无 sudo 权限的隧道账号，并通过 SSH 服务端规则限制为本地转发和 `127.0.0.1:8080`、`127.0.0.1:6185`。不要将任一应用端口开放到公网。
- AstrBot 插件通过内部 Bearer 服务令牌调用 API；`SERVICE_API_TOKEN` 属于高权限凭据，应与 `.env` 同等保护。
- 页面设置了 CSP、反嵌套、MIME 嗅探限制、Referrer Policy 和功能权限响应头；动态文本应经 HTML 转义或使用 `textContent`。

登录限速在单进程内存中计数。它可降低普通暴力尝试，不代替强密码、SSH 密钥访问控制或主机安全更新。

## 文件上传与容器

- Excel 上传限 `.xlsx`，HTTP 上传最大 10 MiB；解析前再限制压缩文件条目数、单条目大小、总解压大小和压缩率。解析错误不会把工作簿内容回显到日志或错误响应。
- API 容器以项目配置的普通 UID/GID 运行，丢弃 Linux capabilities 并启用 `no-new-privileges`。
- AstrBot 挂载的项目插件目录为只读；仅 AstrBot 自己的数据目录持久化写入。
- 只运行本项目的 Compose 命令。不要用 `docker system prune`、清空共享 Docker volume 或删除其他项目目录。

## 密钥轮换和事故处理

若 `.env`、AstrBot 数据目录或备份泄露：先撤销 SSH 隧道密钥或临时关闭相应远程访问，再撤销 AstrBot OpenAPI Key 与模型服务 Key；更换网页登录密码、`SESSION_SECRET` 和 `SERVICE_API_TOKEN`，并重新部署 API/AstrBot。排查聊天日志、命令历史、Git 暂存区和备份副本。已提交的秘密即便后来删掉也可能留在 Git 历史中，应视为已泄漏。

在公共发布前请使用：

```bash
python3 scripts/check-public-release.py
git diff --cached --name-only
git diff --cached --check
```

发布检查验证 Git 暂存文件位于白名单内，并扫描暂存文本中的常见凭据、微信 ID 和家目录路径。它是辅助检查，不代替人工逐个检查新增文件与导出内容。

## 安全范围

该项目面向个人或小范围私有使用，不是多租户服务。它不防御已取得服务器管理员/root/Docker daemon 权限的攻击者，也不加密在线 SQLite 数据库。主机磁盘和异地备份应使用操作系统或存储层加密；系统补丁、SSH 服务和密钥管理由服务器管理员负责。
