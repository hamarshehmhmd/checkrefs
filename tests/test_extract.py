from checkrefs.extract import extract, split_markdown


def kinds(text, **kw):
    return [(c.kind, c.cited) for c in extract(text, **kw)]


def test_path_with_line():
    cs = extract("The bug is in `src/app/core.py:42`.")
    line = [c for c in cs if c.kind == "line"]
    assert line and line[0].path == "src/app/core.py" and line[0].lineno == 42


def test_line_range_github_style():
    c = [c for c in extract("see lib/x.c#L10-L12") if c.kind == "line"][0]
    assert (c.lineno, c.lineno_end) == (10, 12)


def test_line_of_phrase():
    c = [c for c in extract("crash at line 212 of src/h.py") if c.kind == "line"][0]
    assert c.path == "src/h.py" and c.lineno == 212


def test_redundant_path_dropped_when_line_given():
    ks = [k for k, _ in kinds("see `a/b.py:3`")]
    assert ks.count("line") == 1 and "path" not in ks


def test_symbols_from_backticks_and_calls():
    syms = {c.symbol for c in extract("`parse_headers` calls do_thing() badly") if c.kind == "symbol"}
    assert {"parse_headers", "do_thing"} <= syms


def test_plain_words_not_symbols():
    syms = [c for c in extract("`true` and `None` and `self`") if c.kind == "symbol"]
    assert syms == []


def test_flags_only_for_project_commands():
    text = "```sh\ntinyhttp serve --no-limit\npip install --upgrade tinyhttp\n```\n"
    flags = [c.symbol for c in extract(text, project="tinyhttp") if c.kind == "flag"]
    assert flags == ["--no-limit"]


def test_flag_in_prose_backticks():
    flags = [c.symbol for c in extract("run `x --max-headers 5`", project="x") if c.kind == "flag"]
    assert flags == ["--max-headers"]


def test_version_claims():
    vs = [c.symbol for c in extract("Found in tinyhttp 2.1.0. Also\n**Version:** 1.4.0", project="tinyhttp")
          if c.kind == "version"]
    assert vs == ["2.1.0", "1.4.0"]


def test_version_followed_by_period():
    vs = [c.symbol for c in extract("I use tinyhttp 1.4.0.", project="tinyhttp") if c.kind == "version"]
    assert vs == ["1.4.0"]


def test_python_frames():
    tb = ('```\nTraceback (most recent call last):\n  File "/x/site-packages/pkg/mod.py", line 7, in f\n'
          '    return g()\nValueError: no\n```\n')
    fr = [c for c in extract(tb) if c.kind == "frame"][0]
    assert fr.path.endswith("pkg/mod.py") and fr.lineno == 7 and fr.func == "f" and fr.source_line == "return g()"


def test_js_java_go_frames():
    text = ("```\n    at handle (/app/src/server.js:10:5)\n"
            "\tat com.acme.Foo.bar(Foo.java:33)\n"
            "main.main()\n\t/home/u/proj/cmd/main.go:21 +0x1d\n```\n")
    fr = {(c.path.split("/")[-1], c.lineno) for c in extract(text) if c.kind == "frame"}
    assert {("server.js", 10), ("Foo.java", 33), ("main.go", 21)} <= fr


def test_quote_needs_cue():
    q = "The vulnerable code is in `src/a.py`:\n\n```python\ndef f(x):\n    return x\n```\n"
    assert [c for c in extract(q) if c.kind == "quote"]
    nq = "Here is my proof of concept:\n\n```python\nimport a\na.f(1)\n```\n"
    assert not [c for c in extract(nq) if c.kind == "quote"]


def test_quote_path_from_cue():
    q = "The vulnerable code is in `src/a.py`:\n\n```python\ndef f(x):\n    return x\n```\n"
    c = [c for c in extract(q) if c.kind == "quote"][0]
    assert c.path == "src/a.py"


def test_unlabelled_shell_block_is_not_a_quote():
    q = ("The vulnerable code is in Progress.c, found with:\n\n```\n# find it\n"
         "grep -n strcpy lib/progress.c\nsed -n 90,100p lib/progress.c\n```\n")
    assert not [c for c in extract(q) if c.kind == "quote"]


def test_diff_block():
    d = "```diff\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,2 +1,2 @@\n def f(x):\n-    return x\n+    return -x\n```\n"
    c = [c for c in extract(d) if c.kind == "diff"][0]
    assert "--- a/src/a.py" in c.block.text


def test_blob_link():
    c = [c for c in extract("https://github.com/acme/w/blob/v1.2/src/a.py#L5") if c.kind == "line"][0]
    assert c.path == "src/a.py" and c.lineno == 5 and c.ref == "v1.2" and c.symbol == "acme/w"


def test_near_symbols_attached_to_line_claims_and_merged():
    text = "Overflow (lib/ws.c:1287)\n\nAt lib/ws.c:1287 where strcpy(keyval, randstr) is called\n"
    lines = [c for c in extract(text) if c.kind == "line"]
    assert len(lines) == 1 and "strcpy" in lines[0].near


def test_split_markdown_blocks():
    p = split_markdown("text\n```py\nx = 1\n```\nmore\n")
    assert len(p.blocks) == 1 and p.blocks[0].lang == "py" and p.blocks[0].text.strip() == "x = 1"
