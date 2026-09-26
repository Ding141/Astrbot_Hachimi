# Tailscale 私有远程访问

本项目的远程访问方式是 Tailscale Serve：设备浏览器通过 tailnet HTTPS 访问个人助手网页，服务器上的 Tailscale 将请求代理到 `127.0.0.1:8080`。Todo 网页本身仍要求项目管理密码。AstrBot WebUI `6185`、API 服务容器端口和数据库都不转发。

Tailscale Serve 用于 tailnet 私有服务；Funnel 则用于公开互联网访问。本方案只使用 Serve。参考 [Tailscale Serve 文档](https://tailscale.com/docs/features/tailscale-serve)和 [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve)。

## 1. 加入并保护 tailnet

1. 在服务器与要使用的电脑/手机上安装 Tailscale，并加入同一个 tailnet。
2. 在设备管理页批准服务器以及你准备使用的设备；移除不再使用的设备。
3. 检查 tailnet 的 Grants/ACL。新 tailnet 的默认策略可能允许成员访问所有 tailnet 设备；仅加入 tailnet 不代表完成了最小权限配置。将针对个人助手服务器的窄权限规则合并进现有策略，建立单独的设备标签（例如 `tag:pa-server`），只允许你指定的账号/组访问服务器 HTTPS `tcp:443`。如果要限制到具体设备，先使用设备批准和 tailnet 设备访问策略，不要留下覆盖该规则的宽泛允许规则，也不要替换影响其他服务的整个策略。
4. 保留单独的服务器 SSH 管理规则，避免调整访问策略时锁住管理员。

策略文件语法和默认策略以 [Tailscale 访问控制文档](https://tailscale.com/docs/features/access-control)为准。不要把示例占位账号或标签原样当成真实身份。

## 2. 启用 HTTPS

在 Tailscale 管理控制台的 DNS 设置中启用 MagicDNS 和 HTTPS Certificates。Tailscale 需要为 tailnet 设备签发证书；启用 HTTPS 会将设备名称及 tailnet DNS 名称写入公开的证书透明度日志，但**不会公开网页内容**，连接仍由 tailnet 访问策略控制。细节见[Tailscale HTTPS 证书说明](https://tailscale.com/docs/how-to/set-up-https-certificates)。

如果不想让服务器名称进入公开证书日志，先停止并选择其他远程访问方案；不要以关闭网页密码或改用 Funnel 作为替代。

## 3. 启动本地服务并设置 Cookie

确认本地 Docker Compose 已正常启动，服务器上可以访问 `http://127.0.0.1:8080`。服务器 `.env` 设置：

```dotenv
WEB_PORT=8080
COOKIE_SECURE=true
```

Compose 固定将 `8080` 映射到宿主机回环地址，不能通过局域网网卡直连。AstrBot WebUI 仍固定在 `127.0.0.1:6185`。应用会读取 Tailscale Serve 设置的 HTTPS 转发头进行来源校验和 HSTS；同源检查仅在回环来源且 HTTPS 代理标记成立时信任转发的主机名。

应用配置改变后，仅重建本项目 API 服务：

```bash
sudo docker compose up -d assistant-api
```

不要把 `COOKIE_SECURE` 改成 `false` 来排查 HTTPS 登录问题；检查浏览器地址是否为 `https://...`、API 容器状态和 Tailscale 转发状态。

## 4. 配置 Tailscale Serve

服务器本机执行：

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
sudo tailscale serve status
```

命令输出会给出 tailnet 内的 HTTPS 地址。用该地址打开 Todo 网页，输入项目管理密码登录。若当前 Tailscale 版本提示先授权 HTTPS 或升级客户端，按官方提示完成；随后再检查 `tailscale serve status`。

确认映射目标是 `http://127.0.0.1:8080`，不要映射到 `6185`，也不要运行 `tailscale funnel`。其他设备须已在允许访问范围内并登录相同 tailnet。

## 5. 检查与关闭

- 从服务器本机确认 `http://127.0.0.1:8080/healthz` 正常。
- 从已批准设备的 Tailscale HTTPS 地址登录并操作一个临时 Todo。
- 确认普通公网/非 tailnet 网络不能访问同一 tailnet HTTPS 地址，也不能连接服务器公网 `8080`、`6185`。
- 检查管理页面仍要求网页密码；AstrBot WebUI 只在服务器本机访问。
- 检查 Tailscale ACL 没有给无关用户开放服务器 `443`。

需要停止转发时，先查看 `tailscale serve status`。若本机 Serve 只用于本项目，可执行：

```bash
sudo tailscale serve off
```

该命令会关闭这台主机的全部 Serve 映射。如果同一台主机还为其他项目提供 Serve 服务，请按本机 Tailscale CLI 版本的帮助，仅删除本项目的 `8080` 映射；不要执行全局 `off` 或 `reset`。关闭转发后，网页仍可在服务器本机通过 `http://127.0.0.1:8080` 使用。本项目不会安装或修改 Tailscale、系统防火墙或其他项目的网络配置。
