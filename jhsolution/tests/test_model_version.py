import pytest
import pytest_alembic
from typing import Any

class TestModelVersion:
	@pytest.mark.migration
	@pytest.mark.dependency(scope="session", name="test_single_head_revision")
	def test_single_head_revision(self, alembic_runner: Any) -> None:
		pytest_alembic.tests.test_single_head_revision(alembic_runner)

	@pytest.mark.migration
	@pytest.mark.dependency(scope="session", name="test_upgrade")
	def test_upgrade(self, alembic_runner: Any) -> None:
		pytest_alembic.tests.test_upgrade(alembic_runner)

	@pytest.mark.migration
	@pytest.mark.dependency(scope="session", name="test_model_definitions_match_ddl")
	def test_model_definitions_match_ddl(self, alembic_runner: Any) -> None:
		pytest_alembic.tests.test_model_definitions_match_ddl(alembic_runner)

	@pytest.mark.migration
	@pytest.mark.dependency(scope="session", name="test_up_down_consistency")
	def test_up_down_consistency(self, alembic_runner: Any) -> None:
		pytest_alembic.tests.test_up_down_consistency(alembic_runner)
