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

访问 `http://127.0.0.1:8080` 管理 Todo，访问 `http://127.0.0.1:6185` 配置 AstrBot。端口冲突时修改项目 `.env` 的 `WEB_PORT` 或 `ASTRBOT_WEB_PORT`，不修改系统级网络设置。网页 Compose 端口固定绑定回环地址；服务器远程访问按[SSH 隧道操作说明](remote-access.md)配置。

## 常用操作

```bash
# 查看运行状态和日志
sudo docker compose ps
sudo docker compose logs -f assistant-api astrbot

# 更新本项目代码和容器
git pull
sudo docker compose pull
sudo docker compose up -d --build

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
- 个人助手从旧 schema 升级到 v3 时，会先在 `backups/` 生成带版本号的 SQLite 一致性快照，再创建重复 Todo、个人日程、周复盘、每期提醒覆盖和 14 节时间配置。
- JSON 导出包含 Todo、重复系列、提醒、课程、个人日程、周复盘、非秘密设置和操作记录；CSV 可分别导出这些主要资源，不包含密钥。
- 另行备份 `data/astrbot/` 以保存 AstrBot 平台和提供商配置。该目录可能含有平台登录态与密钥，转移时使用私密、加密的方式。
- 至少将 `backups/` 复制到另一块磁盘或受控位置；同盘备份无法防止磁盘故障。

## 迁移到服务器

1. 本机运行 `./scripts/backup.sh`，再停止服务或确保完成备份。
2. 安装 Docker/Compose 后，在服务器准备项目文件。可从代码仓库取公开代码；不要把本地 `.git`、`.venv` 或容器缓存当作迁移依赖。
3. 私密转移 SQLite 备份和 AstrBot `data/`；`.env` 不要从旧机器复制，也不要放入代码仓库。在服务器运行 `./scripts/init-local.sh` 生成独立配置，再把 `.env` 中的 `APP_UID`、`APP_GID` 设置为 `id -u`、`id -g` 的结果，然后执行 `sudo chown -R "$(id -u):$(id -g)" data/service backups`，让 API 容器继续以目标机普通用户写数据库和备份。SSH 隧道访问使用本机 HTTP 地址，保持 `COOKIE_SECURE=false`。
4. 恢复 SQLite，按需重建 API 镜像并启动项目 Compose 服务；核对迁移前备份、服务健康状态与日志。若 AstrBot 容器无法读写迁来的 `data/astrbot/`，按当前固定镜像所使用的容器用户修正该目录属主。检查模型和平台凭据是否仍有效。
5. 若需从外部设备访问网页，按[SSH 隧道操作指南](remote-access.md)创建专用隧道账号并为每台授权电脑登记独立公钥。不要开放 Todo 网页或 AstrBot WebUI 的公网端口。

## 更新与回滚

- 先创建 SQLite 备份，再更新仓库代码；API 源码变化后执行 `sudo docker compose up -d --build assistant-api`。
- AstrBot 镜像版本固定在 `.env` 的 `ASTRBOT_IMAGE`。升级前检查兼容性和插件说明，再显式修改版本并执行 `sudo docker compose pull astrbot && sudo docker compose up -d astrbot`。
- 若更新后异常，先回退本项目代码或镜像，再用 `./scripts/restore.sh <备份文件名>` 恢复数据库。不要清理整个 Docker 主机的镜像、网络或 volumes。
