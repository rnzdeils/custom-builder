#!/usr/bin/env python3
"""Diagnóstico de lectura local de Herdr, sin modificar sesiones ni configuraciones.
No imprime el snapshot completo (puede incluir rutas, comandos y metadatos sensibles).
"""
from __future__ import annotations
import json
import os
import socket
import sys
from collections import Counter
from pathlib import Path

SUBSCRIPTIONS = ["pane.created", "pane.closed", "pane.exited", "pane.agent_detected", "pane.updated"]


def socket_candidates() -> list[Path]:
    override = os.getenv('HERDR_SOCKET_PATH')
    if override:
        return [Path(override).expanduser()]
    config_root = Path(os.getenv('XDG_CONFIG_HOME') or (Path.home() / '.config')) / 'herdr'
    session = os.getenv('HERDR_SESSION')
    if session:
        if session in ('.', '..') or '/' in session or '\\' in session:
            raise ValueError('HERDR_SESSION no es un nombre válido')
        return [config_root / 'sessions' / session / 'herdr.sock']
    default = config_root / 'herdr.sock'
    if default.exists():
        return [default]
    return sorted((config_root / 'sessions').glob('*/herdr.sock'))


def request(path: Path, method: str, params: dict | None = None) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.connect(str(path))
        conn.sendall((json.dumps({'id': f'doctor-{method}', 'method': method, 'params': params or {}}) + '\n').encode())
        payload = bytearray()
        while b'\n' not in payload:
            chunk = conn.recv(8192)
            if not chunk:
                raise RuntimeError(f'{method}: Herdr cerró la conexión sin responder')
            payload.extend(chunk)
            if len(payload) > 10_000_000:
                raise RuntimeError('Respuesta demasiado grande')
        return json.loads(payload.split(b'\n', 1)[0])


def unwrap(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get('agents'), list):
        return payload
    result = payload.get('result')
    if isinstance(result, dict):
        if isinstance(result.get('snapshot'), dict):
            return result['snapshot']
        if isinstance(result.get('agents'), list):
            return result
    return None


def describe(payload: dict) -> tuple[int, list[dict]]:
    snap = unwrap(payload)
    if snap is None:
        raise ValueError('Herdr respondió, pero no existe result.snapshot.agents')
    agents = snap.get('agents') or []
    panes = snap.get('panes') or []
    print(f'Snapshot: {len(agents)} agentes, {len(panes)} panes, estados: {dict(Counter(str(a.get("agent_status", "(sin campo)")) for a in agents))}')
    if not agents:
        print('AVISO: Herdr no está reportando agentes en esta sesión.')
        print('Abrí un agente dentro de Herdr y verificá `herdr agent list --json`.')
    for a in agents[:15]:
        print(f'  pane={a.get("pane_id", "?")} agente={a.get("agent") or a.get("display_agent") or "?"} estado={a.get("agent_status", "?")}')
    if len(agents) > 15:
        print(f'  … y {len(agents)-15} agentes más')
    return len(agents), agents


def main() -> int:
    try:
        candidates = socket_candidates()
    except Exception as exc:
        print('Configuración Herdr inválida:', exc, file=sys.stderr)
        return 2
    if not candidates:
        print('No se encontró socket Herdr. Revisá si corre el servidor y las variables HERDR_SESSION/HERDR_SOCKET_PATH.', file=sys.stderr)
        return 2
    if len(candidates) > 1:
        print('Hay múltiples sesiones Herdr; elegí una con HERDR_SESSION=<nombre> antes de iniciar Pixtuoid:')
        for c in candidates: print(' ', c)
        return 2
    path = candidates[0]
    print('Socket seleccionado:', path)
    try:
        ping = request(path, 'ping')
        if ping.get('error'):
            raise RuntimeError(f'ping rechazado: {ping["error"]}')
        print('Conexión: OK')
        snap = request(path, 'session.snapshot')
        if snap.get('error'):
            raise RuntimeError(f'session.snapshot rechazado: {snap["error"]}')
        count, _ = describe(snap)
        sub = request(path, 'events.subscribe', {'subscriptions': [{'type': t} for t in SUBSCRIPTIONS]})
        if sub.get('error'):
            raise RuntimeError(f'suscripción RECHAZADA: {sub["error"]}')
        print('Suscripción global compatible: OK')
        if count:
            print('Lecturas Herdr OK. Si la oficina sigue vacía, inspeccionar el filtrado/registro Pixtuoid.')
            return 0
        return 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
