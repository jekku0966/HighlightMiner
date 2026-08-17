# HighlightMiner security notes

HighlightMiner is a local-first desktop application. The Streamlit backend is bound to `127.0.0.1` and is not intended to be exposed to a LAN or the public internet.

## v0.2 development hardening

The `v0.2-dev` branch introduces guard rails around untrusted inputs and persistent state:

- Analysis, transcript, candidate, review, rerun, export history, and the active desktop settings profile are stored in a local SQLite database instead of scattered writable JSON state files.
- Source VODs and imported legacy analyses must reference regular local files. Automatic UNC/network-path access is rejected.
- Chat and settings JSON inputs have extension and size limits, and recursive chat JSON has a nesting limit.
- Standard faster-whisper model names are allowed by default. Arbitrary custom model repositories require explicit opt-in in the Settings UI or `allow_custom_whisper_model=true` in an imported profile.
- Numeric settings and scoring weights are range-validated before a settings profile can be used for analysis.
- GitHub Actions dependencies are pinned to full commit SHAs and the workflow token is read-only.
- Release builds generate a SHA-256 checksum for the portable ZIP.

These measures reduce accidental damage and common local-app trust-boundary problems. They are not a sandbox. HighlightMiner invokes FFmpeg and native CUDA/CTranslate2 libraries, so only run binaries obtained from trusted sources.

## Source fingerprints and rerun identity

v0.2 recognizes the same VOD across analysis runs with a sampled SHA-256 fingerprint based on file size and content samples from the beginning, middle, and end of the file. This avoids hashing an entire potentially huge VOD every time it is selected and allows a byte-identical VOD to be recognized after a move/rename.

**The sampled fingerprint is an identity/deduplication mechanism, not a cryptographic integrity guarantee.** It should not be used to prove that an untrusted media file is authentic. Full SHA-256 remains the mechanism used for release/package integrity, and chat cache identity uses a full hash of the selected chat file.

A recognized source may update the stored current local path for its existing analysis runs. Source selection still passes through normal local-file validation before preview/export.

## Embedded desktop UI

On Windows, v0.2 hosts the Streamlit interface in a pywebview window using Microsoft Edge WebView2.

- Streamlit listens only on `127.0.0.1:8501`.
- Streamlit runs headlessly and does not launch a normal browser during the default desktop flow.
- pywebview is forced to its modern `edgechromium` / WebView2 backend; HighlightMiner does not silently fall back to legacy MSHTML.
- Normal external links are opened by the system browser rather than turning the embedded HighlightMiner window into a general-purpose browser.
- Closing the native window terminates the Streamlit child process.
- The in-app **Exit HighlightMiner** request closes both the native window and backend.

The embedded window does not make the Streamlit application safe to expose remotely. Do not bind it to `0.0.0.0`, a LAN address, or a public interface without authentication and a separate threat-model review.

### WebView2 Runtime

The desktop shell relies on the system Microsoft Edge WebView2 Runtime. `HighlightMiner.exe doctor` reports the detected runtime when present.

If WebView2 or the packaged pywebview backend cannot initialize, HighlightMiner displays a native Windows error rather than degrading to a legacy renderer. The explicit fallback is:

```text
HighlightMiner.exe ui --browser
```

## Settings profiles

Normal desktop settings are stored in `highlightminer.db`. `settings.json` remains a migration/interchange format rather than a secrets file.

- The first database settings load may import the trusted local/package `settings.json` so existing defaults and reaction phrases are retained.
- Explicit JSON imports pass through local-file, extension, size, model, and numeric validation before replacing the active profile.
- Custom Hugging Face Whisper repositories require an explicit advanced opt-in because selecting one can cause network access and model/data downloads through the normal faster-whisper/Hugging Face stack.
- Settings export rejects UNC/network destinations by default.

Neither SQLite settings nor exported JSON profiles are encrypted. Do not put credentials, API keys, tokens, or other secrets in them.

## Local data

`highlightminer.db` may contain:

- source VOD fingerprints, paths, and content/game labels;
- multiple analysis runs for the same VOD;
- ranked candidate timings, scores, and feature snapshots;
- transcript text from analyzed VODs;
- Keep/Reject/Unreviewed decisions and edited clip timings;
- review-event history;
- exported clip paths and timestamps;
- the active application settings profile, including reaction phrases and model preferences.

The database is SQLite, not encrypted. Anyone who can read the file can inspect it with SQLite tooling. Do not treat it as a secrets store.

## Local executable/DLL trust

HighlightMiner intentionally supports portable executables and DLLs beside the application, including FFmpeg and CUDA/cuDNN runtime files. Anyone who can replace trusted runtime files in the HighlightMiner folder may be able to cause arbitrary native code to run when HighlightMiner starts or invokes that component.

Do not run HighlightMiner from a shared or world-writable directory. Obtain FFmpeg/CUDA runtime files from trusted sources and verify release checksums where available.

## Network behavior

Expected network access includes the first-time faster-whisper model download through the Hugging Face ecosystem, external links deliberately opened by the user, and normal system-managed Evergreen WebView2 update traffic. The local Streamlit/WebView2 connection remains on loopback.

## CI and release integrity

The Windows build workflow uses read-only repository permission, pins GitHub Actions to immutable commit SHAs, runs unit tests, smoke-tests frozen CTranslate2/faster-whisper and pywebview/WebView2 imports, smoke-tests the packaged Streamlit backend in server-only mode, verifies bundled user documentation, and generates `SHA256SUMS.txt` for the release ZIP.

The release SHA-256 protects against modification after publication only when the checksum itself is obtained from a trusted location.

## Reporting a security issue

Please avoid posting exploit details publicly before the issue can be reviewed. Contact the repository maintainer through the GitHub repository/profile and provide the affected version, reproduction steps, and expected impact.
