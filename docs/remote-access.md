# SSH 隧道远程访问两台管理网页

本指南使用 SSH 本地端口转发，让两三台指定电脑安全访问本项目的两个管理网页。网页端口仍只绑定在服务器本机；外网只需要能连到服务器的 SSH 端口，不需要开放 **8080**、**6185** 等网页端口。

适用页面：

| 页面 | 服务器本机地址 | 访问电脑上的地址 |
| --- | --- | --- |
| 个人助手 Todo、课表、提醒网页 | **127.0.0.1:8080** | **http://127.0.0.1:18080** |
| AstrBot WebUI | **127.0.0.1:6185** | **http://127.0.0.1:16185** |

每台电脑各自保存一把 SSH 私钥，服务器只登记对应的公钥。连接期间保持 SSH 命令运行；关闭命令或终端后，网页访问随之断开。两个网页原有的登录认证仍然有效。

## 访问路径与安全边界

~~~text
获准电脑的浏览器
  ├─ http://127.0.0.1:18080 ─┐
  └─ http://127.0.0.1:16185 ─┤
                              └─ SSH 加密连接 ── 服务器 SSH
                                                    ├─ 127.0.0.1:8080
                                                    └─ 127.0.0.1:6185
~~~

SSH 只允许获准密钥建立隧道，服务器还能把隧道限制为只能到达这两个本机端口。SSH 不会把网页端口暴露给其他公网用户。它保护电脑与服务器之间的传输；电脑或服务器本身若被入侵，SSH 不能保护已经解密的数据。

这里的“按设备授权”指每台电脑各用一把密钥，并不是 SSH 读取电脑硬件身份。私钥如果被复制，复制品也能认证；因此请给私钥设口令、不要转发私钥，遗失设备后立即移除其公钥。

## 一、确认服务器网页只监听本机

在服务器项目目录检查 Compose 服务：

~~~bash
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
~~~

本项目的 compose.yaml 将宿主机的 Todo 网页端口绑定到 **127.0.0.1:8080**，AstrBot WebUI 绑定到 **127.0.0.1:6185**。不要把这两项改成 **0.0.0.0**。云安全组和系统防火墙都不要开放 **8000**、**8080**、**6185**、**6199** 等应用端口。

若服务器还没有 SSH 服务，可在 Ubuntu 上安装：

~~~bash
sudo apt update
sudo apt install openssh-server
sudo systemctl enable --now ssh
~~~

如果你目前已经通过 SSH 登录服务器，就跳过安装。云服务商安全组和服务器防火墙只需允许 SSH 管理端口（默认 TCP **22**，如果你使用了其他 SSH 端口则以实际设置为准）。若两三台电脑有固定公网 IP，可以在云安全组中把 SSH 来源限制到这些 IP；电脑经常切换网络时，则用独立密钥识别设备，不要依赖易变化的 IP 地址。

开始前确认现有管理员 SSH 登录可用。管理员账号也建议使用独立密钥登录；确认密钥登录正常前，不要全局关闭管理员账号的密码认证。后续创建的是单独的隧道账号，不要修改或删除现有管理员账号。

## 二、每台电脑单独生成 SSH 密钥

在第一台电脑运行：

~~~bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -a 64 -f ~/.ssh/astrbot_pc1
~~~

在提示输入 passphrase 时设置一个口令。第二、第三台电脑分别换用不同文件名，例如 **astrbot_pc2**、**astrbot_pc3**，不要把一台电脑的私钥复制给其他电脑。
如果 SSH 提示将覆盖同名密钥文件，请取消操作并改用新的文件名。显示公钥和连接服务器时也要把示例里的 **pc1** 换成该电脑自己的文件名。

Windows PowerShell 使用：

~~~powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -a 64 -f "$env:USERPROFILE\.ssh\astrbot_pc1"
~~~

将公钥内容显示出来：

~~~bash
cat ~/.ssh/astrbot_pc1.pub
~~~

Windows PowerShell：

~~~powershell
Get-Content "$env:USERPROFILE\.ssh\astrbot_pc1.pub"
~~~

复制完整的一行公钥，稍后加入服务器。公钥文件以 **.pub** 结尾；**私钥文件没有 .pub 后缀，绝不要上传、发给别人或复制到其他电脑。**

## 三、在服务器建立专用隧道账号

通过现有管理员 SSH 会话登录服务器，创建没有 sudo 权限的专用账号：

~~~bash
sudo adduser astrbot-tunnel
~~~

按提示设置账号信息。该账号只用于隧道；后续 SSH 规则会要求公钥认证并禁止打开交互式命令行。

确认该账号的 home 目录：

~~~bash
getent passwd astrbot-tunnel
~~~

Ubuntu 默认是 **/home/astrbot-tunnel**。如输出的 home 路径不同，下面命令中的路径都要相应替换。创建 SSH 密钥目录：

~~~bash
sudo install -d -o astrbot-tunnel -g astrbot-tunnel -m 700 /home/astrbot-tunnel/.ssh
sudoedit /home/astrbot-tunnel/.ssh/authorized_keys
~~~

在编辑器中将每台电脑的公钥各放一行，保存后设置文件权限：

~~~bash
sudo chown astrbot-tunnel:astrbot-tunnel /home/astrbot-tunnel/.ssh/authorized_keys
sudo chmod 600 /home/astrbot-tunnel/.ssh/authorized_keys
~~~

不要把 **astrbot-tunnel** 加入 **sudo** 组。要撤销某一台电脑时，只需从 **authorized_keys** 删除那台电脑对应的公钥行。

## 四、限制隧道账号的权限

检查服务器上 nologin 程序的实际路径：

~~~bash
command -v nologin
~~~

Ubuntu 通常返回 **/usr/sbin/nologin**。然后编辑 SSH 服务配置：

~~~bash
sudoedit /etc/ssh/sshd_config
~~~

在配置文件末尾添加以下规则。若 command -v nologin 返回其他路径，请替换 ForceCommand 后的路径。

~~~text
Match User astrbot-tunnel
    AuthenticationMethods publickey
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:8080 127.0.0.1:6185
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    ForceCommand /usr/sbin/nologin
~~~

这些规则要求该账号使用 SSH 公钥认证，只允许客户端发起的本地转发，并把转发目的地限制为服务器自己的 **8080**、**6185**。它不能用密码登录、开启终端、使用 SSH agent 转发或执行远程命令。**ssh -N** 不请求远程命令，因此仍可建立隧道。

检查语法并重新加载 SSH 服务：

~~~bash
sudo sshd -t
sudo systemctl reload ssh
~~~

**sshd -t** 没有输出且返回成功表示语法检查通过。保留当前管理员会话不要关闭，直到你从一台获准电脑确认隧道可用；这样即使配置有误，也能通过原会话修正。

## 五、从获准电脑建立隧道

首次连接前，建议在服务器查看 SSH 主机密钥指纹：

~~~bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
~~~

在客户端第一次连接时，SSH 会询问是否信任服务器主机密钥。只有指纹与服务器上查到的值一致时才接受；不要用关闭主机密钥检查的选项绕过提示。

Linux 或 macOS 客户端运行以下命令。把服务器地址换成你实际使用的公网 IP 或域名：

~~~bash
ssh -N -T -i ~/.ssh/astrbot_pc1 \
  -L 127.0.0.1:18080:127.0.0.1:8080 \
  -L 127.0.0.1:16185:127.0.0.1:6185 \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  astrbot-tunnel@server.example.com
~~~

Windows PowerShell 示例：

~~~powershell
ssh -N -T -i "$env:USERPROFILE\.ssh\astrbot_pc1" -L 127.0.0.1:18080:127.0.0.1:8080 -L 127.0.0.1:16185:127.0.0.1:6185 -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes astrbot-tunnel@server.example.com
~~~

如果 SSH 服务使用的不是默认端口 **22**，在命令中加入 `-p 2222`（将 **2222** 换成实际端口），例如放在私钥参数后面；使用上面的 SSH 配置文件时则增加 `Port 2222`。

保持这个终端运行，然后在同一台电脑的浏览器打开：

- Todo 管理页：<http://127.0.0.1:18080>
- AstrBot WebUI：<http://127.0.0.1:16185>

两三台电脑使用同样的命令，但每台都选自己的私钥文件名。**127.0.0.1** 限制转发监听在该电脑本机，局域网中的其他设备不能借用这个本地端口。关闭 SSH 终端或按 **Ctrl+C** 会断开隧道。

如果电脑上的 **18080** 或 **16185** 已被占用，可以只修改命令中左侧的本机端口，例如：

~~~bash
-L 127.0.0.1:28080:127.0.0.1:8080
~~~

浏览器相应改为 **http://127.0.0.1:28080**。右侧服务器目标端口不要修改。

### 可选：保存简短的 SSH 配置

Linux/macOS 客户端可编辑 **~/.ssh/config**，加入以下段落，并把服务器地址及密钥路径改成实际值：

~~~sshconfig
Host astrbot-pages
    HostName server.example.com
    User astrbot-tunnel
    IdentityFile ~/.ssh/astrbot_pc1
    IdentitiesOnly yes
    LocalForward 127.0.0.1:18080 127.0.0.1:8080
    LocalForward 127.0.0.1:16185 127.0.0.1:6185
    ExitOnForwardFailure yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
~~~

之后用 **ssh -N astrbot-pages** 建立连接。此配置文件每台电脑各自保存，IdentityFile 指向该电脑自己的私钥。

## 六、验收访问与权限

在已经登记公钥的电脑上：

1. 运行 SSH 命令，确认没有 **Permission denied** 或转发错误。
2. 打开两个本机网址，分别使用 Todo 网页密码和 AstrBot WebUI 登录。
3. 关闭 SSH 终端后刷新页面，确认隧道访问中断；重新运行 SSH 命令后访问恢复。
4. 在没有登记公钥的电脑上确认不能以 **astrbot-tunnel** 建立隧道。
5. 检查云安全组和防火墙没有开放 **8080**、**6185** 等网页端口。

如果发现某台电脑丢失，从服务器的 **authorized_keys** 删除其公钥。已建立的隧道不会因删除公钥自动断开；如需立即断开该专用账号的所有现有隧道，可执行：

~~~bash
sudo pkill -u astrbot-tunnel -f '^sshd:'
~~~

该命令会断开所有使用 **astrbot-tunnel** 的电脑；之后仍登记的公钥可以重新连接。

## 七、Cookie、排错与停止访问

本方案的浏览器网址是 **http://127.0.0.1**，因此项目 .env 中应保留：

~~~dotenv
COOKIE_SECURE=false
~~~

SSH 仍会加密电脑到服务器的网络传输；**COOKIE_SECURE** 控制的是浏览器是否只在 HTTPS 网页发送 Cookie。如果之前为其他 HTTPS 代理方案设过 **COOKIE_SECURE=true**，改回 **false** 并重启 API：

~~~bash
sudo docker compose up -d assistant-api
~~~

常见问题：

| 现象 | 检查 |
| --- | --- |
| SSH 超时或拒绝连接 | 检查服务器公网地址、实际 SSH 端口、云安全组和系统防火墙。 |
| Permission denied (publickey) | 确认当前私钥和登记的 .pub 是一对；检查 authorized_keys 的属主和权限。 |
| bind: Address already in use | 改用其他客户端本机端口，只改转发规则左侧端口及浏览器地址。 |
| SSH 登录成功但网页打不开 | 确认项目容器运行、服务器端口为 127.0.0.1:8080 和 127.0.0.1:6185，并检查 PermitOpen 是否与转发目标一致。 |
| 页面能打开但登录后没有会话 | 检查 .env 是否为 COOKIE_SECURE=false，然后重启 assistant-api。 |

不再需要远程访问时，关闭客户端隧道即可；若要彻底撤销某台电脑的授权，再从服务器的 **authorized_keys** 删除该电脑的公钥。若不再需要任何远程 SSH 访问，可关闭云安全组的 SSH 入站规则，但这也会切断管理员 SSH 登录。

## 网络与法律说明

本指南只说明 SSH 的技术配置。SSH 加密传输不等于网络接入方式自动符合所有地区的法规。如果访问设备位于中国大陆、服务器在境外，SSH 隧道不会消除相关国际联网规则可能产生的适用问题；请根据服务器和访问者所在地、服务商要求及实际网络路径另行确认。可参考[《中华人民共和国计算机信息网络国际联网管理暂行规定》](https://xzfg.moj.gov.cn/law/download?LawID=1713&type=pdf)。

本方案不会自动删除服务器上已存在的其他远程访问配置。若之前实际配置过其他代理或隧道，请分别检查其设置；不要为关闭本方案而重置其他项目的网络服务。

## 参考资料

- [OpenSSH 客户端配置：LocalForward](https://man.openbsd.org/ssh_config)
- [OpenSSH 服务端配置：AuthenticationMethods、AllowTcpForwarding、PermitOpen、ForceCommand](https://man.openbsd.org/sshd_config)
- [OpenSSH authorized_keys 选项](https://man.openbsd.org/sshd)
