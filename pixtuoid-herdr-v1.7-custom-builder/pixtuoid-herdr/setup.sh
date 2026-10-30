#!/usr/bin/env bash
set -euo pipefail
THIS="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/opt/pixtuoid-herdr}"
for cmd in git cargo python3; do
  command -v "$cmd" >/dev/null || { echo "Falta: $cmd" >&2; exit 1; }
done
if [[ -e "$TARGET" ]]; then
  echo "La carpeta ya existe, no la modifico: $TARGET" >&2
  echo "Para usar un checkout propio: $THIS/build-local.sh /ruta/pixtuoid" >&2
  exit 1
fi
mkdir -p "$(dirname "$TARGET")"
git clone --depth=1 https://github.com/pixtuoid/pixtuoid.git "$TARGET"
(
  cd "$TARGET"
  git switch -c experimental/herdr-v1
)
"$THIS/build-local.sh" "$TARGET"
printf '\nEjecutá:\n  PIXTUOID_BIN="%s/target/release/pixtuoid" "%s/pixtuoid-herdr" floating\n' "$TARGET" "$THIS"
