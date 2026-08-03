# can-utils 静态交叉编译（头部电机 CAN）

## 目标

在开发机编出 **aarch64 静态** `cansend` / `candump`，拷到 RK3588 控头部电机。

## 依赖

- git、make
- **NDK 路径**：`ANDROID_NDK_HOME`（Android 场景）
- 或 **交叉 GCC**：`gcc-aarch64-linux-gnu`（板端 Linux）

## 编译

```bash
cd tools/canutils-ndk
chmod +x build_static.sh

# RK3588 Linux（推荐）
./build_static.sh linux-aarch64

# 或 Android NDK
export ANDROID_NDK_HOME=/path/to/ndk
./build_static.sh ndk
```

产物：`tools/canutils-ndk/out/bin/{cansend,candump}`

## 板上验证

```bash
scp out/bin/cansend out/bin/candump root@<rk3588>:/usr/local/bin/
ip link set can0 up type can bitrate 1000000
candump can0 &
cansend can0 123#DEADBEEF
```

头部电机帧 ID / 数据域以陈宇童 / 常传勇 的 CAN 协议为准；本工具只提供发送与抓包能力。

## 打包建议

可将 `out/bin/*` 装入 deb 的 `/opt/roboparty/bin/`，在 `debian/install` 中追加一行。
