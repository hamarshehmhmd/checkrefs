import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "tinyhttp")
REPORTS = os.path.join(ROOT, "examples", "reports")

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com")


def git(cwd, *args, date=None):
    env = dict(GIT_ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def make_tinyhttp(dest):
    """examples/tinyhttp as a git repo: v1.3.0 (older chunked.py), then v1.4.0 (current files)."""
    shutil.copytree(EXAMPLE, dest)
    git(dest, "init", "-q", "-b", "main")
    cur = open(os.path.join(dest, "src/tinyhttp/chunked.py")).read()
    with open(os.path.join(dest, "src/tinyhttp/chunked.py"), "w") as fh:
        fh.write('"""old"""\n' * 40 + cur)  # line numbers were 40 lower in 1.3.0
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "1.3.0", date="2024-01-10T12:00:00")
    git(dest, "tag", "v1.3.0")
    with open(os.path.join(dest, "src/tinyhttp/chunked.py"), "w") as fh:
        fh.write(cur)
    git(dest, "commit", "-qam", "1.4.0", date="2024-06-10T12:00:00")
    git(dest, "tag", "v1.4.0")
    return str(dest)


@pytest.fixture
def tinyhttp(tmp_path):
    return make_tinyhttp(tmp_path / "tinyhttp")


@pytest.fixture
def plain(tmp_path):
    d = tmp_path / "plain"
    shutil.copytree(EXAMPLE, d)
    return str(d)
