# Contributing to HighlightMiner

Thanks for helping make the VOD haystack smaller.

## Development setup

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

FFmpeg and ffprobe must be available on `PATH` for media integration work.

## Pull requests

Keep changes focused and explain:

1. what problem the change solves;
2. how it was tested;
3. whether it changes `analysis.json`, `review.json`, chat parsing, or settings compatibility;
4. whether any third-party code or algorithm was adapted.

Add or update tests when changing scoring/parsing behavior.

## Third-party code

Do not paste code from another project without checking its license.

If a contribution adapts third-party code:

- identify the exact repository/file/commit or documentation page;
- preserve required copyright/license notices;
- explain which HighlightMiner file contains the adaptation;
- update `ATTRIBUTIONS.md`.

API usage based on public documentation should also be documented when it is non-obvious.

## Generated files

Do not commit:

- `.venv/`
- `__pycache__/`
- VODs
- extracted WAVs
- generated analysis work folders
- exported clips
- downloaded model caches

## Design direction

Prefer a staged pipeline where cheap local signals narrow the search space before expensive models are considered. False positives are acceptable if review remains fast; silently missing great moments is worse.
