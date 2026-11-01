"""Local registry and conservative image and video matching; no watermark claims are made."""
import hashlib
import json
import os
import shutil
import sqlite3
import statistics
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
    if 'kind' not in {row[1] for row in db.execute('PRAGMA table_info(assets)')}:
        db.execute("ALTER TABLE assets ADD COLUMN kind TEXT NOT NULL DEFAULT 'image'")
    return db


def media_kind(file):
    try:
        with Image.open(file) as image:
            image.verify()
        return 'image'
    except (UnidentifiedImageError, OSError):
        pass
    from .video import is_video
    if is_video(file):
        return 'video'
    raise ValueError('Unsupported file: expected an image or a video.')


def fingerprint(file, kind):
    """Image: one phash. Video: phashes of sampled frames, space-separated."""
    if kind == 'video':
        from .video import fingerprint as video_fingerprint
        return ' '.join(video_fingerprint(file))
    with Image.open(file) as image:
        return str(imagehash.phash(image.convert('RGB')))


def distance(query, registered):
    """Median over query frames of the closest registered frame, so clips of a video still match."""
    query = [imagehash.hex_to_hash(h) for h in query.split()]
    registered = [imagehash.hex_to_hash(h) for h in registered.split()]
    return int(statistics.median(min(q - r for r in registered) for q in query))


def register_asset(file, creator_id, kind=None, phash=None):
    source = Path(file)
    if not creator_id.strip():
        raise ValueError('Creator is required')
    kind = kind or media_kind(source)
    phash = phash or fingerprint(source, kind)
    asset_id = str(uuid.uuid4())
    destination = ROOT / 'originals' / asset_id / source.name
    destination.parent.mkdir(parents=True, mode=0o700)
    shutil.copyfile(source, destination)
    with destination.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    with connect() as db:
        db.execute('INSERT INTO assets (id, creator, original, sha256, phash, created, kind) VALUES (?, ?, ?, ?, ?, ?, ?)', (asset_id, creator_id, str(destination), digest, phash, time.time(), kind))
    return {'asset_id': asset_id, 'creator': creator_id, 'sha256': digest, 'kind': kind}


def verify_media(file, threshold=6, margin=3, kind=None):
    start = time.monotonic()
    try:
        kind = kind or media_kind(file)
        query = fingerprint(file, kind)
    except (ValueError, OSError):
        return {'status': 'UNSUPPORTED', 'reason': 'Only images and videos are supported.'}
    with connect() as db:
        rows = db.execute('SELECT id, creator, phash FROM assets WHERE kind = ?', (kind,)).fetchall()
    matches = sorted(((distance(query, row[2]), row) for row in rows), key=lambda item: item[0])
    algorithm = 'imagehash phash' + (' (sampled frames, median nearest)' if kind == 'video' else '')
    result = {'status': 'INCONCLUSIVE', 'kind': kind, 'elapsed_seconds': round(time.monotonic() - start, 3), 'threshold': threshold, 'threshold_calibrated': False, 'issued_copy': None}
    if matches:
        best, row = matches[0]
        result['fingerprint'] = {'algorithm': algorithm, 'distance': best, 'next_distance': matches[1][0] if len(matches) > 1 else None}
        if best == 0 or (best <= threshold and (len(matches) == 1 or matches[1][0] - best >= margin)):
            result.update(status='CONTENT_MATCH_ONLY', asset_id=row[0], creator=row[1])
    return result


def issue_copy(*args, **kwargs):
    raise NotImplementedError('Watermark engine is not integrated; no copy can be issued safely.')


def on_generation_complete(*args, **kwargs):
    raise NotImplementedError('Publication is blocked until watermarking and verification are implemented.')
