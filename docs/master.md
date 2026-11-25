# Master 与 LuoBackup worker

`luo-master` 是独立的 C++ 控制面，监听本机回环。准备同一版本的 `luo-master` 和 `luobackup-worker`，使用 [Master 配置模板](../config/master.example.json) 新建本机配置。声明实际节点和依赖，创建互相独立的状态目录和归档目录，并生成观察、提交、worker 三份独立随机令牌。状态目录随 Master 的备份操作保留。运行账户只读取所需令牌，授予归档目录访问权。

[适配器模板](../config/master-lifecycle.example.sh) 使用与游戏进程相同的 systemd 用户会话。安装时改为本机绝对路径并赋予执行权限。有单独服务账户的站点需向 Master 提供管理员审核的最小权限 IPC 或 adapter，使其只能管理配置选定的节点。维护期内把其他启停入口纳入同一运维互斥。

## 独立启动与停止

总装可从私有拓扑的 `process` 字段生成单位，也可接入已安装的单位。独立运行使用以下两个命令，在各自会话执行，并保证两个进程均能读同一份配置。

```bash
/opt/luo-master/bin/luo-master --config /srv/group-server/private/master.json
/opt/luo-master/bin/luobackup-worker --config /srv/group-server/private/master.json
```

`GET /readyz` 检查控制服务就绪。worker 在线时，带观察令牌的 `GET /v1/topology` 返回 `worker_online=true`。关闭时先向 Master 发送 SIGTERM，保留 worker 直到 Master 收尾。

当前支持的交互构建可用 `luo-master --config /绝对路径/master.json --console` 前台启动。使用相同状态目录与端口时，先关闭已运行的 Master 单元。对支持 Linux 套接字的发行版，也可在 Master 单元启动参数中加 `--console-socket /私有目录/operator.sock`，再从获准的本机账户运行 `luo-master --attach /私有目录/operator.sock`。保持目录访问权限为 0700。`help` 查看命令，`end` 在维护任务收尾后结束 Master。关闭完整拓扑用 `topologyctl.py stop`。按实际维护上限设置 Master 的停机超时。

维护时由持提交令牌的调用方给 `POST /v1/backups` 传站点声明的 profile 和稳定幂等键。worker 从 Master 领取任务并校验归档，Master 接收结果后恢复之前运行的节点。使用认证后的作业查询等待最终状态。在正式环境释放归档前，验证停服和恢复日志及 SHA-256，并在隔离目录试恢复。
