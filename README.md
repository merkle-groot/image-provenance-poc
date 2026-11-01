# Media provenance POC foundation

A local image registry with perceptual-hash matching and an experimental keyed watermark. Match thresholds are uncalibrated; matches do not establish ownership or recipient identity.

Use Python 3.11 or 3.12:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m media_poc register ./examples/mountain.png --creator alice
python -m media_poc verify ./examples/mountain.png
```

Data defaults to `~/.media-poc`; set `MEDIA_POC_HOME` to change it. Originals and the SQLite registry are local and should be kept private.

## Private-key watermark demonstration

This experimental image-only watermark embeds an authenticated identifier in PNG pixel data. It is not security audited or resistant to JPEG compression, resizing, cropping, copying, or deliberate attacks. Keep the key private: anyone with it can create marks. Watermarking and fingerprint matching are independent.

```sh
python -m media_poc keygen demo.key
python -m media_poc watermark ./examples/mountain.png ./examples/mountain-marked.png --key ./demo.key
python -m media_poc check-watermark ./examples/mountain-marked.png --key ./demo.key
python -m media_poc keygen wrong.key
python -m media_poc check-watermark ./examples/mountain-marked.png --key wrong.key
```

The watermark command requires both an input file and an output file. It overwrites an existing output file. Use an image with at least 768 pixels. The output must be PNG; preserve the file without resizing or recompression. Do not share the key with the image. A successful check confirms the embedded identifier's authentication, not identity or ownership.

## Local website

After installing the dependencies above, start the local interface:

```sh
./.venv/bin/python -m media_poc.web
```

Open http://127.0.0.1:8765. The server listens only on your device; images are processed locally. The fingerprint registry and copies of registered images are stored in `~/.media-poc` (or `MEDIA_POC_HOME`). Watermark images and keys are offered as downloads; keep the key private and save it to check the watermark later. Stop the server with Ctrl+C.

## Videos

Videos go through the same pipeline as images. On the website, Process accepts images and videos together: each video is fingerprinted, registered, and given a watermarked MP4 copy with its own authenticated identifier. Compare checks both fingerprint and watermark, and Database lists both media types. The CLI `register`, `verify`, `watermark`, and `check-watermark` commands detect videos automatically (video output must be `.mp4`):

```sh
python -m media_poc watermark ./clip.mov ./clip-marked.mp4 --key ./demo.key
python -m media_poc check-watermark ./clip-marked.mp4 --key ./demo.key
```

Install `ffmpeg` (with `libx264`) as well as the requirements. Uploads are capped at 50 MB (set `MEDIA_POC_MAX_UPLOAD_MB` to change it). Video frames are marked in parallel on all CPU cores (set `MEDIA_POC_VIDEO_WORKERS` to limit it). Videos need even frame dimensions of at least 80 × 80 pixels; audio is re-encoded to AAC and processing can take several minutes.

- **Fingerprint:** perceptual hashes of up to 16 evenly spaced frames. A query matches by the median distance from each of its frames to the nearest registered frame, so trimmed clips can still match. Videos are compared only with videos, and the threshold is uncalibrated.
- **Watermark:** a keyed spread-spectrum mark in mid-frequency DCT coefficients of the luma channel, adapted from [video-watermarking-poc](https://github.com/HARI-CODER/video-watermarking-poc) (commit `8ce9cb6`). Like the image mark, it carries a random 128-bit identifier and a 128-bit HMAC tag. Embedding cancels each frame's own interference with the keyed pattern. The detector may flip up to 12 low-confidence bits, keeping only results with a valid tag. In testing, it survived trimming and the website's own H.264 encoding. A further CRF 28 re-encode was survived by 720p and 640×360 camera-style footage but not by small (160×120) or saturated synthetic clips. It is not designed to survive scaling, cropping, or deliberate removal.

It does not include VideoSeal, AudioSeal, or the generation-time model. Videos marked by the earlier standalone Video watermark screen are not recognised by this scheme. A positive or negative result does not prove ownership or the absence of a watermark.
