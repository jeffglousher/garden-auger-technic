"""Small local stdio client for the installed noBS CAD engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


class CadClient:
    def __init__(self, executable: Path | None = None, arguments: list[str] | None = None):
        executable = executable or Path(os.environ['LOCALAPPDATA']) / 'nbcad/mcp/nbcad-mcp.exe'
        self.process = subprocess.Popen(
            [str(executable),*(arguments if arguments is not None else ['--headless'])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        self.sequence = 0
        self.request('initialize', {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'garden-auger', 'version': '1'},
        })
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        self.process.stdin.flush()

    def request(self, method: str, params: dict):
        self.sequence += 1
        self.process.stdin.write(json.dumps({
            'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params,
        }) + '\n')
        self.process.stdin.flush()
        while line := self.process.stdout.readline():
            reply = json.loads(line)
            if reply.get('id') != self.sequence:
                continue
            if 'error' in reply:
                raise RuntimeError(reply['error'])
            return reply['result']
        raise RuntimeError(f'CAD engine exited with {self.process.poll()}')

    def call(self, name: str, arguments: dict | None = None):
        result = self.request('tools/call', {'name': name, 'arguments': arguments or {}})
        if result.get('isError'):
            raise RuntimeError(result)
        if 'structuredContent' in result:
            value = result['structuredContent']
            return value['value'] if isinstance(value,dict) and set(value)=={'value'} else value
        content = next(c['text'] for c in result['content'] if c['type'] == 'text')
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=15)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
