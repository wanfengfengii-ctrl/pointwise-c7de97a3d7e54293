import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from session.storage import BusinessError, initialize_store
from sound.monitor_board import (
    create_monitor_board_schema,
    get_receipt,
    get_sound,
    submit_steps,
    submit_switch,
)

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024 * 1024


class MonitorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve('GET')

    def do_POST(self):
        self._serve('POST')

    def log_message(self, format, *args):
        logger.debug(format, *args)

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= MAX_BODY_BYTES:
                raise ValueError('body size')
            raw = self.rfile.read(length) if length else b'{}'
            body = json.loads(raw.decode('utf-8')) if length else {}
        except (ValueError, UnicodeError, RecursionError) as error:
            raise BusinessError(400, 'invalid_json',
                                'Send a UTF-8 JSON object of at most 16 MiB') from error
        if not isinstance(body, dict):
            raise BusinessError(400, 'invalid_json', 'Request body must be a JSON object')
        return body

    def _serve(self, method):
        try:
            status, payload = self._dispatch(method)
        except BusinessError as error:
            status, payload = error.status, {'error': error.code, 'message': str(error)}
        except Exception:
            logger.exception('Monitor request failed')
            status, payload = 500, {'error': 'internal_error',
                                    'message': 'The monitor operation could not finish'}
        data = json.dumps(payload, ensure_ascii=True).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug('Client disconnected while receiving a monitor response')

    def _dispatch(self, method):
        try:
            url = urlsplit(self.path)
            path = [unquote(segment, errors='strict') for segment in url.path.split('/')[1:]]
        except (ValueError, UnicodeError) as error:
            raise BusinessError(400, 'invalid_path', 'Request path is invalid') from error

        database = self.server.database
        body = self._body() if method == 'POST' else {}

        match method, path:
            case 'POST', ['monitor', 'switches']:
                return submit_switch(database, body)
            case 'GET', ['monitor', 'switches', request_id]:
                return 200, get_receipt(database, request_id)
            case 'POST', ['monitor', 'steps']:
                return submit_steps(database, body)
            case 'GET', ['monitor', 'sound']:
                return 200, get_sound(database)
            case _:
                raise BusinessError(404, 'route_not_found', 'No monitor route for this method and path')


def build_server(database, port=0):
    initialize_store(database, (create_monitor_board_schema,))
    server = ThreadingHTTPServer(('127.0.0.1', port), MonitorHandler)
    server.database = database
    return server


def main():
    parser = argparse.ArgumentParser(description='Run the independent monitor desk service')
    parser.add_argument('--database', required=True)
    parser.add_argument('--port', type=int, default=8766)
    arguments = parser.parse_args()
    with build_server(arguments.database, arguments.port) as server:
        print(f'Monitor service listening on 127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
