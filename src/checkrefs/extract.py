"""Pull checkable references out of a Markdown bug report, security report or PR description."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

CODE_EXT = (
    "c h cc cpp cxx hpp hh hxx m mm py pyi pyx js mjs cjs jsx ts tsx mts cts go rs rb java kt kts scala swift "
    "php cs fs vb lua pl pm r jl ex exs erl hrl zig nim dart clj cljs hs ml mli sh bash zsh fish ps1 "
    "vue svelte astro html htm css scss sass less sql proto graphql gql yml yaml toml json json5 ini cfg conf "
    "xml gradle cmake mk mak md rst txt tf hcl lock dockerfile"
).split()
_EXT = "|".join(sorted(CODE_EXT, key=len, reverse=True))
PATH_RX = re.compile(
    r"(?<![\w/.@:-])((?:\.{0,2}/)?(?:[\w.+-]+/)*[\w+-][\w.+-]*\.(?:%s))(?![\w-])"
    r"(?:(?::|#L|,? line |, l\.? ?)(\d+)(?:(?::|-L?)(\d+))?)?" % _EXT, re.I)
SPECIAL_FILES = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*(?:Makefile|Dockerfile|CMakeLists\.txt|Cargo\.toml|"
                           r"go\.mod|Gemfile|Rakefile|Justfile|Procfile))(?![\w.-])(?::(\d+))?")
LINE_OF_RX = re.compile(r"\blines? (\d+)(?:\s*(?:-|–|to)\s*(\d+))? (?:of|in) `?((?:[\w.+-]+/)*[\w+-][\w.+-]*\.(?:%s))`?"
                        % _EXT, re.I)
BLOB_RX = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)/blob/([^/\s]+)/([^\s#)\]>]+)(?:#L(\d+)(?:-L(\d+))?)?")
URL_RX = re.compile(r"https?://[^\s)\]>]+")
INLINE_CODE_RX = re.compile(r"`([^`\n]+)`")
CALL_RX = re.compile(r"(?<![\w.$>:])([A-Za-z_$][\w$]*(?:(?:\.|::|->)[A-Za-z_$][\w$]*)*)\(\)")
ARGCALL_RX = re.compile(r"(?<![\w.$>:])([A-Za-z_$][\w$]*(?:(?:\.|::|->)[A-Za-z_$][\w$]*)*)\(([\w$ ,.*&>-]{1,60})\)")
SHELL_START = re.compile(r"^\s*(?:\$ |# |> |\./|(?:sudo|grep|rg|sed|awk|cat|head|tail|curl|wget|gcc|cc|clang|make|cmake|"
                         r"python3?|pip3?|npm|npx|node|cd|git|echo|printf|nc|export|apt(?:-get)?|brew|ls|valgrind|gdb|"
                         r"docker|go|cargo|ruby|java|mvn|gradle|bash|sh)\b)")
IDENT_RX = re.compile(r"^([A-Za-z_$][\w$]*(?:(?:\.|::|->|#)[A-Za-z_$][\w$]*)*)(\([^()]*\))?;?$")
FLAG_RX = re.compile(r"(?<![\w-])(--[a-z][a-z0-9]*(?:-[a-z0-9]+)+|--[a-z]{3,}[a-z0-9]*)(?![\w-])")
VERSION_RX = r"v?(\d+\.\d+(?:\.\d+)?(?:[-.]?(?:rc|a|b|alpha|beta|dev)\.?\d*)?)"
PY_FRAME_RX = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([^\s]+))?')
JS_FRAME_RX = re.compile(r"^\s*at (?:(?:async )?([^\s(]+) \()?((?:file://)?[^\s()]+?\.(?:m?js|cjs|jsx|tsx?|mts|cts)):(\d+)(?::\d+)?\)?\s*$")
JAVA_FRAME_RX = re.compile(r"^\s*at ([\w$.]+)\.([\w$<>]+)\(([\w$]+\.(?:java|kt|scala)):(\d+)\)")
GO_FRAME_RX = re.compile(r"^\s+(\S+\.go):(\d+)(?: \+0x[0-9a-f]+)?\s*$")

SHELL_LANGS = {"sh", "bash", "shell", "console", "zsh", "fish", "powershell", "ps1", "cmd", "bat", "terminal"}
OUTPUT_LANGS = {"text", "txt", "log", "output", "plaintext", "plain", "stacktrace", "traceback", "pytb", "none"}
QUOTE_CUE = re.compile(
    r"\b(vulnerable|affected|offending|problematic|buggy|faulty|relevant|existing|current|original|following|below)\b"
    r"[^.\n]{0,40}\b(code|snippet|lines?|function|implementation|logic|routine)\b"
    r"|\b(code|snippet|function|implementation)\b[^.\n]{0,40}\b(from|in|at|located|looks like|reads)\b"
    r"|\b(here is|here's)\b[^.\n]{0,30}\b(code|snippet|function)\b", re.I)
NOT_QUOTE_CUE = re.compile(
    r"\b(fix|fixed|patch|suggest\w*|recommend\w*|replace\w*|instead|should|proposed?|repro\w*|example|poc|"
    r"proof of concept|exploit|my|our|minimal|workaround|try|tried|output|error|log|trace(?:back)?|run|ran)\b", re.I)

STOP_IDENTS = set("""true false null nil none None True False undefined NaN self this cls super main init
GET POST PUT PATCH DELETE HEAD OPTIONS TODO FIXME XXX README LICENSE NULL EOF
int char bool void float double long short unsigned signed size_t ssize_t uint8_t uint16_t uint32_t uint64_t
int8_t int16_t int32_t int64_t str bytes list dict set tuple object string number boolean any never unknown
async await return import export from const let var def class struct enum union static extern typedef
if else elif for while do switch case break continue try catch except finally raise throw new delete
""".split())
# Functions from language standard libraries: if a report names one and the repo never uses it, that is not
# evidence of anything, so these are skipped instead of reported as missing.
STD_SYMBOLS = set("""strcpy strncpy strlcpy strcat strncat strlcat sprintf snprintf vsprintf vsnprintf printf fprintf
memcpy memmove memset memcmp malloc calloc realloc free strlen strnlen strcmp strncmp strdup strndup gets fgets
scanf sscanf atoi atol strtol strtoul strtoll alloca system popen exec execve fork open close read write
print len range isinstance getattr setattr hasattr eval exec compile input open format repr super
console.log JSON.parse JSON.stringify parseInt parseFloat setTimeout setInterval fetch require
os.system subprocess.run subprocess.Popen pickle.loads yaml.load
""".split())


@dataclass
class CodeBlock:
    lang: str
    text: str
    start: int  # report line of the first content line (1-based)
    cue: str  # prose just before the block


@dataclass
class Claim:
    kind: str  # path | line | symbol | quote | diff | flag | version | frame
    cited: str
    line: int  # report line (1-based)
    path: Optional[str] = None
    lineno: Optional[int] = None
    lineno_end: Optional[int] = None
    symbol: Optional[str] = None
    func: Optional[str] = None
    source_line: Optional[str] = None
    block: Optional[CodeBlock] = None
    ref: Optional[str] = None  # git ref named in a GitHub blob URL
    frame_lang: Optional[str] = None
    in_backticks: bool = False
    near: List[str] = field(default_factory=list)  # code named on the same report line as a line claim


@dataclass
class Parsed:
    text: str
    blocks: List[CodeBlock] = field(default_factory=list)
    prose: List[Tuple[int, str]] = field(default_factory=list)  # (report line, text)


def split_markdown(text: str) -> Parsed:
    parsed = Parsed(text=text)
    lines = text.splitlines()
    i = 0
    recent: List[str] = []
    while i < len(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)", lines[i])
        if m:
            fence, lang = m.group(1), m.group(2).lower()
            j = i + 1
            body = []
            while j < len(lines) and not lines[j].strip().startswith(fence):
                body.append(lines[j])
                j += 1
            cue = " ".join(x for x in recent[-2:])
            parsed.blocks.append(CodeBlock(lang=lang, text="\n".join(body), start=i + 2, cue=cue))
            recent = []
            i = j + 1
            continue
        parsed.prose.append((i + 1, lines[i]))
        if lines[i].strip():
            recent.append(lines[i].strip())
        i += 1
    return parsed


def _strip_urls(s: str) -> str:
    return URL_RX.sub(lambda m: " " * len(m.group(0)), s)


def _path_claims(s: str, lineno: int, backticked: bool = False) -> List[Claim]:
    out = []
    s2 = _strip_urls(s)
    for m in PATH_RX.finditer(s2):
        p = m.group(1)
        if re.match(r"^\d+(\.\d+)+$", p) or p.lower().startswith(("e.g.", "i.e.")):
            continue
        ln = int(m.group(2)) if m.group(2) else None
        end = int(m.group(3)) if m.group(3) and ln else None
        out.append(Claim("line" if ln else "path", m.group(0).strip(), lineno, path=p, lineno=ln, lineno_end=end,
                         in_backticks=backticked))
    for m in SPECIAL_FILES.finditer(s2):
        ln = int(m.group(2)) if m.group(2) else None
        out.append(Claim("line" if ln else "path", m.group(0), lineno, path=m.group(1), lineno=ln))
    for m in LINE_OF_RX.finditer(s2):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else None
        out.append(Claim("line", m.group(0), lineno, path=m.group(3), lineno=a, lineno_end=b))
    return out


def _symbol(raw: str) -> Optional[str]:
    raw = raw.strip()
    m = IDENT_RX.match(raw)
    if not m:
        return None
    name = m.group(1)
    called = bool(m.group(2))
    last = re.split(r"\.|::|->|#", name)[-1]
    if name in STOP_IDENTS or last in STOP_IDENTS or len(last) < 3:
        return None
    if re.match(r"^v?\d", last):
        return None
    codey = (called or "_" in name or re.search(r"[a-z][A-Z]", name) or re.search(r"\.|::|->|#", name)
             or name.isupper() and len(name) >= 4)
    if not codey and not re.match(r"^[a-z][a-z0-9]{3,}$", name):
        return None
    return name


def extract(text: str, project: Optional[str] = None) -> List[Claim]:
    """All checkable claims in a report, in report order, de-duplicated."""
    parsed = split_markdown(text)
    claims: List[Claim] = []

    # prose: blob URLs, paths, symbols, flags, versions
    for ln, s in parsed.prose:
        for m in BLOB_RX.finditer(s):
            a = int(m.group(5)) if m.group(5) else None
            b = int(m.group(6)) if m.group(6) else None
            c = Claim("line" if a else "path", m.group(0), ln, path=m.group(4), lineno=a, lineno_end=b,
                      ref=m.group(3))
            c.symbol = "%s/%s" % (m.group(1).lower(), m.group(2).lower())  # slug, used to skip other repos
            claims.append(c)
        spans = INLINE_CODE_RX.findall(s)
        line_paths = _path_claims(s, ln)
        claims.extend(line_paths)
        cited_paths = [c.path for c in line_paths]
        names = []
        for span in spans:
            sym = _symbol(span)
            if sym and not PATH_RX.fullmatch(span.strip()):
                names.append((sym, span))
        no_code = _strip_urls(INLINE_CODE_RX.sub(" ", s))
        for m in CALL_RX.finditer(no_code):
            sym = _symbol(m.group(0))
            if sym:
                names.append((sym, m.group(0)))
        for m in ARGCALL_RX.finditer(no_code):
            sym = _symbol(m.group(1) + "()")
            if sym and not any(sym == n for n, _ in names):
                names.append((sym, m.group(0)))
        for c in line_paths:
            if c.kind == "line":
                c.near = [n for n, _ in names]
        for sym, cited in names:
            c = Claim("symbol", cited, ln, symbol=sym, in_backticks=True)
            if len(set(cited_paths)) == 1:
                c.path = cited_paths[0]
            claims.append(c)
        for span in spans + [no_code]:
            words = span.split()
            for m in FLAG_RX.finditer(span):
                standalone = span is not no_code and span.strip() == m.group(1)
                in_cmd = project and words and words[0].lower() in (project.lower(), project.lower() + ".py")
                if standalone or in_cmd:
                    claims.append(Claim("flag", m.group(1), ln, symbol=m.group(1)))
        if project:
            for m in re.finditer(r"(?i)(?<![\w-])%s[ /@-]%s(?![\w]|\.\d)" % (re.escape(project), VERSION_RX), no_code):
                claims.append(Claim("version", m.group(0), ln, symbol=m.group(1)))
        m = re.match(r"^\s*(?:[-*]\s*)?\**(?:%s\s+)?version\**\s*[:=]\**\s*%s\s*$" % (
            re.escape(project) if project else "", VERSION_RX), s, re.I)
        if m:
            claims.append(Claim("version", s.strip(), ln, symbol=m.group(1)))

    # code blocks: stack frames everywhere; diffs; quoted source
    for b in parsed.blocks:
        claims.extend(_frames(b.text, b.start))
        if b.lang in ("diff", "patch") or re.search(r"^@@ .* @@", b.text, re.M):
            claims.append(Claim("diff", "diff at report line %d" % b.start, b.start, block=b))
            continue
        if b.lang in SHELL_LANGS:
            for k, l in enumerate(b.text.splitlines()):
                cmd = re.sub(r"^\s*[$>#%]\s*", "", l)
                w = cmd.split()
                if project and w and w[0].lower() in (project.lower(), project.lower() + ".py"):
                    for m in FLAG_RX.finditer(cmd):
                        claims.append(Claim("flag", m.group(1), b.start + k, symbol=m.group(1)))
            continue
        if b.lang in OUTPUT_LANGS:
            continue
        body = [l for l in b.text.splitlines() if l.strip()]
        if body and sum(1 for l in body if SHELL_START.match(l)) >= max(1, len(body) // 2):
            continue  # unlabelled shell session, not a quote
        cue = b.cue
        first = b.text.lstrip().splitlines()[0] if b.text.strip() else ""
        header = re.match(r"^\s*(?://|#|/\*|--)\s*((?:[\w.+-]+/)*[\w+-][\w.+-]*\.(?:%s))(?::(\d+))?" % _EXT, first, re.I)
        is_quote = bool(header) or (QUOTE_CUE.search(cue) and not NOT_QUOTE_CUE.search(cue))
        if is_quote:
            c = Claim("quote", "code block at report line %d" % b.start, b.start, block=b)
            if header:
                c.path = header.group(1)
            else:
                ps = [x.path for x in _path_claims(cue, b.start)]
                if len(set(ps)) == 1:
                    c.path = ps[0]
            claims.append(c)
    # stack traces pasted without fences
    for ln, s in parsed.prose:
        claims.extend(_frames(s, ln))
    return _dedupe(claims)


def _frame_cite(path: str, lineno: int, func: Optional[str]) -> str:
    tail = "/".join(path.replace("\\", "/").split("/")[-3:])
    return "%s:%d" % (tail, lineno) + (" in %s" % func if func else "")


def _frames(text: str, start: int) -> List[Claim]:
    out = []
    lines = text.splitlines()
    for k, l in enumerate(lines):
        m = PY_FRAME_RX.search(l)
        if m:
            src = lines[k + 1].strip() if k + 1 < len(lines) and not PY_FRAME_RX.search(lines[k + 1]) else None
            if src and (src.startswith(("Traceback", "^", "~")) or re.match(r"^[\w.]+(Error|Exception)\b", src)):
                src = None
            out.append(Claim("frame", _frame_cite(m.group(1), int(m.group(2)), m.group(3)), start + k, path=m.group(1),
                             lineno=int(m.group(2)), func=m.group(3), source_line=src, frame_lang="python"))
            continue
        m = JS_FRAME_RX.match(l)
        if m:
            out.append(Claim("frame", _frame_cite(m.group(2), int(m.group(3)), m.group(1)), start + k,
                             path=re.sub(r"^file://", "", m.group(2)),
                             lineno=int(m.group(3)), func=m.group(1), frame_lang="js"))
            continue
        m = JAVA_FRAME_RX.match(l)
        if m:
            out.append(Claim("frame", _frame_cite(m.group(3), int(m.group(4)), m.group(2)), start + k, path=m.group(3),
                             lineno=int(m.group(4)),
                             func=m.group(2), frame_lang="java"))
            continue
        m = GO_FRAME_RX.match(l)
        if m:
            func = None
            if k > 0:
                fm = re.match(r"^([\w./*()-]+)\.([\w]+)\(", lines[k - 1].strip())
                func = fm.group(2) if fm else None
            out.append(Claim("frame", _frame_cite(m.group(1), int(m.group(2)), func), start + k, path=m.group(1),
                             lineno=int(m.group(2)), func=func,
                             frame_lang="go"))
    return out


def _dedupe(claims: List[Claim]) -> List[Claim]:
    seen = set()
    out = []
    # a path that is also cited with a line number elsewhere on the same report line is redundant
    with_lines = {(c.line, c.path) for c in claims if c.kind == "line"}
    for c in claims:
        if c.kind == "path" and (c.line, c.path) in with_lines:
            continue
        key = (c.kind, c.path, c.lineno, c.lineno_end, c.symbol, c.func, c.source_line,
               c.block.start if c.block else None)
        if key in seen:
            if c.kind == "line" and c.near:
                first = next(o for o in out if o.kind == "line" and o.path == c.path and o.lineno == c.lineno
                             and o.lineno_end == c.lineno_end)
                first.near += [n for n in c.near if n not in first.near]
            continue
        seen.add(key)
        out.append(c)
    return out
