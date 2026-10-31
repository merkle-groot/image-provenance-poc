"""Experimental keyed, authenticated LSB watermark for lossless PNG images.

Not robust against recompression, resizing, cropping, or deliberate attacks.
"""
import hashlib
import hmac
import secrets
from pathlib import Path
from PIL import Image
import numpy as np

DOMAIN = b'media-poc-watermark-v1'
BITS = 256
REPETITIONS = 3


def generate_key(path):
    path = Path(path)
    with path.open('xb') as f:
        import os
        os.chmod(path, 0o600)
        f.write(secrets.token_bytes(32))


def _key(path):
    key = Path(path).read_bytes()
    if len(key) != 32:
        raise ValueError('Key must contain exactly 32 bytes')
    return key


def _positions(key, count):
    if count < BITS * REPETITIONS:
        raise ValueError('Image must have at least 768 pixels')
    # Keyed rejection sampling avoids relying on a non-cryptographic PRNG.
    positions, seen, counter = [], set(), 0
    limit = (1 << 64) - ((1 << 64) % count)
    while len(positions) < BITS * REPETITIONS:
        block = hmac.digest(key, DOMAIN + count.to_bytes(8, 'big') + counter.to_bytes(8, 'big'), 'sha256')
        counter += 1
        for offset in range(0, 32, 8):
            value = int.from_bytes(block[offset:offset+8], 'big')
            if value >= limit:
                continue
            position = value % count
            if position not in seen:
                seen.add(position)
                positions.append(position)
                if len(positions) == BITS * REPETITIONS:
                    break
    return positions


def embed(source, output, key_path):
    if Path(output).suffix.lower() != '.png':
        raise ValueError('Output must be PNG')
    if Path(source).resolve() == Path(output).resolve():
        raise ValueError('Output must differ from source')
    key = _key(key_path)
    with Image.open(source) as image:
        pixels = np.array(image.convert('RGB'), dtype=np.uint8)
    payload = secrets.token_bytes(16)
    tag = hmac.digest(key, DOMAIN + payload, 'sha256')[:16]
    bits = np.unpackbits(np.frombuffer(payload + tag, dtype=np.uint8))
    blue = pixels[:, :, 2].copy().reshape(-1)
    positions = _positions(key, blue.size)
    for i, position in enumerate(positions):
        blue[position] = (int(blue[position]) & 254) | int(bits[i % BITS])
    pixels[:, :, 2] = blue.reshape(pixels.shape[:2])
    Image.fromarray(pixels).save(output, format='PNG')
    result = verify(output, key_path)
    if not result['authenticated'] or result['watermark_id'] != payload.hex():
        Path(output).unlink(missing_ok=True)
        raise RuntimeError('Watermark verification failed; output removed')
    return result


def verify(source, key_path):
    key = _key(key_path)
    with Image.open(source) as image:
        blue = np.asarray(image.convert('RGB'))[:, :, 2].reshape(-1)
    positions = _positions(key, blue.size)
    bits = np.array([int(blue[p]) & 1 for p in positions], dtype=np.uint8).reshape(REPETITIONS, BITS)
    decoded = np.packbits((bits.sum(axis=0) >= 2).astype(np.uint8)).tobytes()
    payload, tag = decoded[:16], decoded[16:]
    authenticated = hmac.compare_digest(tag, hmac.digest(key, DOMAIN + payload, 'sha256')[:16])
    return {'authenticated': authenticated, 'watermark_id': payload.hex() if authenticated else None, 'scheme': 'experimental-keyed-lsb-v1'}
