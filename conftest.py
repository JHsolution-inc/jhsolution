from typing import Generator, List
import pytest, alembic, pytest_alembic

from jhsolution import env

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import model

model.engine = sa.create_engine("sqlite://",
	connect_args={"check_same_thread": False},
	poolclass=sa.pool.StaticPool
)

model.Base.metadata.create_all(model.engine)

@pytest.fixture
def alembic_engine() -> sa.Engine:
	# Override this fixture to configure the exact alembic context setup required
	url = env.TEST_DATABASE_URL
	assert url is not None
	return sa.create_engine(url)

def pytest_addoption(parser: pytest.Parser) -> None:
	parser.addoption(
		"--test-migration", action="store_true", help="run alembic migration tests"
	)

def pytest_configure(config: pytest.Config) -> None:
	config.addinivalue_line("markers", "migration: mark as alembic migration test")

def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
	if config.getoption("--test-migration"):
		return

	skip_alembic = pytest.mark.skip(reason="skip alembic migration test unless --test-migration has set")
	for item in items:
		if 'migration' in item.keywords:
			item.add_marker(skip_alembic)
