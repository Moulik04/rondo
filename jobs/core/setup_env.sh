#!/bin/bash
# Build Rondo's Python environment on a Bridges-2 LOGIN node (needs internet), once.
#
#   bash setup_env.sh <bundle.tar.zst>
#
# Any bundle works (they all carry the same uv.lock for a given commit); the hello bundle is
# the smallest. The environment holds dependencies only: each job runs the code from its own
# bundle.
#
# Where it goes: RONDO_ENV, default $HOME/rondo/env. The home directory has room for it; the
# 10 GB project space doesn't (6.5 GB environment, and the project space also caps file
# counts). uv's download cache and its Python go next to the environment; the cache is
# cleared at the end. hello.sbatch uses the same default.
set -euo pipefail

BUNDLE=${1:?usage: bash setup_env.sh <bundle.tar.zst>}
BUNDLE=$(realpath "$BUNDLE")
ENV_DIR=${RONDO_ENV:-$HOME/rondo/env}
BASE=$(dirname "$ENV_DIR")
mkdir -p "$BASE"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== checking bundle checksum"
(cd "$(dirname "$BUNDLE")" && sha256sum -c "$(basename "$BUNDLE").sha256")

echo "== extracting code"
if tar --help 2>/dev/null | grep -q -- '--zstd'; then
  tar --zstd -xf "$BUNDLE" -C "$WORK"
elif command -v zstd >/dev/null; then
  zstd -dc "$BUNDLE" | tar -xf - -C "$WORK"
else
  echo "neither 'tar --zstd' nor 'zstd' is available; try: module load zstd" >&2
  exit 1
fi

echo "== installing uv (user site) if needed"
if ! command -v uv >/dev/null; then
  python3 -m pip install --user --quiet uv
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

# Keep uv's cache and Python download next to the environment; the cache is cleared at the end.
export UV_CACHE_DIR=$BASE/uv-cache
export UV_PYTHON_INSTALL_DIR=$BASE/python
export UV_PROJECT_ENVIRONMENT=$ENV_DIR
echo "== space used under $BASE before building"
du -sh "$BASE" 2>/dev/null || true

echo "== building environment in $ENV_DIR (CUDA 12.6 PyTorch build)"
cd "$WORK/code"
uv sync --locked --extra cu126 --no-dev --no-install-project --python 3.12

echo "== checking imports"
"$ENV_DIR/bin/python" - <<'PY'
import torch, torch_geometric, zstandard, duckdb, pyarrow
print("torch", torch.__version__, "cuda build", torch.version.cuda)
print("arch list", torch.cuda.get_arch_list() if torch.cuda.is_available() else "(no GPU on login node)")
print("torch_geometric", torch_geometric.__version__)
PY

uv cache clean
echo "== sizes"
du -sh "$ENV_DIR" "$BASE/python" 2>/dev/null || true
echo "done: environment at $ENV_DIR"
