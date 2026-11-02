import json
import os
import subprocess
import sys

import pytest

from checkrefs import __version__
from checkrefs.cli import main
from checkrefs.source import GH_RX, SourceError, fetch_github, from_event, is_github_ref

from conftest import REPORTS, ROOT

SLOP = os.path.join(REPORTS, "slop.md")
REAL = os.path.join(REPORTS, "real-bug.md")


def test_exit_codes(tinyhttp, capsys):
    assert main([REAL, "-C", tinyhttp]) == 0
    assert main([SLOP, "-C", tinyhttp]) == 1
    assert main([SLOP, "-C", tinyhttp, "--fail-on", "never"]) == 0
    out = capsys.readouterr().out
    assert "UNGROUNDED" in out and "GROUNDED" in out


def test_fail_on_warn(plain, tmp_path):
    p = tmp_path / "r.md"
    p.write_text("`frobnicate()` broke")
    assert main([str(p), "-C", plain]) == 0
    assert main([str(p), "-C", plain, "--fail-on", "warn"]) == 1


def test_json_output(tinyhttp, capsys):
    main([SLOP, "-C", tinyhttp, "--format", "json"])
    d = json.loads(capsys.readouterr().out)
    assert d["verdict"] == "ungrounded" and d["counts"]["fail"] >= 5 and d["version"] == __version__
    assert {"status", "kind", "cited", "report_line", "message", "where"} <= set(d["findings"][0])


def test_markdown_and_output_file(tinyhttp, tmp_path, capsys):
    out = tmp_path / "r.md"
    main([SLOP, "-C", tinyhttp, "--format", "markdown", "-o", str(out)])
    md = out.read_text()
    assert md.startswith("### checkrefs: Ungrounded") and "| ❌ |" in md and "does not judge who" in md
    assert "references checked" in capsys.readouterr().out


def test_hide_ok(tinyhttp, capsys):
    main([REAL, "-C", tinyhttp, "--hide-ok"])
    assert "  ok  " not in capsys.readouterr().out


def test_github_summary(tinyhttp, tmp_path, monkeypatch):
    summ = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summ))
    main([SLOP, "-C", tinyhttp, "--github-summary"])
    assert "checkrefs" in summ.read_text()


def test_stdin(tinyhttp, monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(open(SLOP).read()))
    assert main(["-", "-C", tinyhttp]) == 1


def test_event(tinyhttp, tmp_path, capsys):
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"issue": {"number": 7, "title": "bug", "body": open(SLOP).read()},
                              "repository": {"full_name": "acme/tinyhttp"}}))
    assert main(["--event", str(ev), "-C", tinyhttp]) == 1
    assert "acme/tinyhttp#7" in capsys.readouterr().out


def test_event_without_issue(tmp_path, plain, capsys):
    ev = tmp_path / "ev.json"
    ev.write_text("{}")
    assert main(["--event", str(ev), "-C", plain]) == 2


def test_missing_file_and_bad_repo(tmp_path, plain, capsys):
    assert main([str(tmp_path / "nope.md"), "-C", plain]) == 2
    assert main([SLOP, "-C", str(tmp_path / "nowhere")]) == 2
    assert main([SLOP, "-C", plain, "--ref", "v1"]) == 2


def test_report_inside_repo_is_excluded(plain, capsys):
    p = os.path.join(plain, "REPORT.md")
    open(p, "w").write("`totally_invented_function()` in the code")
    main([p, "-C", plain, "--format", "json"])
    d = json.loads(capsys.readouterr().out)
    assert d["findings"][0]["status"] == "warn"


def test_version_flag(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_github_ref_parsing():
    assert GH_RX.match("curl/curl#123").groups() == ("curl", "curl", "123")
    assert GH_RX.match("https://github.com/a/b/pull/9").groups() == ("a", "b", "9")
    assert is_github_ref("a/b#1") and not is_github_ref("report.md")
    with pytest.raises(SourceError):
        fetch_github("not a ref")


def test_fetch_github_uses_api(monkeypatch):
    import io
    import urllib.request
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        return Resp(json.dumps({"title": "T", "body": "B", "pull_request": {}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    text, label, slug = fetch_github("https://github.com/Acme/W/pull/5")
    assert seen["url"].endswith("/repos/Acme/W/issues/5") and seen["auth"] == "Bearer tok"
    assert text.startswith("# T") and label == "Acme/W#5 (PR)" and slug == "acme/w"


def test_from_event_pr(tmp_path):
    ev = tmp_path / "e.json"
    ev.write_text(json.dumps({"pull_request": {"number": 3, "title": "t", "body": None},
                              "repository": {"full_name": "A/B"}}))
    text, label, slug = from_event(str(ev))
    assert label == "A/B#3" and slug == "a/b"


def test_module_entrypoint(tinyhttp):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    r = subprocess.run([sys.executable, "-m", "checkrefs", SLOP, "-C", tinyhttp, "--color", "never"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "FAIL" in r.stdout
