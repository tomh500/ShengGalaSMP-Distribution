# 安装、启动与恢复

## 新装

1. 为新实例选专用非 root 账户，准备相互独立的五个目录，保持代理的工作目录与四个后端分开。按实际 JDK 路径、内存与端口填写私有 `topology.json`。默认读取 `~/.config/luo-topology/topology.json`，也可用 `--config /absolute/path`。配置及其父目录只给部署账户读取。由运营者确认 EULA 后放入相应后端目录。
2. 在各核心首次生成的配置中合并模板字段。后端 `online-mode=false` 配合 Bungee 登录验证和转发，仅绑定回环或限制专用代理来源。公网入口仅放行需要的代理 TCP 和可选 Geyser UDP。各服务保留自己的世界、配置、存储和日志目录。
3. 建好用户会话，执行 `setup-systemd` 和 `systemctl --user daemon-reload`。这会生成 Java 用户单元，以及已启用且配置了 `process` 的 Master、worker 或 QQ 用户单元。接管站点已有单元时，删除私有配置中对应的 `process` 段，沿用其单元名。已有 screen/tmux 实例需先迁移正常停服入口并验证监听端口已释放，再切换监管。需开机无登录运行的站点，可由管理员为运行账户开登录保持。
4. 用 `python3 "$ctl" apply-jars /private/artifacts.json lobby` 查看计划。加 `--apply` 才执行。对代理和其他后端重复。每次执行要求对应单元处于 inactive。脚本按清单装配同名 JAR，升级换文件名时在停服窗口内另行归档旧版，避免两个版本被一起加载。
5. 配置可选服务。MCQQBridge 用独立 venv、私有设置与现有模块入口。按 [Master 独立运行说明](master.md) 准备 Master、worker、游戏生命周期适配器及私有配置。备份 profile 覆盖对目标数据有写入的所有游戏节点和依赖，独立数据库备份在同一维护窗口完成。
6. 用 `wake` 按依赖依次启动并等就绪。加节点名只启动该节点和前置服务。用 `health` 输出逐项结果，`stop` 按依赖关闭并等待退出，或用 `stop <node>` 停指定单元。游戏通过本地 FIFO 发 `stop`，BungeeCord 发 `end`，再等主进程退出。确认 shutdown 日志和世界保存结果之后才能做数据操作。

Master 生命周期适配器只给受管理的游戏节点开放。状态码 0 表示已就绪，3 表示 inactive，4 表示运行状态不确定，其他非零表示错误。Spigot 的 `save` 使用回环 RCON 的 `save-all flush` 并确认回执。先在使用的两个 Spigot 版本分别验收反馈。确需启用时，设置私有 `rcon.password` 与仅部署账户可读的密码文件，避免对外暴露 RCON。代理模板的 `save=noop` 仅用于无所选数据写入的代理。若代理插件会写入备份选中的数据，需纳入一致性流程。

Master 管理地址保持回环。维护员控制台由本地账户与 OS ACL 授权，配置和令牌文件仅授予对应进程读取。公开查询使用低权限 API，QQ 与 Proxy 分别使用专用凭据和独立动作白名单。QQ 主人通过 `/大发命令 master …` 转发是待验收能力，站点开关默认关闭。启用前按最终 Master 契约核对命令白名单及凭据权限，维护员凭据留在本机维护账户。

## 网络与 VPN

Linux 以 IPv6 全局源地址和路由作为就绪条件。总装的 `setup-network --root <暂存根目录>` 安装网络只读探针、两个 systemd 等待单元和环境文件模板。管理员审查后可对系统根目录执行同一命令。此步骤只写模板，配置站点参数后再由管理员决定何时重新加载 unit 配置。续租继续由站点现有 NetworkManager、RA/SLAAC 或 dhcpcd 配置负责；它们在总装中作为可选只读状态。附加地址的同步 timer 保持原调度。若某应用依赖附加地址，启用 `ipv6-listener` 并调用该应用真实监听的健康检查。

系统等待单元从各自的 `/etc/mc-network/*.env` 获取探测参数。总装 CLI 直接调用探针，需定制时在私有拓扑的 `argv` 里填写 `--interface`、`--ipv6-route-probe` 或 `--radmin-peer`。Internet 和跨 VPN 的服务可达性由实际应用探针另行验证。

现有附加地址按定时任务同步时，`ipv6-listener.ready_timeout` 应覆盖整个同步周期和监听恢复时间。模板为 360 秒，可按站点的调度与重试间隔调长。

需发布 DNS 时，在私有拓扑启用 DDNS，等待 IPv6 就绪。若发布依赖附加地址，再把实际监听节点列为前置。总装对已在运行的 ddns-go 只检查状态。进程活跃仅表示发送端已启动，验收要从独立解析器检查 AAAA 是否与当前目标地址相符。凭据及域名记录在本机私有配置。确需让 `wake` 启动已有 DDNS、VPN 或心跳服务时，将对应 `manage` 设为 true，并使用站点授权的 systemd 控制权限。模板的 `stop_managed=false` 在游戏停机时保留网络服务。Linux Radmin 使用既有 Wine prefix 和已登记的身份。选填对端地址时，应从 VPN 网段实际连接代理测试。

Windows 使用厂商安装的 Radmin VPN 及已加入的网络。复制 `config/radmin-windows.example.json` 到私有位置，设置观察到的网卡和 `RvControlSvc`。需要启动托盘程序时填写已安装的 `RvRvpnGui.exe` 完整路径；选填 VPN 对端 IP 和服务端口用于跨端探测。执行 `pwsh -File vpn/radmin-windows.ps1 -Config <私有文件> -Action wake`。管理 Windows 服务需相应权限。`health` 只检查。身份恢复和网络加入由 VPN 管理员单独执行。

## 备份和工件更新

- 数据备份通过 Master 提交白名单 profile。等待 worker 确认归档校验并由 Master 恢复备份前的运行状态，记录归档和检查值。停服应用的 MySQL/MongoDB 等使用各自一致性备份方式。先在独立数据目录试恢复世界、权限和账户映射，再安排真实恢复。
- `inventory` 输出每个受管节点的核心及顶层插件 SHA-256。Windows 上用 `Get-FileHash -Algorithm SHA256` 对相同范围生成清单。云端用只读探查记录实际单元和 JAR 路径，补充 Java 版本、启动参数、QQ Python 模块哈希及可选嵌套插件。版本号相同仍须对差异文件、类与资源做核对；生产清单及运行日志存为本地私有证据。
- Windows 构建机产出并校验工件，仅将需替换的文件与最小启动配置传到对应服务器。用服务一侧的临时私有目录存放清单和输入，命令结束后清理。把旧 JAR 的已核对摘要写进清单 `replaces`，按照计划停受影响服务并执行带校验的替换。脚本保留旧文件及清单在实例的 `.topology-backups`，仅处理核心和顶层插件 JAR。成功启动后重新导出实际摘要并检查健康和日志。
- 同一次更新期间，用统一控制入口管理该实例。避免与 Master 备份、手动 systemctl、screen 或其他录入方式并发操作。现场已有备份目录时，将运维保留策略与工件回滚目录统一。
- 如果更新失败，先正常停对应实例。按备份清单对照当前和备份摘要，将确需恢复的 JAR 作为另一次发布的输入，用同一 `apply-jars` 核对后恢复。全新引入的 JAR 可在停机后移到归档目录。确认回滚后的启动日志、健康与摘要。总装脚本发布的旧版本目录保留在 `versions/`，可从已审定的旧包重新执行安装切回。
