#!/usr/bin/env bash
# Regenerate the Python protobuf bindings from proto/ into
# src/rp_server/protocol/gen/ (without touching the __init__.py markers).
#
# The board ships python3-protobuf 4.21.12 (protoc 21.12), so generate with a
# matching toolchain. grpcio-tools bundles a compatible protoc:
#   python3 -m pip install "grpcio-tools==1.51.1"
set -euo pipefail

cd "$(dirname "$0")/.."

OUT=src/rp_server/protocol/gen
mkdir -p "$OUT"

find "$OUT" -name '*_pb2.py' -delete
python3 -m grpc_tools.protoc \
  -I proto \
  --python_out="$OUT" \
  proto/roboparty/v1/*.proto

echo "generated roboparty.v1 bindings into $OUT"
