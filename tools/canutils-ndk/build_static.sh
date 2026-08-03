#!/usr/bin/env bash
# Static-build can-utils for aarch64 (RK3588 / Android NDK or Linux musl).
# Produces cansend / candump suitable for controlling head motors over CAN.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$ROOT/out}"
CANUTILS_VER="${CANUTILS_VER:-v2023.03}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"

mkdir -p "$OUT/src" "$OUT/bin"

fetch_src() {
  if [[ ! -d "$OUT/src/can-utils/.git" ]]; then
    git clone --depth 1 --branch "$CANUTILS_VER" \
      https://github.com/linux-can/can-utils.git "$OUT/src/can-utils"
  fi
}

build_ndk() {
  : "${ANDROID_NDK_HOME:?Set ANDROID_NDK_HOME to your NDK root}"
  local API="${ANDROID_API:-28}"
  local HOST_TAG
  case "$(uname -s)" in
    Linux*) HOST_TAG=linux-x86_64 ;;
    Darwin*) HOST_TAG=darwin-x86_64 ;;
    *) echo "unsupported host"; exit 1 ;;
  esac
  local TOOLCHAIN="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$HOST_TAG"
  local CC="$TOOLCHAIN/bin/aarch64-linux-android${API}-clang"
  local AR="$TOOLCHAIN/bin/llvm-ar"
  local STRIP="$TOOLCHAIN/bin/llvm-strip"

  echo "[ndk] CC=$CC"
  make -C "$OUT/src/can-utils" clean || true
  make -C "$OUT/src/can-utils" -j"$JOBS" \
    CC="$CC" AR="$AR" \
    CFLAGS="-O2 -static" \
    LDFLAGS="-static" \
    cansend candump

  cp "$OUT/src/can-utils/cansend" "$OUT/src/can-utils/candump" "$OUT/bin/"
  "$STRIP" "$OUT/bin/cansend" "$OUT/bin/candump" || true
  file "$OUT/bin/cansend" "$OUT/bin/candump" || true
  echo "[ndk] artifacts in $OUT/bin"
}

build_linux_aarch64() {
  # Cross GCC (Debian/Ubuntu: gcc-aarch64-linux-gnu)
  local CC="${CROSS_CC:-aarch64-linux-gnu-gcc}"
  make -C "$OUT/src/can-utils" clean || true
  make -C "$OUT/src/can-utils" -j"$JOBS" \
    CC="$CC" \
    CFLAGS="-O2 -static" \
    LDFLAGS="-static" \
    cansend candump
  cp "$OUT/src/can-utils/cansend" "$OUT/src/can-utils/candump" "$OUT/bin/"
  echo "[linux-aarch64] artifacts in $OUT/bin"
}

usage() {
  cat <<EOF
Usage: $0 [ndk|linux-aarch64]

  ndk            Android NDK static aarch64 (set ANDROID_NDK_HOME)
  linux-aarch64  gcc-aarch64-linux-gnu static build for RK3588 Linux

Install on board:
  scp out/bin/cansend out/bin/candump root@rk3588:/usr/local/bin/
  cansend can0 123#DEADBEEF
  candump can0
EOF
}

fetch_src
case "${1:-}" in
  ndk) build_ndk ;;
  linux-aarch64) build_linux_aarch64 ;;
  *) usage; exit 1 ;;
esac
