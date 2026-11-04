# Interactive archive passwords — 2026-11-04

User-reported failure: a protected7z ends immediately with a generic extraction
error. Requested behavior: ask for password in private chat, accept it, retry on
wrong password, allow /cancel. No re-upload should be needed for retries.

Approach: retain the streamed libarchive extractor for existing formats. Add
py7zr1.1.4 for encrypted7z, because libarchive does not decrypt7z AES. Use a custom
writer with path/type/count/actual-byte/disk validation; never unrestricted extractall
to the host filesystem. Passwords go to the existing subprocess through stdin,
not logs, process arguments, state files or environment.

Session: same owner/private-chat guard as all commands. A job remains active while
waiting, accepts one plain text password per prompt, preserves exact message text,
and clears password references after use. /status and /cancel stay available.
Idle password wait expires after10minutes. No automatic resume after restart.
Retry uses the same downloaded archive, clears partial output, and sends files
only after successful full extraction. Caption passwords remain optional.

Differentiate password-needed/wrong-password from unsupported/corrupt/unsafe
archives. Encrypted corruption can resemble a wrong password and may retry;
unsupported encryption must not be claimed fixed. RAR remains library-dependent.

Plan:
- [x] RED real protected7z tests (header encryption on/off, correct/wrong/missing
  password) and security/limits; encryptedZIP regression where available.
- [x] Implement classified password exit status2 plus safe7z backend.
- [x] RED dialog tests (owner, retry, no download repetition, cleanup, timeout,
  cancellation, plain text exactness, unrelated messages).
- [x] Implement wait/retry state and update README.
- [x] Build, full suite, independent review, fixes if needed, commit.
- [ ] Push to GitHub: currently rejected by the remote with Internal Server Error.
- [x] Prepare a verified Git bundle for an existing-VPS update without GitHub;
  live user archive remains unverified.

No cache-cleanup redesign or unrelated installer changes in this password fix.

Evidence: missing-backend tests first failed on absent PasswordNeeded; dialog test
first failed because the bot ended instead of waiting. Real AES7z(header on/off),
ZIP ZipCrypto/AES, security and dialog tests then passed. Final source suite57/57.
Reviewer found wrong-password codec errors for DEFLATE/BZIP2/ZSTD/BROTLI and plain
corrupt7z+caption misclassification. Both reproduced RED, corrected, GREEN.
Ruling: the caption/plain-corruption finding is material to the user's requested
password dialog, despite being labelled Minor; fix false password prompts by
probing actual encryption without the supplied password. No minors deferred.
Ruling: encrypted corruption may resemble a wrong password. Keep retry/cancel and
timeout, document uncertainty, never claim the password is certainly incorrect.
The user's actual archive and updated deployment remain unverified.
