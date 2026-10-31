"""Local registry and conservative image matching; no watermark claims are made."""
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
import imagehash

ROOT = Path(os.environ.get('MEDIA_POC_HOME', Path.home() / '.media-poc')).expanduser().resolve()


def connect():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(ROOT / 'registry.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, creator TEXT NOT NULL, original TEXT NOT NULL, sha256 TEXT NOT NULL, phash TEXT NOT NULL, created REAL NOT NULL)')
    return db


def register_asset(file, creator_id):
    source = Path(file)
    if not creator_id.strip():
        raise ValueError('Creator is required')
    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        fingerprint = str(imagehash.phash(image.convert('RGB')))
    asset_id = str(uuid.uuid4())
    destination = ROOT / 'originals' / asset_id / source.name
    destination.parent.mkdir(parents=True, mode=0o700)
    shutil.copyfile(source, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    with connect() as db:
        db.execute('INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?)', (asset_id, creator_id, str(destination), digest, fingerprint, time.time()))
    return {'asset_id': asset_id, 'creator': creator_id, 'sha256': digest}


def verify_media(file, threshold=6, margin=3):
    start = time.monotonic()
    try:
        with Image.open(file) as image:
            fingerprint = imagehash.phash(image.convert('RGB'))
    except (UnidentifiedImageError, OSError):
        return {'status': 'UNSUPPORTED', 'reason': 'Only images are currently supported.'}
    with connect() as db:
        rows = db.execute('SELECT id, creator, phash FROM assets').fetchall()
    matches = sorted(((int(fingerprint - imagehash.hex_to_hash(row[2])), row) for row in rows), key=lambda item: item[0])
    result = {'status': 'INCONCLUSIVE', 'elapsed_seconds': round(time.monotonic() - start, 3), 'threshold': threshold, 'threshold_calibrated': False, 'issued_copy': None}
    if matches:
        distance, row = matches[0]
        result['fingerprint'] = {'algorithm': 'imagehash phash', 'distance': distance, 'next_distance': matches[1][0] if len(matches) > 1 else None}
        if distance <= threshold and (len(matches) == 1 or matches[1][0] - distance >= margin):
            result.update(status='CONTENT_MATCH_ONLY', asset_id=row[0], creator=row[1])
    return result


def issue_copy(*args, **kwargs):
    raise NotImplementedError('Watermark engine is not integrated; no copy can be issued safely.')


def on_generation_complete(*args, **kwargs):
    raise NotImplementedError('Publication is blocked until watermarking and verification are implemented.')
