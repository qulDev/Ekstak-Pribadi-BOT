# Media preview — 2026-11-04

The user approved sending extracted photos/videos as native Telegram media and
other/unsupported files as documents, then explicitly requested implementation.

## Design

Use the existing Local Bot API and local file URI upload. Select a candidate by
case-insensitive extension: jpg/jpeg/png/webp -> sendPhoto; mp4/m4v/mov -> sendVideo.
Only nonempty photos <=10,000,000 bytes are candidates; videos must be nonempty.
Photo dimensions/ratio and actual video encoding are validated by Telegram.
On an explicit media rejection (API error400/413), fall back once to sendDocument.
Other errors, especially ambiguous transport failures, propagate without a fallback.
Keep captions, upload timeout, owner checks, counters and cleanup. Binary split
parts are documents. Media sending may result in Telegram processing photos;
no byte-for-byte photo preservation or universal preview/thumbnail guarantee.

Approaches: native media with document fallback is selected. Automatic conversion,
thumbnail generation and media probing add dependencies and alter archived content;
they are deferred. No albums or new commands are needed for this change.

## Implementation plan

- [x] RED tests for photo/video selection, case/size boundaries, split/document
  paths, explicit rejection fallback, no duplicate-risk retries, and mixed job.
- [x] Implement Bot.send_file(path: Path, caption: str), replacing the single
  sendDocument call in Bot.work. No additional dependencies or external processes.
- [x] GREEN full test suite and Docker build, update README and verification.
- [x] Independent read-only review; fix material issues with regression tests.
- [x] Commit and update the existing Git remote; no VPS access.

Review focus: URI encoding for special characters; file-size boundaries; no media
attempt on split parts; no fallback after ambiguous upload failure; same caption,
counter and cleanup when falling back. Local routing tests cannot establish actual
Telegram previews; that remains a live verification step.

Sources: https://core.telegram.org/bots/api#sendphoto and
https://core.telegram.org/bots/api#sendvideo. Existing pinned server is Bot API10.3.

Evidence: new tests first failed because send_file was missing and the mixed
archive used three document sends. After implementation, all 38 tests passed.
Independent read-only review found no Critical, Important or Minor issues.
No new dependencies, thumbnail generation, conversion or live credentials added.
Ruling: actual Telegram rendering/codecs/large uploads are not inferred from fake
API routing tests; README and verification.md retain explicit live-test limits.
