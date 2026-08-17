# HighlightMiner security notes

HighlightMiner is a local-first desktop application. The Streamlit backend is bound to `127.0.0.1` and is not intended to be exposed to a LAN or the public internet.

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

## Embedded desktop UI

On Windows, v0.2 hosts the Streamlit interface in a pywebview window using the Microsoft Edge WebView2 Runtime.

The security boundary remains deliberately narrow:

- Streamlit listens only on `127.0.0.1:8501`.
- Streamlit runs headlessly and does not launch a normal browser during the default desktop flow.
- pywebview is forced to its modern `edgechromium` / WebView2 backend; HighlightMiner does not silently fall back to legacy MSHTML.
- Normal external links are opened by the system browser rather than turning the embedded HighlightMiner window into a general-purpose browser.
- Closing the native window terminates the Streamlit child process.
- The existing in-app **Exit HighlightMiner** shutdown request also closes the native window and backend.

The embedded window does not make the Streamlit application safe to expose remotely. Do not change the server binding to `0.0.0.0`, a LAN address, or a public interface without adding authentication and performing a separate threat-model review.

### WebView2 Runtime

The desktop shell relies on the system Microsoft Edge WebView2 Runtime. `HighlightMiner.exe doctor` checks the runtime registration documented by Microsoft and reports the detected version when present.

If WebView2 or the packaged pywebview backend cannot initialize, HighlightMiner displays a native Windows error message rather than automatically degrading to a legacy renderer. The user may explicitly choose the system-browser fallback from a terminal with:

```text
HighlightMiner.exe ui --browser
```

## Local data

`highlightminer.db` may contain:

- source VOD paths and content/game labels;
- ranked candidate timings and scores;
- transcript text from analyzed VODs;
- Keep/Reject decisions and edited clip timings;
- exported clip paths and timestamps.

The database is SQLite, not encrypted. It is less casually editable than JSON, but anyone who can read the file can inspect it with SQLite tooling. Do not treat it as a secrets store.

## Local executable/DLL trust

HighlightMiner intentionally supports portable executables and DLLs beside the application, including FFmpeg and CUDA/cuDNN runtime files. Anyone who can replace trusted runtime files in the HighlightMiner folder may be able to cause arbitrary native code to run when HighlightMiner starts or invokes that component.

Do not run HighlightMiner from a shared or world-writable directory. Obtain FFmpeg/CUDA runtime files from trusted sources and verify release checksums where available.

## Network behavior

HighlightMiner's own application workflow is designed to remain local. Expected network access includes:

- the first-time faster-whisper model download performed through the Hugging Face ecosystem when the selected model is not already cached;
- external links that the user deliberately opens from documentation/UI content;
- normal update traffic performed by the system-managed Evergreen WebView2 Runtime, outside HighlightMiner itself.

The local Streamlit/WebView2 connection stays on loopback.

## CI and release integrity

The Windows build workflow:

- uses read-only repository contents permission;
- pins GitHub Actions to immutable commit SHAs;
- runs unit tests;
- smoke-tests the frozen CTranslate2/faster-whisper imports;
- smoke-tests frozen pywebview/WinForms/WebView2 backend imports;
- smoke-tests the packaged Streamlit backend in server-only mode;
- generates `SHA256SUMS.txt` for the release ZIP.

The SHA-256 checksum protects against accidental or malicious modification after publication only when the checksum itself is obtained from a trusted location.

## Reporting a security issue

Please avoid posting exploit details publicly before the issue can be reviewed. Contact the repository maintainer through the GitHub repository/profile and provide the affected version, reproduction steps, and expected impact.
