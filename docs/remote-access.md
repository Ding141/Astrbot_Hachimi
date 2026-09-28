# 用 Tailscale 安全访问服务器管理网页

本指南说明如何从两三台指定电脑访问服务器上的 Todo 管理页和 AstrBot WebUI。项目已将这两个网页限制在服务器本机回环地址；远程访问使用 **Tailscale Serve** 在 tailnet（你的 Tailscale 私有网络）中提供 HTTPS 入口。

配置好后，日常使用只需在电脑上打开 Tailscale，再用浏览器访问两个 HTTPS 地址。无需安装或配置 OpenSSH 隧道账号、复制 SSH 密钥、输入长命令或保持终端窗口运行。

~~~text
授权电脑浏览器
   │  Tailscale 私有网络 + HTTPS
   ├── https://服务器名.你的tailnet.ts.net/       Todo 管理页
   └── https://服务器名.你的tailnet.ts.net:8443/ AstrBot WebUI
                    │
                    ▼
              Tailscale Serve
                ├── 127.0.0.1:8080  Todo
                └── 127.0.0.1:6185 AstrBot WebUI
~~~

Tailscale Serve 只向 tailnet 提供网页；它不会把管理页公开给普通互联网用户。**不要使用 Tailscale Funnel**，也不要在云安全组/主机防火墙开放项目的网页端口。

**重要：**Tailscale ping 成功只说明两台设备能通过 tailnet 通信，不代表服务器已经为网页开了 Serve。项目的 `8080` 和 `6185` 只监听服务器本机回环地址，因此从 Windows 直接访问 `http://服务器Tailscale-IP:8080` 或 `:6185` 不会通。Serve 配置要在运行项目网页的 Ubuntu 设备上执行；在 Windows 运行 `tailscale serve status` 只会显示 Windows 自己的 Serve 配置，显示 `No serve config` 并不说明 Ubuntu 配置失败。

## 先了解安全边界

访问需要同时满足：

1. 电脑登录你的 Tailscale tailnet，且该设备已获批准。
2. tailnet 访问策略允许这台电脑访问服务器 TCP 443 和 8443。
3. 网页自身的登录认证通过。Todo 管理页与 AstrBot WebUI 保留各自的登录认证。

Tailscale 使用 WireGuard 加密设备间的网络流量；Tailscale Serve 另外以 HTTPS 提供网页。若直接连接不可用，Tailscale 可以通过 DERP 中继传递已经加密的数据。加密能保护网络传输，不能保护已被入侵的电脑、服务器或已解密数据。请为 Tailscale 账号启用 MFA 或 Passkey，批准自己实际使用的设备，并使用强网页登录密码。

Tailscale 默认策略可能允许 tailnet 内的所有设备互通。因此本指南会给出只让指定电脑访问服务器网页端口的策略示例。设备审批与访问策略用途不同：审批决定设备能否加入 tailnet，访问策略决定加入后能连接哪些设备和端口。

使用 HTTPS 前请留意：Tailscale 为服务器名称申请的 HTTPS 证书会进入公开的 Certificate Transparency（证书透明度）日志。证书日志可能显示服务器的 tailnet DNS 名称；它**不会**因此让 Serve 网页对公众开放。如果设备名或 tailnet 名称包含个人信息，请先把它们改成不敏感的名称，再启用 HTTPS。详见 [Tailscale HTTPS 证书说明](https://tailscale.com/docs/how-to/set-up-https-certificates)。

## 第一步：让服务器和电脑加入同一个 Tailscale 网络

### 1. 在 Ubuntu 服务器安装并登录

从服务器终端运行：

~~~bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
sudo tailscale up
~~~

`tailscale up` 会显示一次性登录链接。用浏览器打开链接并登录你的 Tailscale 账号，将服务器加入 tailnet。Tailscale 服务会在服务器重启后启动。

确认连接并记录服务器地址和机器名：

~~~bash
tailscale status
tailscale ip -4
~~~

Tailscale IPv4 通常是 `100.x.y.z`。使用服务器命令实际显示的地址；不要用来历不明的公网 IP 或复制文档中的示例地址。Tailscale 为设备分配的地址通常来自 `100.64.0.0/10`。

### 2. 在 Windows 等电脑安装并登录

Windows：从 [Tailscale 官方 Windows 下载页](https://tailscale.com/download/windows)安装，登录同一个 Tailscale 账号。

macOS 或 Linux：按 [Tailscale 官方安装说明](https://tailscale.com/download)安装并登录同一个账号。

最简单的个人用法是让你自己的电脑登录同一账号。登录不同账号的设备，需要先由 tailnet 管理员邀请加入。不要分享账号密码或导出设备密钥。

### 3. 启用设备审批并批准自己的电脑

打开 [Tailscale 管理控制台](https://login.tailscale.com/admin/)：

1. 在设备管理设置中启用 **Device approval（设备审批）**。
2. 打开 Machines（设备）列表。
3. 找到你刚加入的每台电脑和服务器，核对名称后批准。
4. 删除不认识或不再使用的设备。

若启用了设备审批，尚未批准的设备不能正常访问 tailnet。不要批准无法确认来源的设备。

## 第二步：只授权指定电脑访问服务器网页

打开 Tailscale 管理控制台的 **Access controls（访问控制）**。先从服务器与每台客户端读取各自 Tailscale IPv4：

~~~bash
tailscale ip -4
~~~

Windows 也可在 Tailscale 客户端或管理控制台 Machines 列表中查看地址。

如果这是专供本项目使用的新 tailnet，可用下方示例作为完整的最小策略。把所有示例 IP 换成真实 Tailscale IPv4；不用的电脑删除对应主机和列表项。空的 `acls` 列表用于关闭默认 ACL 全开放规则，`grants` 再精确放行网页端口：

~~~json
{
  "acls": [],
  "hosts": {
    "pa-server": "100.85.23.17",
    "pa-pc1": "100.85.23.18",
    "pa-pc2": "100.85.23.19",
    "pa-pc3": "100.85.23.20"
  },
  "grants": [
    {
      "src": ["pa-pc1", "pa-pc2", "pa-pc3"],
      "dst": ["pa-server"],
      "ip": ["tcp:443", "tcp:8443"]
    }
  ]
}
~~~

这个示例只允许列出的电脑访问服务器的 TCP 443 和 8443。示例地址不能照抄。`hosts` 是 IP 地址的易读别名；`src` 是授权电脑；`dst` 是服务器；`ip` 是允许连接的端口。

保存策略前，先使用控制台的策略校验。检查原策略中是否有覆盖面更广的允许规则。Tailscale 访问规则会叠加；较窄的规则不能抵消原有的全开放规则，例如 `"src": ["*"], "dst": ["*"], "ip": ["*"]` 或旧格式 ACL 中允许 `*` 访问 `*:*`。新 tailnet 的默认策略也可能允许所有设备互通，需要按示例收紧。

如果这个 tailnet 还承载其他设备或服务，不要用上面示例覆盖整份现有策略。将这条 grant 合并进去，并保留其他设备实际需要的规则；同时确认没有不需要的全开放规则。若不熟悉现有策略，使用一个仅包含服务器和这两三台电脑的独立个人 tailnet 会更容易检查。

若设备删除后重新加入，请重新查看 Tailscale IP 并更新 `hosts`。也可以在 `src` 中使用你的 Tailscale 用户邮箱来简化策略，但这通常会授权该账号下所有设备，而非精确到两三台电脑。

## 第三步：打开 DNS 和 HTTPS

在 Tailscale 管理控制台的 DNS 设置中：

1. 确认 **MagicDNS** 已启用。
2. 启用 **HTTPS Certificates（HTTPS 证书）**。
3. 如果控制台提示设备名会出现在公开证书日志中，先确认机器名和 tailnet 名称不包含你不希望公开的信息。

Tailscale Serve 使用 MagicDNS 名称生成浏览器访问地址，并自动取得有效的 HTTPS 证书。证书让浏览器能验证它连接到正确的服务器并加密网页访问。

## 第四步：在服务器开启两个 Serve 地址

先确认项目运行正常，并查看服务器是否已有其他 Serve 配置：

~~~bash
sudo docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
sudo tailscale serve status
~~~

若输出显示同一台服务器上已有其他 Serve 路由，先确认它们用途，避免改动无关服务。没有冲突时，在服务器执行：

~~~bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
sudo tailscale serve --bg --https=8443 http://127.0.0.1:6185
sudo tailscale serve status
~~~

`--bg` 让 Serve 在后台持续运行，并在 Tailscale 重启或服务器重启后恢复。首次启用 HTTPS 时，命令可能提示确认；按提示同意为本 tailnet 启用 Serve/证书。

`tailscale serve status` 会列出具体 HTTPS 地址和各地址转发到的本地端口。保留这个输出，下一步从授权电脑访问它显示的地址。

配置成功时，输出结构类似下面这样（主机名和 tailnet 名称以你的服务器实际输出为准）：

~~~text
Available within your tailnet:

https://<服务器名>.<tailnet名称>.ts.net/
|-- proxy http://127.0.0.1:8080

https://<服务器名>.<tailnet名称>.ts.net:8443/
|-- proxy http://127.0.0.1:6185
~~~

末尾的 `tailscale serve status` 还应显示这两个路由，并标记为 `tailnet only`。这表示路由已经配置在 Ubuntu 服务器上，只能由 tailnet 内的设备访问。若在 Windows 执行状态命令看到 `No serve config`，无需在 Windows 再设置 Serve；直接从 Ubuntu 输出复制两个 HTTPS 地址。

**不要运行 `tailscale funnel` 命令。**Serve 面向 tailnet；Funnel 会把服务发布到普通互联网。

## 第五步：设置安全 Cookie 并重启 API

在服务器项目目录编辑私有 `.env`，将这一项设为：

~~~dotenv
COOKIE_SECURE=true
~~~

在服务器项目目录编辑 `.env` 并保存：

~~~bash
sudo nano .env
~~~

然后重启助手 API 让新设置生效：

~~~bash
sudo docker compose up -d assistant-api
~~~

本项目的登录 Cookie 会在 HTTPS 访问时设置 Secure 标志。项目代码也会识别 Tailscale Serve 转发的 HTTPS 来源，保证网页登录和来源校验能通过。

本机开发测试仍通过 HTTP 使用 `http://127.0.0.1:8080` 时，应保持本机 `.env` 中的 `COOKIE_SECURE=false`。服务器的生产 `.env` 与本机测试配置彼此独立。

## 第六步：从获准电脑访问并验收

在已登录且已批准的电脑上打开 Tailscale 客户端，确认状态为已连接。然后用浏览器打开 `tailscale serve status` 显示的地址，通常是：

- Todo 管理页：`https://服务器名.你的tailnet.ts.net/`
- AstrBot WebUI：`https://服务器名.你的tailnet.ts.net:8443/`

第一个地址使用 HTTPS 443。第二个地址使用 HTTPS 8443。应以服务器 `tailscale serve status` 显示的完整主机名为准。

分别验证两个网页能打开并用各自密码登录。不要把示例中的机器名照抄到实际地址里，也不要改用 `http://Tailscale-IP:8080` / `:6185`。设备被批准但网页打不开时，先检查 Ubuntu 上的 Serve 状态、tailnet 访问策略以及 Windows Tailscale 客户端状态；不要把网页端口映射到公网来“临时修复”。

## Windows 上使用 Clash Verge TUN 时

首次配置时建议暂时关闭 Clash Verge 的 TUN 模式，先确认 Tailscale 客户端已连接并能打开网页。若关闭 TUN 时正常、重新开启后失败，可能是 Mihomo 的规则把 Tailscale 地址送进代理。

在 Mihomo/Clash 的规则列表中，将以下规则放在全局兜底规则（例如 MATCH）之前，然后重载配置：

~~~yaml
rules:
  - IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
  # 后面保留你已有的规则，包括兜底规则
~~~

这条规则让 Tailscale IPv4 地址段走直连路由，由 Tailscale 虚拟网卡接管。不同 Clash Verge 配置方式的规则入口可能不同；如果不熟悉配置，继续临时关闭 TUN 使用 Tailscale，待确认规则后再启用。Mihomo 规则格式见[官方路由规则说明](https://wiki.metacubex.one/config/rules/)。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| `tailscale up` 提示登录链接 | 在浏览器登录你的 Tailscale 账号并批准设备，然后回服务器运行 `tailscale status` 确认在线。 |
| Windows 的 `tailscale serve status` 显示 `No serve config` | 这是 Windows 自己的 Serve 状态。网页路由要在 Ubuntu 服务器上配置；在 Ubuntu 运行 `sudo tailscale serve status`，再从 Windows 打开 Ubuntu 显示的 HTTPS 地址。 |
| Tailscale ping 成功，但 `http://100.x.x.x:8080` 打不开 | 这是项目预期的网络边界：`8080`/`6185` 绑定 `127.0.0.1`。在 Ubuntu 配置 Serve，并从 Windows 使用 Serve 输出的 HTTPS 地址。 |
| 客户端看不到服务器 | 核对两端是否在同一个 tailnet、是否在线，以及服务器和电脑是否都已通过设备审批。 |
| HTTPS 命令提示 DNS/证书未就绪 | 在控制台启用 MagicDNS 和 HTTPS Certificates；检查服务器网络能否连接 Tailscale。再运行对应 Serve 命令并查看提示。 |
| Ubuntu 有 Serve 路由但 Windows 浏览器打不开 | Windows 确认 Tailscale 已连接；如果访问策略有限制，放行该电脑到服务器的 TCP `443`、`8443`。可在 PowerShell 对服务器 Tailscale IP 执行 `Test-NetConnection <服务器Tailscale-IP> -Port 443` 和 `-Port 8443`。 |
| Serve 地址能打开，但提示来源校验失败 | 确认服务器运行当前项目版本、`COOKIE_SECURE=true`，并重启 `assistant-api`；不要在 Serve 前面再套一层未配置的反向代理。 |
| Todo 能开，AstrBot 页面不能开 | 执行 `sudo tailscale serve status`，确认 8443 转发到 `http://127.0.0.1:6185`；确认 tailnet 策略放行服务器 8443。 |
| 只有某台电脑打不开 | 检查该设备是否批准、策略中的客户端 Tailscale IP 是否正确，以及 Clash TUN 是否接管 `100.64.0.0/10`。 |
| 服务器重启后地址失效 | 检查 `sudo systemctl status tailscaled` 和 `sudo tailscale serve status`；后台 Serve 配置应随 Tailscale 恢复。 |
| 网页登录后没有会话 | 服务器 `.env` 设为 `COOKIE_SECURE=true`，然后执行 `sudo docker compose up -d assistant-api`。 |

## 停止或撤销访问

停止其中一个页面的 Serve 路由：

~~~bash
sudo tailscale serve --https=443 off
sudo tailscale serve --https=8443 off
sudo tailscale serve status
~~~

只运行需要停止的那一条。执行前用 `tailscale serve status` 核对端口用途。不要用 `tailscale serve reset`，它会清除服务器上所有 Serve 配置。

撤销某台电脑的权限：在 Tailscale 控制台移除该设备，并从访问策略的 `hosts` 和 `src` 列表中删除它。若设备丢失，尽快撤销，随后修改 Todo 和 AstrBot 网页密码。服务器的 SSH 管理通道是独立设置；本网页方案不会为其开放公网端口。

## 法规与适用范围

加密只能说明传输保护方式，不能单独证明某种跨境网络连接符合所有地区的法律、监管要求或服务商条款。如果访问者与服务器位于不同国家/地区，应结合双方所在地、服务商要求和实际网络路径确认适用规则。技术配置不是法律意见。可阅读[《中华人民共和国计算机信息网络国际联网管理暂行规定》](https://xzfg.moj.gov.cn/law/download?LawID=1713&type=pdf)，并在需要时咨询合格的专业人士。

## 官方参考

- [Tailscale：Linux 安装](https://tailscale.com/docs/install/linux)
- [Tailscale：Windows 客户端下载](https://tailscale.com/download/windows)
- [Tailscale：设备审批](https://tailscale.com/docs/features/access-control/device-management/device-approval)
- [Tailscale：Grant 访问策略](https://tailscale.com/docs/features/access-control/grants)
- [Tailscale：Grant 语法与设备/IP 选择器](https://tailscale.com/docs/reference/syntax/grants)
- [Tailscale：ACL 默认允许所有设备互通](https://tailscale.com/docs/features/access-control/acls)
- [Tailscale：tailscale serve 命令和 HTTPS](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Tailscale：只向 tailnet 提供网站](https://tailscale.com/docs/features/tailscale-funnel/how-to/host-websites)
- [Tailscale：设备间加密](https://tailscale.com/docs/concepts/tailscale-encryption)
- [Mihomo：路由规则](https://wiki.metacubex.one/config/rules/)
