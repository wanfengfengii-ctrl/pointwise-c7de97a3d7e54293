import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from arrangement.layouts import create_layout_schema, register_layout
from control.delivery import Delivery, direct_delivery
from control.presses import submit_press
from control.receipts import lookup_operation
from control.releases import submit_release
from control.request_book import create_request_schema
from review.archive import create_archive_schema
from review.lookup import listen_session
from session.closing import close_session
from session.lifecycle import SessionTurns
from session.opening import open_session
from session.session_book import create_session_schema
from session.storage import BusinessError, initialize_store, require_text
from sound.output import create_output_schema
from sound.tuning import change_transposition, create_tuning_schema
from sound.voices import create_voice_schema

logger = logging.getLogger(__name__)


class RehearsalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve('GET')

    def do_POST(self):
        self._serve('POST')

    def log_message(self, format, *args):
        logger.debug(format, *args)

    def _serve(self, method):
        try:
            status, payload = self._dispatch(method)
        except BusinessError as error:
            status, payload = error.status, {'error': error.code, 'message': str(error)}
        except Exception:
            logger.exception('Rehearsal request failed')
            status, payload = 500, {'error': 'internal_error', 'message': 'The operation could not finish'}
        data = json.dumps(payload, ensure_ascii=True).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug('Client disconnected while receiving a response')

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 65536:
                raise ValueError('body size')
            body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
        except (ValueError, UnicodeError, RecursionError) as error:
            raise BusinessError(400, 'invalid_json', 'Send a UTF-8 JSON object of at most 65536 bytes') from error
        if not isinstance(body, dict):
            raise BusinessError(400, 'invalid_json', 'Request body must be a JSON object')
        return body

    def _dispatch(self, method):
        try:
            url = urlsplit(self.path)
            path = [unquote(segment, errors='strict') for segment in url.path.split('/')[1:]]
        except (ValueError, UnicodeError) as error:
            raise BusinessError(400, 'invalid_path', 'Request path is invalid') from error
        delivery = self.server.delivery
        database = delivery.database
        body = self._body() if method == 'POST' else {}
        match method, path:
            case 'POST', ['layouts']:
                layout = register_layout(database, body.get('layout_id'), body.get('keyboards'))
                return 201, layout.to_dict()
            case 'POST', ['sessions']:
                return 201, open_session(database, body.get('layout_id'))
            case 'POST', ['sessions', session_id, 'close']:
                return 200, close_session(delivery, require_text(session_id, 'session_id'))
            case 'POST', ['keys', 'press']:
                result = submit_press(delivery, body.get('session_id'), body.get('keyboard_id'),
                                      body.get('request_id'), body.get('key'))
                return _operation_response(result)
            case 'POST', ['keys', 'release']:
                result = submit_release(delivery, body.get('session_id'), body.get('keyboard_id'),
                                        body.get('request_id'), body.get('press_id'))
                return _operation_response(result)
            case 'POST', ['transpositions']:
                return 200, change_transposition(database, delivery.turns, body.get('session_id'),
                                                 body.get('keyboard_id'), body.get('transposition'))
            case 'GET', ['operations', request_id]:
                sessions = parse_qs(url.query, keep_blank_values=True).get('session_id', [])
                if len(sessions) != 1:
                    raise BusinessError(400, 'invalid_query', 'Supply one session_id query parameter')
                session_id = require_text(sessions[0], 'session_id')
                return 200, lookup_operation(database, session_id, request_id).to_dict()
            case 'GET', ['sessions', session_id, 'sound']:
                return 200, listen_session(database, session_id)
            case _:
                raise BusinessError(404, 'route_not_found', 'No route for this method and path')


def _operation_response(result):
    codes = {'completed': 200, 'pending': 202, 'rejected': 422}
    body = result.to_dict()
    if result.error == 'invalid_reference':
        body['message'] = 'The referenced press can no longer be released'
    return codes[result.status], body


def build_server(database, port=0, *, transport=direct_delivery):
    initialize_store(database, (
        create_layout_schema, create_session_schema, create_request_schema,
        create_tuning_schema, create_voice_schema, create_output_schema, create_archive_schema,
    ))
    server = ThreadingHTTPServer(('127.0.0.1', port), RehearsalHandler)
    server.delivery = Delivery(database, SessionTurns(), transport)
    return server


def main():
    parser = argparse.ArgumentParser(description='Run the local rehearsal service')
    parser.add_argument('--database', required=True)
    parser.add_argument('--port', type=int, default=8765)
    arguments = parser.parse_args()
    with build_server(arguments.database, arguments.port) as server:
        print(f'Rehearsal service listening on 127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
