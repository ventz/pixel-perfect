# Self-host the web app securely

The web service is **unauthenticated and compute-intensive**. It is safe to run
locally as-is, but exposing it to a network requires hardening. This guide
covers a safe deployment.

> See also [SECURITY.md](../../SECURITY.md) for the security model and reporting.

## Default: localhost only (safe)

```bash
uv run app.py
```

Binds `127.0.0.1:8000` — reachable only from the same machine. Nothing else to
do for personal use.

## Exposing to a network

Do **not** simply bind to all interfaces. Put a reverse proxy in front that adds
TLS, authentication, rate limiting, and a body-size cap. Bind the app to
localhost and let the proxy face the network.

```bash
# app stays on localhost; proxy talks to it
uv run app.py --port 8000
```

### nginx example

```nginx
server {
    listen 443 ssl;
    server_name pixelperfect.example.com;
    # ssl_certificate / ssl_certificate_key ...

    client_max_body_size 20m;              # match the app's upload cap

    limit_req_zone $binary_remote_addr zone=pp:10m rate=5r/s;

    location / {
        auth_basic "Pixel-Perfect";
        auth_basic_user_file /etc/nginx/.htpasswd;
        limit_req zone=pp burst=10 nodelay;
        proxy_pass http://127.0.0.1:8000;
    }
}
```

## Built-in limits you can tune

| Variable | Default | Purpose |
|----------|---------|---------|
| `PIXELPERFECT_MAX_UPLOAD_MB` | `20` | Reject larger requests (413), before the body is parsed. |
| `PIXELPERFECT_MAX_JOBS` | `2` | Image-processing jobs allowed to run at once; extra requests queue. |
| `PIXELPERFECT_ALLOW_ORIGINS` | _(none)_ | CORS allow-list; leave empty for same-origin only. |

Decoded images are also capped at ~4 megapixels in `pixelperfect.io` to defuse
decompression bombs, forced grid sizes at 512 cells per axis, and previews at
16 megapixels.

## Run with resource limits

Because image processing is CPU/RAM heavy, run under a container or systemd unit
with limits and as a non-root user:

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  --memory=1g --cpus=2 --user 1000:1000 \
  -e PIXELPERFECT_MAX_UPLOAD_MB=10 \
  your-image uv run app.py --host 0.0.0.0
```

(`--host 0.0.0.0` is fine *inside* the container since the published port is
bound to `127.0.0.1` on the host and the proxy fronts it.)

## Limit concurrency

The app runs at most `PIXELPERFECT_MAX_JOBS` restores at once (default 2) and
queues the rest. Set it to roughly the CPU cores you want to dedicate. Queued
requests still hold connections, so also cap connections at the proxy or with
uvicorn's `--limit-concurrency`:

```bash
PIXELPERFECT_MAX_JOBS=2 uv run uvicorn pixelperfect.web.api:app \
  --host 127.0.0.1 --limit-concurrency 8
```
