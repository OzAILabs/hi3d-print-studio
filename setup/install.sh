#!/usr/bin/env bash
# Hi3D Print Studio - one-shot setup on Windows (run from Git Bash, or double-click Setup.bat).
#
# Builds everything into this folder (nothing goes to C: except what Windows itself needs):
#   ComfyUI_py312\   ComfyUI v0.46.0 on embedded Python 3.12.10 + PyTorch 2.8.0 / CUDA 12.8
#                    (the versions MostAadTech's WTiVo watertight node is compiled for)
#   + AeroX's native Hi3D nodes, VisualBruno's ComfyUI-Trellis2 (CuMesh),
#     PixelArtistry's Watertight / Image-to-3D-Print / Animated-Characters packs (UltraTex),
#     and this repo's Hi3D-ColourPrint node (linked, not copied)
#   + all models (~33 GB), each checked against its SHA-256 where the source publishes one.
# Safe to re-run: finished steps are skipped, downloads resume.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DL="$ROOT/downloads"
DEST="$ROOT/ComfyUI_py312"
PYDIR="$DEST/python_embeded"
PY="$PYDIR/python.exe"
COMFY="$DEST/ComfyUI"
MODELS="$COMFY/models"
COMFY_TAG="v0.46.0"
HI3D_COMMIT="227d18f4fb8938e73ef5f4675a3656aa8d337f76"
VB_COMMIT="b0e84c0f29857a444e8bcb5b9be2ea218e96efd0"
PY_ZIP="python-3.12.10-embed-amd64.zip"
PY_SHA="4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
mkdir -p "$DEST" "$DL"
win() { cygpath -w "$1"; }

nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || { echo "No NVIDIA GPU / driver found."; exit 1; }

echo "== 1/10 Python 3.12.10 (embedded, checksum verified)"
if [ ! -f "$PY" ]; then
    curl -fL -s -S --retry 5 -o "$DL/$PY_ZIP" "https://www.python.org/ftp/python/3.12.10/$PY_ZIP"
    (cd "$DL" && echo "$PY_SHA  $PY_ZIP" | sha256sum -c -)
    mkdir -p "$PYDIR"
    unzip -q -o "$DL/$PY_ZIP" -d "$PYDIR"
    rm -f "$DL/$PY_ZIP"
    printf '../ComfyUI\npython312.zip\n.\nLib/site-packages\nLib\nScripts\nimport site\n' > "$PYDIR/python312._pth"
    curl -fL -s -S --retry 5 -o "$PYDIR/get-pip.py" "https://bootstrap.pypa.io/get-pip.py"
    (cd "$PYDIR" && ./python.exe -I get-pip.py --no-warn-script-location -q && rm -f get-pip.py)
fi
"$PY" -I -m pip install -q --no-warn-script-location --upgrade pip uv

echo "== 2/10 PyTorch 2.8.0 + CUDA 12.8"
printf 'torch==2.8.0\ntorchvision==0.23.0\ntorchaudio==2.8.0\n' > "$DEST/torch-constraints.txt"
C="$DEST/torch-constraints.txt"
"$PY" -I -m pip install -q --no-warn-script-location torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 \
    --index-url https://download.pytorch.org/whl/cu128

echo "== 3/10 ComfyUI $COMFY_TAG"
[ -d "$COMFY/.git" ] || git clone --quiet https://github.com/Comfy-Org/ComfyUI "$COMFY"
git -C "$COMFY" fetch --quiet --tags origin
git -C "$COMFY" checkout --quiet --force "$COMFY_TAG"
"$PY" -I -m uv pip install -q --python "$PY" -c "$C" pygit2 -r "$COMFY/requirements.txt"
"$PY" -I -m pip install -q --no-warn-script-location -c "$C" \
    trimesh scipy scikit-image fast-simplification manifold3d pymeshlab aiohttp

echo "== 4/10 Triton (< 3.5, matches torch 2.8) + Python headers it compiles against"
"$PY" -I -m pip install -q --no-warn-script-location -c "$C" "triton-windows<3.5"
# The embedded Python ships without Include/ and libs/; Triton (UltraTex) needs them.
# Official python 3.12.10 NuGet package from the Python Software Foundation.
if [ ! -f "$PYDIR/libs/python312.lib" ]; then
    curl -fsSL -o "$DL/python-3.12.10.nupkg" https://www.nuget.org/api/v2/package/python/3.12.10
    "$PY" -I - "$(win "$DL/python-3.12.10.nupkg")" "$(win "$PYDIR")" <<'PYEOF'
import os, sys, zipfile
z, dest = zipfile.ZipFile(sys.argv[1]), sys.argv[2]
for name in z.namelist():
    for src, dst in (("tools/include/", "Include"), ("tools/libs/", "libs")):
        if name.startswith(src) and not name.endswith("/"):
            out = os.path.join(dest, dst, name[len(src):])
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(z.read(name))
PYEOF
fi

echo "== 5/10 AeroX's Hi3D nodes at ${HI3D_COMMIT:0:7}"
NODE="$COMFY/custom_nodes/Aero-Ex-ComfyUI-Hi3D"
[ -d "$NODE/.git" ] || git clone --quiet https://github.com/Aero-Ex/Aero-Ex-ComfyUI-Hi3D "$NODE"
git -C "$NODE" fetch --quiet origin
git -C "$NODE" checkout --quiet --force "$HI3D_COMMIT"

echo "== 6/10 Hi3D-ColourPrint node (this repo, linked into ComfyUI)"
LINK="$COMFY/custom_nodes/Hi3D-ColourPrint"
if [ ! -e "$LINK" ]; then
    # (cmd's mklink /J gets its switch mangled by Git Bash's path conversion; PowerShell doesn't)
    powershell -NoProfile -Command "New-Item -ItemType Junction -Path '$(win "$LINK")' -Target '$(win "$ROOT/comfyui_nodes/Hi3D-ColourPrint")' | Out-Null"
fi

echo "== 7/10 Models for shape + Hi3D (~22 GB, SHA-256 checked)"
HF="https://huggingface.co/Aero-Ex/ComfyUI-Hi3D/resolve/10e577aabc5c3c748f56b1fcc91178f581039312"
BIREF="https://huggingface.co/Comfy-Org/BiRefNet/resolve/884af709e9b795d89dafbf97f29c8d6a2386f5c6"
T2="https://huggingface.co/Comfy-Org/TRELLIS.2/resolve/430a9d09b2416687018c8fe8edced2ad4858a439"
PX="https://huggingface.co/Comfy-Org/Pixal3D/resolve/f37641be376725d324c56626007cc477f1249a69"
MOGE="https://huggingface.co/Comfy-Org/MoGe/resolve/1484985258ba7ef45c314144fcf0e90924ffbf44"
# Already have these models in another ComfyUI? Set HI3D_SHARED_MODELS to its models folder.
SHARED="${HI3D_SHARED_MODELS:-}"
while IFS='|' read -r folder file sha url; do
    dest="$MODELS/$folder/$file"
    if [ -f "$dest" ] || { [ -n "$SHARED" ] && [ -f "$SHARED/$folder/$file" ]; }; then
        echo "   have $folder/$file"; continue
    fi
    mkdir -p "$(dirname "$dest")"
    echo "   downloading $folder/$file"
    curl -L --fail -C - --retry 5 --retry-delay 10 -s -S -o "$dest.part" "$url"
    [ "$(sha256sum "$dest.part" | cut -d' ' -f1)" = "$sha" ] || { echo "   SHA-256 mismatch: $file"; rm -f "$dest.part"; exit 1; }
    mv "$dest.part" "$dest"
done <<EOF
checkpoints|hi3d_v1_int8.safetensors|b9eb785f7adf47208223a9262a593df6a1645f790a7c452a5e1f79440498af89|$HF/checkpoints/hi3d_v1_int8.safetensors
clip_vision|dinov2-large.safetensors|399fba97a95f22c36834418bc69373364a99af3a1153da1c0fb31db567c92e23|$HF/clip_vision/dinov2-large.safetensors
clip_vision|clip-vit-large-patch14.safetensors|a2bf730a0c7debf160f7a6b50b3aaf3703e7e88ac73de7a314903141db026dcb|$HF/clip_vision/clip-vit-large-patch14.safetensors
background_removal|birefnet.safetensors|9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154|$BIREF/background_removal/birefnet.safetensors
diffusion_models|trellis_2_int8_convrot.safetensors|d01952ad137213f6a868f86b6b877026276f84af5eec23069217475a0bad3a31|$T2/diffusion_models/trellis_2_int8_convrot.safetensors
vae|trellis_2_shape_vae_bf16.safetensors|de0cb4949a76c59ee5c091a995a69bcc8c51d5aeda939f0c641a50d2a72341f4|$T2/vae/trellis_2_shape_vae_bf16.safetensors
clip_vision|dino_v3_L_naf_fp32.safetensors|4ad2ec4e0879a5b5b04cd97325cc37da954a7b6edca5170b86510f17f2b2290f|$PX/clip_vision/dino_v3_L_naf_fp32.safetensors
diffusion_models|pixal3d_int8_convrot.safetensors|4621eac3b715484f79303c7152af641fe0b2b14f4d0e3d394fd6922d00f955ec|$PX/diffusion_models/pixal3d_int8_convrot.safetensors
geometry_estimation|moge_2_vitl_normal_fp16.safetensors|cb1a692d03235671e959e81360d7b4d9f44aefadb1f852d6ca6aa17799d5e31f|$MOGE/geometry_estimation/moge_2_vitl_normal_fp16.safetensors
EOF
if [ -n "$SHARED" ]; then
    cat > "$COMFY/extra_model_paths.yaml" <<EOF
hi3d_shared:
    base_path: $(win "$SHARED")
    checkpoints: checkpoints
    clip_vision: clip_vision
    diffusion_models: diffusion_models
    vae: vae
    background_removal: background_removal
    geometry_estimation: geometry_estimation
EOF
fi

echo "== 8/10 VisualBruno ComfyUI-Trellis2 at ${VB_COMMIT:0:7} + CuMesh wheels (torch 2.8 / cp312)"
VB="$COMFY/custom_nodes/ComfyUI-Trellis2"
[ -d "$VB/.git" ] || git clone --quiet https://github.com/visualbruno/ComfyUI-Trellis2 "$VB"
git -C "$VB" fetch --quiet origin
git -C "$VB" checkout --quiet --force "$VB_COMMIT"
W="$VB/wheels/Windows/Torch280"
"$PY" -I -m pip install -q --no-warn-script-location -c "$C" \
    "$W/cumesh-1.0-cp312-cp312-win_amd64.whl" "$W/nvdiffrast-0.4.0-cp312-cp312-win_amd64.whl" \
    "$W/nvdiffrec_render-0.0.0-cp312-cp312-win_amd64.whl" "$W/flex_gemm-0.0.1-cp312-cp312-win_amd64.whl" \
    "$W/o_voxel-0.0.1-cp312-cp312-win_amd64.whl"
"$PY" -I -m uv pip install -q --python "$PY" -c "$C" -r "$VB/requirements.txt"

echo "== 9/10 PixelArtistry packs (WTiVo watertight, mesh tools, UltraTex) - their own installers"
for r in PixelArtistry-Hi3D PixelArtistry-Watertight-Meshes PixelArtistry-Image-to-3D-Print PixelArtistry-Animated-Characters; do
    [ -d "$DL/$r/.git" ] || git clone --quiet --depth 1 "https://github.com/pixelartistry/$r" "$DL/$r"
done
run_installer() {   # repo, installer, answers (one letter per Y/N prompt, piped into `choice`)
    cp "$DL/$1/$2" "$DEST/$2"
    (printf '%s' "$3" | cmd //c "$(win "$DEST/$2")" 2>&1) | tr -d '\r' | grep -E '\[(OK|FAIL|WARN)' || true
    rm -f "$DEST/$2"
}
run_installer PixelArtistry-Watertight-Meshes watertightMeshes_win_installer.bat "Y"
run_installer PixelArtistry-Image-to-3D-Print install_win.bat "NNY"
cp "$DL/PixelArtistry-Animated-Characters/pa_helper.py" "$DEST/pa_helper.py"
run_installer PixelArtistry-Animated-Characters Install-PixelArtistry-Animated-Characters.bat "Y"
# Its UltraTex model download prompt comes after a nested installer; make sure it ran.
"$PY" -I "$DEST/pa_helper.py" models "$(win "$COMFY")" --download | grep -E '\[(OK|GET|MISSING|FAIL)' || true

echo "== 10/10 Workflows (ComfyUI sidebar > PixelArtistry) + check"
WF="$COMFY/user/default/workflows/PixelArtistry/Hi3D"
mkdir -p "$WF"
cp "$DL/PixelArtistry-Hi3D/workflows/"*.json "$WF/"
"$PY" -c "import sys, torch; print('Python', sys.version.split()[0], '| torch', torch.__version__, '| CUDA', torch.version.cuda, '|', torch.cuda.get_device_name(0))"
"$PY" -s - <<'PYEOF'
import torch, triton, triton.language as tl
@triton.jit
def k(x, o, n, B: tl.constexpr):
    i = tl.program_id(0) * B + tl.arange(0, B)
    tl.store(o + i, tl.load(x + i, mask=i < n) * 2, mask=i < n)
x = torch.rand(1024, device="cuda"); o = torch.empty_like(x)
k[(1,)](x, o, 1024, B=1024)
print("Triton kernel OK:", bool(torch.allclose(o, x * 2)))
PYEOF
echo
echo "Done. Start the studio with 'Start Hi3D Print Studio.bat'."
