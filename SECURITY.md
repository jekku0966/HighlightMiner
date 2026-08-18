# HighlightMiner security notes

HighlightMiner is a local-first desktop application. The Streamlit backend is bound to `127.0.0.1` and is not intended to be exposed to a LAN or the public internet.

## v0.2 development hardening

The v0.2 branches introduce guard rails around untrusted inputs and persistent state:

- Analysis, transcript, candidate, review, rerun, export history, and the active desktop settings profile are stored in a local SQLite database instead of scattered writable JSON state files.
- Source VODs and imported legacy analyses must reference regular local files. Automatic UNC/network-path access is rejected.
- Chat and settings JSON inputs have extension and size limits, and recursive chat JSON has a nesting limit.
- Standard faster-whisper model names are allowed by default. Arbitrary custom model repositories require explicit opt-in in the Settings UI or `allow_custom_whisper_model=true` in an imported profile.
- Recognition-model network downloads require an explicit local user decision. HighlightMiner checks configured local and cached models without networking before offering a download.
- Cached and manually selected recognition models load with local-files-only behavior. Manual model folders must contain the required CTranslate2 model/tokenizer files and cannot use network/UNC paths.
- Model-download permission is stored separately from ordinary importable/exportable settings, so importing a settings profile cannot grant network-download consent.
- Numeric settings and scoring weights are range-validated before a settings profile can be used for analysis.
- GitHub Actions dependencies are pinned to full commit SHAs and the workflow token is read-only.
- Windows builds validate the Python interpreter used by `.build-venv` instead of silently reusing an unreadable or unsupported environment.
- Portable CUDA packaging copies only an explicit CUDA 12 / cuDNN 9 DLL allowlist from `runtime\cuda`; arbitrary repository DLLs are not swept into packaged builds.
- Ordinary public Windows CI is validation-only and does not publish compiled release artifacts.
- Official release packaging generates a SHA-256 checksum and a provenance manifest for the Windows ZIP.

These measures reduce accidental damage and common local-app trust-boundary problems. They are not a sandbox. HighlightMiner invokes FFmpeg and native CUDA/CTranslate2 libraries, so only run binaries obtained from trusted sources.

## Source fingerprints and rerun identity

v0.2 recognizes the same VOD across analysis runs with a sampled SHA-256 fingerprint based on file size and content samples from the beginning, middle, and end of the file. This avoids hashing an entire potentially huge VOD every time it is selected and allows a byte-identical VOD to be recognized after a move/rename.

**The sampled fingerprint is an identity/deduplication mechanism, not a cryptographic integrity guarantee.** It should not be used to prove that an untrusted media file is authentic. Full SHA-256 remains the mechanism used for release/package integrity, and chat cache identity uses a full hash of the selected chat file.

A recognized source may update the stored current local path for its existing analysis runs. Source selection still passes through normal local-file validation before preview/export.

A deliberately skipped speech-recognition stage is stored as skipped and receives no normal reusable Whisper transcript signature. This avoids an empty no-transcription run shadowing an older valid cached transcript.

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

## Settings profiles and model access

Normal desktop settings are stored in `highlightminer.db`. `settings.json` remains a migration/interchange format rather than a secrets file.

- The first database settings load may import the trusted local/package `settings.json` so existing defaults and reaction phrases are retained.
- Explicit JSON imports pass through local-file, extension, size, model, and numeric validation before replacing the active profile.
- Custom Hugging Face Whisper repositories require an explicit advanced opt-in because selecting one can cause model/data downloads through the normal faster-whisper/Hugging Face stack after download permission is granted.
- Recognition-model download permission and the manually selected local model path are kept in separate SQLite model-access state and are not granted through imported JSON settings.
- Settings export rejects UNC/network destinations by default.

A fresh model-download policy is **Ask**. The desktop does not contact Hugging Face merely because the application starts. When a fresh transcript actually requires an uncached model, the user can explicitly allow the download, select a local model, or continue without speech recognition. A previously saved **Never download models** choice is honored without repeatedly prompting.

The CLI is non-interactive: an undecided missing model causes a clean refusal unless the user passes `--allow-model-download` or `--no-transcription`. The per-command download flag does not silently modify the saved desktop preference.

Neither SQLite settings nor exported JSON profiles are encrypted. Do not put credentials, API keys, tokens, or other secrets in them.

## Local data

`highlightminer.db` may contain:

- source VOD fingerprints, paths, and content/game labels;
- multiple analysis runs for the same VOD;
- ranked candidate timings, scores, feature snapshots, and signal-availability metadata;
- transcript text from analyzed VODs;
- Keep/Reject/Unreviewed decisions and edited clip timings;
- review-event history;
- exported clip paths and timestamps;
- the active application settings profile, including reaction phrases;
- recognition-model access preference and an optional local model path.

The database is SQLite, not encrypted. Anyone who can read the file can inspect it with SQLite tooling. Do not treat it as a secrets store.

## Local executable/DLL/model trust

HighlightMiner intentionally supports portable executables and DLLs, including FFmpeg and CUDA/cuDNN runtime files. In source mode, the preferred CUDA runtime location is `runtime\cuda`; packaged builds copy the allowlisted CUDA/cuDNN files beside `HighlightMiner.exe`. The older source-root CUDA layout remains a compatibility fallback but is not used as a packaging source.

Anyone who can replace trusted runtime files in the selected CUDA directory or packaged HighlightMiner folder may be able to cause arbitrary native code to run when HighlightMiner starts or invokes that component. Do not run HighlightMiner from a shared or world-writable directory. Obtain FFmpeg/CUDA runtime files from trusted sources and verify upstream checksums/signatures when available.

The same trust rule applies to a manually selected Whisper/CTranslate2 model folder. HighlightMiner validates the expected file structure and local path, but it does not cryptographically certify the origin or contents of an arbitrary user-supplied model. Use models obtained from sources you trust.

## Official binary provenance

Only Windows binaries manually attached by the maintainer to the public HighlightMiner **GitHub Releases** page are official project binaries. Public CI deliberately does not upload a downloadable EXE or ZIP.

HighlightMiner is open source, so third parties can compile the public source themselves. A third-party executable may be perfectly legitimate, but it is not an official HighlightMiner build and should not be assumed to match the maintainer's release inputs or runtime files.

Official Windows release assets include:

- `HighlightMiner-v<version>-windows-x64.zip`;
- `SHA256SUMS.txt`;
- `RELEASE_MANIFEST.json` containing the public source tag/commit and hashes of the bundled local FFmpeg/CUDA runtime inputs.

The manifest records what was bundled; it does not independently prove that a third-party runtime was trustworthy when originally downloaded.

## Network behavior

HighlightMiner does not require a recognition-model network request at application startup. When a fresh transcript requires a model that is not available locally, the desktop asks before permitting a faster-whisper/Hugging Face download. Cached/manual model discovery is performed with local-files-only behavior. If downloads are denied, HighlightMiner can continue mining with audio plus optional chat rather than silently contacting the network.

Other expected network activity includes external links deliberately opened by the user and normal system-managed Evergreen WebView2 update traffic. The local Streamlit/WebView2 connection remains on loopback.

## CI and release integrity

The public Windows workflow uses read-only repository permission, pins GitHub Actions to immutable commit SHAs, runs unit tests, smoke-tests frozen CTranslate2/faster-whisper and pywebview/WebView2 imports, smoke-tests the packaged Streamlit backend in server-only mode, verifies bundled user documentation, and asserts that ordinary CI did not create a release ZIP. CI process cleanup also guards failed process startup so cleanup cannot obscure the original failure.

Official release packaging is intentionally separate from ordinary public CI. The maintainer release process builds from an exact public tag, requires the tag and project version to match, stages the explicit trusted runtime allowlist, requires packaged `doctor` to pass, smoke-tests the frozen Streamlit backend, and generates the release ZIP, manifest, and checksums for manual upload to GitHub Releases.

A release SHA-256 protects against modification after publication only when the checksum itself is obtained from a trusted location. Runtime binaries copied into an official build are still trusted inputs and must be sourced/verified appropriately before packaging.

## Reporting a security issue

Please avoid posting exploit details publicly before the issue can be reviewed. Contact the repository maintainer through the GitHub repository/profile and provide the affected version, reproduction steps, and expected impact.
