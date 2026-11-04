# roboparty_rp_server 协议改造（roboparty.v1，Protobuf-only）

> 状态：已实施（无兼容期）｜ 契约源：`proto/roboparty/v1`（本仓）
>
> 决策：**彻底 Protobuf-only，删除 AT/JSON，不考虑向后兼容**。旧客户端（AT
> 行协议 / UDP JSON）将无法与本服务通信，App 侧必须同步升级。

---

## 1. 背景与问题

rp_server 是 RK3588 上的网关，对外 WebSocket / UDP / 串口 / 蓝牙四路传输，对内管理
电机、IMU、BMS、虚拟手柄与推理进程。改造前的问题：

1. 无契约（IDL）：消息是裸 AT 字符串 / 裸 JSON，跨语言、跨仓无法机器校验。
2. 编解码与业务耦合：handler 直接拼字符串。
3. 鉴权自造：`auth/udp_auth.py` docstring 写 JWT，实为随机 hex。
4. 驱动被上层直连：`drivers/*` 直接 `import motors_py/imu_py`。

## 2. 目标与非目标

**目标**
- 单一契约源 `proto/roboparty/v1`，生成各语言绑定。
- 所有传输、所有消息统一为 `Envelope`（Protocol Buffers）。
- 驱动层抽象稳定接口。
- 删除 AT/JSON 全部代码路径。

**非目标**
- 不重写电机/CAN 驱动，不改协议语义（LRO/DM/EVO/XYN、CANopen 手）。
- 不引入 MQTT。
- 不改实时控制时序与 `mock` 路径。
- 不做任何兼容层。

## 3. 总体设计

```
proto/roboparty/v1/            ← IDL 单一真源
        │ scripts/gen_proto.sh (protoc 21.x)
        ▼
protocol/gen/roboparty/v1/*_pb2.py   ← 生成绑定
        │
protocol/codec.py   ← ProtobufCodec + 分帧（UDP magic / 流式 varint）
protocol/enums.py   ← proto 枚举 ↔ 驱动字符串名
protocol/handler.py ← CommandHandler：Envelope → list[Envelope]
        │
transport/*   ← WS / UDP / Serial / BT / CAN-joy，收发均为 Envelope
        │
drivers/*     ← RobotDriver Protocol（motors/imu/bms/joy/policy）
```

**分帧**

| 传输 | 分帧 |
|------|------|
| WebSocket | 一个 binary frame = 一个 `Envelope` |
| UDP | `0x52` + 版本 `0x01` + `Envelope` |
| 串口/蓝牙 | varint 长度前缀 + `Envelope`（字节流无边界） |

**关键文件**
- `proto/roboparty/v1/{common,commands,responses,telemetry,auth,envelope}.proto`
- `src/rp_server/protocol/{codec,enums,handler}.py` + `gen/`
- `src/rp_server/transport/{ws_server,udp_listener,serial_server,bt_server,can_joy_listener}.py`
- `src/rp_server/monitors/`、`src/rp_server/protocol/gamepad.py`
- `src/rp_server/drivers/base.py`

## 4. 阶段与状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0 | 定义 `proto/roboparty/v1` 契约，protoc 校验 | 已完成 |
| P1 | 生成绑定 + `ProtobufCodec` + 分帧（UDP/流式） | 已完成 |
| P2 | `CommandHandler`（Envelope→Envelope）+ 枚举映射 | 已完成 |
| P3 | 四路传输全部改为 Protobuf；删除 AT/JSON | 已完成 |
| P4 | 驱动 `RobotDriver` Protocol | 已完成 |
| P5 | 鉴权与传输安全（方案见 §10） | 未开始 |
| P6 | （可选）Rust 网关 | 未开始 |

## 5. 兼容与迁移

**无兼容期**：AT 与 UDP JSON 代码已删除。

- 旧 AT 行协议、旧 UDP JSON 控制/遥测**不再被解析**（UDP 会丢弃非 v1 帧并 debug 日志）。
- 已内置 AT 生产者（`gamepad.py`、`can_joy_listener.py`）已改为产出 `Envelope`。
- 升级顺序：先升级 rp_server，再同步升级 App（否则 App 无法控制）。
- WebSocket 旧文本帧不再二次解析为协议命令。

## 6. 构建与依赖

- 生成绑定：`scripts/gen_proto.sh`（需 `grpcio-tools`，protoc 21.x）。
- 板端运行时：`python3-protobuf` 4.21.12（Ubuntu noble），已加入 `debian/control`
  （`scripts/check_python_depends.py` 按实际 import 校验）。
- 生成目录 `protocol/gen/roboparty/v1/*_pb2.py` 随包安装；`protocol/__init__.py`
  与 `gen/__init__.py` 负责把生成目录加入 `sys.path`（生成代码用绝对 `roboparty.v1.*` 导入）。

## 7. 测试与验收

- `tests/`：codec/分帧 round-trip、handler 路由（假驱动）、枚举映射。
- 运行：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/`（本机 pytest 6.2
  与用户态 anyio 插件冲突，故禁用插件自动加载；板端无此问题）。
- 现场：只读抓包核对 UDP magic/帧格式；任何使能/运动前按工作区约定占位。

## 8. 风险与待决

| 风险/待决 | 说明 |
|-----------|------|
| 破坏式升级 | 无兼容期，App 必须同步；这是既定决策 |
| 枚举/轴序与 App 对齐 | `protocol/enums.py` 名称需与 App 端逐一核对 |
| `SkillAction` 无 token | 现仅做会话校验（原 AT 语义带 token），如需可加字段 |
| 服务端心跳复用 `Heartbeat` | 该消息语义偏客户端→服务端；如需专用 ping 可新增 body |
| 错误响应 | 未匹配 body 返回 `error`（新行为，旧 AT 直接忽略） |
| P5 鉴权 | 见 §10（未实施） |

## 9. 变更清单（已实施）

新增：
- `proto/roboparty/v1/*.proto`
- `src/rp_server/protocol/gen/**`（生成）
- `src/rp_server/protocol/{codec.py,enums.py,handler.py}`
- `src/rp_server/drivers/base.py`
- `scripts/gen_proto.sh`
- `tests/{conftest,test_codec,test_handler}.py`

修改：
- `src/rp_server/transport/{ws_server,udp_listener,serial_server,bt_server,can_joy_listener}.py`
- `src/rp_server/protocol/gamepad.py`
- `src/rp_server/monitors/`
- `src/rp_server/state.py`（`at_handler` → `handler`）
- `config/server.yaml`、`debian/control`、`README.md`

删除：
- `src/rp_server/protocol/at_parser.py`
- `src/rp_server/protocol/at_handler.py`
- `src/rp_server/protocol/messages.py`

---

## 10. 鉴权与传输安全方案（P5 历史设计）

2026-11-03 实现更新：HTTP 与 protobuf WS 已补 Bearer/scope 检查，JSON WS
校验配对 JWT 并跟踪撤销；两类 WS 共享显式 control lease、TTL 与独立输入超时。
旧 UDP/串口/蓝牙/CAN 手柄入口暂时禁止启用，避免绕过仲裁。软件停止不再调用
清错路径；TLS 仍需部署配置。下面的“当前”风险表是本次修改前的设计基线，
新的配置和客户端迁移方式以 README 的 Shared access and control ownership 为准。
此次只有离线验证，没有完成真机验收，不能把 P5 整体标为已交付。

### 10.1 现状与问题

| 问题 | 位置 / 证据 |
|------|-------------|
| 自造鉴权：随机内存 token，无标准签名 | `auth/udp_auth.py`（docstring 写 JWT，实为 `secrets.token_hex`） |
| `secret_key` 已改为留空 + `RP_UDP_SECRET` 注入；空值仍会自动随机（重启失效） | `config/server.yaml`、`auth/udp_auth.py` |
| **WS 完全无鉴权**：同网任何人可发摇杆/按钮/`reset`/policy | `transport/ws_server.py`（`/ws` 无握手与门禁） |
| UDP 软件急停已要求 token+会话；控制/凭据仍明文，可嗅探重放 | `udp_listener.py:_handle_stop` |

### 10.2 威胁模型（防什么）

| 威胁 | 现状 | 目标 |
|------|------|------|
| 同网嗅探（token/摇杆明文） | 有 | 传输加密（TLS）；UDP 只跑遥测 |
| 重放（抓包重发控制/急停） | 部分（timestamp/seq 太弱） | 短时 token + 每会话单调窗口 + 握手 nonce |
| 伪造控制 / 乱发 `reset`、`policy` | **有**（WS 无鉴权） | 强制鉴权 + 能力分级（read/control/admin） |
| MITM（冒充机器人） | 无防护 | 服务端证书 pinning（SPKI） |
| 暴力破解挑战码 | 弱 | 限速 + 锁定 + 短 TTL + 挑战单次使用 |
| 密钥进仓库 / 自动随机 | 有 | fail-closed + 设备级 provisioning 下发 |

### 10.3 推荐方案（一句话）

每设备凭据在 **TLS 内换取短时 JWT（Ed25519/EdDSA，带 `read`/`control`/`admin` scope）**；
**控制走 WSS**、UDP 只留遥测；服务端证书 **pin** 防 MITM；密钥 **provisioning 下发并
fail-closed**。

### 10.4 设计要点

**身份与信任根**
- 每台机器人一份 **Ed25519 密钥对**（板端持私钥签发 JWT）。
- 客户端身份：优先**每设备 PSK / 每设备 Ed25519 公钥**（provisioning 下发到机器人），
  不使用全局共享密钥。
- 不做大 CA：机器人用**自签 TLS 证书**，App **pin SPKI 指纹**（首次配对写入）。

**传输安全（关键决策）**
- **控制面迁到 WSS**：TLS 1.3 + 鉴权握手（摇杆/按钮/云台/reset/policy）。
- **UDP 只留遥测**（IMU/电池/电机态）：非敏感、高频、可丢，保留低延迟；如需可加只读 token。
- 若坚持 UDP 控制：必须 **DTLS** 或 **Noise 握手派生会话密钥 + 每包认证**（复杂，不推荐第一版）。

**Token 与授权**
- **JWT（Ed25519/EdDSA）**，短 TTL（如 15 min）+ refresh；RFC 7519，可离线验签、无状态。
- 获取：TLS 内做一次挑战-响应（客户端用 PSK/私钥证明身份）→ 机器人签发 JWT。
- **scope 分级**：`read`（遥测/query）/ `control`（摇杆/按钮/云台）/ `admin`（policy/reset）。
- `CommandHandler` 前置**授权门**：按 `Envelope` body 要求对应 scope，不满足返回 `error`。

**重放 / 限速**
- 握手 nonce 单次 + 短 TTL（现有 5 min 收到秒级）。
- 数据：`Envelope.header.sequence/timestamp_ms` 做**每会话单调窗口**，乱序/重复丢弃。
- 挑战连续失败：限速 + 临时锁定。
- 撤销：短 TTL + 每设备凭据（可单独停用）。

**密钥下发与 fail-closed**
- 凭据从 `/etc/rp-server/auth.env`（0600）或 `RP_AUTH_*` 读取，随 `robopi_config`
  provisioning 每台一份，**不进 git**。
- **删除占位符、删除"空则随机"**：未配置时**禁用控制类能力**（或启动失败），`--mock` 例外。
- `server.yaml` 只留开关，不放密钥。

### 10.5 各链路落点

| 链路 | 鉴权 | 加密 | 说明 |
|------|------|------|------|
| WSS（App/上位机） | JWT + scope | TLS 1.3 + pin | 控制 + 遥测 + 管理 |
| UDP | 只读 token（可选） | 无 | 仅遥测 |
| 串口 / 蓝牙 | 本地物理信任 | 无 | 本地调试；可选 PSK |
| CAN 手柄 | 本地总线信任 | 无 | 物理接入 |
| REST `/api/*` | JWT（admin/read） | TLS | 管理面 |

### 10.6 为什么不全上 mTLS / DTLS

- **mTLS**：最强，但需给每台 App 分发/轮换客户端证书，运维重；第一版
  "PSK/客户端密钥 → JWT + 服务端证书 pin" 性价比更高，后续可升级 mTLS。
- **DTLS / Noise（UDP）**：能给 UDP 控制加密，但库与 App 支持复杂；把控制收敛到 WSS 更省事。

### 10.7 代码落点（设计）

- `proto/roboparty/v1/auth.proto`：补 token/scope 字段（或 `Envelope.auth` context）。
- `src/rp_server/auth/` 已建立：`udp_auth.py`/`udp_session.py`/`app_auth.py`/`pairing.py`/`device_key.py`/`tls.py` 统一收纳。
- `src/rp_server/protocol/handler.py`：授权门 + scope 校验。
- `src/rp_server/transport/ws_server.py`：鉴权握手 + WSS（TLS 配置）。
- `src/rp_server/transport/udp_listener.py`：控制回退为遥测；token 校验沿用。
- `config/server.yaml` + `etc/default/rp-server`：密钥来源走环境/文件，去掉占位符。
- `tests/`：握手、scope 拒绝、重放窗口、fail-closed。

### 10.8 落地顺序（低风险）

1. **fail-closed + 删占位符 + 密钥走 env/provisioning**（先堵"自动随机/明文密钥"）。
2. **WS 接入鉴权握手 + scope 授权门**（先堵"WS 无鉴权"最大洞）。
3. **WSS（TLS + pin）**，控制迁到 WSS；UDP 收敛为遥测。
4. token 换 JWT（Ed25519）。
5. 重放窗口 / 限速 / 撤销完善。

> 第 1、2 步即可消除"占位符/自动随机"和"WS 无鉴权"两个立即风险。

### 10.9 待决

- token 形态：JWT(Ed25519) / HMAC 自包含 / 保留挑战-响应仅加固。
- UDP 控制：改走 WSS（推荐） / 保留 UDP 上 DTLS·Noise / 先只加固 token 接受局域网信任。
- 密钥下发：设备级 provisioning（推荐） / 全局部署密钥或统一 CA / 先环境变量。

## 11. v2 协议变更（2026-11-04）

本节记录已落地的破坏性更新；v2 不保证兼容 v1 客户端。

### 11.1 版本与能力

- `/identity` 的 `protocolVersion` 升级为 `2`，新增 `features`：
  `pair-pin-v2`、`policy-ready-v2`、`stop-receipt-v2`、`control-lock-v2`。
- `ConnResponse` 与 `AuthResult` 增加 `protocol_version` 和 `features`。
- joystick 与 control MCP 必须拒绝 `protocolVersion < 2` 的服务端。

### 11.2 配对与 TLS pinning

- `/pair/code` 返回 `payload` 和 `roboparty://pair?data=...` URI；负载包含
  `tlsSpkiSha256`、`deviceSpkiSha256`、SN、过期时间和设备密钥签名。
- 客户端只能通过该 URI/二维码/标签完成首次配对，并把 TLS SPKI 持久化。
- `/identity`、`/pair/register`、`/ws-json` 全部使用已钉住的 TLS SPKI；
  禁止 trust-all，禁止跳过主机名验证。
- TLS 默认开启；证书缺失时服务端生成带本机 SAN 的自签名证书。

### 11.3 运控状态与停止回执

- `PolicyResponse.State` 增加 `STATE_STARTING`、`STATE_STOPPING`、
  `STATE_UNKNOWN`，并增加 `pid`、`exit_code`、`message`、`ready`、
  `updated_at_ms`。
- `STATE_RUNNING` 仅在就绪探测通过后返回；异常退出返回 `STATE_FAIL`。
- `StopRequest` 增加 `request_id`；`StopAck` 增加 `state`、`confirmed`、
  `reason`、`confirmed_at_ms`。最终回执为 `stopped`/`failed`，不再使用
  `accepted` 作为完成状态。
- JSON stop 同样返回 `stopped`/`failed` 和 `request_id`。

### 11.4 控制锁

- 统一锁：`/dev/shm/roboparty-control.lock`。
- rp_server、start、deploy、TUI 维护任务和刷写脚本共享该锁；运控期间
  维护任务快速失败，不排队等待。

### 11.5 移除 rp_server 直控 head

- 删除 `drivers/head.py`、`HeadDriverLike`、`head` 配置、`HeadCommand` 及
  `Envelope.head`（字段 13 已 `reserved`）。头部电机控制不再由 rp_server
  直接执行，必须由运控侧或独立服务承载。

### 11.6 受影响组件

- rp_server：proto、handler、policy、ws_server、udp_listener、配对脚本。
- control MCP：vendor proto、`tools.py`（状态/回执字段）。
- Android joystick：配对 URI、TLS pin 持久化、停止回执、协议版本检查。
