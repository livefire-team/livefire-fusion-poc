"""assert_order.py's exit codes and output, driven through a fake pyodbc (no database needed)."""
import json
import os
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "assert_order.py"
PASSWORD = "pw-test-value"
ENV = {
    "SQL_SERVER_FQDN": "sql.example.test",
    "SQL_DB_NAME": "orders",
    "REFEREE_SQL_PASSWORD": PASSWORD,
    "RUN_ID": "drill-1-r1",
}
NULL_COUNTS = {"orders_persisted": None, "payment_auths_persisted": None}


class FakeDbError(Exception):
    """Stands in for pyodbc.Error: args are (sqlstate, message)."""


def make_pyodbc(results=(1, 1), connect_error=None):
    """A fake pyodbc module. Each item in results answers one query; an exception item is raised instead."""
    module = types.ModuleType("pyodbc")
    module.Error = FakeDbError
    module.connection_strings = []
    module.query_params = []
    answers = iter(results)

    class Cursor:
        def execute(self, _sql, *params):
            module.query_params.append(params)
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return types.SimpleNamespace(fetchval=lambda: answer)

    def connect(connection_string, **_kwargs):
        module.connection_strings.append(connection_string)
        if connect_error is not None:
            raise connect_error
        return types.SimpleNamespace(cursor=Cursor)

    module.connect = connect
    return module


@pytest.fixture
def run_script(monkeypatch, capsys):
    def run(pyodbc_module, env=ENV):
        monkeypatch.setitem(sys.modules, "pyodbc", pyodbc_module)
        for name in ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("SQL_TRUST_CERT", raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        try:
            runpy.run_path(str(SCRIPT), run_name="__main__")
            code = 0
        except SystemExit as stop:
            code = stop.code
        captured = capsys.readouterr()
        return types.SimpleNamespace(code=code, out=captured.out, err=captured.err)
    return run


# ---- the check ran ----

def test_one_order_and_one_authorization_exits_zero(run_script):
    result = run_script(make_pyodbc(results=(1, 1)))
    assert result.code == 0
    assert json.loads(result.out) == {"orders_persisted": 1, "payment_auths_persisted": 1}


@pytest.mark.parametrize("orders, auths", [(0, 0), (2, 2), (1, 0), (1, 2), (0, 1)])
def test_any_other_counts_exit_one_and_are_reported(run_script, orders, auths):
    result = run_script(make_pyodbc(results=(orders, auths)))
    assert result.code == 1
    assert json.loads(result.out) == {"orders_persisted": orders, "payment_auths_persisted": auths}


def test_both_queries_filter_on_the_run_id(run_script):
    fake = make_pyodbc()
    run_script(fake)
    assert fake.query_params == [("drill-1-r1",), ("drill-1-r1",)]


def test_server_certificate_is_verified_by_default(run_script):
    fake = make_pyodbc()
    run_script(fake)
    assert "TrustServerCertificate=no;" in fake.connection_strings[0]


def test_trust_setting_can_be_turned_on_for_a_local_self_signed_certificate(run_script):
    fake = make_pyodbc()
    run_script(fake, env={**ENV, "SQL_TRUST_CERT": "yes"})
    assert "TrustServerCertificate=yes;" in fake.connection_strings[0]


# ---- the check could not run ----

def test_failed_connection_exits_two_with_null_counts(run_script):
    fake = make_pyodbc(connect_error=FakeDbError("28000", "Login failed for user"))
    result = run_script(fake)
    assert result.code == 2
    assert json.loads(result.out) == NULL_COUNTS


def test_failed_first_query_exits_two_with_null_counts(run_script):
    result = run_script(make_pyodbc(results=(FakeDbError("42S02", "Invalid object name"), 1)))
    assert result.code == 2
    assert json.loads(result.out) == NULL_COUNTS


def test_failed_second_query_does_not_report_a_partial_count(run_script):
    result = run_script(make_pyodbc(results=(1, FakeDbError("42000", "SELECT permission denied"))))
    assert result.code == 2
    assert json.loads(result.out) == NULL_COUNTS


@pytest.mark.parametrize("missing", sorted(ENV))
def test_missing_setting_exits_two_with_null_counts(run_script, missing):
    env = {name: value for name, value in ENV.items() if name != missing}
    result = run_script(make_pyodbc(), env=env)
    assert result.code == 2
    assert json.loads(result.out) == NULL_COUNTS


def test_unavailable_driver_library_exits_two_with_null_counts(run_script):
    result = run_script(None)  # None in sys.modules makes `import pyodbc` raise ImportError
    assert result.code == 2
    assert json.loads(result.out) == NULL_COUNTS


def test_failure_names_the_error_on_stderr_and_keeps_stdout_as_json(run_script):
    result = run_script(make_pyodbc(connect_error=FakeDbError("28000", "Login failed for user")))
    assert "FakeDbError" in result.err and "28000" in result.err
    assert result.out.count("\n") == 1


def test_failure_output_never_contains_the_password(run_script):
    error = FakeDbError("28000", f"Login failed using {PASSWORD}")
    result = run_script(make_pyodbc(connect_error=error))
    assert PASSWORD not in result.out + result.err


def test_process_exit_code_is_two_when_settings_are_missing():
    env = {name: value for name, value in os.environ.items() if name not in ENV}
    done = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    assert json.loads(done.stdout) == NULL_COUNTS
