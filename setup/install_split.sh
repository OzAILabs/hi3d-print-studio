#!/usr/bin/env bash
# Optional, experimental: the "Split into pieces" feature (Tencent P3-SAM part finder).
# Run from Git Bash in the Hi3D Print Studio folder after setup/install.sh:
#     bash setup/install_split.sh
# Installs into parts/ (about 7 GB, nothing outside this folder):
#   parts/Hunyuan3D-Part   Tencent's code (unmodified; split/run_p3sam.py applies the Windows changes)
#   parts/.venv-p3sam      its own Python 3.10 with PyTorch 2.8 (CUDA 12.8, works on RTX 50 / Blackwell)
#   parts/weights          P3-SAM (431 MB) and Sonata (414 MB)
# Needs: uv (https://docs.astral.sh/uv/), git, an NVIDIA GPU with 24 GB.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd -W 2>/dev/null || pwd)"
PARTS="$ROOT/parts"
mkdir -p "$PARTS/weights"
export UV_CACHE_DIR="$PARTS/.uv-cache" UV_PYTHON_INSTALL_DIR="$PARTS/.uv-python" UV_LINK_MODE=copy

step() { echo; echo "== $*"; }

step "1/4 Tencent Hunyuan3D-Part code"
[ -d "$PARTS/Hunyuan3D-Part" ] || git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-Part.git "$PARTS/Hunyuan3D-Part"

step "2/4 Python 3.10 environment"
[ -x "$PARTS/.venv-p3sam/Scripts/python.exe" ] || uv venv --python 3.10 "$PARTS/.venv-p3sam"
PY="$PARTS/.venv-p3sam/Scripts/python.exe"

step "3/4 PyTorch 2.8 + sparse convolution + the rest"
uv pip install --python "$PY" torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python "$PY" torch-scatter -f https://data.pyg.org/whl/torch-2.8.0+cu128.html
uv pip install --python "$PY" spconv-cu126 addict fpsample numba timm omegaconf safetensors trimesh \
    scikit-learn scipy huggingface_hub "numpy<2" "setuptools<70"

step "4/4 Weights"
"$PY" - "$PARTS/weights" <<'EOF'
import sys
from huggingface_hub import hf_hub_download
w = sys.argv[1]
print(hf_hub_download("tencent/Hunyuan3D-Part", "p3sam/p3sam.safetensors", local_dir=w))
print(hf_hub_download("facebook/sonata", "sonata.pth", local_dir=w + "/sonata"))
EOF

"$PY" -c "import torch, spconv.pytorch; assert torch.cuda.is_available(); print('P3-SAM environment ready:', torch.cuda.get_device_name(0))"
echo
echo "Done. Restart the studio; finished prints now show 'Split into pieces (experimental)'."
echo "The download cache in parts/.uv-cache can be deleted."
