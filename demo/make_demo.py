"""Set up the demo: <dir> = examples/tinyhttp as a git repo with v1.3.0/v1.4.0, <dir>/../reports with the
example reports plus curl HackerOne report 3418528 (public), and <dir>/../curl -> $DEMO_CURL (curl 8.17.0)."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
dst = sys.argv[1] if len(sys.argv) > 1 else "/home/dev/tinyhttp"
base = os.path.dirname(dst)
subprocess.run(["sh", os.path.join(ROOT, "examples", "make_repo.sh"), dst], check=True)
reports = os.path.join(base, "reports")
shutil.rmtree(reports, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "examples", "reports"), reports)
h1 = os.environ.get("DEMO_H1", "/tmp/h1/3418528.md")
shutil.copy(h1, os.path.join(reports, "h1-3418528.md"))
curl = os.path.join(base, "curl")
if os.path.islink(curl):
    os.remove(curl)
os.symlink(os.environ.get("DEMO_CURL", "/tmp/curl-8_17_0"), curl)
print("demo at", dst)
