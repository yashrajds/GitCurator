from http.server import BaseHTTPRequestHandler
import json

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response_data = {
            'status': 'online',
            'service': 'GitCurator API',
            'version': '0.1.0',
            'description': 'Autonomous AI GitHub Profile & Repository Manager',
            'endpoints': [
                '/api/status',
                '/api/audit'
            ]
        }
        self.wfile.write(json.dumps(response_data).encode('utf-8'))
