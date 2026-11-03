#!/usr/bin/env python3
"""Enlarge the Pixtuoid floating window once without requiring a TOML library.

Preserves unrelated config sections; Pixtuoid itself persists later user resizes.
"""
from pathlib import Path
import os
import re


def configure(home: Path, width=1600, height=1000, zoom=3):
    cfgdir = home / 'pixtuoid'
    cfgdir.mkdir(parents=True, exist_ok=True)
    marker = cfgdir / '.herdr-floating-sized-v1.8'
    config = cfgdir / 'config.toml'
    if marker.exists():
        return False
    old = config.read_text(encoding='utf-8') if config.exists() else ''
    lines = old.splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r'\s*\[floating\]\s*(?:#.*)?', line)), None)
    values = {'width': width, 'height': height, 'zoom': zoom}
    if start is None:
        if lines and lines[-1].strip():
            lines.append('')
        lines.extend(['[floating]', *(f'{key} = {value}' for key, value in values.items())])
    else:
        stop = next((i for i in range(start + 1, len(lines)) if re.match(r'\s*\[', lines[i])), len(lines))
        for key, value in values.items():
            match = next((i for i in range(start + 1, stop) if re.match(rf'\s*{key}\s*=', lines[i])), None)
            if match is not None:
                lines[match] = f'{key} = {value}'
            else:
                lines.insert(stop, f'{key} = {value}')
                stop += 1
    changed = '\n'.join(lines).rstrip() + '\n'
    if changed != old:
        config.write_text(changed, encoding='utf-8')
    marker.write_text('Size initialized; resize normally from now on.\n', encoding='utf-8')
    return True


if __name__ == '__main__':
    root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    configure(root)
