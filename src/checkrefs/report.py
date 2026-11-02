"""Render results as text, Markdown or JSON."""
from __future__ import annotations

import json

from . import __version__
from .verify import FAIL, OK, SKIP, WARN, Result

LABEL = {OK: "ok", WARN: "WARN", FAIL: "FAIL", SKIP: "skip"}
COLOR = {OK: "32", WARN: "33", FAIL: "31", SKIP: "2"}
VERDICT_TEXT = {
    "ungrounded": "the code. Ask the reporter for a reproduction before spending review time.",
    "partly-verified": "nothing contradicts the code, but some references could not be confirmed.",
    "grounded": "every reference checked matches the code.",
    "nothing-to-check": "no files, lines, functions, code quotes or stack frames to check.",
}


def summary_line(res: Result) -> str:
    n = len(res.checked)
    return "%d reference%s checked: %d match, %d wrong, %d unclear (%d skipped)" % (
        n, "" if n == 1 else "s", res.count(OK), res.count(FAIL), res.count(WARN), res.count(SKIP))


def _verdict(res: Result) -> str:
    v = res.verdict
    if v == "ungrounded":
        k = res.count(FAIL)
        return "UNGROUNDED: %d reference%s %s" % (k, " doesn't match" if k == 1 else "s don't match", VERDICT_TEXT[v])
    return v.upper().replace("-", " ") + ": " + VERDICT_TEXT[v]


def _order(res: Result, show_ok: bool, show_skip: bool):
    rank = {FAIL: 0, WARN: 1, OK: 2, SKIP: 3}
    fs = [f for f in res.findings if (show_ok or f.status != OK) and (show_skip or f.status != SKIP)]
    return sorted(fs, key=lambda f: (rank[f.status], f.line))


def text(res: Result, source: str, color: bool = False, show_ok: bool = True, show_skip: bool = False) -> str:
    def c(code, s):
        return "\x1b[%sm%s\x1b[0m" % (code, s) if color else s

    out = [c("1", "checkrefs") + " %s  vs  %s" % (source, res.repo), ""]
    for f in _order(res, show_ok, show_skip):
        cited = f.cited if len(f.cited) <= 60 else f.cited[:57] + "..."
        out.append("  %s  L%-4d %s" % (c(COLOR[f.status], "%-4s" % LABEL[f.status]), f.line, c("1", cited)))
        msg = f.message + ("  [%s]" % f.where if f.where and f.status == OK else "")
        out.append("              " + c("2" if f.status in (OK, SKIP) else "0", msg))
    if res.findings:
        out.append("")
    out.append(summary_line(res))
    v = res.verdict
    col = {"ungrounded": "31;1", "grounded": "32;1", "partly-verified": "33;1"}.get(v, "1")
    out.append(c(col, _verdict(res)))
    return "\n".join(out) + "\n"


def markdown(res: Result, source: str, show_ok: bool = True) -> str:
    icon = {OK: "✅", WARN: "⚠️", FAIL: "❌", SKIP: "➖"}
    out = ["### checkrefs: %s" % _verdict(res).split(":")[0].title(), "",
           "Checked the references in %s against `%s`. %s." % (source, res.repo, summary_line(res)), ""]
    rows = _order(res, show_ok, False)
    if rows:
        out += ["| | cited | report line | result |", "|---|---|---|---|"]
        for f in rows:
            msg = f.message + (" (`%s`)" % f.where if f.where and f.status == OK else "")
            out.append("| %s | `%s` | %d | %s |" % (icon[f.status], f.cited.replace("|", "\\|").replace("`", "'")[:80],
                                                   f.line, msg.replace("|", "\\|")))
        out.append("")
    out.append("_%s_" % _verdict(res).split(": ", 1)[1])
    out.append("")
    out.append("<sub>checkrefs %s checks that cited files, lines, functions, code quotes, options, versions and "
               "stack frames exist. It does not judge who or what wrote the report.</sub>" % __version__)
    return "\n".join(out) + "\n"


def as_json(res: Result, source: str) -> str:
    return json.dumps({
        "version": __version__, "source": source, "repo": res.repo, "verdict": res.verdict,
        "counts": {"ok": res.count(OK), "fail": res.count(FAIL), "warn": res.count(WARN), "skip": res.count(SKIP)},
        "findings": [f.as_dict() for f in res.findings],
    }, indent=2) + "\n"
