# 圣旮旯 SMP 群组服总装

用于在新环境装配 BungeeCord、四个 Spigot 后端、MCQQBridge、SpigotMaster-GAL 插件组合和独立的 `luo-master` 控制面。Ubuntu 负责游戏服务和可选的系统网络服务，Windows 可加入 Radmin VPN。时区、网络、路径、内存、功能开关以及凭据由安装方填写。

这个候选版本打包总装脚本和通用配置。游戏核心、插件、JDK、VPN 客户端、控制面产物和现场配置各自取得并锁定。公开源码和依赖范围见 [组件清单](docs/components.md)。

## 安装总装脚本

Linux 需要 Bash、GNU wget/coreutils、Python 3.12+。运行服务需要 systemd 用户会话和对应 JDK。将命令中的地址和两个摘要替换成审核通过的发布信息。发布者把 `bootstrap.sh` 和 `topology-0.1.0.tar.gz` 放到版本目录，并独立提供两份 SHA-256。

```bash
base=https://downloads.example.org/group-server
version=0.1.0
wget --https-only -O bootstrap.sh "$base/v$version/bootstrap.sh" &&
    printf '%s  %s\n' '<可信 bootstrap.sh SHA-256>' bootstrap.sh | sha256sum --strict -c - &&
    bash bootstrap.sh "$base" "$version" '<可信 tar.gz SHA-256>'
```

从审核过的本地检出安装可用 `bash install.sh`。默认安装位置为 `~/.local/share/luo-topology`，可用 `--prefix` 设置新位置。按 [运行手册](docs/operations.md) 准备专用目录、私有配置和版本化组件。模板中 QQ、Master 和 VPN 等可选项需要按现场启用。

```bash
ctl="$HOME/.local/share/luo-topology/current/topologyctl.py"
python3 "$ctl" setup-systemd
systemctl --user daemon-reload
python3 "$ctl" wake
python3 "$ctl" health
python3 "$ctl" stop
```

## 重建总装

`python tools/release.py build --output dist` 可在 Windows 或 Linux 运行。归档按文件清单生成，顺序、属主、权限与时间戳固定。在同一 Python/zlib 工具链下，同一内容重复构建应得到相同 SHA-256。第三方依赖和自研源码分别采用 [固定版本检出与构建流程](docs/components.md#构建顺序)，许可和构建验证通过后再生成组件锁。
