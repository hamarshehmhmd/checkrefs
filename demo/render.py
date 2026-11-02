"""Render the narrated demo video: real command output + edge-tts narration.

Usage: python demo/render.py   (needs ffmpeg, edge-tts, Pillow, git, checkrefs on PATH; DEMO_CURL=path to a curl 8.17.0 checkout)
Every terminal scene runs its commands for real and shows the actual output;
each scene lasts exactly as long as its narration.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
OUT = os.path.join(ROOT, "demo.mp4")
W, H, FPS = 1280, 720, 24
VOICE = "en-US-AndrewNeural"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG, FG = (24, 26, 33), (220, 223, 228)
ANSI = {"31": (255, 95, 95), "32": (95, 215, 120), "33": (240, 200, 80), "2": (130, 135, 145), "36": (90, 200, 230)}
PROMPT = "tinyhttp $ "

SCENES = [
    {"kind": "title", "title": "checkrefs", "sub": "does this bug report match\nthe code it cites?",
     "say": "This is checkrefs, a small open source tool for maintainers. Give it a bug report, a security report "
            "or a pull request, and it checks that the files, line numbers, functions, code quotes, versions and "
            "stack frames it cites really exist in your repo."},
    {"kind": "bullets", "title": "The problem",
     "bullets": ["Maintainers are flooded with confident, made-up reports",
                 "curl: \"We still have not seen a valid security report",
                 "   done with AI help\" (Daniel Stenberg, 2025)",
                 "Each one costs an hour to disprove by hand",
                 "Invented functions, wrong files, impossible line numbers"],
     "say": "Open source maintainers are getting buried in reports that sound convincing but cite code that isn't "
            "there. Curl's maintainer said they had still not seen a valid security report written with A I help. "
            "Each one can take an hour to disprove, because you have to go and look up every function, file and line."},
    {"kind": "term", "cmds": ["head -n 16 ../reports/slop.md"],
     "say": "Here's a demo library called tiny H T T P, and a report claiming a critical heap overflow. It names a "
            "version, a file, a function, a line number, quotes the vulnerable code and even includes a stack trace."},
    {"kind": "term", "cmds": ["checkrefs ../reports/slop.md --color always; echo \"exit code: $?\""],
     "say": "Run checkrefs on it. Version two point one doesn't exist, the latest release is one point four. "
            "parser dot pie isn't a file. headers dot pie has twenty eight lines, not two hundred and twelve. "
            "The quoted code isn't in it, and neither is the stack frame. The verdict is ungrounded, with exit code one."},
    {"kind": "term", "cmds": ["checkrefs ../reports/real-bug.md --color always; echo \"exit code: $?\""],
     "say": "Now a genuine bug report about chunk extensions. Every reference checks out: the version, the file and line, "
            "the functions, the command line flags, and each stack frame's file, line and function. Grounded, exit code zero. "
            "That's the one worth your time."},
    {"kind": "term", "cmds": ["checkrefs ../reports/h1-3418528.md -C ../curl --project curl --hide-ok --color always"],
     "say": "And a real one. This is a public HackerOne report from curl's collection of A I slop reports. It blames a function "
            "called Curl ldap err2string. That function doesn't exist in curl. The real one has an underscore A suffix "
            "and a different signature, and checkrefs points straight at it."},
    {"kind": "bullets", "title": "What it can and can't do",
     "bullets": ["Checks references, not reasoning or who wrote it",
                 "16 public curl slop reports: 2 cite made-up code,",
                 "   8 have refs it can't confirm, 6 cite real code",
                 "--ref TAG / --at DATE: check the version they used",
                 "GitHub Action: job summary, optional label"],
     "say": "To be clear about limits: it checks references, not reasoning, and it doesn't guess who wrote the report. "
            "On sixteen public curl slop reports, two cited made up code, eight had references it couldn't confirm, "
            "and six cited real code with wrong conclusions. You can check against the version the reporter used, "
            "and run it as a GitHub Action on new issues."},
    {"kind": "bullets", "title": "Try it",
     "bullets": ["curl -fsSL https://raw.githubusercontent.com/",
                 "   hamarshehmhmd/checkrefs/main/install.sh | sh",
                 "checkrefs report.md      checkrefs owner/repo#123",
                 "", "Python 3.9+  ·  zero dependencies",
                 "GNU AGPL-3.0 (commercial licenses available)"],
     "say": "checkrefs needs Python three point nine or newer and has no dependencies. Install it with one line, then "
            "point it at a report file or a GitHub issue. It's licensed under the GNU A G P L version 3, with commercial "
            "licenses available from the author. It's on GitHub at hamarsheh m h m d slash checkrefs."},
]


async def tts(text, path):
    import edge_tts
    for attempt in range(8):  # the edge-tts service occasionally returns no audio; retry
        try:
            await edge_tts.Communicate(text, VOICE, rate="+4%").save(path)
            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == 7:
                raise
            await asyncio.sleep(5)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path], text=True)
    return float(out.strip())


def run_cmd(cmd, cwd):
    env = dict(os.environ, NO_COLOR="")
    env.pop("NO_COLOR")
    env["PATH"] = os.path.dirname(shutil.which("checkrefs")) + os.pathsep + env["PATH"]
    full = cmd
    p = subprocess.run(["bash", "-c", "shopt -s nullglob; " + full], cwd=cwd, capture_output=True, text=True, env=env)
    out = (p.stdout + p.stderr).rstrip("\n")
    # pretty-print hook JSON
    if out.startswith("{"):
        import json
        try:
            out = json.dumps(json.loads(out), indent=2)
        except ValueError:
            pass
    return out


def parse_ansi(line):
    """Return [(text, color, bold)] spans for a line with SGR codes."""
    spans, color, bold = [], FG, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            for code in (m.group(1) or "0").split(";"):
                if code == "0":
                    color, bold = FG, False
                elif code == "1":
                    bold = True
                elif code in ANSI:
                    color = ANSI[code]
        elif part:
            spans.append((part, color, bold))
    return spans


class Term:
    def __init__(self):
        self.font = ImageFont.truetype(MONO, 17)
        self.bold = ImageFont.truetype(MONO_B, 17)
        self.cw = self.font.getlength("M")
        self.lh = 24
        self.cols = int((W - 80) / self.cw)

    def wrap(self, spans):
        lines, cur, n = [], [], 0
        for text, c, b in spans:
            while text:
                room = self.cols - n
                if len(text) <= room:
                    cur.append((text, c, b)); n += len(text); text = ""
                else:
                    cut = text.rfind(" ", 0, room + 1)
                    cut = cut if cut > 0 else room
                    cur.append((text[:cut], c, b)); lines.append(cur); cur, n = [], 0
                    text = "    " + text[cut:].lstrip(" ")
        lines.append(cur)
        return lines

    def frame(self, lines, cursor=False):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 14, W - 20, H - 14], 12, fill=(30, 33, 41), outline=(60, 64, 76))
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([40 + i * 24, 30, 54 + i * 24, 44], fill=c)
        d.text((W // 2, 37), "~/tinyhttp — bash", font=ImageFont.truetype(SANS, 15), fill=(150, 155, 165), anchor="mm")
        visible = lines[-26:]
        y = 64
        for ln in visible:
            x = 40
            for text, c, b in ln:
                d.text((x, y), text, font=self.bold if b else self.font, fill=c)
                x += self.cw * len(text)
            y += self.lh
        if cursor:
            last = visible[-1] if visible else []
            x = 40 + self.cw * sum(len(t) for t, _, _ in last)
            d.rectangle([x, y - self.lh + 3, x + self.cw - 2, y - 4], fill=FG)
        return img


def card(scene):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if scene["kind"] == "title":
        d.text((W // 2, 280), scene["title"], font=ImageFont.truetype(MONO_B, 84), fill=(95, 215, 120), anchor="mm")
        d.multiline_text((W // 2, 420), scene["sub"], font=ImageFont.truetype(SANS, 34), fill=FG, anchor="mm",
                         align="center", spacing=12)
        d.text((W // 2, 620), "github.com/hamarshehmhmd/checkrefs  ·  AGPL-3.0", font=ImageFont.truetype(SANS, 22),
               fill=(150, 155, 165), anchor="mm")
    else:
        d.text((90, 90), scene["title"], font=ImageFont.truetype(SANS_B, 52), fill=(95, 215, 120))
        f = ImageFont.truetype(SANS, 29)
        y = 200
        for b in scene["bullets"]:
            if b and not b.startswith("   "):
                d.text((90, y), "•", font=f, fill=(240, 200, 80))
            d.text((130, y), b.strip(), font=f, fill=FG)
            y += 58 if b.startswith("   ") or not b else 62
    return img


class Writer:
    def __init__(self, path, audio):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio,
                                   "-af", "apad", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                   "-shortest", path], stdin=subprocess.PIPE)
        self.n = 0

    def put(self, img, count=1):
        data = img.tobytes()
        for _ in range(count):
            self.p.stdin.write(data)
        self.n += count

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        if self.p.returncode:
            sys.exit("ffmpeg failed")


def render_scene(i, scene, workdir):
    audio = os.path.join(BUILD, f"s{i}.mp3")
    if not os.path.exists(audio):
        asyncio.run(tts(scene["say"], audio))
    total = int((duration(audio) + 0.7) * FPS)
    path = os.path.join(BUILD, f"s{i}.mp4")
    w = Writer(path, audio)
    if scene["kind"] != "term":
        w.put(card(scene), total)
        w.close()
        return path
    t = Term()
    shown = scene.get("show", scene["cmds"])
    outputs = [run_cmd(c, workdir) for c in scene["cmds"]]
    # When a scene's displayed command differs from what runs (heredoc), show
    # the display lines; the last displayed line always maps to the last command.
    steps = []
    if len(shown) != len(scene["cmds"]):
        steps = [(s, "") for s in shown[:-1]] + [(shown[-1], outputs[-1])]
    else:
        steps = list(zip(shown, outputs))
    # timing budget: typing ~ 30 chars/s, then pause, spread over the narration
    typing = sum(len(s) for s, _ in steps) / 32 * FPS
    pause = max(6, int((total - typing) / max(1, len(steps))) - 4)
    lines = []
    for cmd, out in steps:
        prompt = [(PROMPT, (95, 215, 120), True)]
        for k in range(0, len(cmd) + 1, 2):
            frame = t.frame(lines + t.wrap(prompt + [(cmd[:k], FG, False)]), cursor=True)
            w.put(frame)
        lines += t.wrap(prompt + [(cmd, FG, False)])
        for ol in out.splitlines():
            lines += t.wrap(parse_ansi(ol))
        lines.append([])
        hold = min(pause, max(0, total - w.n))
        w.put(t.frame(lines), hold)
    final = t.frame(lines + t.wrap([(PROMPT, (95, 215, 120), True)]), cursor=True)
    if w.n < total:
        w.put(final, total - w.n)
    w.close()
    return path


def main():
    os.makedirs(BUILD, exist_ok=True)
    workdir = os.environ.get("DEMO_DIR", "/home/dev/tinyhttp")
    subprocess.run([sys.executable, os.path.join(HERE, "make_demo.py"), workdir], check=True)
    parts = [render_scene(i, s, workdir) for i, s in enumerate(SCENES)]
    with open(os.path.join(BUILD, "list.txt"), "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    os.path.join(BUILD, "list.txt"), "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", OUT], check=True)
    with open(os.path.join(BUILD, "narration.txt"), "w") as fh:
        fh.write("\n\n".join(s["say"] for s in SCENES) + "\n")
    print(OUT, round(duration(OUT), 1), "s")


if __name__ == "__main__":
    main()
