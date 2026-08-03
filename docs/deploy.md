# 生产部署说明

## 前置条件

- 真实机器人配置存在于
  `/opt/roboparty/share/roboto-inference/config/robot/robot.yaml`
- `motors_py`、`imu_py`、`bms_py` 已由 RoboParty 硬件包安装
- 板子安装了 `python3-pip`，并能访问 Python 包源
- `.env` 已包含 `RP_DEEPSEEK_API_KEY` 和随机 `RP_JWT_SECRET`

正式服务不会自动回退到 mock。未连接电机、IMU 或 BMS 时，服务仍会启动，
`/health` 返回 `degraded` 并列出缺失项；接好硬件后重启服务即可重新初始化。
验收硬件时可手工添加 `--require-hardware`，让任一必需硬件缺失都阻止启动。

## 从源码一键安装 systemd

先停止手工运行的服务，然后执行：

```bash
cd ~/roboparty_rp_server
sudo bash scripts/install_systemd.sh
```

如真实配置不在默认路径：

```bash
sudo bash scripts/install_systemd.sh /absolute/path/to/robot.yaml
```

安装器会：

1. 校验真实配置和三个硬件 pybind 模块
2. 安装代码到 `/opt/roboparty`
3. 将 `websockets` 固定为 `10.4`，隔离在 `vendor-packages`
4. 将密钥安装到 `/etc/rp-server/rp-server.env`（权限 `0600`）
5. 安装并启用 `rp-server.service`
6. 检查服务及 `/health`

## 服务管理

```bash
sudo systemctl status rp-server --no-pager
sudo systemctl restart rp-server
sudo systemctl stop rp-server
sudo journalctl -u rp-server -f
systemctl is-enabled rp-server
```

服务启用后，SSH/串口终端关闭不影响运行，并会在开机后自动启动。

## 环境变量（`/etc/default/rp-server`）

| 变量 | 含义 |
|------|------|
| `RP_HOST` / `RP_PORT` | 监听地址，默认 `0.0.0.0:8765` |
| `RP_LOG_LEVEL` | info/debug |
| `RP_ROBOT_CONFIG` | robot.yaml |
| `RP_SERVER_CONFIG` | server.yaml |

密钥放在 `/etc/rp-server/rp-server.env`，不要放进 Git。生产 systemd unit
不设置 `RP_MOCK`，因此使用真实驱动；硬件未接时以 degraded 状态继续提供
网页、登录、聊天和 MCP 服务。

## 开发启动

```bash
cd /path/to/roboparty_rp_server
set PYTHONPATH=src   # Windows PowerShell: $env:PYTHONPATH="src"
python3 -m rp_server --config config/dev_robot.yaml --mock --port 8765
python3 scripts/ws_selftest.py --url http://127.0.0.1:8765
```

## 配置要点（`config/server.yaml`）

- `server.mock`：生产必须为 `false`
- `hardware.required`：默认 `motors/imu/bms`
- `hardware.fail_startup_if_unavailable`：systemd 通过 CLI 强制为 `true`
- `auth.require_token`：正式发版建议 `true`  
- `mcp.readonly`：正式发版写操作保持 `true` 除非明确开放  
- `chat.model`：默认 `chat-fast`

## 自检清单

- [ ] `curl /health` → `"status":"ok","hw_ready":true,"mock":false`
- [ ] `python3 -c 'import websockets; print(websockets.__version__)'` → `10.4`
- [ ] WS 收 `+CONN` 与 `@IMU`/`@BAT`  
- [ ] `systemctl is-enabled rp-server` → `enabled`
- [ ] 关闭 SSH 后网页仍可访问
- [ ] 重启板子后 `systemctl is-active rp-server` → `active`
- [ ] 生产已设置 `RP_JWT_SECRET`  
- [ ] apt 仓库版本与文档一致（对齐凡晓兵 CI）

## RDK X5（地瓜 D-Robotics）部署差异

X5 上没有 `roboparty-base/motors/imu/bms/inference` 这套 deb，硬件栈是
`~/atom01_deploy` 里的 ROS 2 colcon 工作区，因此**不能走 deb 安装**，用
`scripts/install_systemd.sh` 从源码装。

1. pybind 模块不在系统 python 路径，软链进 `dist-packages`：

```bash
for so in ~/atom01_deploy/install/*/lib/python3.10/site-packages/*.so; do
  sudo ln -sfn "$so" /opt/roboparty/lib/python3/dist-packages/"$(basename "$so")"
done
```

2. `robot.yaml` 路径不同，安装时显式传入：

```bash
sudo bash scripts/install_systemd.sh \
  ~/atom01_deploy/install/roboparty_inference/share/roboparty_inference/config/robot.yaml
```

3. X5 没有 BMS（既无 `bms_py` 也无 BMS 硬件），把 `config/server.yaml` 的
   `hardware.required` 改为 `["motors", "imu"]`，否则 preflight 失败。
   `/health` 会返回 `bms:false`、`battery` 为 `null`。

4. 板子不联网时，先在有网的机器上取 arm64 依赖，再拷到板上离线安装：

```bash
pip download -d rp_wheels --only-binary=:all: \
  --platform manylinux2014_aarch64 --python-version 3.10 \
  --implementation cp --abi cp310 fastapi uvicorn
sudo python3 -m pip install --no-index --find-links=rp_wheels \
  --target /opt/roboparty/lib/python3/vendor-packages fastapi uvicorn
sudo dpkg -i python3-evdev_1.4.0+dfsg-1build2_arm64.deb
sudo env PIP_NO_INDEX=1 PIP_FIND_LINKS=$PWD/rp_wheels bash scripts/install_systemd.sh <robot.yaml>
```

`python3-evdev` 用官方 deb，不要用 pip 装 evdev 源码包：Ubuntu 22.04 自带的
setuptools 认不出它的 pyproject 元数据，会装成一个不可导入的 `UNKNOWN` 包。

5. rp_server 与 `~/atom01_deploy/tools/start_robot.sh`（inference_node）
   会争用同一组 CAN 总线，同一时间只能运行其中一个。
