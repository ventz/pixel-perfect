# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public GitHub issue.

Use [GitHub Security Advisories](https://github.com/ventz/pixel-perfect/security/advisories/new)
("Report a vulnerability") on this repository. We aim to acknowledge reports
within a few days.

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest release on the
`main` branch.

## Security model

Pixel-Perfect is an image-processing tool. Keep these properties in mind:

- **The web service has no authentication or authorization.** Anyone who can
  reach it can submit images for processing.
- **It is compute- and memory-intensive.** Image processing with NumPy, OpenCV,
  and scikit-learn can consume significant CPU/RAM.
- **It binds to `127.0.0.1` (localhost) by default**, which is the safe default
  for personal use.

**Do not expose the service directly to an untrusted network.** If you must,
put it behind a reverse proxy providing TLS, authentication, rate limiting, and
a request-size cap, and run it under resource limits (container/systemd) as a
non-root user. See [docs/how-to/self-host-securely.md](docs/how-to/self-host-securely.md).

## Built-in mitigations

- **Request size cap, enforced before parsing** — default 20 MB, configurable via
  `PIXELPERFECT_MAX_UPLOAD_MB`. A middleware rejects oversized bodies with `413`
  from `Content-Length` or while streaming, before multipart parsing spools
  anything to disk. The export JSON body is also bounded by field length limits.
- **Decompression-bomb guard** — decoded images are capped at ~4 megapixels
  (`pixelperfect.io.MAX_PIXELS`), and `PIL.Image.MAX_IMAGE_PIXELS` is set
  accordingly. Both the soft cap and Pillow's own bomb error return `413`.
- **Format allow-list** — only PNG, JPEG, WebP, GIF, BMP are decoded.
- **Bounded work per request** — forced grid sizes are capped at 512 cells per
  axis and to the image size, previews at 16 megapixels, and palette clustering
  pre-merges unique colors so its memory stays bounded.
- **Bounded concurrency** — processing runs off the event loop, at most
  `PIXELPERFECT_MAX_JOBS` (default 2) at once; other requests wait.
- **Input validation** — bad parameters, including non-finite numbers, return
  `4xx`; unexpected errors return a generic `500` with no stack trace.
- **CORS is closed by default** — set `PIXELPERFECT_ALLOW_ORIGINS` to opt in.

## Known limitations

- There is no built-in rate limiting or request timeout; enforce these at a
  proxy for network deployments. Requests beyond `PIXELPERFECT_MAX_JOBS` queue
  rather than fail, so a flood still delays legitimate users.
