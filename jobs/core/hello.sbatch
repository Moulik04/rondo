#!/bin/bash
# Hello job: proves CUDA, PyTorch and PyG work on a V100 (a few minutes of GPU time).
#
#   sbatch -A <allocation> jobs/core/hello.sbatch $PROJECT/rondo/bundles/hello-train-<sha7>.tar.zst
#
#SBATCH -J rondo-hello
#SBATCH -p GPU-shared
#SBATCH --gpus=v100-32:1
#SBATCH -t 00:10:00
#SBATCH -o rondo-hello-%j.out
set -euo pipefail

BUNDLE=${1:?usage: sbatch -A <allocation> hello.sbatch <bundle.tar.zst>}
ENV_DIR=${RONDO_ENV:-$PROJECT/rondo/env}
RUNS=$PROJECT/rondo/runs
mkdir -p "$RUNS"

echo "== nvidia-smi"
nvidia-smi

echo "== checking bundle checksum"
(cd "$(dirname "$BUNDLE")" && sha256sum -c "$(basename "$BUNDLE").sha256")

echo "== copying bundle to node-local \$LOCAL"
WORK=$LOCAL/rondo-$SLURM_JOB_ID
mkdir -p "$WORK"
cp "$BUNDLE" "$WORK/"
"$ENV_DIR/bin/python" - "$WORK/$(basename "$BUNDLE")" "$WORK" <<'PY'
import sys, tarfile, zstandard
src, dest = sys.argv[1], sys.argv[2]
with open(src, "rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as zr, \
        tarfile.open(fileobj=zr, mode="r|") as tar:
    tar.extractall(dest, filter="data")
PY

echo "== hello"
cd "$WORK"
PYTHONPATH=$WORK/code/src "$ENV_DIR/bin/python" -m rondo.core.hello --runs "$RUNS"
