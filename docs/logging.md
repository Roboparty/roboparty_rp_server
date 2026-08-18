# 日志功能说明

## 概述

RoboParty RP Server 支持文件日志和控制台日志，便于生产环境问题排查和运行监控。

## 日志文件

| 文件 | 用途 |
|------|------|
| `rp_server.log` | 主日志（系统运行、错误、连接状态） |
| `packets.log` | 数据包日志（UDP/WebSocket 接收的原始数据） |

## 启动参数

```bash
python -m rp_server --config config/server.yaml --mock --log-level DEBUG --log-dir logs
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--log-level` | 日志级别 | `INFO` |
| `--log-dir` | 日志文件目录 | `logs` |

## 配置文件

在 `config/server.yaml` 中配置日志参数：

```yaml
logging:
  level: "INFO"           # 日志级别: DEBUG/INFO/WARNING/ERROR/CRITICAL
  dir: "logs"             # 日志文件目录
  file: "rp_server.log"   # 主日志文件名
  packet_file: "packets.log"  # 数据包日志文件名
  max_size: 10485760      # 单个日志文件最大大小 (字节), 10MB
  backup_count: 5         # 保留的备份文件数量
```

**优先级**: 命令行参数 > 配置文件 > 默认值

## 日志级别

| 级别 | 用途 |
|------|------|
| `DEBUG` | 详细调试信息（AT 命令、UDP 数据包） |
| `INFO` | 一般运行信息（连接建立/断开、服务状态） |
| `WARNING` | 警告信息（硬件异常、命令执行失败） |
| `ERROR` | 错误信息（硬件初始化失败、服务降级） |
| `CRITICAL` | 严重错误（服务无法启动） |

## 日志内容

### 系统生命周期

```
2026-08-08 10:00:00 [rp_server] INFO 日志系统初始化完成 level=INFO dir=logs file=rp_server.log
2026-08-08 10:00:01 [rp_server.transport] INFO mock: skipping hardware driver init
2026-08-08 10:00:01 [rp_server.transport] INFO rp_server ready mock=True port_cfg={'host': '0.0.0.0', 'port': 9000}
```

### 连接管理

```
2026-08-08 10:01:00 [rp_server.transport] INFO WebSocket 连接建立: 192.168.1.100
2026-08-08 10:01:05 [rp_server.transport] INFO WebSocket 连接断开: 192.168.1.100 (时长: 5.0s)
2026-08-08 10:02:00 [rp_server.udp] INFO UDP listener ready on 10.43.21.32:9000
```

### AT 命令（DEBUG 级别）

```
2026-08-08 10:01:02 [rp_server.transport] DEBUG WebSocket 收到命令: AT+BTN=a,down,1 (来源: 192.168.1.100)
2026-08-08 10:01:02 [rp_server.protocol] DEBUG AT 命令分发: AT+BTN (参数: ['a', 'down', '1'])
2026-08-08 10:01:03 [rp_server.transport] DEBUG UDP 数据包接收: 128 字节 (来源: 192.168.1.100:54321)
```

### 硬件状态

```
2026-08-08 10:00:01 [rp_server.drivers.motors] INFO motors initialised: 4
2026-08-08 10:00:01 [rp_server.drivers.imu] INFO IMU initialised
2026-08-08 10:05:00 [rp_server.drivers.motors] WARNING motor_mit_cmd[0] failed: timeout
```

### 数据包日志 (packets.log)

```
2026-08-08 10:01:02 [rp_server.packets] WS_RECV src=192.168.1.100 data=AT+BTN=a,down,1
2026-08-08 10:01:03 [rp_server.packets] WS_RECV src=192.168.1.100 data=AT+JOY=lx,0.500
2026-08-08 10:02:00 [rp_server.packets] UDP_RECV src=192.168.1.100:54321 size=128 data={"type":"control","sequence":1,"left_stick_x":0.5}
2026-08-08 10:02:01 [rp_server.packets] UDP_RECV src=192.168.1.100:54321 size=96 data={"type":"control","sequence":2,"btn_a":true}
```

## 查看日志

### 实时查看

```bash
# Linux/macOS
tail -f logs/rp_server.log

# Windows PowerShell
Get-Content -Path logs\rp_server.log -Wait
```

### 搜索日志

```bash
# 搜索错误
grep "ERROR" logs/rp_server.log

# 搜索特定客户端
grep "192.168.1.100" logs/rp_server.log

# 搜索 AT 命令
grep "AT+BTN" logs/rp_server.log
```

### 日志轮转

日志文件达到 `max_size` 后自动轮转：

```
logs/
├── rp_server.log        # 当前日志
├── rp_server.log.1      # 上一个日志
├── rp_server.log.2      # 更早的日志
├── ...
└── rp_server.log.5      # 最早的备份
```

## systemd 部署

使用 systemd 时，日志会同时输出到 journal：

```bash
# 查看 journal 日志
journalctl -u rp-server -f

# 查看文件日志
tail -f /opt/roboparty/logs/rp_server.log
```
