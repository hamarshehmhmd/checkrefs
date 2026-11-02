import os

import pytest

from checkrefs.repo import Repo, RepoError
from checkrefs.verify import FAIL, OK, SKIP, WARN, check_text

from conftest import REPORTS, git


def statuses(text, root, **kw):
    res = check_text(text, Repo(root, kw.pop("ref", None), kw.pop("at", None)), **kw)
    return {(f.kind, f.cited): f.status for f in res.findings}, res


def test_existing_path_ok(plain):
    s, _ = statuses("see `src/tinyhttp/headers.py`", plain)
    assert s[("path", "src/tinyhttp/headers.py")] == OK


def test_suffix_path_ok(plain):
    s, _ = statuses("see `tinyhttp/headers.py`", plain)
    assert s[("path", "tinyhttp/headers.py")] == OK


def test_project_prefixed_path_ok(plain):
    s, _ = statuses("see plain/src/tinyhttp/cli.py", plain)
    assert s[("path", "plain/src/tinyhttp/cli.py")] == OK


def test_missing_nested_path_fails_with_closest(plain):
    res = check_text("bug in `src/tinyhttp/parser.py`", Repo(plain))
    f = res.findings[0]
    assert f.status == FAIL and "headers.py" in f.message or "chunked.py" in f.message


def test_missing_bare_filename_is_skipped(plain):
    s, _ = statuses("compile `poc.c` and run it", plain)
    assert s[("path", "poc.c")] == SKIP


def test_case_insensitive_match_warns(plain):
    s, _ = statuses("bug in Headers.py", plain)
    assert s[("path", "Headers.py")] == WARN


def test_system_header_skipped(plain):
    s, _ = statuses("include stdio.h first", plain)
    assert s[("path", "stdio.h")] == SKIP


def test_line_in_range_and_out_of_range(plain):
    s, _ = statuses("`src/tinyhttp/chunked.py:7` and `src/tinyhttp/chunked.py:700`", plain)
    assert s[("line", "src/tinyhttp/chunked.py:7")] == OK
    assert s[("line", "src/tinyhttp/chunked.py:700")] == FAIL


def test_line_with_named_code_nearby_ok(plain):
    s, _ = statuses("at src/tinyhttp/chunked.py:17 where _read_chunk_size(line) is called", plain)
    assert s[("line", "src/tinyhttp/chunked.py:17")] == OK


def test_line_with_code_elsewhere_in_file_warns(plain):
    res = check_text("at src/tinyhttp/chunked.py:22 where _read_chunk_size(line) is called", Repo(plain))
    f = [f for f in res.findings if f.kind == "line"][0]
    assert f.status == WARN and "try --ref or --at" in f.message


def test_line_with_code_not_in_file_fails(plain):
    res = check_text("at src/tinyhttp/chunked.py:2 where memmove(buf, data) is called", Repo(plain))
    f = [f for f in res.findings if f.kind == "line"][0]
    assert f.status == FAIL


def test_symbol_found(plain):
    s, _ = statuses("`decode_chunked()` breaks", plain)
    assert s[("symbol", "decode_chunked()")] == OK


def test_unknown_symbol_warns(plain):
    s, _ = statuses("`frobnicate_widget()` breaks", plain)
    assert s[("symbol", "frobnicate_widget()")] == WARN


def test_unknown_project_prefixed_symbol_fails_with_closest(plain):
    res = check_text("`tinyhttp_parse()` is broken; also `tinyhttp_decode()`", Repo(plain), project="tinyhttp")
    assert all(f.status == FAIL for f in res.findings if f.kind == "symbol")


def test_symbol_attributed_to_wrong_file(plain):
    s, _ = statuses("`decode_chunked()` in `src/tinyhttp/headers.py` is wrong", plain)
    assert s[("symbol", "decode_chunked()")] == WARN


def test_std_symbol_not_in_cited_file_fails(plain):
    s, _ = statuses("`strcpy()` in `src/tinyhttp/headers.py` overflows", plain)
    assert s[("symbol", "strcpy()")] == FAIL


def test_flag(plain):
    s, _ = statuses("```sh\nplain req.txt --max-headers 3\nplain req.txt --no-such-flag\n```\n", plain,
                    project="plain")
    assert s[("flag", "--max-headers")] == OK and s[("flag", "--no-such-flag")] == WARN


def test_versions_against_tags(tinyhttp):
    s, _ = statuses("tinyhttp 1.4.0 and tinyhttp 1.3.0 but tinyhttp 2.1.0", tinyhttp)
    assert s[("version", "tinyhttp 1.4.0")] == OK
    assert s[("version", "tinyhttp 1.3.0")] == OK
    assert s[("version", "tinyhttp 2.1.0")] == FAIL


def test_unreleased_minor_version_warns(tinyhttp):
    s, _ = statuses("tinyhttp 1.3.7", tinyhttp)
    assert s[("version", "tinyhttp 1.3.7")] == WARN


def test_version_skipped_without_tags(plain):
    s, _ = statuses("plain 9.9.9", plain)
    assert s[("version", "plain 9.9.9")] == SKIP


def test_version_skipped_in_shallow_clone(tinyhttp, tmp_path):
    shallow = tmp_path / "shallow"
    git(str(tmp_path), "clone", "-q", "--depth", "1", "file://" + tinyhttp, str(shallow))
    s, _ = statuses("shallow 9.9.9", str(shallow))
    assert s[("version", "shallow 9.9.9")] == SKIP


def test_ref_changes_line_numbers(tinyhttp):
    text = "at src/tinyhttp/chunked.py:47 where _read_chunk_size(line) returns"
    now, _ = statuses(text, tinyhttp)
    old, _ = statuses(text, tinyhttp, ref="v1.3.0")
    assert now[("line", "src/tinyhttp/chunked.py:47")] == FAIL  # file is 21 lines now
    assert old[("line", "src/tinyhttp/chunked.py:47")] == OK


def test_at_date_picks_older_commit(tinyhttp):
    r = Repo(tinyhttp, at="2024-03-01")
    assert "as of 2024-03-01" in r.label()
    assert len(r.lines("src/tinyhttp/chunked.py")) > 50


def test_at_before_history_errors(tinyhttp):
    with pytest.raises(RepoError):
        Repo(tinyhttp, at="2001-01-01")


def test_bad_ref_errors(tinyhttp):
    with pytest.raises(RepoError):
        Repo(tinyhttp, "v9.9.9")


def test_python_frame_checks(plain):
    tb = ('```\nTraceback (most recent call last):\n'
          '  File "/v/site-packages/tinyhttp/chunked.py", line 7, in _read_chunk_size\n    return int(size, 16)\n'
          '  File "/v/site-packages/tinyhttp/chunked.py", line 7, in _read_chunk_size\n    os.system(cmd)\n'
          '  File "/v/site-packages/tinyhttp/headers.py", line 214, in f\n    x\n'
          '  File "/usr/lib/python3.12/json/decoder.py", line 3, in decode\n    y\nValueError\n```\n')
    res = check_text(tb, Repo(plain))
    st = [f.status for f in res.findings if f.kind == "frame"]
    assert st[0] == OK and FAIL in st[1:3]
    assert any(f.status == SKIP for f in res.findings if "decoder.py" in f.cited)


def test_quote_found_and_not_found(plain):
    good = ("The vulnerable code in `src/tinyhttp/chunked.py`:\n\n```python\ndef _read_chunk_size(line):\n"
            "    size = line.strip()\n    return int(size, 16)\n```\n")
    bad = ("The vulnerable code in `src/tinyhttp/chunked.py`:\n\n```python\ndef unsafe_copy(dst, src):\n"
           "    memmove(dst, src, len(src))\n    return dst\n```\n")
    assert check_text(good, Repo(plain)).findings[-1].status == OK
    assert any(f.status == FAIL for f in check_text(bad, Repo(plain)).findings if f.kind == "quote")


def test_quote_with_trailing_comments_still_matches(plain):
    q = ("The vulnerable code in `src/tinyhttp/chunked.py`:\n\n```python\ndef _read_chunk_size(line):\n"
         "    size = line.strip()  # VULNERABLE LINE\n    return int(size, 16)  # <-- here\n```\n")
    assert [f.status for f in check_text(q, Repo(plain)).findings if f.kind == "quote"] == [OK]


def test_quote_from_reporters_own_file_skipped(plain):
    q = "My test server, poc_server.py:\n\n```python\nimport socket\ns = socket.socket()\ns.bind(('', 1))\n```\n"
    res = check_text(q, Repo(plain))
    assert not any(f.status == FAIL for f in res.findings)


def test_diff_applies_and_not(plain):
    good = ("```diff\n--- a/src/tinyhttp/chunked.py\n+++ b/src/tinyhttp/chunked.py\n@@ -5,3 +5,3 @@\n"
            " def _read_chunk_size(line: bytes) -> int:\n-    size = line.strip()\n+    size = line.split(b';', 1)[0].strip()\n```\n")
    bad = ("```diff\n--- a/src/tinyhttp/chunked.py\n+++ b/src/tinyhttp/chunked.py\n@@ -5,3 +5,3 @@\n"
           " def made_up(line):\n-    return parse_everything(line)\n+    return None\n```\n")
    assert [f.status for f in check_text(good, Repo(plain)).findings if f.kind == "diff"] == [OK]
    assert [f.status for f in check_text(bad, Repo(plain)).findings if f.kind == "diff"] == [FAIL]


def test_other_repo_blob_link_skipped(plain):
    res = check_text("https://github.com/someone/else/blob/main/src/x.py#L3", Repo(plain), slug="me/plain")
    assert [f.status for f in res.findings] == [SKIP]


def test_example_reports(tinyhttp):
    real = check_text(open(os.path.join(REPORTS, "real-bug.md")).read(), Repo(tinyhttp))
    slop = check_text(open(os.path.join(REPORTS, "slop.md")).read(), Repo(tinyhttp))
    assert real.verdict == "grounded" and real.count(FAIL) == 0 and real.count(WARN) == 0
    assert slop.verdict == "ungrounded" and slop.count(FAIL) >= 5


def test_nothing_to_check(plain):
    assert check_text("It crashes sometimes. Please fix.", Repo(plain)).verdict == "nothing-to-check"


def test_unknown_symbol_in_existing_cited_file_fails(plain):
    assert check_text("`frobnicate()` in src/tinyhttp/cli.py", Repo(plain)).verdict == "ungrounded"


def test_verdict_partly(plain):
    assert check_text("`frobnicate()` broke.\n\nSee src/tinyhttp/cli.py", Repo(plain)).verdict == "partly-verified"


def test_non_git_directory_walk(plain):
    r = Repo(plain)
    assert not r.is_git and "src/tinyhttp/headers.py" in r.files()


def test_git_ignored_files_excluded(tinyhttp):
    os.makedirs(os.path.join(tinyhttp, "build"))
    open(os.path.join(tinyhttp, ".gitignore"), "w").write("build/\n")
    open(os.path.join(tinyhttp, "build", "gen.py"), "w").write("x = 1\n")
    assert "build/gen.py" not in Repo(tinyhttp).files()
