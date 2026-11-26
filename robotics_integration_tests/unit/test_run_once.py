from unittest.mock import Mock

import pytest

from robotics_integration_tests.utilities.run_once import run_once_per_session


def test_action_runs_once_and_every_caller_gets_its_result(tmp_path):
    calls = []

    def action(output):
        calls.append(output)
        output.write_text("schema")

    first = run_once_per_session(tmp_path, "template.sql", action)
    second = run_once_per_session(tmp_path, "template.sql", action)

    assert len(calls) == 1
    assert first == second
    assert first.read_text() == "schema"


def test_failure_is_reported_to_later_callers_without_retrying(tmp_path):
    action = Mock(side_effect=RuntimeError("Migrator failed with exit code 1"))

    with pytest.raises(RuntimeError, match="Migrator failed"):
        run_once_per_session(tmp_path, "template.sql", action)
    with pytest.raises(RuntimeError, match="already failed.*Migrator failed"):
        run_once_per_session(tmp_path, "template.sql", action)

    action.assert_called_once()
    assert not (tmp_path / "template.sql").exists()
