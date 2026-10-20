"""First-party verification fixture exposing the packaged runtime and docs identity."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


sys.path.insert(0, '/app/runtime')
import evaluate  # noqa: E402

runtime = Path('/app/runtime')
revision = os.environ['PROOF_REVISION']
assessment = evaluate.evaluate(
    *[evaluate.load_document(runtime / name) for name in ('policy.yaml', 'profiles.yaml', 'control-catalog.yaml', 'providers.yaml')],
    {'version': 2, 'subject': {'type': 'git-commit', 'revision': revision}, 'results': {}},
    'change', revision, 'git-commit',
)
if not assessment['controls']:
    raise RuntimeError('Packaged Proof runtime did not evaluate any controls')


class Handler(BaseHTTPRequestHandler):
    def version_string(self):
        return 'ToolkitVerificationFixture'

    def do_GET(self):
        if self.path == '/health':
            body = json.dumps({'revision': os.environ['PROOF_REVISION'], 'runtime_controls_evaluated': len(assessment['controls']), 'runtime_missing_evidence_status': assessment['status'], 'documentation_files': len(list(Path('/app/docs').rglob('*.md')))}).encode()
            code = 200
        elif self.path == '/':
            body = b'<!doctype html><html><head><title>Toolkit verification fixture</title></head><body>Packaged Proof runtime and documentation verification.</body></html>'
            code = 200
        else:
            body, code = b'Not found', 404
        self.send_response(code)
        self.send_header('Content-Type', 'application/json' if self.path == '/health' else 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
