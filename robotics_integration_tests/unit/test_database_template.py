from unittest.mock import Mock

import pytest

from robotics_integration_tests.custom_containers.postgres import (
    create_postgres_container,
    create_sara_postgres_container,
)
from robotics_integration_tests.utilities.database_template import (
    run_once_per_session,
)


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


@pytest.mark.parametrize(
    "create_container", [create_postgres_container, create_sara_postgres_container]
)
def test_template_is_mounted_as_init_script_only_when_given(tmp_path, create_container):
    template = tmp_path / "template.sql"

    assert create_container(Mock()).volumes == {}
    assert create_container(Mock(), init_sql_path=template).volumes == {
        str(template): {
            "bind": "/docker-entrypoint-initdb.d/001_schema.sql",
            "mode": "ro",
        }
    }
