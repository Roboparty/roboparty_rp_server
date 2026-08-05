# can-utils Static Cross-Compile (Head Motor CAN)

## Goal

Build **aarch64 static** `cansend` / `candump` on dev machine, copy to RK3588 for head motor control.

## Dependencies

- CMake ≥ 3.14
- C compiler + static libc
- **NDK path**: `ANDROID_NDK_HOME` (Android scenario)
- Or **cross GCC**: `gcc-aarch64-linux-gnu` (on-board Linux)

## Build

```bash
cd tools/canutils-ndk

# RK3588 Linux (recommended)
CC=aarch64-linux-gnu-gcc bash build_static.sh

# Or Android NDK
ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/26.3.11579264 bash build_static.sh
```

Output: `tools/canutils-ndk/out/bin/{cansend,candump}`

## On-Board Verification

```bash
# Send CAN frame
./cansend can0 123#DEADBEEF

# Monitor
./candump can0
```

Head motor frame IDs and data fields follow the CAN protocol from Chen Yutong / Chang Chuanyong.
This tool only provides sending and sniffing capability.

## Packaging Suggestion

Copy `out/bin/*` into deb's `/opt/roboparty/bin/`, append a line to `debian/install`.
