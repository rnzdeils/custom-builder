#!/usr/bin/env bash
# El ejecutable se compila dentro del contenedor, pero no se ejecuta aqui.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export CARGO_BUILD_JOBS="${BUILD_JOBS:-2}"
export CARGO_PROFILE_RELEASE_DEBUG=0

apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    ca-certificates git python3 pkg-config lld clang cmake \
    libasound2-dev libudev-dev \
    libx11-dev libxcb1-dev libxkbcommon-dev libwayland-dev \
    libxi-dev libxrandr-dev libxcursor-dev libxinerama-dev \
    libgl1-mesa-dev libvulkan-dev >/dev/null

mkdir -p /build
cd /build
if [[ -n "${PIXTUOID_REF:-}" ]]; then
  # La revision puede fijarse a un tag/commit para reproducibilidad.
  git init -q pixtuoid
  cd pixtuoid
  git remote add origin https://github.com/pixtuoid/pixtuoid.git
  git fetch -q --depth 1 origin "$PIXTUOID_REF"
  git checkout -q --detach FETCH_HEAD
else
  git clone -q --depth 1 https://github.com/pixtuoid/pixtuoid.git pixtuoid
  cd pixtuoid
fi
printf 'Upstream commit: '
git rev-parse HEAD
python3 /kit/apply_fork.py /build/pixtuoid
if [[ "${HERDR_SOFT_GRAY:-1}" == "1" ]]; then
  python3 /kit/apply_soft_gray.py /build/pixtuoid || echo 'WARNING: gray palette unsupported on this upstream; retaining normal.' >&2
fi
cargo fmt --all
# Cargo test --lib compiles all upstream test harnesses, which is not required
# to produce a release binary. Enable it explicitly when debugging.
if [[ "${RUN_RUST_TESTS:-0}" == "1" ]]; then
  cargo test --locked -p pixtuoid --lib herdr
fi
cargo build --locked --release -p pixtuoid

# Publicar de forma atomica: no reemplazar un binario anterior hasta tener build terminado.
install -m 0755 target/release/pixtuoid /out/pixtuoid.new
mv -f /out/pixtuoid.new /out/pixtuoid
(
  cd /out
  sha256sum pixtuoid > pixtuoid.sha256
)
git rev-parse HEAD >/out/upstream-commit.txt
chown "${HOST_UID:-0}:${HOST_GID:-0}" /out/pixtuoid /out/pixtuoid.sha256 /out/upstream-commit.txt
