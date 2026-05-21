#!/usr/bin/env python3
"""Push today's edition to the user's phone via ntfy.sh (and optionally other channels).

Stdlib only. Reads config from `notify.yaml` at the project root, with optional
override via environment variables. Designed to run after `build_page.py` as the
last step of the daily pipeline.

Usage:
  python3 scripts/notify.py                        # send today's edition
  python3 scripts/notify.py --dry-run              # print what would be sent
  python3 scripts/notify.py --config /path/to/notify.yaml
  python3 scripts/notify.py --message "custom text"

Exit codes:
  0  sent (or dry-run completed)
  1  bad config / missing required field
  2  HTTP error from the push service
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "notify.yaml"
EDITION_PATH = ROOT / "output" / "edition.json"

UA = "semi-news-daily/1.0 (+notify)"


# ---------------------------------------------------------------------------
# Minimal YAML reader for the two-level subset notify.yaml uses.
# Supports:
#   channel:
#     key: value
#     other: value
# and comments (#). No flow style, no anchors.
# ---------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    cfg: dict = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            if stripped.endswith(":"):
                current = stripped[:-1].strip()
                cfg[current] = {}
            elif ":" in stripped:
                k, v = stripped.split(":", 1)
                cfg[k.strip()] = v.strip()
                current = None
        else:
            if current is None or ":" not in stripped:
                continue
            k, v = stripped.split(":", 1)
            v = v.strip()
            # Strip surrounding quotes if present.
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            # Coerce booleans.
            if v.lower() in ("true", "yes", "on"):
                v_out: object = True
            elif v.lower() in ("false", "no", "off"):
                v_out = False
            else:
                v_out = v
            cfg[current][k.strip()] = v_out
    return cfg


def env_override(cfg: dict) -> dict:
    """Allow environment variables to override file config.
    Useful for CI / secret managers.
    """
    ntfy = cfg.setdefault("ntfy", {})
    if os.environ.get("NTFY_TOPIC"):
        ntfy["topic"] = os.environ["NTFY_TOPIC"]
        ntfy.setdefault("enabled", True)
    if os.environ.get("NTFY_SERVER"):
        ntfy["server"] = os.environ["NTFY_SERVER"]
    if os.environ.get("NTFY_TOKEN"):
        ntfy["token"] = os.environ["NTFY_TOKEN"]
    if os.environ.get("PUBLIC_URL"):
        cfg.setdefault("site", {})["public_url"] = os.environ["PUBLIC_URL"]
    return cfg


# ---------------------------------------------------------------------------
# Build the notification body from the edition
# ---------------------------------------------------------------------------
def load_edition() -> dict | None:
    if not EDITION_PATH.exists():
        return None
    try:
        return json.loads(EDITION_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_payload(edition: dict | None,
                  override_message: str | None,
                  public_url: str | None) -> dict:
    if override_message:
        return {
            "title": "Semi News",
            "body": override_message,
            "click": public_url or "",
        }
    if edition is None:
        return {
            "title": "Semi News",
            "body": "Today's edition could not be loaded.",
            "click": public_url or "",
        }
    theme = (edition.get("theme") or {}).get("en") or "Today's edition"
    dek = (edition.get("dek") or {}).get("en") or ""
    date = edition.get("date") or ""
    # Body: dek + section/story count for fast scanning.
    sections = edition.get("sections") or []
    n_stories = sum(len(s.get("stories") or []) for s in sections)
    research = edition.get("research") or {}
    n_papers = sum(len(a.get("papers") or []) for a in research.get("areas", []))
    counters = f"{n_stories} stor{'y' if n_stories == 1 else 'ies'}"
    if n_papers:
        counters += f" · {n_papers} paper{'s' if n_papers != 1 else ''}"
    body_parts = [dek] if dek else []
    body_parts.append(f"[{date}] {counters}")
    return {
        "title": theme,
        "body": "\n\n".join(body_parts),
        "click": public_url or "",
    }


# ---------------------------------------------------------------------------
# ntfy.sh sender
# ---------------------------------------------------------------------------
def send_ntfy(ntfy_cfg: dict, payload: dict, dry_run: bool) -> int:
    if not ntfy_cfg.get("enabled"):
        print("ntfy: not enabled (set ntfy.enabled: true in notify.yaml)", file=sys.stderr)
        return 0
    topic = ntfy_cfg.get("topic")
    if not topic:
        print("ntfy: missing required field 'topic'", file=sys.stderr)
        return 1
    server = (ntfy_cfg.get("server") or "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"

    headers = {
        "User-Agent": UA,
        "Title": payload["title"][:200],
        "Content-Type": "text/plain; charset=utf-8",
    }
    if payload.get("click"):
        headers["Click"] = payload["click"]
    # Priority: 3 (default). Bump to 4 for must-see; keep at 3.
    priority = str(ntfy_cfg.get("priority", "3"))
    if priority:
        headers["Priority"] = priority
    if ntfy_cfg.get("tags"):
        headers["Tags"] = str(ntfy_cfg["tags"])
    if ntfy_cfg.get("token"):
        headers["Authorization"] = f"Bearer {ntfy_cfg['token']}"

    body = (payload["body"] or "—").encode("utf-8")

    if dry_run:
        print("---- ntfy dry-run ----")
        print(f"POST {url}")
        for k, v in headers.items():
            redacted = "<redacted>" if k.lower() == "authorization" else v
            print(f"  {k}: {redacted}")
        print(f"\n{body.decode('utf-8')}")
        return 0

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in (200, 201)
            print(f"ntfy: HTTP {resp.status} → {url}", file=sys.stderr)
            return 0 if ok else 2
    except urllib.error.HTTPError as e:
        print(f"ntfy: HTTP error {e.code}: {e.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as e:
        print(f"ntfy: network error: {e.reason}", file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent, do not contact the network")
    ap.add_argument("--message", default=None,
                    help="override the default body; useful for testing")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    cfg = env_override(cfg)

    if not cfg:
        print(f"no notify config found at {args.config}; nothing to do", file=sys.stderr)
        print(f"(copy {ROOT / 'notify.yaml.example'} → notify.yaml to enable)", file=sys.stderr)
        return 0  # not a failure — just nothing configured

    edition = load_edition()
    public_url = (cfg.get("site") or {}).get("public_url")
    payload = build_payload(edition, args.message, public_url)

    rc = 0
    if cfg.get("ntfy", {}).get("enabled"):
        rc = max(rc, send_ntfy(cfg["ntfy"], payload, args.dry_run))
    else:
        print("no enabled channels in notify.yaml", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
