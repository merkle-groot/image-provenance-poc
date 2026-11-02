"""Web interface for the proof of concept.

The server listens on loopback only; to publish it, put an HTTPS reverse proxy in
front and set MEDIA_POC_ORIGIN to the public origin (e.g. https://example.com).
"""
import base64
import binascii
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from PIL import Image
from .core import connect, fingerprint, media_kind, register_asset, verify_media
from . import watermark


def engine(kind):
    if kind == 'video':
        from . import video
        return video
    return watermark

WEB = Path(__file__).resolve().parent.parent / 'web'
MAX_UPLOAD_MB = int(os.environ.get('MEDIA_POC_MAX_UPLOAD_MB', '50'))
CHUNK = 1024 * 1024
# Extra origin allowed to POST, for a deployment behind a reverse proxy.
PUBLIC_ORIGIN = os.environ.get('MEDIA_POC_ORIGIN', '').rstrip('/')


JOB_TTL = 3600
ERRORS = (ValueError, KeyError, TypeError, OSError, binascii.Error, sqlite3.Error)


def database():
    db = connect()
    db.execute('CREATE TABLE IF NOT EXISTS watermarks (asset_id TEXT PRIMARY KEY, watermark_id TEXT NOT NULL, filename TEXT NOT NULL)')
    return db


class Job:
    """One uploaded file being watermarked and registered in the background."""
    jobs, lock = {}, threading.Lock()
    runner = threading.Lock()  # One file at a time: each video already uses every core.

    def __init__(self, name):
        self.id, self.name, self.created = secrets.token_urlsafe(16), name, time.time()
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.state, self.stage, self.done, self.total = 'queued', 'Waiting for previous file', 0, None
        self.result = self.error = self.output = self.content_type = None
        with Job.lock:
            for old in [job for job in Job.jobs.values() if job.state in ('done', 'error') and time.time() - job.created > JOB_TTL]:
                old.discard()
            Job.jobs[self.id] = self

    def report(self, stage, done=0, total=None):
        self.stage, self.done, self.total = stage, done, total

    def status(self):
        return {'state': self.state, 'stage': self.stage, 'done': self.done, 'total': self.total, 'result': self.result, 'error': self.error}

    def discard(self):
        Job.jobs.pop(self.id, None)
        self.directory.cleanup()

    def run(self):
        with Job.runner:
            self.state = 'running'
            source, key = self.root / 'upload', self.root / 'key'
            try:
                self.report('Checking file')
                kind = media_kind(source)
                if kind == 'image':
                    with Image.open(source) as img:
                        if img.width * img.height < 768: raise ValueError('Image must have at least 768 pixels.')
                    self.report('Watermarking image')
                output = self.root / ('marked.mp4' if kind == 'video' else 'marked.png')
                # Fingerprinting only reads the source, so it overlaps with watermarking.
                with ThreadPoolExecutor(1) as side:
                    phash = side.submit(fingerprint, source, kind)
                    result = engine(kind).embed(source, output, key, **({'progress': self.report} if kind == 'video' else {}))
                    self.report('Registering fingerprint')
                    registered = register_asset(source, self.name, kind, phash.result())
                with database() as db:
                    db.execute('INSERT INTO watermarks VALUES (?, ?, ?)', (registered['asset_id'], result['watermark_id'], self.name))
                result.update(registered)
                self.output, self.content_type, self.result = output, 'video/mp4' if kind == 'video' else 'image/png', result
                self.report('Done'); self.state = 'done'
            except (*ERRORS, RuntimeError) as exc:
                self.error, self.state = str(exc) or 'Could not process the file.', 'error'
            finally:
                key.unlink(missing_ok=True); source.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path.startswith('/api/jobs/'):
            job_id, _, part = self.path[len('/api/jobs/'):].partition('/')
            job = Job.jobs.get(job_id)
            if not job or part not in ('', 'file'):
                return self.respond({'error': 'Job not found.'}, 404)
            if not part:
                return self.respond(job.status())
            if job.state != 'done':
                return self.respond({'error': 'File is not ready.'}, 409)
            try:
                self.respond_file(job.output, job.content_type)
            finally:
                with Job.lock: job.discard()
            return
        if self.path == '/api/config':
            return self.respond({'max_upload_mb': MAX_UPLOAD_MB})
        if self.path == '/api/database':
            with database() as db:
                rows = db.execute('SELECT a.id, a.creator, a.sha256, a.phash, a.created, a.kind, w.watermark_id, w.filename FROM assets a LEFT JOIN watermarks w ON a.id=w.asset_id ORDER BY a.created DESC').fetchall()
            return self.respond({'items': [dict(zip(('asset_id','name','sha256','phash','created','kind','watermark_id','filename'), row)) for row in rows]})
        if self.path not in files:
            self.send_error(404)
            return
        name, content_type = files[self.path]
        data = (WEB / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}', PUBLIC_ORIGIN} - {''}
        if origin and origin not in allowed:
            self.send_error(403); return
        # Raw bodies with custom headers force a CORS preflight, which cross-site pages cannot pass.
        if self.headers.get_content_type() != 'application/octet-stream':
            self.send_error(415); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > MAX_UPLOAD_MB * 1024 * 1024:
                self.close_connection = True
                raise ValueError(f'File is empty or too large (maximum {MAX_UPLOAD_MB} MB).')
            name = unquote(self.headers.get('X-File-Name', '')) or 'upload'
            key_bytes = base64.b64decode(self.headers.get('X-Media-Key', ''), validate=True)
            if self.path == '/api/jobs':
                job = Job(name)
                try:
                    self.receive(job.root / 'upload', length)
                    (job.root / 'key').write_bytes(key_bytes)
                except BaseException:
                    with Job.lock: job.discard()
                    raise
                threading.Thread(target=job.run, daemon=True).start()
                return self.respond({'job_id': job.id})
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source = root / 'upload'
                self.receive(source, length)
                if self.path == '/api/inspect':
                    with Image.open(source) as img:
                        return self.respond({'format': img.format, 'width': img.width, 'height': img.height, 'mode': img.mode, 'pixels': img.width * img.height})
                if self.path == '/api/compare':
                    key = root / 'key'; key.write_bytes(key_bytes)
                    try:
                        kind = media_kind(source)
                    except ValueError:
                        kind = None
                    # The fingerprint lookup and the watermark check both only read the file, so run them together.
                    with ThreadPoolExecutor(1) as side:
                        match = side.submit(verify_media, source, kind=kind)
                        try:
                            mark = engine(kind).verify(source, key) if kind else None
                        except ValueError:
                            mark = None
                        result = match.result()
                    if result.get('asset_id'):
                        with database() as db:
                            result['registered_at'] = db.execute('SELECT created FROM assets WHERE id = ?', (result['asset_id'],)).fetchone()[0]
                    result['watermark'] = mark or {'authenticated': False}
                    if mark and mark['authenticated']:
                        with database() as db:
                            row = db.execute('SELECT w.filename, a.created FROM watermarks w JOIN assets a ON a.id = w.asset_id WHERE w.watermark_id = ?', (mark['watermark_id'],)).fetchone()
                        mark['registered_as'], mark['registered_at'] = row if row else (None, None)
                    return self.respond(result)
                self.send_error(404)
        except ERRORS as exc:
            self.respond({'error': str(exc) or 'Could not process the file.'}, 400)

    def receive(self, path, length):
        with path.open('wb') as out:
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(CHUNK, remaining))
                if not chunk: raise ValueError('Upload was interrupted.')
                out.write(chunk); remaining -= len(chunk)

    def respond_file(self, path, content_type):
        self.send_response(200); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(path.stat().st_size))
        self.send_header('Cache-Control', 'no-store'); self.end_headers()
        with path.open('rb') as f:
            shutil.copyfileobj(f, self.wfile, CHUNK)

    def respond(self, result, status=200):
        body = json.dumps(result).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(body)


def main():
    port = int(os.environ.get('MEDIA_POC_PORT', '8765'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Listening on http://127.0.0.1:{port}' + (f' (public origin {PUBLIC_ORIGIN})' if PUBLIC_ORIGIN else '') + '. Press Ctrl+C to stop.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()
