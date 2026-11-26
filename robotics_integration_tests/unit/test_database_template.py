from unittest.mock import Mock

import pytest

from robotics_integration_tests.custom_containers.postgres import (
    create_postgres_container,
    create_sara_postgres_container,
)


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
