"""Experimental keyed DCT video watermark adapted from video-watermarking-poc.

Each video carries a random 128-bit identifier and a 128-bit HMAC tag, mirroring
the image watermark. Embedding cancels the host frame's correlation with the
keyed pattern so the identifier decodes reliably. Not robust against scaling,
cropping, heavy recompression, or deliberate attacks.
"""
import hashlib
import hmac
import os
import secrets
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

from .watermark import _key

DOMAIN = b'media-poc-video-watermark-v1'
SCHEME = 'experimental-keyed-dct-video-v1'
BITS = 256
POSITIONS = [(0,2),(0,3),(1,1),(1,2),(2,0),(2,1),(3,0),(0,4),(1,3),(2,2),(3,1)]
ROWS, COLS = np.array(POSITIONS).T
ALPHA = 8.0
EMBED_PASSES = 4
FINGERPRINT_FRAMES = 16
CHECK_STRIDE = 4
REPAIR_BITS = 12
# Frames are marked independently; NumPy matmul and OpenCV release the GIL, so threads scale.
WORKERS = max(1, int(os.environ.get('MEDIA_POC_VIDEO_WORKERS', os.cpu_count() or 1)))
_n = np.arange(8)
DCT = (np.sqrt(np.where(_n[:, None] == 0, 1 / 8, 2 / 8)) * np.cos(np.pi * (2 * _n[None, :] + 1) * _n[:, None] / 16)).astype(np.float32)


def _pattern(key, count):
    derive = lambda label: hmac.new(key, label, hashlib.sha256).digest()
    encryptor = Cipher(algorithms.ChaCha20(derive(b'video-dct-key'), derive(b'video-dct-nonce')[:16]), mode=None).encryptor()
    return (np.frombuffer(encryptor.update(bytes(count)), dtype=np.uint8) % 2).astype(np.float32) * 2 - 1


def _dct(luma):
    """8×8 block DCT as two large matrix products; coefficients are laid out (row block, k, column block, l)."""
    bh = luma.shape[0] // 8
    return ((DCT @ luma.reshape(bh, 8, -1)).reshape(-1, 8) @ DCT.T).reshape(bh, 8, -1, 8)


def _idct(coeffs):
    bh = coeffs.shape[0]
    return (DCT.T @ (coeffs.reshape(-1, 8) @ DCT).reshape(bh, 8, -1)).reshape(bh * 8, -1)


def _layout(key, height, width):
    """Keyed ±1 pattern shaped (row block, column block, position); coefficient n carries bit n % BITS."""
    bh, bw = -(-height // 8), -(-width // 8)
    count = bh * bw * len(POSITIONS)
    if count < BITS * 4:
        raise ValueError('Video frames must be at least 80 × 80 pixels.')
    padded = -(-count // BITS) * BITS
    return _pattern(key, count).reshape(bh, bw, len(POSITIONS)), np.bincount(np.arange(count) % BITS, minlength=BITS), padded


def _luma(frame):
    ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    h, w = ycc.shape[:2]
    return ycc, np.pad(ycc[:, :, 0].astype(np.float32), ((0, -h % 8), (0, -w % 8)), mode='edge')


# Strided slices and reshaped sums instead of fancy indexing and bincount: these release
# the GIL, so frames marked on different threads actually run in parallel.
def _correlation(coeffs, layout):
    pattern, counts, padded = layout
    observed = np.zeros(padded, dtype=np.float32)
    view = observed[:pattern.size].reshape(pattern.shape)
    for p, (row, col) in enumerate(POSITIONS):
        np.multiply(coeffs[:, row, :, col], pattern[:, :, p], out=view[:, :, p])
    return observed.reshape(-1, BITS).sum(axis=0, dtype=np.float64) / counts


def _add_bits(coeffs, layout, values):
    """Add values[bit] × pattern to every coefficient carrying that bit."""
    pattern, _, padded = layout
    spread = np.empty(padded, dtype=np.float32)
    spread.reshape(-1, BITS)[:] = values
    spread = spread[:pattern.size].reshape(pattern.shape)
    np.multiply(spread, pattern, out=spread)
    for p, (row, col) in enumerate(POSITIONS):
        target = coeffs[:, row, :, col]
        np.add(target, spread[:, :, p], out=target)


def _mark_frame(frame, layout, signs):
    ycc, luma = _luma(frame)
    coeffs = _dct(luma)
    # Raise each bit's mean correlation to at least ±ALPHA, cancelling host interference.
    # Clipping saturated pixels and colours erodes the mark, so re-measure the
    # actual output frame and top up a few times. Only luma changes; chroma stays 8-bit.
    h, w = ycc.shape[:2]
    output = frame
    for _ in range(EMBED_PASSES):
        shortfall = np.maximum(ALPHA - _correlation(coeffs, layout) * signs, 0) * signs
        if not shortfall.any():
            break
        _add_bits(coeffs, layout, shortfall)
        luma = _idct(coeffs)
        ycc[:, :, 0] = np.clip(luma[:h, :w] + 0.5, 0, 255)  # rounds on the uint8 cast
        output = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
        luma[:h, :w] = cv2.cvtColor(output, cv2.COLOR_BGR2YCrCb)[:, :, 0]
        coeffs = _dct(luma)
    return output


def _open(source):
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError('Could not open this video.')
    return cap


def is_video(source):
    cap = cv2.VideoCapture(str(source))
    try:
        return cap.isOpened() and cap.read()[0]
    finally:
        cap.release()


def fingerprint(source):
    """Perceptual hashes of up to FINGERPRINT_FRAMES evenly spaced frames."""
    cap = _open(source)
    step = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) // FINGERPRINT_FRAMES)
    hashes, index = [], 0
    try:
        while len(hashes) < FINGERPRINT_FRAMES * 2:
            ok, frame = cap.read()
            if not ok: break
            if index % step == 0:
                hashes.append(str(imagehash.phash(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))))
            index += 1
    finally:
        cap.release()
    if not hashes:
        raise ValueError('Video contains no readable frames.')
    return hashes


def _frame_total(cap):
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    return total if total > 0 else None


def embed(source, output, key_path, progress=None):
    """progress, if given, is called as progress(stage, done, total); total may be None."""
    if Path(output).suffix.lower() != '.mp4':
        raise ValueError('Output must be MP4')
    if Path(source).resolve() == Path(output).resolve():
        raise ValueError('Output must differ from source')
    key = _key(key_path)
    payload = secrets.token_bytes(16)
    tag = hmac.digest(key, DOMAIN + payload, 'sha256')[:16]
    signs = np.unpackbits(np.frombuffer(payload + tag, dtype=np.uint8)).astype(np.float32) * 2 - 1
    cap = _open(source)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not fps or not width or not height or width % 2 or height % 2:
        cap.release()
        raise ValueError('Video needs a valid frame rate and even frame dimensions.')
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0', '-i', str(source), '-map', '0:v:0', '-map', '1:a?', '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(output)]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        cap.release()
        raise ValueError('FFmpeg is required to watermark videos.') from None
    layout = _layout(key, height, width)
    count, pending, total = 0, deque(), _frame_total(cap)
    try:
        with ThreadPoolExecutor(WORKERS) as pool:
            # Keep a bounded window of frames in flight and write them back in order.
            while True:
                ok, frame = cap.read()
                if ok:
                    pending.append(pool.submit(_mark_frame, frame, layout, signs))
                while pending and (not ok or len(pending) >= WORKERS * 2):
                    proc.stdin.write(pending.popleft().result().tobytes())
                    count += 1
                    if progress: progress('Watermarking frames', count, total)
                if not ok: break
        proc.stdin.close()
        if progress: progress('Encoding video', 0, None)
        error = proc.stderr.read().decode(errors='replace')
        if proc.wait() or not count:
            raise ValueError('Video encoding failed: ' + (error.strip() or 'no frames'))
    except Exception:
        proc.kill()
        proc.wait()
        Path(output).unlink(missing_ok=True)
        raise
    finally:
        cap.release()
    result = verify(output, key_path, progress)
    if not result['authenticated'] or result['watermark_id'] != payload.hex():
        Path(output).unlink(missing_ok=True)
        raise RuntimeError('Watermark verification failed; output removed')
    result['frames'] = count
    return result


def verify(source, key_path, progress=None):
    key = _key(key_path)
    cap = _open(source)
    total, layout, sampled, index, frames = np.zeros(BITS), None, 0, 0, _frame_total(cap)
    try:
        while True:
            ok, frame = cap.read()
            if not ok: break
            if index % CHECK_STRIDE == 0:
                if layout is None:
                    layout = _layout(key, *frame.shape[:2])
                total += _correlation(_dct(_luma(frame)[1]), layout)
                sampled += 1
            index += 1
            if progress: progress('Verifying watermark', index, frames)
    finally:
        cap.release()
    if not sampled:
        raise ValueError('Video contains no readable frames.')
    bits = (total > 0).astype(np.uint8)
    # The tag doubles as an error check: retry with the least confident bits flipped.
    weakest = np.argsort(np.abs(total))[:REPAIR_BITS]
    for flips in range(1 << REPAIR_BITS):
        candidate = bits.copy()
        candidate[weakest] ^= ((flips >> np.arange(REPAIR_BITS)) & 1).astype(np.uint8)
        decoded = np.packbits(candidate).tobytes()
        payload, tag = decoded[:16], decoded[16:]
        if hmac.compare_digest(tag, hmac.digest(key, DOMAIN + payload, 'sha256')[:16]):
            return {'authenticated': True, 'watermark_id': payload.hex(), 'scheme': SCHEME, 'frames_sampled': sampled, 'bits_corrected': int(flips).bit_count()}
    return {'authenticated': False, 'watermark_id': None, 'scheme': SCHEME, 'frames_sampled': sampled}
