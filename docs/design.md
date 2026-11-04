# Bot ekstrak pribadi

Scope approved in chat: private Telegram bot on AlmaLinux 10.2; single archives
up to 2,000,000,000 bytes, extracted contents returned as documents.

Update: the user subsequently requested native photo/video preview. Eligible files
now use sendPhoto/sendVideo, with document fallback; see media-preview.md for the
current media policy and limits. Split parts remain documents.

Update: password-protected archives now use an interactive retry/cancel dialog.
Encrypted 7z AES uses py7zr with validated writers; see password-dialog.md for the
current behavior. The caption-only/encrypted-7z limitations below describe the
initial design and are superseded by that update.

Approaches: public Bot API cannot download these archives (20 MB download limit).
A local Bot API service supports the requested size. Multipart input/link import
was considered for 5 GB and is unnecessary after the user's 2 GB decision.

Implementation choices: Docker Compose; pinned aiogram image packaging the official
Telegram Bot API; a Python bot using urllib and libarchive-c. No web UI, database,
public service ports or Docker socket. Two nonprivileged runtime processes share
file volumes. Secrets are entered with a terminal wizard on the VPS, never in chat.
Owner enrollment requires a random one-time phrase in a private message to the bot.

Defaults decided by implementer: one active job, 300 regular files, 3,000 entries,
20,000,000,000 expanded bytes, 10 GB free reserve, one hour extraction deadline.
Only regular files/directories are accepted; no links, devices or traversal paths.
Extraction writes streamed blocks, enforcing both declared and actual byte limits.
Files above 2,000,000,000 bytes are returned as binary parts of 1,900,000,000 bytes.
Nested archives are returned without recursive extraction. Basic encrypted formats
supported by libarchive use caption `password: ...`; encrypted 7z/RAR variants not
supported by libarchive return an explicit error. No support claim for every format.

Job output and its downloaded document are cleaned on completion/failure/cancel;
startup cleans abandoned job folders and stale documents, never API databases.
Original messages in Telegram are retained. A restart does not resume jobs and
notifies the owner to resend. Updates accepted before a restart are not replayed.
Status/cancel remain responsive; cancellation during a Telegram transfer waits for
that request to return. No unbounded network retries, no secret-bearing URLs logged.

Local validation: real container extraction/security tests, fake HTTP Bot API tests,
Compose checks, build and wizard smoke tests. Real VPS deployment/Telegram large-file
round trip require user's secrets and interaction; local checks cannot establish them.
