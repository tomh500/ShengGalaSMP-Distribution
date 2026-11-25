# 组件与复刻范围

## 拓扑

| 单元 | 运行与依赖 |
| --- | --- |
| BungeeCord 代理 | Java 25 示例。Java 认证和后端转发。Geyser-BungeeCord 提供 Bedrock UDP 入口，Floodgate 提供身份；BungeeMaster-GAL 依赖 Floodgate。 |
| 大厅、起床战争、小游戏 | Spigot 1.12.2，Java 8 模板。起床战争加载 BedWars1058 和地图定义，小游戏加载 Minigames 和 Multiverse-Core。 |
| 生存 | Spigot 26.2、Java 25。单独的 JAR 和游戏目录。 |
| SpigotMaster-GAL、BungeeMaster-GAL、FabricMaster-GAL | 前两者加载到相应 Java 进程。Fabric 按 Minecraft 版本单独构建及安装到玩家端。代理与子服必须核对信道、能力协商与 Via 兼容矩阵。Forge / NeoForge 需各自独立验收，当前总装不声明支持。 |
| MCQQBridge | Bungee 与 Spigot 插件、可选 Floodgate 数据库扩展、Python 3.11+ API/Bot。Bot 需要自有 QQ 机器人资质、凭据及实际消息通道。按启用功能配置 SQLite、MySQL、PostgreSQL、MongoDB 或 Redis，并选择聊天室、白名单及跨服命令。 |
| Master 控制面 | 独立 `luo-master.service` 管理备份生命周期；`luobackup-worker.service` 独立执行、校验归档。Master 先启动，停止接单并收尾后再停止 worker。回环监听 18776，QQ API 使用独立端口。 |
| IPv6、DDNS 与 VPN | 地址和路由由 Linux 现场网络配置提供，ddns-go 与 VPN 作为独立系统服务接入。Windows 原生 Radmin VPN，Ubuntu 的 Wine 适配由安装方另行维护。 |

Linux 侧 Minecraft status 查询检查真实协议响应，QQ API 的 `/healthz` 检查其连接的存储。Bot 服务状态只能表明进程运行，真实 QQ 收发需单独验收。Master 单元用 `/readyz` 判定就绪，worker 需要观察令牌及 `worker_online=true`。SpigotMaster-GAL 的日志探测只检查当次启动加载迹象，Fabric 消息往返、切服重协商和 Bedrock 表单还需真实客户端。

统一经济暂列为待验证的 Master API 扩展。经济服务、数据迁移与客户端接入由独立工作验证后再锁定版本和启用方式。

## 来源与许可

- 公开自研项目由 [源码锁](../locks/sources.json) 固定提交。MCQQBridge 包含已发布的 GAL 组件，正在迁移的 SpigotMaster、BungeeMaster、FabricMaster 需等迁移完成后再更新锁。ShengGalaSMP-Plugins 包含 GalVoice、LuoBackup、BwLegacyCombat、Minigames、ShengGalaMetadata。LuoGameBalance、NeteasePets 独立维护。NeteasePets 有重建内容，MIT 仓库信息不能替代对第三方材料来源的审查。
- [核心兼容锁](../locks/cores.json) 记录三份已核对并测试的核心工件。BungeeCord 请从固定构建号的上游或可验证源码构建取得。Spigot 通过对应版本的 BuildTools 或正式构建入口取得，由运营者确认 [Minecraft EULA](https://www.minecraft.net/en-us/eula)。Bungee 插件要核对与 Java 25 和 Geyser/Floodgate 组合的兼容性。
- 代理的增强组件包括 BungeeChat、BungeeHub、BungeeTabListPlus、LuckPerms、Geyser、Floodgate、UltimateAntibot。BungeeChat 和 Floodgate 是启用对应 MCQQBridge 及 GAL 功能时的依赖。
- 大厅的增强组件包括 EssentialsX 及配套模块、ChestCommands、Vault、LuckPerms、PlaceholderAPI 和 ViaVersion/ViaBackwards。生存另外用到 ViaRewind、AppleSkinSpigot、DistantHorizonsSupport、GraveStonesPlus 和 JEI Recipe Bridge 等。生存的本地自定义保护、传送及工具插件要另行确认源码与发布许可。
- 起床战争需要来自合法来源的 BedWars1058 及所选适配补丁。地图、队伍、重生点、数据库、菜单、NPC 和奖励规则由部署方创建。扩展项包括 Citizens、DeluxeMenus、DecentHolograms、GadgetsMenu、HubParkour、MinigamesAddons、PlayerPoints、PlaceholderAPI、TAB、Vault、XConomy、ajLeaderboards、ProtocolLib、LuckPerms、GoldenGG、WoodSkins、Via 组件及各 BedWars1058 附加组件。部分旧版或本地补丁没有确认可下载的上游产物。
- 小游戏需要 Minigames、Multiverse-Core 2.5.0 和新建的大厅、房间及地图。ChestCommands、GalVoice、MCQQSpigot、SpigotMaster-GAL 及适用的 Via 组件可按玩法加入。
- Radmin 安装程序仅从 [厂商](https://www.radmin-vpn.com/help/) 获取，官方要求 Windows。Linux Wine 适配及心跳必须独立取得并验证。可另选 [EasyTier](https://github.com/EasyTier/EasyTier) 的原生跨平台方案，双方需加入同一个 EasyTier 网络。

附加项按 [运行手册](operations.md) 导出实际顶层 JAR 与哈希。总装归档仅包含文件白名单中的源码、脚本和通用模板。运行配置和世界、玩家文件、数据库、Java 私有插件、QQ 私有实现、客户端专有素材及未经许可的二进制留在各自授权范围内。

## 构建顺序

1. 运行 `python tools/checkout_sources.py /path/to/clean/checkouts`，从公开仓库检出完整 SHA。保持工作区源码、下载缓存和暂存构件留在构建机。
2. 固定上游核心、JDK、Maven、Gradle、依赖 JAR 和 Python 运行环境版本。记录 SHA-256、来源构建号、许可证和编译参数。BuildTools 运行本身也固定版本及摘要。使用合法取得的 BungeeCord、Spigot、Floodgate、BungeeChat、BedWars1058 和 Multiverse-Core 作为编译输入。
3. 按 MCQQBridge 锁定提交的 README 构建 Bungee、Spigot、Floodgate 扩展和 GAL 组件。Spigot 模块用 Maven，并传编译专用 `-Dmcserver.root` 路径。Fabric 根据 MC 目标版本用相应 Gradle/JDK。命名迁移后的构建入口使用后续审核过的新提交。
4. ShengGalaSMP-Plugins 用 PowerShell 7 和 JDK 25 执行该仓库的 `build-plugin.ps1 -Project <项目> -DependencyJars <固定依赖>`，GalVoice 的 Fabric 端按其独立说明。LuoGameBalance 和 NeteasePets 分别按锁定仓库的 Maven 构建指引执行。备份控制面与 worker 使用各自审定的 C++ 源码及工具链。
5. MCQQBridge 在相同 Python/目标平台构建 wheel，对所有传递依赖生成固定版本、带哈希的 requirements 锁。新虚拟环境用 `pip install --require-hashes -r runtime.lock` 并以 `pip check` 验证。安装自有 wheel 时同样核对摘要。Windows 与 Linux 需分别锁定平台相关的 wheel。
6. 把授权可用的产物放入现场私有组件缓存，填入 `artifacts.example.json` 的相对文件名、目标路径和实际 SHA-256。对生成物执行插件加载和功能验证，再将构建参数、锁文件和审核后的归档摘要写入发行记录。
