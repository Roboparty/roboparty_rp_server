#!/usr/bin/env bash

# RoboParty 软件快速停止
# 真正紧急情况请优先使用硬件急停。
#
# 可选环境变量：
#   RP_WORKSPACE_DIR : 推理工作区（含 install/setup.bash）
#   RP_ROBOT_USER    : 运行 inference 的用户（默认自动探测 robo / orangepi）
#   ROS_SETUP        : ROS 环境脚本路径（默认自动探测）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "正在执行软件快速停止..."

# ---- ROS 环境（Jazzy 优先，兼容 Humble） ----
if [ -n "${ROS_SETUP:-}" ] && [ -f "${ROS_SETUP}" ]; then
    # shellcheck disable=SC1090
    source "${ROS_SETUP}"
else
    for candidate in \
        "/opt/ros/${ROS_DISTRO:-}/setup.bash" \
        "/opt/ros/jazzy/setup.bash" \
        "/opt/ros/humble/setup.bash"; do
        if [ -f "$candidate" ]; then
            # shellcheck disable=SC1090
            source "$candidate"
            break
        fi
    done
fi

# ---- 推理工作区 ----
WORKSPACE_DIR="${RP_WORKSPACE_DIR:-}"
if [ -z "$WORKSPACE_DIR" ]; then
    for candidate in \
        "$HOME/rp1_deploy" \
        "$HOME/atom01_deploy" \
        "/home/robo/rp1_deploy" \
        "/home/robo/atom01_deploy" \
        "/home/orangepi/roboparty_deploy" \
        "/home/orangepi/atom01_deploy" \
        "$SCRIPT_DIR/../../roboparty_deploy"; do
        if [ -f "$candidate/install/setup.bash" ]; then
            WORKSPACE_DIR="$candidate"
            break
        fi
    done
fi
if [ -n "$WORKSPACE_DIR" ] && [ -f "$WORKSPACE_DIR/install/setup.bash" ]; then
    # shellcheck disable=SC1090
    source "$WORKSPACE_DIR/install/setup.bash"
fi

# ---- 运行用户（用于清理 screen 会话） ----
RUN_USER="${RP_ROBOT_USER:-}"
if [ -z "$RUN_USER" ]; then
    for candidate in robo orangepi; do
        if id "$candidate" >/dev/null 2>&1; then
            RUN_USER="$candidate"
            break
        fi
    done
fi

# deinit_motors 内部会先停止推理，再向电机发送失能命令。
# 最多等待 1 秒，避免服务异常时阻塞。
if command -v ros2 >/dev/null 2>&1; then
    timeout 1s ros2 service call \
        /deinit_motors \
        std_srvs/srv/Trigger \
        '{}' >/dev/null 2>&1 || true
fi

# 立即关闭 start_robot.sh 创建的 screen 会话。
if [ -n "$RUN_USER" ] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$RUN_USER" -- screen -S inference_session -X quit \
        >/dev/null 2>&1 || true
    runuser -u "$RUN_USER" -- screen -S joy_session -X quit \
        >/dev/null 2>&1 || true
fi

# 给退出信号极短的处理时间。
sleep 0.2

# 结束节点和 ros2 launch 父进程。
pkill -TERM -x inference_node >/dev/null 2>&1 || true
pkill -TERM -x joy_node >/dev/null 2>&1 || true
pkill -TERM -f '[r]os2 launch .*inference' >/dev/null 2>&1 || true
# 最新 deploy 的 isolated 模式由 realtime_run.py 管理；SIGTERM 让它进入
# 清理路径，守护进程会恢复 CPU 隔离并释放 /run/roboparty-realtime.lock。
# 不要对 realtime_run.py 使用 SIGKILL，否则守护进程也可能被一并杀掉。
pkill -TERM -f '[r]ealtime_run.py' >/dev/null 2>&1 || true

sleep 0.3

# 对仍未退出的相关进程强制结束（不包含 realtime_run.py）。
pkill -KILL -x inference_node >/dev/null 2>&1 || true
pkill -KILL -x joy_node >/dev/null 2>&1 || true
pkill -KILL -f '[r]os2 launch .*inference' >/dev/null 2>&1 || true

# 等待实时隔离守护进程释放锁，避免紧接着启动时撞 25 秒锁等待。
if [ -e /run/roboparty-realtime.lock ] && command -v flock >/dev/null 2>&1; then
    released=no
    for _ in {1..50}; do
        if ( flock -n 9 9< /run/roboparty-realtime.lock ); then
            released=yes
            break
        fi
        sleep 0.2
    done
    [ "$released" = yes ] || echo "警告：实时隔离锁仍未释放，下一次启动可能等待" >&2
fi

echo "软件快速停止完成。"
