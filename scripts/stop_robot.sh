#!/usr/bin/env bash

# RoboParty 软件快速停止
# 真正紧急情况请优先使用硬件急停。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/../../roboparty_deploy" && pwd)"

echo "正在执行软件快速停止..."

# 加载 ROS2 环境。
if [ -f "/opt/ros/humble/setup.bash" ]; then
    # shellcheck disable=SC1091
    source "/opt/ros/humble/setup.bash"
fi

if [ -f "$WORKSPACE_DIR/install/setup.bash" ]; then
    # shellcheck disable=SC1091
    source "$WORKSPACE_DIR/install/setup.bash"
fi

# deinit_motors 内部会先停止推理，再向电机发送失能命令。
# 最多等待 1 秒，避免服务异常时阻塞。
if command -v ros2 >/dev/null 2>&1; then
    timeout 1s ros2 service call \
        /deinit_motors \
        std_srvs/srv/Trigger \
        '{}' >/dev/null 2>&1 || true
fi

# 立即关闭 start_robot.sh 创建的 orangepi screen 会话。
runuser -u orangepi -- screen -S inference_session -X quit \
    >/dev/null 2>&1 || true
runuser -u orangepi -- screen -S joy_session -X quit \
    >/dev/null 2>&1 || true

# 给退出信号极短的处理时间。
sleep 0.2

# 结束节点和 ros2 launch 父进程。
pkill -TERM -x inference_node >/dev/null 2>&1 || true
pkill -TERM -x joy_node >/dev/null 2>&1 || true
pkill -TERM -f '[r]os2 launch roboparty_inference inference.launch.py' \
    >/dev/null 2>&1 || true

sleep 0.3

# 对仍未退出的相关进程强制结束。
pkill -KILL -x inference_node >/dev/null 2>&1 || true
pkill -KILL -x joy_node >/dev/null 2>&1 || true
pkill -KILL -f '[r]os2 launch roboparty_inference inference.launch.py' \
    >/dev/null 2>&1 || true

echo "软件快速停止完成。"
