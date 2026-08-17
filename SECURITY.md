# HighlightMiner security notes

HighlightMiner is a local-first desktop-style application. The Streamlit UI is bound to `127.0.0.1` and is not intended to be exposed to a LAN or the public internet.

## v0.2 development hardening

The `v0.2-dev` branch introduces several guard rails around untrusted inputs and persistent state:

- Analysis, transcript, candidate, review, and export history is stored in a local SQLite database instead of writable JSON state files.
- Source VODs and imported legacy analyses must reference regular local files. Automatic UNC/network-path access is rejected.
- Chat and settings inputs have extension and size limits, and recursive chat JSON has a nesting limit.
- Standard faster-whisper model names are allowed by default. Arbitrary custom model repositories require the explicit `allow_custom_whisper_model=true` setting.
- Numeric settings and scoring weights are range-validated before analysis begins.
- GitHub Actions dependencies are pinned to full commit SHAs and the workflow token is read-only.
- Release builds generate a SHA-256 checksum for the portable ZIP.

These measures reduce accidental damage and common local-app trust-boundary problems. They are not a sandbox. HighlightMiner invokes FFmpeg and native CUDA/CTranslate2 libraries, so only run binaries obtained from trusted sources.

## Local data

`highlightminer.db` may contain:

- source VOD paths and content/game labels;
- ranked candidate timings and scores;
- transcript text around the analyzed VOD;
- Keep/Reject decisions and edited clip timings;
- exported clip paths and timestamps.

The database is SQLite, not encrypted. It is less casually editable than JSON, but anyone who can read the file can inspect it with SQLite tooling. Do not treat it as a secrets store.

## Network behavior

HighlightMiner itself is designed to work locally. The main expected network access is the first-time faster-whisper model download performed by the Hugging Face ecosystem when the selected model is not already cached.

The packaged Streamlit server must remain loopback-only (`127.0.0.1:8501`). Do not deliberately reconfigure it for public exposure without adding authentication and a separate threat-model review.

## Reporting a security issue

Please avoid posting exploit details publicly before the issue can be reviewed. Contact the repository maintainer through the GitHub repository/profile and provide the affected version, reproduction steps, and expected impact.
