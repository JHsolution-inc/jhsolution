import pytest, datetime, uuid

import sqlalchemy as sa
from sqlalchemy import orm
from jhsolution import model

class TestModel:
	@pytest.mark.dependency(
		scope="session",
		name="TestModelDummy",
		depends=[]
	)
	def test_start_dummy(self) -> None: pass

	@pytest.mark.dependency(
		scope="session", name="TestModel",
		depends=["test_membership", "test_order_page"]
	)
	def test_end_dummy(self) -> None: pass


	@pytest.mark.dependency(
		scope="session",
		name="test_user_auth_password",
		depends=["TestModelDummy"]
	)
	def test_user_auth_password(self) -> None:
		assert not model.UserAuth().is_valid_auth

		auth = model.UserAuth(password="123")

		with pytest.raises(AttributeError):
			pw = auth.password

		assert auth.is_valid_auth
		assert auth.is_valid_password("123")
		assert not auth.is_valid_password("1234")

		auth.password = "1234"
		assert auth.is_valid_password("1234")
		assert not auth.is_valid_password("123")

	@pytest.mark.dependency(
		scope="session",
		name="test_user_creation",
		depends=["test_user_auth_password"]
	)
	def test_user_creation(self, session: orm.Session) -> None:
		# prevent unique constraint
		fake_hp = uuid.uuid1().hex
		fake_vehicle_id = uuid.uuid1().hex

		driver_role = model.DriverRole(
			name="name", HP=fake_hp, birthday=datetime.date.today(),
			vehicle_id=fake_vehicle_id, vehicle_type=model.VehicleType.TRUCK_1T
		)
		sender_role = model.SenderRole()
		auth = model.UserAuth(password="123")

		sender = model.User.create_user(
			session, auth, sender_role=sender_role
		)

		driver = model.User.create_user(
			session, auth, driver_role=driver_role
		)

	@pytest.mark.dependency(
		scope="session",
		name="test_membership",
		depends=["test_user_creation"]
	)
	def test_membership(
		self,
		session: orm.Session,
		sender: model.User,
		owner: model.User,
		member: model.User,
		company: model.Company,
	) -> None:
		assert company.sender_role is not None

		document = model.Document(
			doc_type=model.DocumentType.PDF,
			content=b"document"
		)
		session.add(document)
		session.flush([document])

		order = model.Order(
			sender_role_id=company.sender_role_id,
			did=document.id
		)
		session.add(order)
		session.commit()

		assert not sender.can_access(order)
		assert owner.can_access(order)
		assert member.can_access(order)

		session.delete(order)
		session.delete(document)
		session.commit()

	@pytest.mark.dependency(
		scope="session",
		name="test_order_page",
		depends=["test_user_creation"]
	)
	def test_order_page(
		self,
		session: orm.Session,
		sender: model.User,
		driver: model.User,
		other_sender: model.User,
		other_driver: model.User
	) -> None:
		assert sender.sender_role is not None
		assert driver.driver_role is not None

		# Initialize objects

		document = model.Document(
			doc_type=model.DocumentType.PDF,
			content=b"document"
		)
		session.add(document)
		session.flush([document])

		order = model.Order(
			sender_role_id=sender.sender_role_id,
			did=document.id
		)
		session.add(order)
		session.commit()

		expected: dict[tuple[str, str], list[model.Order]]
		users = {
			"sender": sender,
			"driver": driver,
			"other_sender": other_sender,
			"other_driver": other_driver
		}

		# Define helper functions

		def get_order(type: str, user: model.User) -> list[model.Order]:
			if type == "requested":
				condition = model.Order.state == model.OrderStatusEnum.REQUESTED
			elif type == "ongoing":
				condition = model.Order.state == model.OrderStatusEnum.ALLOCATED
				condition |= model.Order.state == model.OrderStatusEnum.SHIPPING
			elif type == "completed":
				condition = model.Order.state == model.OrderStatusEnum.COMPLETED
			else:
				raise ValueError()

			condition &= model.Order.can_user_access(user)
			board = model.PageBoard(model.Order, condition, session)
			return board.pages(1, 10, model.Order.ordered_time)

		def assert_expectation(expected: dict[tuple[str, str], list[model.Order]]) -> None:
			for i, (k, v) in enumerate(expected.items()):
				(method_type, user_type), expected_orders = k, v
				orders = get_order(method_type, users[user_type])
				assert orders == expected_orders

		# Test requested state
		# Each expected state follows the format:
		# ("order type", "requesting user"): [order, ...]

		order.state = model.OrderStatusEnum.REQUESTED
		session.commit()

		expected = {
			("requested", "sender"): [order],
			("requested", "driver"): [],
			("requested", "other_sender"): [],
			("requested", "other_driver"): [],
			("ongoing", "sender"): [],
			("ongoing", "driver"): [],
			("ongoing", "other_sender"): [],
			("ongoing", "other_driver"): [],
			("completed", "sender"): [],
			("completed", "driver"): [],
			("completed", "other_sender"): [],
			("completed", "other_driver"): [],
		}
		assert_expectation(expected)

		# Test allocated state

		order.driver_role_id = driver.driver_role.id
		order.state = model.OrderStatusEnum.ALLOCATED
		session.commit()

		expected = {
			("requested", "sender"): [],
			("requested", "driver"): [],
			("requested", "other_sender"): [],
			("requested", "other_driver"): [],
			("ongoing", "sender"): [order],
			("ongoing", "driver"): [order],
			("ongoing", "other_sender"): [],
			("ongoing", "other_driver"): [],
			("completed", "sender"): [],
			("completed", "driver"): [],
			("completed", "other_sender"): [],
			("completed", "other_driver"): [],
		}
		assert_expectation(expected)

		# Test finished state

		order.state = model.OrderStatusEnum.COMPLETED
		session.commit()

		expected = {
			("requested", "sender"): [],
			("requested", "driver"): [],
			("requested", "other_sender"): [],
			("requested", "other_driver"): [],
			("ongoing", "sender"): [],
			("ongoing", "driver"): [],
			("ongoing", "other_sender"): [],
			("ongoing", "other_driver"): [],
			("completed", "sender"): [order],
			("completed", "driver"): [order],
			("completed", "other_sender"): [],
			("completed", "other_driver"): [],
		}
		assert_expectation(expected)

		# Clean up

		session.delete(order)
		session.delete(document)
		session.commit()
