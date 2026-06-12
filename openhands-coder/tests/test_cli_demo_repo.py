"""demo-repo command — sample repos materialize correctly."""

import os
import subprocess
from types import SimpleNamespace

from openhands_coder.cli import cmd_demo_repo


def test_materializes_sample_as_git_repo(tmp_path, capsys):
    dest = str(tmp_path / "demo")
    rc = cmd_demo_repo(SimpleNamespace(name="textstats", dest=dest))
    assert rc == 0
    assert os.path.isfile(os.path.join(dest, "test_demo.py"))
    assert os.path.isfile(os.path.join(dest, "textstats", "__init__.py"))
    log = subprocess.run(["git", "-C", dest, "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "demo starting state" in log
    out = capsys.readouterr().out
    assert "goose run" in out  # prints the exact command to run the agent


def test_unknown_sample_rejected(tmp_path, capsys):
    rc = cmd_demo_repo(SimpleNamespace(name="nope", dest=str(tmp_path / "x")))
    assert rc == 1
    assert "csvstats" in capsys.readouterr().err  # lists what IS available


def test_refuses_non_empty_destination(tmp_path):
    dest = tmp_path / "busy"
    dest.mkdir()
    (dest / "existing.txt").write_text("do not clobber")
    rc = cmd_demo_repo(SimpleNamespace(name="textstats", dest=str(dest)))
    assert rc == 1
    assert (dest / "existing.txt").read_text() == "do not clobber"
