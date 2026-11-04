# Local verification — 2026-11-04

- Docker build: successful on Docker Desktop Linux engine 29.5.3.
- Bundled tests: `docker run --rm --network none ekstrak-pribadi:local python -m unittest discover -s tests -q`: **28 passed**.
- Real ZIP, TAR.GZ and 7z extraction tested; fake headers verify streamed byte cap.
- Real files test traversal/link/duplicate protections and lossless splitting.
- Owner-only, busy/cancel/status, worker cleanup and restart state tested.
- HTTP fake server tests form encoding and secret-safe API errors.
- Wizard tests one-time private enrollment, secret-free stdout, configuration mode600.
- Compose rendering and bootstrap bash syntax passed.
- Runtime smoke: API10.3 up, UID101, read-only rootfs; bot UID101 writes work volume,
  API UID101 reads it; bot reaches API TCP8081 with HTTP404 on root route; no published ports.
- Independent review: three Important issues corrected with regression tests; no Critical or deferred Minor findings.

Limits: no real Telegram secrets used; no SSH session opened by the agent. Live
AlmaLinux package installation, SELinux, registration/migration, exact cache paths,
RAR/encryption variants, and 2 GB transfers still need live verification. Local
success is not deployment success.
