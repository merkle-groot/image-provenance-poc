# Fingerprinting and Watermarking PoC

This repo tests two ways of tracing an image or video back to its source. The first is a registry: every file you process gets a perceptual fingerprint, so a copy that's been re-saved or lightly edited can still be matched to the original later. The second is a watermark hidden in the pixels, carrying a random identifier that only someone holding the key can read or forge.

You can drive it from the command line or from a small web interface. A hosted copy runs at https://verify.primemodulus.com behind a shared password.

## Setup

You need Python 3.11 or newer, plus ffmpeg built with libx264 if you want video. The hosted server runs Python 3.14 and ffmpeg 8.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Get ffmpeg with `brew install ffmpeg` on macOS or `apt install ffmpeg` on Ubuntu.

Data lives in `~/.media-poc` unless you set `MEDIA_POC_HOME`. You'll find a SQLite database there (`registry.sqlite3`) and a full copy of every registered file under `originals/<asset id>/`. Those copies are the real uploads, not thumbnails, so keep the directory private.

## Command line

The CLI decides by itself whether a file is an image or a video.

```sh
python -m media_poc register ./examples/mountain.png --creator alice
python -m media_poc verify ./examples/mountain.png

python -m media_poc keygen demo.key
python -m media_poc watermark ./examples/mountain.png ./examples/mountain-marked.png --key demo.key
python -m media_poc check-watermark ./examples/mountain-marked.png --key demo.key

python -m media_poc watermark ./clip.mov ./clip-marked.mp4 --key demo.key
```

`keygen` writes 32 random bytes and won't overwrite an existing file. `watermark` will overwrite its output, which must be `.png` for an image or `.mp4` for a video. It also reads its own output back before returning, and if the mark doesn't decode it deletes the file and exits with an error. Try `check-watermark` with a second key from `keygen wrong.key` and you should get `"authenticated": false`.

Every command prints JSON. `verify` reports one of these statuses:

- `CONTENT_MATCH_ONLY`, with the asset id and creator, when the closest registered file sits inside the threshold and clearly ahead of the runner-up
- `INCONCLUSIVE` when nothing is close enough, or two candidates are too close to call
- `UNSUPPORTED` for anything that isn't an image or video

`examples/` holds CC0 test images, and `examples/README.md` says where each one came from.

## Web interface

```sh
.venv/bin/python -m media_poc.web
```

Then open http://127.0.0.1:8765.

The first screen asks for a secret key. Your browser runs whatever you type through SHA-256 to get the 32-byte watermark key and keeps the result in localStorage. Each upload carries it in an `X-Media-Key` header; the server writes it to a temp file for the length of that job and deletes it afterwards.

The dashboard has four screens:

- **Process** accepts images and videos, or a whole folder. Each file gets registered and you get a watermarked copy back: PNG for images, H.264 MP4 for videos. "Download all" saves each file separately, and Chrome asks once whether the site may download several files.
- **Compare** gives two independent answers per file: does the fingerprint match anything in the registry, and is there a watermark made with your current key?
- **Database** lists every registered file with its hashes and watermark id.
- **Settings** changes the key. Files you've already marked still need the old one.

Processing runs as a background job, one file at a time, since a single video already keeps every core busy. The page polls for progress and shows a frame count for video. Finished files wait on the server for up to an hour and get deleted as soon as you download them.

| Variable | Default | Purpose |
|---|---|---|
| `MEDIA_POC_HOME` | `~/.media-poc` | Registry and copies of originals |
| `MEDIA_POC_PORT` | `8765` | Port the server binds on 127.0.0.1 |
| `MEDIA_POC_MAX_UPLOAD_MB` | `50` | Largest accepted upload |
| `MEDIA_POC_VIDEO_WORKERS` | CPU count | Threads used to mark video frames |
| `MEDIA_POC_ORIGIN` | unset | Public origin allowed to upload, such as `https://verify.primemodulus.com` |

The server never listens on anything but 127.0.0.1. A POST with an `Origin` header must come from localhost or from `MEDIA_POC_ORIGIN`. Uploads go up as raw `application/octet-stream` bodies with custom headers, which forces a CORS preflight that other sites can't pass. The app has no login of its own, so put an authenticating proxy in front before anyone else can reach it.

## Fingerprints

An image gets one 64-bit perceptual hash from `imagehash.phash`. A video gets one for each of roughly 16 evenly spaced frames. Comparison uses Hamming distance; for video, every query frame finds its nearest registered frame and the score is the median of those distances, which is why a trimmed clip can still match the full video. Videos only get compared with other videos.

A match needs a distance of 6 or less and a lead of at least 3 over the next closest file, and a distance of 0 always matches.

## Watermarks

Both schemes hide 256 bits: a random 128-bit identifier followed by a 128-bit HMAC-SHA256 tag computed over it. When checking, the tag must verify under your key, so a wrong key or a damaged mark gives you "not authenticated" instead of a bogus identifier.

**Images** (`experimental-keyed-lsb-v1`). The key selects 768 pixel positions by HMAC-based rejection sampling, and each of the 256 bits goes into the least significant bit of the blue channel at three of them; reading takes a majority vote. Images need at least 768 pixels.

**Videos** (`experimental-keyed-dct-video-v1`), adapted from [video-watermarking-poc](https://github.com/HARI-CODER/video-watermarking-poc) at commit `8ce9cb6`. A keyed ±1 pattern goes into 11 mid-frequency coefficients of every 8×8 DCT block in the luma channel, and colour is left alone. The embedder first measures how strongly the frame's own content already correlates with the pattern, then adds just enough to push each bit past a fixed strength. Clipping in bright or saturated areas eats into the mark, so it measures again and tops up, up to four rounds per frame. The checker reads every fourth frame and sums the correlations. If the tag fails, it retries with up to 12 of the least confident bits flipped.

The video mark survives trimming and the H.264 encode the tool itself does. Frames need even dimensions of at least 80×80, and audio gets re-encoded to AAC.

## Hosted deployment

The copy at https://verify.primemodulus.com runs on Ubuntu 26.04. The setup:

- **Caddy** handles TLS on port 443, the only public web port. It gets its Let's Encrypt certificate through the TLS-ALPN challenge, which works on 443 alone, so port 80 stays closed. It also adds HTTP basic auth with one shared account, a 51 MiB request limit, HSTS and a strict Content-Security-Policy. HTTP/3 is off because it needs UDP 443, and the firewall blocks that.
- **The app** runs under systemd as a system user with no login shell, bound to 127.0.0.1:8765. The unit makes the filesystem read-only apart from `/var/lib/media-poc` and caps memory at 3 GB.
- **ufw** blocks every incoming connection except SSH (rate limited) and 443. SSH takes keys only, for a single non-root account with sudo, and root login is disabled. Unattended security upgrades run daily.
- **DNS** is on Cloudflare with the proxy switched off (grey cloud). Leave it off: with the proxy on, Let's Encrypt can't reach Caddy and the certificate won't renew.

### First-time server setup

```sh
sudo apt install python3-venv ffmpeg ufw
sudo useradd --system --home-dir /var/lib/media-poc --create-home --shell /usr/sbin/nologin mediapoc
sudo mkdir /opt/media-poc
# copy the repo into /opt/media-poc (see "Updating" below), then:
sudo python3 -m venv /opt/media-poc/.venv
sudo /opt/media-poc/.venv/bin/pip install -r /opt/media-poc/requirements.txt

sudo ufw default deny incoming
sudo ufw limit 22/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Install Caddy from its [official apt repository](https://caddyserver.com/docs/install#debian-ubuntu-raspbian). Ubuntu's own package is 2.6 from 2022.

`/etc/systemd/system/media-poc.service`:

```ini
[Unit]
Description=Fingerprinting and Watermarking PoC
After=network.target

[Service]
User=mediapoc
WorkingDirectory=/opt/media-poc
Environment=MEDIA_POC_HOME=/var/lib/media-poc/data
Environment=MEDIA_POC_PORT=8765
Environment=MEDIA_POC_ORIGIN=https://verify.primemodulus.com
ExecStart=/opt/media-poc/.venv/bin/python -m media_poc.web
Restart=on-failure
MemoryMax=3G
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/media-poc
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
```

`/etc/caddy/Caddyfile` (generate the password hash with `caddy hash-password`):

```caddy
{
	auto_https disable_redirects
	servers {
		protocols h1 h2
	}
}

verify.primemodulus.com {
	tls {
		issuer acme {
			disable_http_challenge
		}
	}
	encode zstd gzip
	request_body {
		max_size 51MiB
	}
	basic_auth {
		admin <password hash>
	}
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
		Permissions-Policy "camera=(), microphone=(), geolocation=()"
		Content-Security-Policy "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
		-Server
	}
	reverse_proxy 127.0.0.1:8765
}
```

Then `sudo systemctl enable --now media-poc` and `sudo systemctl reload caddy`.

### Updating

```sh
git archive HEAD | ssh <user>@<host> 'rm -rf /tmp/release && mkdir /tmp/release && tar -x -C /tmp/release'
ssh <user>@<host> 'sudo rsync -a --delete --exclude .venv /tmp/release/ /opt/media-poc/ && sudo systemctl restart media-poc'
```

Re-run the `pip install` step if `requirements.txt` changed. A restart kills whatever job is running, so check first with `pgrep -u mediapoc ffmpeg`. If only files under `web/` changed you can skip the restart, because the server reads them fresh on every request.

Logs come from `journalctl -u media-poc` and `journalctl -u caddy`. If an upload fails with a JSON parse error in the browser, the app probably restarted mid-job; look for `oom-kill` in its journal.
