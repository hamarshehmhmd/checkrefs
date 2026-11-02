"""checkrefs command line."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__, report
from .repo import Repo, RepoError
from .source import SourceError, from_event, load
from .verify import FAIL, WARN, check_text

EPILOG = """examples:
  checkrefs report.md                      check a report against the repo in the current directory
  checkrefs curl/curl#12345 -C ~/src/curl  fetch an issue or PR from GitHub (uses $GITHUB_TOKEN if set)
  checkrefs report.md --ref v1.4.0         check against the version the reporter says they used
  pbpaste | checkrefs -                    read the report from stdin
  checkrefs --event "$GITHUB_EVENT_PATH" --format markdown   inside GitHub Actions

exit codes: 0 no wrong references, 1 wrong references found (see --fail-on), 2 usage or input error"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="checkrefs", epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Check that the files, line numbers, functions, code quotes, options, versions and stack "
                    "frames a bug report, security report or PR cites actually exist in your repository.")
    ap.add_argument("source", nargs="?", help="report file, '-' for stdin, or a GitHub issue/PR (owner/repo#N or URL)")
    ap.add_argument("-C", "--repo", default=".", help="repository to check against (default: .)")
    ap.add_argument("--ref", help="git revision to check against instead of the working tree (tag, branch, sha)")
    ap.add_argument("--at", metavar="DATE", help="check against the last commit before DATE (e.g. the day the "
                                              "report was filed: 2025-10-21)")
    ap.add_argument("--event", metavar="PATH", help="read the issue/PR from a GitHub Actions event JSON file")
    ap.add_argument("--project", help="project name used to spot '<name> 1.2.3' versions and '<name> --flag' "
                                      "commands (default: repo directory name)")
    ap.add_argument("--slug", help="owner/repo of this repository, to ignore links to other repos "
                                   "(default: from git remote origin)")
    ap.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    ap.add_argument("-o", "--output", help="write the report to a file (still prints the summary)")
    ap.add_argument("--fail-on", choices=["fail", "warn", "never"], default="fail",
                    help="exit 1 when there are wrong references (fail, default), any doubtful ones (warn), or never")
    ap.add_argument("--hide-ok", action="store_true", help="only list problems")
    ap.add_argument("--show-skipped", action="store_true", help="also list references that were skipped")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--github-summary", action="store_true", help="append a Markdown report to $GITHUB_STEP_SUMMARY")
    ap.add_argument("--version", action="version", version="checkrefs " + __version__)
    a = ap.parse_args(argv)

    try:
        repo = Repo(a.repo, a.ref, a.at)
        slug = a.slug
        if a.event:
            text, label, ev_slug = from_event(a.event)
            slug = slug or ev_slug
        else:
            text, label, src_slug = load(a.source)
            slug = slug or src_slug
    except (RepoError, SourceError) as e:
        print("checkrefs: error: %s" % e, file=sys.stderr)
        return 2
    except FileNotFoundError:
        print("checkrefs: error: git is required", file=sys.stderr)
        return 2

    if a.source and a.source != "-" and os.path.isfile(a.source):
        rel = repo.relpath(a.source)
        if rel:
            repo.exclude.add(rel)
    res = check_text(text, repo, project=a.project, slug=slug)
    color = a.color == "always" or (a.color == "auto" and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
                                   and not a.output)
    if a.format == "json":
        out = report.as_json(res, label)
    elif a.format == "markdown":
        out = report.markdown(res, label, show_ok=not a.hide_ok)
    else:
        out = report.text(res, label, color=color, show_ok=not a.hide_ok, show_skip=a.show_skipped)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(report.summary_line(res))
        print(report._verdict(res))
    else:
        sys.stdout.write(out)
    if a.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report.markdown(res, label, show_ok=not a.hide_ok))
    if a.fail_on == "never":
        return 0
    bad = res.count(FAIL) + (res.count(WARN) if a.fail_on == "warn" else 0)
    return 1 if bad else 0


def run():
    sys.exit(main())


if __name__ == "__main__":
    run()
