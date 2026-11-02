"""Check extracted claims against a repository."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .extract import STD_SYMBOLS, Claim, extract
from .repo import Repo, RepoError

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


@dataclass
class Finding:
    status: str  # ok | warn | fail | skip
    kind: str
    cited: str
    line: int  # report line
    message: str
    where: Optional[str] = None  # repo location that confirms or best matches

    def as_dict(self):
        return {"status": self.status, "kind": self.kind, "cited": self.cited, "report_line": self.line,
                "message": self.message, "where": self.where}


@dataclass
class Result:
    repo: str
    findings: List[Finding] = field(default_factory=list)

    def count(self, status):
        return sum(1 for f in self.findings if f.status == status)

    @property
    def checked(self):
        return [f for f in self.findings if f.status != SKIP]

    @property
    def verdict(self):
        if self.count(FAIL):
            return "ungrounded"
        if not self.checked:
            return "nothing-to-check"
        if self.count(WARN):
            return "partly-verified"
        return "grounded"


SYSTEM_HEADERS = set("""assert.h ctype.h errno.h fcntl.h float.h inttypes.h limits.h locale.h math.h netdb.h
pthread.h setjmp.h signal.h stdarg.h stdbool.h stddef.h stdint.h stdio.h stdlib.h string.h strings.h time.h unistd.h
wchar.h sys/types.h sys/socket.h sys/stat.h sys/time.h sys/wait.h sys/mman.h sys/select.h netinet/in.h arpa/inet.h
windows.h winsock2.h ws2tcpip.h dlfcn.h dirent.h poll.h termios.h iostream vector""".split())


def _strip_comment(s: str) -> str:
    return re.sub(r"\s*(//.*|/\*.*\*/|#\s.*)$", "", s)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _significant(line: str) -> bool:
    n = _norm(line)
    if len(n) < 8 or re.fullmatch(r"[{}()\[\];,]*", n):
        return False
    if n.startswith(("//", "#", "/*", "*", "--")) and len(n) < 20:
        return False
    if "..." in n or "…" in n:
        return False
    return True


class Checker:
    def __init__(self, repo: Repo, slug: Optional[str] = None):
        self.repo = repo
        self.slug = (slug or repo.remote_slug() or "").lower() or None
        self._index: Optional[Dict[str, Tuple[str, int]]] = None
        self._other: Dict[str, Optional[Repo]] = {}

    # --- helpers -------------------------------------------------------------------------
    def _norm_index(self):
        if self._index is None:
            idx = {}
            for f, t in self.repo.text_files():
                for k, l in enumerate(t.splitlines(), 1):
                    n = _norm(l)
                    if len(n) >= 8 and n not in idx:
                        idx[n] = (f, k)
            self._index = idx
        return self._index

    def _repo_for(self, ref: Optional[str]) -> Repo:
        if not ref or ref == self.repo.ref or not self.repo.is_git:
            return self.repo
        if ref not in self._other:
            try:
                self._other[ref] = Repo(self.repo.root, ref)
            except RepoError:
                self._other[ref] = None
        return self._other[ref] or self.repo

    def _resolve(self, repo: Repo, path: str) -> List[str]:
        return repo.resolve(path)

    def _frame_path(self, path: str) -> Tuple[List[str], bool]:
        """Map a path from a stack trace to repo files. Returns (matches, looked_like_ours)."""
        p = path.replace("\\", "/")
        p = re.sub(r"^[A-Za-z]:", "", p)
        if "site-packages/" in p or "dist-packages/" in p:
            p = re.split(r"(?:site|dist)-packages/", p)[-1]
        if "node_modules/" in p:
            p = p.split("node_modules/")[-1]
        parts = [x for x in p.split("/") if x not in ("", ".")]
        for k in range(len(parts)):
            suffix = "/".join(parts[k:])
            if k == len(parts) - 1 and len(parts) > 1:
                break  # don't match on bare basename for a long absolute path
            hits = self.repo.resolve(suffix)
            if hits:
                return hits, True
        if len(parts) == 1:
            hits = self.repo.basename_matches(parts[0])
            return hits, bool(hits)
        return [], False

    # --- checks --------------------------------------------------------------------------
    def check(self, claims: List[Claim]) -> Result:
        res = Result(repo=self.repo.label())
        for c in claims:
            fn = getattr(self, "_check_" + c.kind)
            out = fn(c)
            if out:
                res.findings.append(out)
        return res

    def _missing_path_msg(self, path, repo=None):
        repo = repo or self.repo
        near = difflib.get_close_matches(path, repo.files(), n=1, cutoff=0.6)
        if not near:
            bm = repo.basename_matches(path)
            near = bm[:1]
        return "no such file in %s" % repo.label() + ("; closest: %s" % near[0] if near else ""), (near[0] if near else None)

    def _check_path(self, c: Claim):
        if c.ref is not None and self.slug and c.symbol and c.symbol != self.slug:
            return Finding(SKIP, "path", c.cited, c.line, "link to another repository (%s)" % c.symbol)
        if c.path.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", c.path) or "node_modules/" in c.path \
                or "site-packages/" in c.path:
            return Finding(SKIP, "path", c.cited, c.line, "absolute or third-party path")
        repo = self._repo_for(c.ref)
        hits = self._resolve(repo, c.path)
        if len(hits) == 1:
            return Finding(OK, "path", c.cited, c.line, "file exists", hits[0])
        if len(hits) > 1:
            return Finding(OK, "path", c.cited, c.line, "%d files match" % len(hits), ", ".join(hits[:3]))
        if c.path in SYSTEM_HEADERS:
            return Finding(SKIP, "path", c.cited, c.line, "system header")
        nocase = repo.resolve_nocase(c.path)
        if len(nocase) == 1:
            return Finding(WARN, "path", c.cited, c.line, "only a case-insensitive match: %s" % nocase[0], nocase[0])
        msg, near = self._missing_path_msg(c.path, repo)
        if "/" not in c.path.strip("./"):
            return Finding(SKIP, "path", c.cited, c.line, msg + " (probably the reporter's own file)", near)
        return Finding(FAIL, "path", c.cited, c.line, msg, near)

    def _check_line(self, c: Claim):
        f = self._check_path(c)
        if f.status != OK:
            f.kind = "line"
            return f
        repo = self._repo_for(c.ref)
        hits = self._resolve(repo, c.path)
        bad = []
        for h in hits:
            lines = repo.lines(h) or []
            hi = c.lineno_end or c.lineno
            if hi <= len(lines) and c.lineno >= 1:
                code = _norm(lines[c.lineno - 1])[:70]
                return self._line_near(c, h, lines, code)
            bad.append((h, len(lines)))
        h, n = bad[0]
        return Finding(FAIL, "line", c.cited, c.line, "%s has only %d lines in %s" % (h, n, repo.label()),
                       h)

    def _line_near(self, c: Claim, h: str, lines, code: str):
        lo, hi = c.lineno, c.lineno_end or c.lineno
        for sym in c.near:
            last = re.split(r"\.|::|->|#", sym)[-1]
            rx = re.compile(r"(?<![\w$])%s(?![\w$])" % re.escape(last))
            window = lines[max(0, lo - 4):hi + 3]
            if any(rx.search(l) for l in window):
                continue
            at = [k for k, l in enumerate(lines, 1) if rx.search(l)]
            if at:
                return Finding(WARN, "line", c.cited, c.line,
                               "line %d is `%s`, but %s is at line %s (different version? try --ref or --at)"
                               % (lo, code[:50], last, ", ".join(map(str, at[:3]))), "%s:%d" % (h, at[0]))
            return Finding(FAIL, "line", c.cited, c.line, "%s is not in %s at all (line %d is `%s`)"
                           % (last, h, lo, code[:50]), "%s:%d" % (h, lo))
        extra = " (and %s is there)" % ", ".join(c.near) if c.near else ""
        return Finding(OK, "line", c.cited, c.line, "line exists: %s%s" % (code or "(blank line)", extra),
                       "%s:%d" % (h, c.lineno))

    def _check_symbol(self, c: Claim):
        name = c.symbol
        parts = [p for p in re.split(r"\.|::|->|#", name) if p]
        last = parts[-1]
        if c.path:
            hits = self.repo.resolve(c.path)
            if len(hits) == 1:
                t = self.repo.text(hits[0]) or ""
                if re.search(r"(?<![\w$])%s(?![\w$])" % re.escape(last), t):
                    return Finding(OK, "symbol", c.cited, c.line, "found in the cited file", hits[0])
                if name in STD_SYMBOLS or last in STD_SYMBOLS:
                    return Finding(FAIL, "symbol", c.cited, c.line,
                                   "report says it's used in %s, but it isn't" % hits[0], hits[0])
                elsewhere = self.repo.where_word(last)
                if elsewhere:
                    return Finding(WARN, "symbol", c.cited, c.line,
                                   "not in %s (the cited file), but found in %s" % (hits[0], elsewhere[0]),
                                   elsewhere[0])
                return Finding(FAIL, "symbol", c.cited, c.line,
                               "not in %s (the cited file) or anywhere else in the repo" % hits[0], hits[0])
        hits = self.repo.where_word(last)
        if hits:
            return Finding(OK, "symbol", c.cited, c.line, "found in the repo", hits[0])
        if name in STD_SYMBOLS or last in STD_SYMBOLS:
            return Finding(SKIP, "symbol", c.cited, c.line, "standard-library name, not used in the repo")
        proj = re.sub(r"\W", "", getattr(self.repo, "project", "") or "").lower()
        if proj and len(proj) >= 3 and re.match(r"%s[_.]" % re.escape(proj), last.lower()):
            near = None
            for f in self.repo.where_text(last)[:5]:
                m = re.search(r"(?<![\w$])%s\w+" % re.escape(last), self.repo.text(f) or "")
                if m:
                    near = "%s (in %s)" % (m.group(0), f)
                    break
            return Finding(FAIL, "symbol", c.cited, c.line, "looks like a %s identifier, but '%s' does not exist in %s%s"
                           % (getattr(self.repo, "project", ""), last, self.repo.label(),
                              "; closest: " + near if near else ""), near)
        return Finding(WARN, "symbol", c.cited, c.line, "no identifier '%s' anywhere in %s (a dependency or the "
                       "reporter's own code?)" % (last, self.repo.label()))

    def _check_flag(self, c: Claim):
        hits = self.repo.where_text(c.symbol)
        if hits:
            return Finding(OK, "flag", c.cited, c.line, "option appears in the source", hits[0])
        return Finding(WARN, "flag", c.cited, c.line, "option '%s' does not appear anywhere in %s"
                       % (c.symbol, self.repo.label()))

    def _check_version(self, c: Claim):
        if self.repo.shallow:
            return Finding(SKIP, "version", c.cited, c.line, "shallow clone, release tags are incomplete")
        tags = self.repo.tags()
        if not tags:
            return Finding(SKIP, "version", c.cited, c.line, "repository has no tags to compare with")
        want = _vtuple(c.symbol)
        known = {}
        for t in tags:
            v = _tag_version(t)
            if v:
                known.setdefault(v, t)
        if not known:
            return Finding(SKIP, "version", c.cited, c.line, "no version-like tags")
        if want in known:
            return Finding(OK, "version", c.cited, c.line, "release exists", "tag " + known[want])
        latest = max(known)
        if want > latest:
            return Finding(FAIL, "version", c.cited, c.line, "newer than the latest release (%s)" % known[latest],
                           "tag " + known[latest])
        return Finding(WARN, "version", c.cited, c.line, "no release tag for %s (latest is %s)"
                       % (c.symbol, known[latest]))

    def _check_frame(self, c: Claim):
        hits, ours = self._frame_path(c.path)
        if not ours:
            return Finding(SKIP, "frame", c.cited, c.line, "frame outside this repository")
        if len(hits) > 1:
            # pick the file in which the function exists
            best = [h for h in hits if c.func and c.func in (self.repo.text(h) or "")]
            hits = best or hits
        h = hits[0]
        lines = self.repo.lines(h) or []
        if c.lineno > len(lines):
            return Finding(FAIL, "frame", c.cited, c.line, "%s has only %d lines, trace says line %d"
                           % (h, len(lines), c.lineno), h)
        t = self.repo.text(h) or ""
        func = c.func
        if func and func not in ("<module>", "<lambda>", "<listcomp>", "<dictcomp>", "<genexpr>", "<anonymous>",
                                 "<init>", "<clinit>", "Object.<anonymous>"):
            short = re.split(r"[.#]", func)[-1]
            if c.frame_lang == "python":
                ok = re.search(r"^\s*(?:async\s+)?(?:def|class)\s+%s\b" % re.escape(short), t, re.M)
            else:
                ok = re.search(r"(?<![\w$])%s(?![\w$])" % re.escape(short), t)
            if not ok:
                return Finding(FAIL, "frame", c.cited, c.line, "no function '%s' in %s" % (short, h), h)
        if c.source_line:
            actual = _norm(lines[c.lineno - 1])
            want = _norm(c.source_line)
            if actual != want:
                at = next((k for k, l in enumerate(lines, 1) if _norm(l) == want), None)
                if at:
                    return Finding(WARN, "frame", c.cited, c.line,
                                   "trace shows `%s` at line %d but it is at line %d in %s (different version? try --ref)"
                                   % (want[:60], c.lineno, at, self.repo.label()), "%s:%d" % (h, at))
                return Finding(FAIL, "frame", c.cited, c.line, "trace shows `%s`, which is not in %s; line %d is `%s`"
                               % (want[:60], h, c.lineno, actual[:60]), "%s:%d" % (h, c.lineno))
        return Finding(OK, "frame", c.cited, c.line, "file, line and function match", "%s:%d" % (h, c.lineno))

    def _quote_lines(self, text):
        return [l for l in text.splitlines() if _significant(l)]

    def _check_quote(self, c: Claim):
        sig = self._quote_lines(c.block.text)
        if len(sig) < 2:
            return Finding(SKIP, "quote", c.cited, c.line, "too short to check")
        target = None
        if c.path:
            hits = self.repo.resolve(c.path)
            if len(hits) == 1:
                target = hits[0]
            elif not hits:
                msg, near = self._missing_path_msg(c.path)
                if "/" not in c.path.strip("./"):
                    return Finding(SKIP, "quote", c.cited, c.line, "quoted from %s, not in the repo (probably the "
                                   "reporter's own file)" % c.path, near)
                return Finding(FAIL, "quote", c.cited, c.line, "quoted as from %s: %s" % (c.path, msg), near)
        found, first = 0, None
        if target:
            flines = [_norm(l) for l in (self.repo.lines(target) or [])]
            fset = {l: i for i, l in reversed(list(enumerate(flines, 1)))}
            for l in sig:
                n = _norm(l) if _norm(l) in fset else _norm(_strip_comment(l))
                if n in fset:
                    found += 1
                    first = first or "%s:%d" % (target, fset[n])
        else:
            idx = self._norm_index()
            for l in sig:
                n = _norm(l) if _norm(l) in idx else _norm(_strip_comment(l))
                if n in idx:
                    found += 1
                    if not first:
                        first = "%s:%d" % idx[n]
        n = len(sig)
        where = "in %s" % target if target else "anywhere in %s" % self.repo.label()
        if found / n >= 0.6:
            return Finding(OK, "quote", c.cited, c.line, "%d/%d quoted lines found %s" % (found, n, where), first)
        near = self._closest(sig, target)
        if found == 0:
            return Finding(FAIL, "quote", c.cited, c.line, "presented as repo code, but none of its %d lines are %s"
                           % (n, where) + (near and "; closest: %s" % near[1] or ""), near and near[0])
        return Finding(WARN, "quote", c.cited, c.line, "only %d/%d quoted lines found %s" % (found, n, where), first)

    def _closest(self, sig, target):
        cand = []
        if target:
            cand = [(target, k, l) for k, l in enumerate(self.repo.lines(target) or [], 1)]
        else:
            return None
        best = (0.0, None)
        for l in sig[:6]:
            nl = _norm(l)
            for f, k, x in cand:
                nx = _norm(x)
                if abs(len(nx) - len(nl)) > 40:
                    continue
                r = difflib.SequenceMatcher(None, nl, nx).quick_ratio()
                if r > best[0] and r > 0.55:
                    r = difflib.SequenceMatcher(None, nl, nx).ratio()
                    if r > best[0]:
                        best = (r, ("%s:%d" % (f, k), "`%s`" % nx[:60]))
        return best[1] if best[0] >= 0.6 else None

    def _check_diff(self, c: Claim):
        files = {}
        cur = None
        for l in c.block.text.splitlines():
            m = re.match(r"^(?:---|\+\+\+) (?:[ab]/)?(\S+)", l)
            if m and m.group(1) != "/dev/null":
                cur = m.group(1)
                files.setdefault(cur, [])
                continue
            if l.startswith(("-", " ")) and not l.startswith("---"):
                files.setdefault(cur, []).append(l[1:])
        old = [(f, l) for f, ls in files.items() for l in ls if _significant(l)]
        if not old:
            return Finding(SKIP, "diff", c.cited, c.line, "diff has no removed/context lines to check")
        found, missing_file = 0, None
        idx = None
        for f, l in old:
            if f:
                hits = self.repo.resolve(f)
                if not hits:
                    missing_file = f
                    continue
                if _norm(l) in {_norm(x) for x in (self.repo.lines(hits[0]) or [])}:
                    found += 1
            else:
                idx = idx or self._norm_index()
                if _norm(l) in idx:
                    found += 1
        n = len(old)
        if missing_file and found == 0:
            msg, near = self._missing_path_msg(missing_file)
            return Finding(FAIL, "diff", c.cited, c.line, "patches %s: %s" % (missing_file, msg), near)
        if found / n >= 0.6:
            return Finding(OK, "diff", c.cited, c.line, "%d/%d removed/context lines exist" % (found, n))
        if found == 0:
            return Finding(FAIL, "diff", c.cited, c.line,
                           "none of its %d removed/context lines exist in %s, so it can't apply" % (n, self.repo.label()))
        return Finding(WARN, "diff", c.cited, c.line, "only %d/%d removed/context lines exist" % (found, n))


def _vtuple(v: str):
    nums = re.findall(r"\d+", re.sub(r"(?i)(rc|a|b|alpha|beta|dev).*$", "", v))
    t = tuple(int(x) for x in nums[:3])
    return t + (0,) * (3 - len(t))


def _tag_version(tag: str):
    m = re.search(r"(\d+)[._](\d+)(?:[._](\d+))?(?![\d])", tag)
    if not m or re.search(r"(?i)(rc|alpha|beta|dev|pre)\d*$", tag):
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def check_text(text: str, repo: Repo, project: Optional[str] = None, slug: Optional[str] = None) -> Result:
    import os
    project = project or os.path.basename(repo.root)
    repo.project = project
    return Checker(repo, slug).check(extract(text, project))
