"""Read-only view of a repository: the working tree, or any git revision."""
from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from typing import Dict, List, Optional

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
             ".pytest_cache", "dist", "build", "target", ".next", ".idea", ".vscode"}
MAX_FILE_BYTES = 2_000_000


class RepoError(Exception):
    pass


def _git(root: str, *args: str, binary: bool = False):
    p = subprocess.run(["git", "-C", root, *args], capture_output=True)
    if p.returncode != 0:
        raise RepoError(p.stderr.decode("utf-8", "replace").strip() or "git %s failed" % args[0])
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def _is_text(data: bytes) -> bool:
    return b"\0" not in data[:8192]


class Repo:
    """Files of a repository at a revision (``ref``) or in the working tree (``ref=None``)."""

    def __init__(self, root: str, ref: Optional[str] = None, at: Optional[str] = None):
        self.root = os.path.abspath(root)
        if not os.path.isdir(self.root):
            raise RepoError("not a directory: %s" % root)
        self.ref = ref
        self.is_git = False
        try:
            top = _git(self.root, "rev-parse", "--show-toplevel").strip()
            self.is_git = True
            self.root = top
        except (RepoError, FileNotFoundError):
            if ref:
                raise RepoError("--ref needs a git repository: %s" % root)
        if at:
            if not self.is_git:
                raise RepoError("--at needs a git repository: %s" % root)
            base = ref or "HEAD"
            try:
                sha = _git(self.root, "rev-list", "-1", "--before=" + at, base).strip()
            except RepoError as e:
                raise RepoError("cannot resolve --at %s: %s" % (at, e))
            if not sha:
                raise RepoError("no commit on %s before %s" % (base, at))
            ref = sha
            self.ref = sha[:12]
            self.at = at
        if ref:
            try:
                self.commit = _git(self.root, "rev-parse", "--verify", "--quiet", ref + "^{commit}").strip()
            except RepoError:
                raise RepoError("unknown git revision: %s" % ref)
        self.shallow = False
        if self.is_git:
            try:
                self.shallow = _git(self.root, "rev-parse", "--is-shallow-repository").strip() == "true"
            except RepoError:
                pass
        self._files: Optional[List[str]] = None
        self.exclude = set()  # repo paths never searched (e.g. the report file itself)
        self._text: Dict[str, Optional[str]] = {}

    # ---- listing -------------------------------------------------------------------------
    def files(self) -> List[str]:
        if self._files is None:
            if self.ref:
                out = _git(self.root, "ls-tree", "-r", "--name-only", "-z", self.commit)
                self._files = [f for f in out.split("\0") if f]
            elif self.is_git:
                out = _git(self.root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
                self._files = [f for f in out.split("\0") if f and os.path.isfile(os.path.join(self.root, f))]
            else:
                found = []
                for d, dirs, names in os.walk(self.root):
                    dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
                    for n in sorted(names):
                        found.append(os.path.relpath(os.path.join(d, n), self.root).replace(os.sep, "/"))
                self._files = found
            self._files.sort()
        return self._files

    @property
    def fileset(self):
        if not hasattr(self, "_fileset"):
            self._fileset = set(self.files())
        return self._fileset

    def text(self, path: str) -> Optional[str]:
        """Decoded text of a file, or None for binaries/huge files/missing files."""
        if path not in self._text:
            data = None
            try:
                if self.ref:
                    data = _git(self.root, "cat-file", "blob", "%s:%s" % (self.commit, path), binary=True)
                else:
                    full = os.path.join(self.root, path)
                    if os.path.getsize(full) <= MAX_FILE_BYTES:
                        with open(full, "rb") as fh:
                            data = fh.read()
            except (OSError, RepoError):
                data = None
            if data is not None and (len(data) > MAX_FILE_BYTES or not _is_text(data)):
                data = None
            self._text[path] = data.decode("utf-8", "replace") if data is not None else None
        return self._text[path]

    def lines(self, path: str) -> Optional[List[str]]:
        t = self.text(path)
        return None if t is None else t.splitlines()

    def text_files(self):
        """Text files, source code first and docs (md/rst/txt) last, minus excluded files."""
        files = [f for f in self.files() if f not in self.exclude]
        docs = tuple(".%s" % e for e in ("md", "markdown", "rst", "txt", "adoc", "html"))
        files.sort(key=lambda f: f.lower().endswith(docs))
        for f in files:
            t = self.text(f)
            if t is not None:
                yield f, t

    # ---- lookups -------------------------------------------------------------------------
    def relpath(self, path: str) -> Optional[str]:
        """Repo-relative path of a file on disk, if it is inside this repo."""
        full = os.path.realpath(path)
        root = os.path.realpath(self.root)
        if full.startswith(root + os.sep):
            return os.path.relpath(full, root).replace(os.sep, "/")
        return None

    def resolve(self, path: str) -> List[str]:
        """Repository files a cited path refers to: exact match, else unique-ish suffix match."""
        p = path.strip().lstrip("./").replace("\\", "/")
        p = re.sub(r"^(a|b)/", "", p) if p not in self.fileset else p
        if p in self.fileset:
            return [p]
        if not p:
            return []
        suffix = "/" + p
        hits = [f for f in self.files() if f.endswith(suffix)]
        if not hits and "/" in p:
            # "curl/lib/telnet.c": the reporter prefixed the path with the project directory
            first, rest = p.split("/", 1)
            if first.lower() in (os.path.basename(self.root).lower(), getattr(self, "project", "").lower()):
                return self.resolve(rest)
        return hits

    def resolve_nocase(self, path: str) -> List[str]:
        p = path.strip().lstrip("./").replace("\\", "/").lower()
        return [f for f in self.files() if f.lower() == p or f.lower().endswith("/" + p)]

    def basename_matches(self, path: str) -> List[str]:
        base = path.rstrip("/").rsplit("/", 1)[-1]
        return [f for f in self.files() if f.rsplit("/", 1)[-1] == base]

    @lru_cache(maxsize=4096)
    def where_word(self, word: str, limit: int = 5) -> List[str]:
        """Files that contain ``word`` as a whole word (identifier boundaries)."""
        rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])")
        hits = []
        for f, t in self.text_files():
            if word in t and rx.search(t):
                hits.append(f)
                if len(hits) >= limit:
                    break
        return hits

    @lru_cache(maxsize=4096)
    def where_text(self, needle: str, limit: int = 5) -> List[str]:
        hits = []
        for f, t in self.text_files():
            if needle in t:
                hits.append(f)
                if len(hits) >= limit:
                    break
        return hits

    def tags(self) -> List[str]:
        if not self.is_git:
            return []
        try:
            return [t for t in _git(self.root, "tag", "--list").split("\n") if t]
        except RepoError:
            return []

    def remote_slug(self) -> Optional[str]:
        if not self.is_git:
            return None
        try:
            url = _git(self.root, "remote", "get-url", "origin").strip()
        except RepoError:
            return None
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        return ("%s/%s" % (m.group(1), m.group(2))).lower() if m else None

    def label(self) -> str:
        name = os.path.basename(self.root)
        if getattr(self, "at", None):
            return "%s@%s (as of %s)" % (name, self.ref, self.at)
        return "%s@%s" % (name, self.ref) if self.ref else name
