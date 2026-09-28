# 部署与数据运维

从本机首次连接 DeepSeek 到服务器迁移的完整步骤见[本机测试与服务器部署操作指南](setup-guide.md)。本文聚焦常见运维和数据迁移细节。

## 前置条件

Ubuntu 22.04 或更新版本安装 Docker Engine 和 Compose Plugin 时，使用 Docker 官方安装说明：<https://docs.docker.com/engine/install/ubuntu/>。

Docker daemon 的访问权限接近 root。本项目没有将登录用户加入 `docker` 组；启动脚本会优先尝试普通 `docker`，不具备访问权限时使用 `sudo docker`。

## 首次启动

```bash
./scripts/init-local.sh
./scripts/up.sh
```

初始化脚本只在项目目录创建 `.env` 与 `data/`、`backups/` 目录。`.env` 权限为当前用户只读写；管理密码和内部令牌由随机数生成器创建。将首次显示的管理密码保存到安全位置。

访问 `http://127.0.0.1:8080` 管理 Todo，访问 `http://127.0.0.1:6185` 配置 AstrBot。端口冲突时修改项目 `.env` 的 `WEB_PORT` 或 `ASTRBOT_WEB_PORT`，不修改系统级网络设置。网页 Compose 端口固定绑定回环地址；服务器远程访问按 [Tailscale Serve 操作指南](remote-access.md)配置。

## 常用操作

```bash
# 查看运行状态和日志
sudo docker compose ps
sudo docker compose logs -f assistant-api astrbot

# 更新本项目代码和容器（详细步骤见下方“更新与回滚”）
git pull --ff-only origin main
./scripts/up.sh

# 正常停止本项目容器
sudo docker compose down

# 创建数据库快照
./scripts/backup.sh

# 从备份恢复（恢复时 API 容器会暂时停止）
./scripts/restore.sh assistant-YYYYMMDDTHHMMSSZ.sqlite3
```

只停止 Compose 服务，不要执行 `docker system prune`、清空 Docker volume 或删除 `data/`；这些命令可能影响其他项目或删除用户数据。

## 备份和恢复

- `./scripts/backup.sh` 调用 SQLite online backup，快照保存在 `backups/`。
- `./scripts/restore.sh <文件名>` 要求备份位于项目 `backups/`，先做 SQLite 完整性检查，再以临时文件原子替换当前数据库。
- 个人助手从旧 schema 升级到 v5 时，会先在 `backups/` 生成带版本号的 SQLite 一致性快照。迁移会增加待办开始日期/时刻和重复待办每期开始时刻；旧学期结束日期按 18 周估算并标记为推测值，建议在网页中核对。已停用的子任务数据会软删除并从活动列表分离，迁移前快照仍可恢复。
- JSON 导出包含 Todo、重复系列、提醒、课程、个人日程、周复盘、非秘密设置和操作记录；CSV 可分别导出这些主要资源，不包含密钥。
- 另行备份 `data/astrbot/` 以保存 AstrBot 平台和提供商配置。该目录可能含有平台登录态与密钥，转移时使用私密、加密的方式。
- 至少将 `backups/` 复制到另一块磁盘或受控位置；同盘备份无法防止磁盘故障。

## 迁移到服务器

1. 本机运行 `./scripts/backup.sh`，再停止服务或确保完成备份。
2. 安装 Docker/Compose 后，在服务器准备项目文件。可从代码仓库取公开代码；不要把本地 `.git`、`.venv` 或容器缓存当作迁移依赖。
3. 私密转移 SQLite 备份和 AstrBot `data/`；`.env` 不要从旧机器复制，也不要放入代码仓库。在服务器运行 `./scripts/init-local.sh` 生成独立配置，再把 `.env` 中的 `APP_UID`、`APP_GID` 设置为 `id -u`、`id -g` 的结果，然后执行 `sudo chown -R "$(id -u):$(id -g)" data/service backups`，让 API 容器继续以目标机普通用户写数据库和备份。本机 HTTP 测试使用 `COOKIE_SECURE=false`；配置 Tailscale Serve HTTPS 后，服务器 `.env` 改为 `COOKIE_SECURE=true`。
4. 恢复 SQLite，按需重建 API 镜像并启动项目 Compose 服务；核对迁移前备份、服务健康状态与日志。若 AstrBot 容器无法读写迁来的 `data/astrbot/`，按当前固定镜像所使用的容器用户修正该目录属主。检查模型和平台凭据是否仍有效。
5. 若需从外部设备访问网页，按 [Tailscale Serve 操作指南](remote-access.md)为实际运行项目的服务器和指定电脑启用 Tailscale，并配置设备审批与访问策略。Serve 路由属于单台设备；本机/WSL 测试机的配置不会自动迁移，需在服务器重新运行两条 Serve 命令，并使用服务器输出的 HTTPS 地址。不要开放 Todo 网页或 AstrBot WebUI 的公网端口，也不要启用 Funnel。

## 更新与回滚

在服务器项目目录按顺序执行。先确认没有尚未提交的服务器端代码修改，并记录当前版本，便于回退：

```bash
git status --short
git rev-parse --short HEAD
./scripts/backup.sh
git pull --ff-only origin main
./scripts/up.sh
```

`git pull --ff-only` 遇到本地分叉或修改时会停止，不会自行制造合并提交。此时先保留并检查本地改动，不要用 `reset --hard` 覆盖。`up.sh` 会构建并启动项目服务；数据库升级时应用会自动在 `backups/` 留一致性快照。

随后重启 AstrBot，让它重新载入项目插件，并检查服务与网页 API：

```bash
sudo docker compose restart astrbot
sudo docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
sudo docker compose logs --tail=100 assistant-api astrbot
```

如生产环境设置了不同的 `WEB_PORT`，把健康检查地址中的 `8080` 换成对应端口。网页仍经服务器原有 Tailscale Serve HTTPS 地址访问；只有 API/插件代码更新时，通常不需要重新配置 Serve。

如果新版本无法启动，先记录日志并备份当前数据库，然后停止服务。由于 v5 数据库结构不能交给旧版本程序使用，回滚必须同时恢复旧代码和更新前的数据库备份：

1. 找到更新前记录的 Git 提交号和更新前的 SQLite 备份文件。手工备份由 `./scripts/backup.sh` 创建，名称类似 `assistant-20260928T120000Z.sqlite3`。
2. 停止 Compose 服务：`sudo docker compose down`。如果 API 仍可用且故障后的数据也要保留，可在停止前另运行一次 `./scripts/backup.sh`；服务无法运行时，在停止后把 `data/service/assistant.sqlite3` 复制到 `backups/` 并另存一份日志。
3. 在项目目录切回旧版本：`git switch --detach HASH`，把 `HASH` 换成升级前 `git rev-parse --short HEAD` 记录的提交号。
4. 用升级前的数据库备份恢复数据：`./scripts/restore.sh assistant-20260928T120000Z.sqlite3`。把文件名换成 `backups/` 中实际的更新前备份文件名。恢复脚本会检查 SQLite 完整性并清理数据库的 WAL/SHM 辅助文件。
5. 运行 `./scripts/up.sh`，再运行 `sudo docker compose restart astrbot`，最后检查 `sudo docker compose ps` 和日志。

恢复旧数据库会丢弃该备份之后写入的新数据。先将故障后的数据库和日志另存一份；不要在运行中的数据库上直接覆盖文件，也不要运行 `docker system prune` 或删除 Docker volumes。回滚后仓库处于 detached HEAD；后续恢复更新时先切回 `main`，再按正常更新步骤操作。

AstrBot 镜像版本固定在 `.env` 的 `ASTRBOT_IMAGE`。升级 AstrBot 镜像前检查兼容性和插件说明，再显式修改服务器 `.env` 并执行：

```bash
sudo docker compose pull astrbot
sudo docker compose up -d astrbot
```
