"""candidate-scope.sh: checks a candidate's changed files against the allowed-path patterns in an environment variable.

The patterns here are made up; the real list is a repository Actions variable, not a tracked file.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "candidate-scope.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")

PATTERNS = "app/[a-z_]+\\.py\n# a comment line\n\ndocs/allowed\\.md\n"


def run(files, patterns=PATTERNS):
    env = {**os.environ, "CANDIDATE_ALLOWED_PATHS": patterns}
    if patterns is None:
        env.pop("CANDIDATE_ALLOWED_PATHS")
    # bytes, so Windows doesn't turn a newline inside a file name into CRLF
    stdin = "".join(f + "\0" for f in files).encode("utf-8")
    r = subprocess.run([BASH, SCRIPT.as_posix()], input=stdin, env=env, capture_output=True, timeout=30)
    return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8"))


def test_only_allowed_files_pass():
    r = run(["app/store.py", "docs/allowed.md"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 changed file(s): 2 allowed, 0 refused" in r.stdout


def test_a_file_outside_the_patterns_fails_and_is_named():
    r = run(["app/store.py", "README.md"])
    assert r.returncode == 1
    assert "::error::a candidate may not change README.md" in r.stdout
    assert "2 changed file(s): 1 allowed, 1 refused" in r.stdout


def test_patterns_match_the_whole_path():
    r = run(["xapp/store.py", "app/store.py.bak", "docs/allowed.md/x"])
    assert r.returncode == 1
    assert "3 changed file(s): 0 allowed, 3 refused" in r.stdout


def test_file_names_with_spaces_are_kept_whole():
    r = run(["app/store.py", "docs/my notes.md"])
    assert r.returncode == 1
    assert "::error::a candidate may not change docs/my notes.md" in r.stdout


def test_no_changed_files_passes():
    r = run([])
    assert r.returncode == 0
    assert "0 changed file(s): 0 allowed, 0 refused" in r.stdout


@pytest.mark.parametrize("patterns", [None, "", "\n# only a comment\n\n"])
def test_a_missing_or_empty_pattern_list_fails_closed(patterns):
    r = run(["app/store.py"], patterns)
    assert r.returncode == 2
    assert "::error::CANDIDATE_ALLOWED_PATHS is not set" in r.stdout


def test_an_invalid_pattern_fails_closed():
    r = run(["app/store.py"], "app/(unclosed\n")
    assert r.returncode == 2
    assert "::error::CANDIDATE_ALLOWED_PATHS holds an invalid pattern" in r.stdout


def test_a_crlf_only_pattern_list_fails_closed():
    r = run(["app/store.py"], "\r\n\r\n")
    assert r.returncode == 2


def test_crlf_line_endings_in_the_patterns_are_ignored():
    r = run(["app/store.py", "docs/allowed.md"], "app/[a-z_]+\\.py\r\ndocs/allowed\\.md\r\n")
    assert r.returncode == 0, r.stdout


def test_a_file_name_cannot_inject_workflow_commands():
    r = run(["docs/x\n::warning::forged\r%25.md"])
    assert r.returncode == 1
    assert not any(line.startswith("::warning") for line in r.stdout.splitlines())
    assert "::error::a candidate may not change docs/x%0A::warning::forged%0D%2525.md" in r.stdout


def test_the_patterns_are_never_printed():
    for r in (run(["app/store.py", "README.md"]), run(["app/store.py"], "app/(unclosed\n")):
        out = r.stdout + r.stderr
        assert "[a-z_]" not in out and "allowed\\.md" not in out and "(unclosed" not in out
