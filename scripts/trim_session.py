#!/usr/bin/env python3
"""Trim an exported browser session down to the cookies LinkedIn actually needs.

A session exported from a normal browser is not just LinkedIn. It can also carry
signed-in Google cookies, Indeed cookies and a pile of advertising/analytics
identifiers.  None of that is needed to schedule a LinkedIn post, and all of it
widens the blast radius if the secret ever leaks.

So: keep the LinkedIn domains (plus LinkedIn's bot-protection vendor), drop
everything else.

Usage:
    python3 scripts/trim_session.py browser_profile/storage.json
    python3 scripts/trim_session.py browser_profile/storage.json --out trimmed.json

Writes <input>.trimmed by default.  Prints counts only, never cookie names or
values.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# A cookie domain or origin is kept when it contains one of these.
# "linkedin" covers .linkedin.com, .www.linkedin.com and linkedin-ei.com.
# "protechts" is LinkedIn's bot-protection vendor; dropping it can make the
# posting flow more likely to hit a challenge, so it stays.
KEEP_SUBSTRINGS = ("linkedin", "protechts")


def should_keep(value: str) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in KEEP_SUBSTRINGS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session", help="path to the exported storage.json")
    parser.add_argument(
        "--out",
        default=None,
        help="output path (default: <session>.trimmed)",
    )
    args = parser.parse_args()

    src = Path(args.session)
    if not src.is_file():
        print(f"No such file: {src}", file=sys.stderr)
        return 1

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"That file is not valid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("That file is not a Playwright storage state object.", file=sys.stderr)
        return 1

    cookies = data.get("cookies") or []
    origins = data.get("origins") or []

    kept_cookies = [c for c in cookies if should_keep(c.get("domain", ""))]
    kept_origins = [o for o in origins if should_keep(o.get("origin", ""))]

    if not kept_cookies:
        print(
            "No LinkedIn cookies found. That session was not signed in, "
            "or it came from the wrong browser profile.",
            file=sys.stderr,
        )
        return 1

    trimmed = {"cookies": kept_cookies, "origins": kept_origins}

    dest = Path(args.out) if args.out else src.with_suffix(src.suffix + ".trimmed")
    dest.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")
    try:
        dest.chmod(0o600)
    except OSError:
        pass

    dropped = len(cookies) - len(kept_cookies)
    print(f"kept:    {len(kept_cookies)} of {len(cookies)} cookies")
    print(f"dropped: {dropped} unrelated cookies")
    print(f"origins: kept {len(kept_origins)} of {len(origins)}")
    print(f"wrote:   {dest}")
    print()
    print("Base64 it and store it as the repo secret:")
    print(f'  base64 -i "{dest}" | pbcopy')
    print("  gh secret set LINKEDIN_STORAGE_STATE_B64 --repo mrfentmen/linkedin")

    return 0


if __name__ == "__main__":
    sys.exit(main())
