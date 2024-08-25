from typing import Any, Awaitable, Callable, Optional
from types import SimpleNamespace
import datetime, httpx, pathlib, pytest, structlog, time

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

import sqlalchemy as sa
from sqlalchemy import orm

import barocert

from jhsolution import model, router, utils
from jhsolution.main import logging_middleware
from jhsolution.router import dependency

logger = structlog.get_logger("JHsolution")

app = FastAPI()

@app.middleware("http")
async def middleware(
	request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
	return await logging_middleware(request, call_next)

app.include_router(router.api)
client = TestClient(app)

class TestAPI:
	@pytest.mark.dependency(
		scope="session", name="TestAPIDummy",
		depends=["TestModel", "test_signer"]
	)
	def test_start_dummy(self) -> None: pass

	@pytest.mark.dependency(
		scope="session", name="TestAPI",
		depends=["test_user_auth", "test_document_posting", "test_order_flow"]
	)
	def test_end_dummy(self) -> None: pass

	def user_access_token(self, user: model.User) -> bytes:
		return dependency.api_access_token_signer.sign(user.id)

	def token_access_header(self, token: bytes) -> dict[str, str]:
		return {"Authorization": f"Bearer {token.decode()}"}

	def user_access_header(self, user: model.User) -> dict[str, str]:
		return self.token_access_header(self.user_access_token(user))

	################################################################################
	# User test
	################################################################################

	@pytest.mark.dependency(
		scope="session", name="test_user_auth", depends=["TestAPIDummy"]
	)
	def test_user_auth(self, driver: model.User, password: str) -> None:
		user = driver

		headers = {"Authorization": f"Basic {user.HP}:{password}x"}
		response = client.get("/token", headers=headers)
		assert response.status_code != 200

		headers = {"Authorization": f"Basic {user.HP}:{password}"}
		response = client.get("/token", headers=headers)
		assert response.status_code == 200
		token = response.json()

		headers = {"Authorization": f"Bearer {token}"}
		response = client.get("/account", headers=headers)
		assert response.status_code == 200
		data = response.json()
		assert data["id"] == user.id

		headers = {"Authorization": f"Bearer {token[:-1]}"}
		response = client.get("/account", headers=headers)
		assert response.status_code != 200

	################################################################################
	# Document posting test
	################################################################################

	@pytest.mark.dependency(
		scope="session", name="test_document_posting", depends=["TestAPIDummy"]
	)
	def test_document_posting(self, session: orm.Session, sender: model.User) -> None:
		headers = self.user_access_header(sender)

		# Test pdf posting

		test_path = pathlib.Path(__file__).parent.resolve()
		files = {'order_files': open(f"{test_path}/test_file.pdf", "rb")}

		response = client.post(
			"/orders/pdf", headers=headers, files=files
		)
		assert response.status_code == 200
		pdf_oid = response.json()["oid"]

		# Test json posting

		columns = ["1", "2", "3", "4"]
		row = ["a", "b", "c", "d"]
		data = [row] * 10

		response = client.post(
			"/orders/json", headers=headers, json={"columns": columns, "data": data}
		)
		assert response.status_code == 200
		json_oid = response.json()["oid"]

		# Clean up

		pdf_order = model.Order.get(session, pdf_oid)
		pdf_document = pdf_order.document
		session.delete(pdf_order)
		session.delete(pdf_document)

		json_order = model.Order.get(session, json_oid)
		json_document = json_order.document
		session.delete(json_order)
		session.delete(json_document)

		session.commit()

	################################################################################
	# Order flow test
	################################################################################

	def send_action_request(
		self, method: str, role: str,
		sender: model.User, driver: model.User, order: model.Order
	) -> httpx.Response:
		sender_header = self.user_access_header(sender)
		driver_header = self.user_access_header(driver)
		access_token = dependency.order_access_token_signer.sign(order.id)
		headers = {"sender": sender_header, "driver": driver_header}

		assert sender.is_sender
		assert driver.is_driver

		request_headers, json = None, {}
		if role == "receiver":
			url = f"/orders/by-token/{access_token.decode()}/{method}?vender=kakao"
			json = {"name": "name", "birthday": "1980-01-01", "HP": "01012345678"}
		else:
			url = f"/orders/{order.id}/{method}?vender=kakao"
			request_headers = headers[role]

		if method == "allocate":
			assert driver.vehicle_id is not None
			json = {**json, "vehicle_id": driver.vehicle_id}

		return client.post(url, headers=request_headers, json=json)

	def subtest_order_action(
		self, allowed_method: str, allowed_role: Optional[str],
		sender: model.User, driver: model.User, order: model.Order
	) -> None:
		method = allowed_method
		roles = ["sender", "driver", "receiver"]

		for role in roles:
			if role == allowed_role: continue
			response = self.send_action_request(method, role, sender, driver, order)
			assert response.status_code // 100 == 4

		if allowed_role:
			role = allowed_role
			response = self.send_action_request(method, role, sender, driver, order)
			assert response.status_code == 204

	def reset_order(self, session: orm.Session, order: model.Order) -> None:
		select_stmt = sa.select(model.Signature)
		select_stmt = select_stmt.where(model.Signature.did == order.did)
		rows = session.execute(select_stmt).all()
		signatures = [row.Signature for row in rows]

		for signature in signatures:
			cert_result = signature.cert_result
			session.delete(signature)
			session.flush([signature])
			session.delete(cert_result)

		delete_stmt = sa.delete(model.OrderAction)
		delete_stmt = delete_stmt.where(model.OrderAction.oid == order.id)
		session.execute(delete_stmt)
		session.commit() # ???: just flushing raises error and commit resolves it but we don't know why

		order.state = model.OrderStatusEnum.REQUESTED
		order.driver_role_id = None
		session.commit()

	# TODO: test scenario generator helps to write scenario easily, but need to improve readability
	def run_test_set(
		self,
		session: orm.Session,
		sender: model.User,
		driver: model.User,
		order: model.Order,
		test_set: list[tuple[str, Optional[str]]],
		reset: bool = True
	) -> None:
		for i, (method, role) in enumerate(test_set):
			self.subtest_order_action(method, role, sender, driver, order)
		if reset:
			self.reset_order(session, order)

	@pytest.mark.dependency(
		scope="session",
		name="test_order_flow",
		depends=["test_user_auth"]
	)
	def test_order_flow(
		self,
		session: orm.Session,
		sender: model.User,
		driver: model.User,
		other_driver: model.User,
		order: model.Order,
		monkeypatch: pytest.MonkeyPatch,
	) -> None:
		# Monkey patch

		def requestSign(self: Any, clientCode: Any, sign: Any) -> Any:
			index = getattr(requestSign, 'index', 0)
			setattr(requestSign, 'index', index + 1)
			return SimpleNamespace(receiptID=index)

		def getSignStatus(self: Any,clientCode: Any, receiptID: Any) -> Any:
			return SimpleNamespace(
				receiptID=receiptID, clientCode=clientCode, state=1
			)
		
		def verifySign(
			self: Any, clientCode: Any, receiptID: Any, signVerify: Any = None
		) -> Any:
			return SimpleNamespace(
				receiptID=receiptID, state=1, signedData="fake signed data"
			)

		services = [
			barocert.KakaocertService,
			barocert.NavercertService,
			barocert.PasscertService
		]

		for service in services:
			monkeypatch.setattr(service, "requestSign", requestSign)
			monkeypatch.setattr(service, "getSignStatus", getSignStatus)
			monkeypatch.setattr(service, "verifySign", verifySign)
		
		def add_task(self: Any, function: Any, *args: Any, **kwargs: Any) -> None:
			function(*args, **kwargs)
	
		monkeypatch.setattr(BackgroundTasks, "add_task", add_task)

		# Initialization

		contact = model.OrderContact(
			oid=order.id, name="name", HP="01012345678",
			role=model.OrderContactRole.RECEIVER
		)

		session.add(contact)
		session.commit()

		def test_scenarios(
			allowed_role: str, allowed_method: str, disallowed_methods: list[str]
		) -> list[tuple[str, Optional[str]]]:
			disallowed_cases = [(method, None) for method in disallowed_methods]
			return disallowed_cases + [(allowed_method, allowed_role)]

		all_methods = [
			"allocate", "deallocate", "onboard", "outboard", "cancel", "set-failed"
		]

		# Successful Flow Test

		self.run_test_set(session, sender, driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="allocate",
				disallowed_methods=["deallocate", "onboard", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="driver", allowed_method="onboard", 
				disallowed_methods=["allocate", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="receiver", allowed_method="outboard",
				disallowed_methods=["allocate", "deallocate", "onboard", "cancel", "set-failed"]
			),
			*[(method, None) for method in all_methods] # should be disallowed for all methods
		])

		# Deallocation Flow Test

		self.run_test_set(session, sender, driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="allocate",
				disallowed_methods=["deallocate", "onboard", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="driver", allowed_method="deallocate",
				disallowed_methods=["allocate", "outboard", "set-failed"]
			),
			# should be disallowed for all methods excepts cancel method
			*[(method, None) for method in all_methods if not method in ["cancel"]]
		], reset=False)

		self.run_test_set(session, sender, other_driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="allocate",
				disallowed_methods=["deallocate", "onboard", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="driver", allowed_method="onboard",
				disallowed_methods=["allocate", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="receiver", allowed_method="outboard",
				disallowed_methods=["allocate", "deallocate", "onboard", "cancel", "set-failed"]
			),
			*[(method, None) for method in all_methods]
		])

		# Cancel Flow Test on Allocated State

		self.run_test_set(session, sender, driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="allocate",
				disallowed_methods=["deallocate", "onboard", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="sender", allowed_method="cancel",
				disallowed_methods=["allocate", "outboard", "set-failed"]
			),
			*[(method, None) for method in all_methods]
		])

		# Cancel Flow Test on Deallocated State

		self.run_test_set(session, sender, driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="allocate",
				disallowed_methods=["deallocate", "onboard", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="driver", allowed_method="deallocate",
				disallowed_methods=["allocate", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="sender", allowed_method="cancel",
				disallowed_methods=["allocate", "deallocate", "onboard", "outboard", "set-failed"]
			),
			*[(method, None) for method in all_methods]
		])

		# Cancel Flow Test on Deallocated State

		self.run_test_set(session, sender, driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="allocate",
				disallowed_methods=["deallocate", "onboard", "outboard", "set-failed"]
			),
			*test_scenarios(
				allowed_role="driver", allowed_method="onboard",
				disallowed_methods=["allocate", "outboard", "set-failed"]
			),
		], reset=False)

		for action in order.actions:
			if action.action == model.OrderActionEnum.ONBOARD:
				action.timestamp -= datetime.timedelta(days=2)
		session.commit()

		self.run_test_set(session, sender, driver, order, test_set=[
			*test_scenarios(
				allowed_role="sender", allowed_method="set-failed",
				disallowed_methods=["allocate", "deallocate", "onboard", "cancel"]
			),
			*[(method, None) for method in all_methods]
		])

		# Clean up

		session.delete(contact)
		session.commit()
