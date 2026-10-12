"""A tiny OpenAI-compatible chat-completions server for tests (standard library only).

Responses are scripted; every request is recorded (path, headers, JSON body) so tests can assert
exactly what left the server.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def tool_call(name: str, arguments: dict, call_id: str = 'call_1') -> dict:
    return {
        'choices': [
            {
                'message': {
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [
                        {
                            'id': call_id,
                            'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps(arguments)},
                        }
                    ],
                }
            }
        ],
        'usage': {'total_tokens': 100},
    }


def answer(text: str, tokens: int = 50) -> dict:
    return {
        'choices': [{'message': {'role': 'assistant', 'content': text}}],
        'usage': {'total_tokens': tokens},
    }


class FakeProvider:
    def __init__(self) -> None:
        self.script: list[tuple[int, object, dict]] = []  # (status, body, extra headers)
        self.requests: list[dict] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}')
                provider.requests.append(
                    {'path': self.path, 'headers': dict(self.headers), 'body': body}
                )
                status, payload, extra = (
                    provider.script.pop(0) if provider.script else (200, answer('done'), {})
                )
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                for key, value in extra.items():
                    self.send_header(key, value)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def push(self, payload: object, status: int = 200, **headers: str) -> None:
        self.script.append((status, payload, headers))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def sent_text(self) -> str:
        return json.dumps([r['body'] for r in self.requests])
