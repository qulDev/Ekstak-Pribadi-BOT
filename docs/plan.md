# Private extractor implementation plan

> For agentic workers: use executing-plans inline. Steps use checkbox syntax.

Goal: deliver a tested deployable package and guide the user through AlmaLinux setup.
Architecture: local Bot API + single Python polling bot; isolated extraction subprocess.
Tech stack: Docker Compose, Python 3.13, libarchive-c 5.3, libarchive system package.
Spec: docs/design.md

## Global constraints
- Archive cap 2,000,000,000 bytes; one private authorized owner only.
- 20 GB expanded output; 300 files; 3,000 entries; 10 GB reserve; one hour extraction.
- Runtime nonroot, no public ports, no privileged containers; .env not bundled.
- No SSH credential use; the user deploys using their current SSH session.

## Review focus
- Mixed separators, absolute paths, links, duplicate entries, archive bombs.
- Unsupported/encrypted/corrupt archives and failure cleanup.
- Unauthorized messages, replayed updates, restart during job, busy/cancel behavior.
- Shared-volume permissions and local file paths across the two containers.
- Wizard escaping/secret storage, API errors and upload ambiguity.

## Task 1: Safe streaming extractor
- [x] Write failing unittest tests for ZIP/TAR/7z content, traversal, links, actual-byte
  caps, entry caps, corrupt archives, and per-file splitting; run RED in container.
- [x] Implement extractor.py: safe_path(root, name), extract_archive(source, output,
  password=None, limits=Limits()), iter_send_files(path, scratch, limit, part_size).
- [x] Run real library tests GREEN.

## Task 2: Telegram loop and job lifecycle
- [x] Write failing tests using fake HTTP API and temporary volumes for owner check,
  input size, file-path bounds, busy/status/cancel, offset persistence and cleanup.
- [x] Implement bot.py with TelegramAPI.call(), Bot.handle(), Bot.work(), run().
- [x] Run tests GREEN; no real Telegram requests from test suite.

## Task 3: Deployment and verification
- [x] Add setup.py terminal wizard, Compose, Dockerfile, bootstrap.sh and README.
- [x] Validate wizard using mocked HTTP/input and real config file permissions;
  run shell syntax, Docker build, Compose rendering, nonroot and volume smoke checks.
- [x] Independent read-only whole-package review; fix important findings with tests.
- [x] Package without secrets; give user PowerShell copy command and VPS bootstrap.

## Progress
Initial directory empty and not a Git repository; no worktree/commits applicable.
User's 'sudah siap' continues the agreed bot setup, no new approval round needed.
Library docs unavailable in Context7; API signatures verified in official library source.

Task 1 complete: real extraction tests passed in Linux container, UID101, network none.
Task 2 complete: owner/limits/lifecycle/fake-HTTP tests passed; real Telegram unverified.
Task 3 review: independent reviewer reported three Important issues, no Critical/Minor.
Fixed upload URI (RED assertion → file:/// URI), /cancel and shutdown reference race
(RED AttributeError → captured local reference), splitting reserve (RED → block-level
free-space guard). Local Compose smoke found a YAML comma splitting tmpfs options;
daemon rejection reproduced then fixed with quoted mount; rerun passed.
Runtime smoke: API10.3 starts nonroot with read-only rootfs, both services UID101,
shared work readable by API, bot reaches API over container-only network (HTTP404).
Ruling: tests and Docker smoke cannot establish real Telegram/VPS behavior. Preserve
explicit live verification steps and wait for the user's deployment output.

Final verification: rebuilt ekstrak-pribadi:local and ran its bundled suite as UID101
with --network none: 28 tests passed. Compose config --quiet and bash -n passed.
All three review findings fixed RED→GREEN; no deferred minors. Packaging uses an
explicit allowlist; no .env, tokens, API hashes, SSH credentials or cache included.
Deployment and real Telegram authentication/2 GB transfer remain pending user run.
