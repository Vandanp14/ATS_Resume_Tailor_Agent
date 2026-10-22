"""Check which Gemini models the configured API key can call.

Spends about ten requests of the key's free-tier quota. Run from the repo root:

    .venv/bin/python scripts/probe_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from prompt import GEMINI_API_KEY  # noqa: E402

CANDIDATES = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
)


def main() -> int:
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set in .env")
        return 1
    # A busy model can hang for minutes; give each request a minute at most.
    client = genai.Client(
        api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=60_000)
    )
    gemma = [
        model.name for model in client.models.list() if "gemma" in (model.name or "")
    ]
    print("gemma models listed:", ", ".join(gemma) or "none", flush=True)
    config = types.GenerateContentConfig(max_output_tokens=5)
    for model in CANDIDATES:
        try:
            client.models.generate_content(
                model=model, contents="Reply with OK.", config=config
            )
            print(f"{model}: OK", flush=True)
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            code = getattr(exc, "code", None) or type(exc).__name__
            print(f"{model}: {code} {str(exc)[:80]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
