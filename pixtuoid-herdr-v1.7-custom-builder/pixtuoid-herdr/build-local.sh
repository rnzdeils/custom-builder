#!/usr/bin/env bash
set -euo pipefail
# Copies/patches an existing Pixtuoid checkout, compiles it and places a launcher next to it.
ROOT="${1:-}"
if [[ -z "$ROOT" ]]; then echo "Uso: $0 /ruta/al/checkout/pixtuoid" >&2; exit 2; fi
THIS="$(cd "$(dirname "$0")" && pwd)"
python3 "$THIS/apply_fork.py" "$ROOT"
if [[ "${HERDR_SOFT_GRAY:-1}" == "1" ]]; then
  python3 "$THIS/apply_soft_gray.py" "$ROOT" || echo 'WARNING: gray palette unsupported on this upstream; retaining normal.' >&2
fi
cd "$ROOT"
cargo fmt --all
cargo test -p pixtuoid --lib herdr
cargo build --release -p pixtuoid
printf '\nCompiled: %s/target/release/pixtuoid\n' "$PWD"
cat <<EOF
Launch floating:
  PIXTUOID_BIN="$PWD/target/release/pixtuoid" "$THIS/pixtuoid-herdr" floating
Launch TUI:
  PIXTUOID_BIN="$PWD/target/release/pixtuoid" "$THIS/pixtuoid-herdr"
EOF
