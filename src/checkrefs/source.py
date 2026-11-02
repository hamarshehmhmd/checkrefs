"""Load report text from a file, stdin, a GitHub issue/PR, or a GitHub Actions event payload."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple

GH_RX = re.compile(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+)(?:#|/(?:issues|pull)/)(\d+)\b")


class SourceError(Exception):
    pass


def is_github_ref(s: str) -> bool:
    return bool(GH_RX.match(s)) and not os.path.exists(s)


def fetch_github(ref: str, api: str = "https://api.github.com") -> Tuple[str, str, str]:
    """Return (title + body as markdown, label, slug) for owner/repo#N or an issue/PR URL."""
    m = GH_RX.match(ref)
    if not m:
        raise SourceError("not a GitHub issue/PR reference: %s" % ref)
    owner, repo, num = m.groups()
    url = "%s/repos/%s/%s/issues/%s" % (api.rstrip("/"), owner, repo, num)
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "checkrefs"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise SourceError("GitHub API %s for %s/%s#%s" % (e.code, owner, repo, num))
    except urllib.error.URLError as e:
        raise SourceError("could not reach GitHub: %s" % e.reason)
    text = "# %s\n\n%s\n" % (data.get("title") or "", data.get("body") or "")
    kind = "PR" if "pull_request" in data else "issue"
    return text, "%s/%s#%s (%s)" % (owner, repo, num, kind), ("%s/%s" % (owner, repo)).lower()


def from_event(path: str) -> Tuple[str, str, Optional[str]]:
    with open(path, encoding="utf-8") as fh:
        ev = json.load(fh)
    item = ev.get("pull_request") or ev.get("issue")
    if not item:
        raise SourceError("event has no issue or pull_request (use on: issues / pull_request_target)")
    slug = (ev.get("repository") or {}).get("full_name")
    num = item.get("number")
    text = "# %s\n\n%s\n" % (item.get("title") or "", item.get("body") or "")
    return text, "%s#%s" % (slug or "event", num), slug.lower() if slug else None


def load(source: Optional[str]) -> Tuple[str, str, Optional[str]]:
    """Return (text, label, slug-or-None)."""
    if source in (None, "-"):
        if source is None and sys.stdin.isatty():
            raise SourceError("give a report file, '-' for stdin, or a GitHub issue/PR (owner/repo#123)")
        return sys.stdin.read(), "stdin", None
    if is_github_ref(source):
        return fetch_github(source)
    try:
        with open(source, encoding="utf-8", errors="replace") as fh:
            return fh.read(), source, None
    except OSError as e:
        raise SourceError("cannot read %s: %s" % (source, e.strerror))
