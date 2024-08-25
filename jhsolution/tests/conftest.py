from typing import Any, Generator, TypeVar
import pytest, datetime, uuid

import sqlalchemy as sa
from sqlalchemy import orm
import alembic

from jhsolution import env, model

T = TypeVar("T")
Yield = Generator[T, None, None]

def driver_generator(
	session: orm.Session, password: str
) -> Yield[model.User]:
	auth = model.UserAuth()
	auth.set_password(password)

	# prevent unique constraint
	fake_hp = uuid.uuid1().hex
	fake_vehicle_id = uuid.uuid1().hex

	driver_role = model.DriverRole(
		name="name",
		HP=fake_hp,
		birthday=datetime.date.today(),
		vehicle_id=fake_vehicle_id,
		vehicle_type=model.VehicleType.TRUCK_1T
	)

	user = model.User.create_user(
		session, auth,
		driver_role=driver_role,
		commit=True
	)

	yield user

	session.refresh(user)
	session.delete(driver_role)
	session.delete(user.auth)
	session.delete(user)
	session.commit()

def sender_generator(
	session: orm.Session, password: str
) -> Yield[model.User]:
	auth = model.UserAuth()
	auth.set_password(password)

	user = model.User.create_user(
		session, auth,
		sender_role=model.SenderRole(),
		commit=True
	)
	
	yield user

	session.refresh(user)
	assert user.sender_role is not None

	session.delete(user.sender_role)
	session.delete(user.auth)
	session.delete(user)
	session.commit()

################################################################################
# Alembic fixture
################################################################################

SingleRevisionData = list[dict[str, Any]]
RevisionDataConfig = dict[str, dict[str, SingleRevisionData]]

@pytest.fixture
def alembic_config() -> RevisionDataConfig:
	config = alembic.config.Config("alembic.ini")
	script_directory = alembic.script.ScriptDirectory.from_config(config)

	head = script_directory.get_current_head()
	assert head is not None
	script = script_directory.get_revision(head)

	data_config: RevisionDataConfig = {
		"before_revision_data": {}, "at_revision_data": {}
	}

	for script in script_directory.walk_revisions():
		revision = script.module.revision
		insert_before = getattr(script.module, "insert_before", None)
		if insert_before is not None:
			data_config["before_revision_data"][revision] = insert_before

	return data_config

################################################################################
# User fixtures
################################################################################

@pytest.fixture
def session() -> Yield[orm.Session]: 
	with orm.Session(model.engine, autoflush=False) as session: yield session

@pytest.fixture
def password() -> str:
	return "password"

@pytest.fixture
def driver(session: orm.Session, password: str) -> Yield[model.User]:
	for driver in driver_generator(session, password): yield driver

@pytest.fixture
def other_driver(session: orm.Session, password: str) -> Yield[model.User]:
	for driver in driver_generator(session, password): yield driver

@pytest.fixture
def sender(session: orm.Session, password: str) -> Yield[model.User]:
	for user in sender_generator(session, password): yield user

@pytest.fixture
def other_sender(session: orm.Session, password: str) -> Yield[model.User]:
	for user in sender_generator(session, password): yield user

@pytest.fixture
def owner(session: orm.Session, password: str) -> Yield[model.User]:
	for user in sender_generator(session, password): yield user

@pytest.fixture
def company(
	session: orm.Session, owner: model.User
) -> Yield[model.Company]:
	sender_role = model.SenderRole()
	session.add(sender_role)
	session.flush([sender_role])

	company = model.Company(
		name="company",
		owner_id=owner.id,
		sender_role_id=sender_role.id
	)
	session.add(company)
	session.flush([company])

	membership = model.CompanyMembership(
		company_id=company.id, member_id=owner.id
	)
	session.add(membership)

	session.commit()

	yield company

	session.delete(membership)
	session.delete(company)
	session.delete(sender_role)

	session.commit()

@pytest.fixture
def member(
	session: orm.Session, company: model.Company, password: str
) -> Yield[model.User]:
	for user in sender_generator(session, password):
		membership = model.CompanyMembership(
			company_id=company.id, member_id=user.id
		)

		session.add(membership)
		session.commit()
		session.refresh(user)

		yield user

		session.delete(membership)
		session.commit()

################################################################################
# Order fixtures
################################################################################

@pytest.fixture
def document(
	session: orm.Session, sender: model.User
) -> Yield[model.Document]:
	assert sender.sender_role is not None

	document = model.Document(
		doc_type=model.DocumentType.PDF,
		content=b'doc'
	)
	session.add(document)
	session.commit()

	yield document
	
	session.delete(document)
	session.commit()

@pytest.fixture
def order(
	session: orm.Session,
	document: model.Document,
	sender: model.User,
	driver: model.User
) -> Yield[model.Order]:
	order = model.Order(
		sender_role_id=sender.sender_role_id,
		did=document.id
	)
	session.add(order)
	session.commit()

	yield order

	session.delete(order)
	session.commit()
