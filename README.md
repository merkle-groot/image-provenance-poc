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
