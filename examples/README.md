# Demo images

`mountain.png` and `shapes.png` are original illustrations generated for this project using Pillow, with no third-party image assets. They are dedicated to the public domain under CC0 1.0: https://creativecommons.org/publicdomain/zero/1.0/

`mountain-marked.png` was made from `mountain.png` with the experimental watermark. `demo.key` is a locally generated demonstration key, ignored by Git. It is only for demonstration and must not be used to protect real material. If it is absent, generate a new key and marked image:

```sh
.venv/bin/python -m media_poc keygen examples/demo.key
.venv/bin/python -m media_poc watermark examples/mountain.png examples/mountain-marked.png --key examples/demo.key
```

Verify and compare against the original:

```sh
.venv/bin/python -m media_poc check-watermark examples/mountain-marked.png --key examples/demo.key
.venv/bin/python -m media_poc check-watermark examples/mountain.png --key examples/demo.key
```

The marked PNG and key must be regenerated together. Keep a real key separate from any shared image. See the main README for limitations.

## Photograph from Wikimedia Commons

`landscape-photo.jpg` is [Random landscape photo I took](https://commons.wikimedia.org/wiki/File:Random_landscape_photo_I_took.jpg), by Philsacor, published under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). `landscape-photo-marked.png` is the watermarked PNG derived from that photograph using the local demo key. To recreate and check it:

```sh
.venv/bin/python -m media_poc watermark examples/landscape-photo.jpg examples/landscape-photo-marked.png --key examples/demo.key
.venv/bin/python -m media_poc check-watermark examples/landscape-photo-marked.png --key examples/demo.key
.venv/bin/python -m media_poc check-watermark examples/landscape-photo.jpg --key examples/demo.key
```
