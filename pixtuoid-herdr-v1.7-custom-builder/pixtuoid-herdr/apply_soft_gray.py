#!/usr/bin/env python3
"""Mute only environmental color *literals* in the upstream normal theme.

This intentionally does not touch sprite definitions, UI/status/tool colors, or any
code outside theme/normal.rs. It is a palette variant, not a new registered theme.
Fails closed if upstream color syntax no longer matches the supported forms.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

ENV_GROUPS = {'surface','office','furniture','lighting','appliance','appliances'}
TRIPLE = re.compile(r'(?P<prefix>(?:Rgb::new|Rgb|rgb|Color::Rgb|rgb8)\s*\(\s*)(?P<r>0x[0-9a-fA-F]{1,2}|\d{1,3})(?P<comma1>\s*,\s*)(?P<g>0x[0-9a-fA-F]{1,2}|\d{1,3})(?P<comma2>\s*,\s*)(?P<b>0x[0-9a-fA-F]{1,2}|\d{1,3})(?P<suffix>\s*\))')
HEX6 = re.compile(r'0x[0-9a-fA-F]{6}\b')
GROUP = re.compile(r'^\s*(surface|office|lighting|furniture|appliances?|furniture_colors)\s*:\s*\w+(?:::[:\w]+)?\s*\{')


def tone_channel(r, g, b):
    # Reduce chroma around luminance, tiny neutral blending for a calm office.
    y = .2126*r + .7152*g + .0722*b
    return tuple(max(0, min(255, round(.20*v + .76*y + .04*134))) for v in (r,g,b))


def transform_color(match):
    nums = [match.group(k) for k in ('r','g','b')]
    rgb = [int(n, 16) if n.startswith('0x') else int(n) for n in nums]
    if max(rgb) > 255: return match.group(0)
    soft = tone_channel(*rgb)
    new = dict(zip(('r','g','b'), (f'0x{v:02X}' if o.startswith('0x') else str(v) for o,v in zip(nums,soft))))
    return ''.join((match.group('prefix'),new['r'],match.group('comma1'),new['g'],match.group('comma2'),new['b'],match.group('suffix')))


def transform(src: str):
    out=[]; active=False; depth=0; modified=0
    for line in src.splitlines(keepends=True):
        # Theme fields are defined in nested struct groups. Keep UI/status colors intact.
        if not active:
            match=GROUP.search(line)
            if match and (match.group(1) in ENV_GROUPS):
                active=True
                depth=0
        if active:
            if not line.lstrip().startswith('//'):
                new, n=TRIPLE.subn(transform_color, line)
                def sub_hex(m):
                    val=int(m.group(0),16)
                    r,g,b=(val >>16)&255, (val>>8)&255, val&255
                    rr,gg,bb=tone_channel(r,g,b)
                    return f'0x{rr:02X}{gg:02X}{bb:02X}'
                new, nh=HEX6.subn(sub_hex,new)
                modified += n + nh
                line=new
            depth+=line.count('{')-line.count('}')
            if depth<=0: active=False
        out.append(line)
    return ''.join(out),modified


def apply(root: Path):
    path=root/'crates/pixtuoid-scene/src/theme/normal.rs'
    if not path.is_file():
        raise RuntimeError(f'Cannot find upstream normal theme: {path}')
    before=path.read_text(encoding='utf-8')
    after,count=transform(before)
    if count<8:
        raise RuntimeError(f'Unsupported upstream theme syntax: only {count} matching colors; refusing partial palette.')
    path.write_text(after,encoding='utf-8')
    print(f'Herdr Soft Gray: muted {count} environmental palette colors. UI, status and character palettes unchanged.')
    return count

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('upstream',type=Path)
    args=parser.parse_args()
    apply(args.upstream)
