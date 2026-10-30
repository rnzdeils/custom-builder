#!/usr/bin/env bash
# Compila Pixtuoid + Herdr en un contenedor efimero. Solo deja el binario en dist/.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
command -v docker >/dev/null 2>&1 || {
  echo 'Error: falta Docker. Esta opcion no requiere instalar Rust ni Cargo en el host.' >&2
  exit 1
}
# Evitar ruta relativa en bind mounts y no tocar un binario de Pixtuoid ya instalado.
OUT="${PIXTUOID_OUTPUT_DIR:-$HERE/dist}"
mkdir -p -- "$OUT"
OUT="$(cd -- "$OUT" && pwd -P)"
RUST_IMAGE="${RUST_IMAGE:-rust:1.99.1-bookworm}"
BUILD_JOBS="${BUILD_JOBS:-2}"
case "$BUILD_JOBS" in
  ''|*[!0-9]*) echo 'Error: BUILD_JOBS debe ser un numero entero positivo' >&2; exit 2 ;;
esac
if (( BUILD_JOBS < 1 || BUILD_JOBS > 16 )); then
  echo 'Error: BUILD_JOBS debe estar entre 1 y 16' >&2; exit 2
fi
if [[ "$(uname -s)" != 'Linux' || "$(uname -m)" != 'x86_64' ]]; then
  echo 'Error: este script esta preparado para Linux x86_64 (Mint/Ubuntu).' >&2
  exit 2
fi

printf 'Pixtuoid-Herdr: compilacion en Docker (sin Rust en el host)\nImagen: %s\nSalida: %s\nJobs: %s\n' "$RUST_IMAGE" "$OUT" "$BUILD_JOBS"
# Montajes acotados: codigo del kit solo lectura, salida en carpeta dedicada.
# No se monta ~/.ssh, $HOME, socket Docker, ni las sesiones Herdr.
docker run --rm --init \
  --security-opt=no-new-privileges \
  --mount "type=bind,src=$HERE,dst=/kit,readonly" \
  --mount "type=bind,src=$OUT,dst=/out" \
  --env "BUILD_JOBS=$BUILD_JOBS" \
  --env "RUN_RUST_TESTS=${RUN_RUST_TESTS:-0}" \
  --env "HOST_UID=$(id -u)" \
  --env "HOST_GID=$(id -g)" \
  --env "PIXTUOID_REF=${PIXTUOID_REF:-}" \
  "$RUST_IMAGE" bash /kit/docker/build-in-container.sh

printf '\nCompilacion finalizada. Para ejecutar desde tu Linux Mint:\n'
printf '  "%s/pixtuoid-herdr" floating\n' "$HERE"
