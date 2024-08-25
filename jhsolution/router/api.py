from typing import Annotated, Optional
import base64, datetime, io, pypdf, structlog

from fastapi import (
	APIRouter, BackgroundTasks, Body, Depends, Form,
	HTTPException, Request, Response, UploadFile
)
from fastapi.responses import StreamingResponse
from fastapi.security.utils import get_authorization_scheme_param

from pydantic import BaseModel

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import model, utils
from jhsolution.model import UserInfo, OrderInfo, OrderContactInfo

from . import background, dependency

router = APIRouter()
logger = structlog.get_logger("JHsolution")

class JsonOrderData(BaseModel):
	columns: list[str]
	data: list[list[str]]

################################################################################
# Auth
################################################################################

@router.get('/token')
async def issue_token(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> str:
	authorization = request.headers.get("Authorization")
	scheme, param = get_authorization_scheme_param(authorization)

	if authorization and scheme.lower() == 'basic':
		try:
			parts = param.split(':')
			email_or_HP, password = parts[0], ':'.join(parts[1:])
		except:
			raise HTTPException(401)

		user: Optional[model.User] = None
		get_user = model.User.get_user_or_none

		if not user: user = get_user(session, HP=email_or_HP)
		if user and not user.has_verified: user = None
		if not user: user = get_user(session, email=email_or_HP)
		if user and not user.has_verified: user = None

		if user and user.has_valid_password(password):
			return dependency.api_access_token_signer.sign(user.id).decode()

	raise HTTPException(401)

@router.get('/token/new')
async def renew_token(user: Annotated[model.User, Depends(dependency.get_user)]) -> str:
	return dependency.api_access_token_signer.sign(user.id).decode()

################################################################################
# User Information
################################################################################

@router.get('/account')
async def user_info(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
) -> UserInfo:
	return UserInfo.model_validate(user.get(session, user.id))

@router.post('/account')
async def modify_user_info(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	user_info: UserInfo,
) -> Response:
	# NOTE: Modifying driver information is not allowed here and only admin can modify it

	if sender_role := user.sender_role:
		if user_info.company_name:
			sender_role.company_name = user_info.company_name
		if user_info.company_address:
			sender_role.company_address = user_info.company_address

	if user_info.company_name or user_info.company_address:
		session.commit()

	return Response(status_code=204)

@router.patch('/account/password')
async def change_password(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	password: Annotated[str, Body(embed=True)],
) -> Response:
	user.auth.set_password(password)
	session.commit()
	return Response(status_code=204)

################################################################################
# Order List
################################################################################

@router.post('/orders/json')
async def post_json(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order_data: JsonOrderData,
) -> dict[str, int]:
	# Check input and permission

	if user.sender_role is None:
		logger.warning("Only sender can post the order")
		raise HTTPException(403)

	if len(order_data.columns) == 0:
		logger.warning("Empty column")
		raise HTTPException(403)

	for row in order_data.data:
		if len(row) != len(order_data.columns):
			logger.warning("Broken row data")
			raise HTTPException(403)

	# Post the order

	json_data = order_data.model_dump_json().encode()

	document = model.Document(
		doc_type=model.DocumentType.JSON,
		content=json_data
	)

	session.add(document)
	session.flush([document])

	sender_role_id = user.company.sender_role_id if user.company else user.sender_role_id
	order = model.Order(did=document.id, sender_role_id=sender_role_id)
	session.add(order)
	session.commit()

	logger.info('Order has posted', order=order)

	return {"oid": order.id}

# Deprecated
@router.post('/orders/pdf')
async def post_pdf(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order_files: list[UploadFile],
) -> dict[str, int]:
	# Check input and permission

	total_size = 0

	for order_file in order_files:
		assert order_file.size is not None
		total_size += order_file.size

	if total_size > 100_000_000:
		logger.warning("file is too large")
		raise HTTPException(413)

	if user.sender_role is None:
		logger.warning("Only sender can post the order")
		raise HTTPException(403)

	# Merge pdf files

	order_pdf = pypdf.PdfWriter()
	for pdf_data in order_files:
		sub_pdf = pypdf.PdfReader(pdf_data.file)
		for page in sub_pdf.pages:
			order_pdf.add_page(page)

	buffer = io.BytesIO()
	order_pdf.write(buffer)
	buffer.seek(0)
	content = buffer.read()

	# Post the order

	document = model.Document(
		doc_type=model.DocumentType.PDF,
		content=content
	)

	session.add(document)
	session.flush([document])

	sender_role_id = user.company.sender_role_id if user.company else user.sender_role_id
	order = model.Order(did=document.id, sender_role_id=sender_role_id)
	session.add(order)
	session.commit()

	logger.info('Order has posted', order=order)

	return {"oid": order.id}

@router.get('/orders/requested')
async def requested_orders(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	page: int = 1, page_size: int = 10,
) -> list[OrderInfo]:
	if page_size > 50: page_size = 50

	condition = model.Order.state == model.OrderStatusEnum.REQUESTED
	condition &= model.Order.can_user_access(user)
	board = model.PageBoard(model.Order, condition, session)

	orders = board.pages(page, page_size, model.Order.ordered_time)
	return [OrderInfo.model_validate(order) for order in orders]

@router.get('/orders/ongoing')
async def ongoing_orders(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
) -> list[OrderInfo]:
	condition = model.Order.state == model.OrderStatusEnum.ALLOCATED
	condition |= model.Order.state == model.OrderStatusEnum.SHIPPING
	condition &= model.Order.can_user_access(user)
	board = model.PageBoard(model.Order, condition, session)

	orders = board.pages(1, board.count, model.Order.ordered_time)
	return [OrderInfo.model_validate(order) for order in orders]

@router.get('/orders/completed')
async def completed_orders(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	request: Request, page: int = 1, page_size: int = 10,
) -> list[OrderInfo]:
	if page_size > 50: page_size = 50

	condition = model.Order.state == model.OrderStatusEnum.COMPLETED
	condition &= model.Order.can_user_access(user)
	board = model.PageBoard(model.Order, condition, session)

	orders = board.pages(1, board.count, model.Order.ordered_time)
	return [OrderInfo.model_validate(order) for order in orders]

################################################################################
# Order Infos
################################################################################

@router.get('/orders/by-token/{order_token}')
async def order_item_by_token(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	order_token: str
) -> OrderInfo:
	signer = dependency.order_access_token_signer
	oid = signer.unsign(order_token.encode())
	if not oid: raise HTTPException(403)

	order = model.Order.get_or_none(session, oid)
	if not order: raise HTTPException(403)
	return OrderInfo.model_validate(order)

@router.get("/orders/by-token/{order_token}/document")
async def document_token_access(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	order_token: str
) -> Response:
	signer = dependency.order_access_token_signer
	oid = signer.unsign(order_token.encode())
	if not oid: raise HTTPException(403)

	order = model.Order.get_or_none(session, oid)
	if not order: raise HTTPException(403)

	file_format = order.document.doc_type.name.lower()
	return StreamingResponse(
		iter([order.document.content]),
		headers={"content-disposition": f'filename="{oid}.{file_format}"'}
	)

@router.get('/orders/{oid}')
async def order_item(
	order: Annotated[model.Order, Depends(dependency.get_order)],
) -> OrderInfo:
	return OrderInfo.model_validate(order)

@router.get("/orders/{oid}/document")
async def document(
	oid: int, order: Annotated[model.Order, Depends(dependency.get_order)]
) -> Response:
	file_format = order.document.doc_type.name.lower()
	return StreamingResponse(
		iter([order.document.content]),
		headers={"content-disposition": f'filename="{oid}.{file_format}"'}
	)

@router.get("/orders/{oid}/token")
async def get_order_token(
	request: Request,
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)]
) -> str:
	if user.can_access(order):
		signer = dependency.order_access_token_signer
		return signer.sign(order.id).decode()
	else:
		raise HTTPException(403)

@router.get("/orders/{oid}/contacts")
async def get_order_contacts(
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
) -> list[OrderContactInfo]:
	return list(map(OrderContactInfo.model_validate, order.contacts))

################################################################################
# Order Contact Modification
################################################################################

@router.post('/orders/{oid}/contacts')
async def append_order_contact(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
	contacts: Annotated[list[OrderContactInfo], Body()]
) -> list[OrderContactInfo]:
	if not user.is_sender:
		logger.warning("Only sender can modify order contacts")
		raise HTTPException(403)

	if order.has_finished:
		logger.warning("Cannot change contact for finished order")
		raise HTTPException(403)

	contact_models: list[model.OrderContact] = []
	for contact in contacts:
		role, name, HP = contact.role, contact.name, contact.HP

		if len(name) > 1000 or len(HP) > 1000:
			logger.warning("Unconventionally large name or HP", name=name, HP=HP)
			raise HTTPException(403)

		contact_model = model.OrderContact(oid=order.id, role=role, name=name, HP=HP)
		contact_models.append(contact_model)

	for contact_model in contact_models:
		session.add(contact_model)
	session.commit()

	validate = OrderContactInfo.model_validate
	return [validate(contact_model) for contact_model in contact_models]

@router.patch("/orders/{oid}/contacts/{cid}")
async def alter_order_contact(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
	order_contact: Annotated[model.OrderContact, Depends(dependency.get_order_contact)],
	name: Annotated[str, Body()] = "",
	HP: Annotated[str, Body()] = "",
) -> Response:
	if order.has_finished:
		logger.warning("Cannot change contact for finished order")
		raise HTTPException(403)

	if len(name) > 1000 or len(HP) > 1000:
		logger.warning("Unconventionally large name or HP", name=name, HP=HP)
		raise HTTPException(403)

	order_contact.name = name
	order_contact.HP = HP
	session.commit()

	return Response(status_code=204)

@router.delete("/orders/{oid}/contacts/{cid}")
async def delete_order_contact(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
	order_contact: Annotated[model.OrderContact, Depends(dependency.get_order_contact)],
) -> Response:
	if order.has_finished:
		logger.warning("Cannot change contact for finished order")
		raise HTTPException(403)
	
	session.delete(order_contact)
	session.commit()
	return Response(status_code=204)

################################################################################
# Order transactions
################################################################################

@router.post('/orders/{oid}/allocate')
async def allocate_order(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
	vehicle_id: Annotated[str, Body(embed=True)],
) -> Response:
	# Lock objects
	
	user = model.User.get(session, user.id, lock=True)
	order = model.Order.get(session, order.id, lock=True)

	# Check permission

	if not user.can_modify(order):
		logger.warning("Only allowed sender can allocate the order")
		raise HTTPException(403)
	if order.state != model.OrderStatusEnum.REQUESTED:
		logger.warning("Only requested order can be allocated")
		raise HTTPException(403)
	if order.driver is not None:
		logger.warning("Replacing driver is not allowed")
		raise HTTPException(403)

	get_driver_role = model.DriverRole.get_driver_role_or_none
	if driver_role := get_driver_role(session, vehicle_id=vehicle_id):
		driver = driver_role.user
	else:
		logger.warning("No driver with given vehicle id")
		raise HTTPException(403)

	if driver.has_deallocated(order):
		logger.warning("Reallocation is not allowed")
		raise HTTPException(403)

	# Execute action

	order_action = model.OrderAction(
		oid=order.id, uid=user.id, action=model.OrderActionEnum.ALLOCATE,
		description=f"Driver: {driver.id}"
	)
	session.add(order_action)

	order.state = model.OrderStatusEnum.ALLOCATED
	order.driver_role_id = driver_role.id

	session.commit()
	session.refresh(order)

	logger.info("Driver has allocated to the order", order=order)
	return Response(status_code=204)

@router.post('/orders/{oid}/deallocate')
async def deallocate_order(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
) -> Response:
	# Lock objects
	
	user = model.User.get(session, user.id, lock=True)
	order = model.Order.get(session, order.id, lock=True)

	# Check permission

	if order.state != model.OrderStatusEnum.ALLOCATED:
		logger.warning("Only Allocated order can be deallocated")
		raise HTTPException(403)
	if not user.is_driver:
		logger.warning("Only driver can deallocate")
		raise HTTPException(403)
	if user != order.driver:
		logger.warning("Only allocated driver can deallocate")
		raise HTTPException(403)

	# Execute action

	order_action = model.OrderAction(
		oid=order.id, uid=user.id, action=model.OrderActionEnum.DEALLOCATE
	)
	session.add(order_action)

	order.state = model.OrderStatusEnum.REQUESTED
	order.driver_role_id = None

	session.commit()
	session.refresh(order)

	logger.info("Driver has deallocated to the order", order=order)
	return Response(status_code=204)

@router.post('/orders/{oid}/onboard')
async def onboard_order(
	background_tasks: BackgroundTasks,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
	vender: str
) -> Response:
	# TODO: make permission checking logic into the method

	if not vender in ["kakao", "naver", "pass"]:
		raise HTTPException(403)
	if order.state != model.OrderStatusEnum.ALLOCATED:
		logger.warning("Only Allocated order can be onboarded")
		raise HTTPException(403)
	if not user.driver_role or user.driver_role != order.driver_role:
		logger.warning("Only allocated driver can onboard the order")
		raise HTTPException(403)

	purpose = model.SignPurposeEnum.CONFIRM_ONBOARD

	original_url = None
	if vender == 'pass':
		token = dependency.pass_access_signer.sign(order.did)
		original_url = f"/doc/{token.decode()}"

	name, HP, birthday =  user.driver_role.name, user.driver_role.HP, user.driver_role.birthday

	vender_enum = model.CertVenderEnum[vender.upper()]

	background_tasks.add_task(background.sign_order,
		name, HP, birthday, order, purpose, vender_enum
	)
	return Response(status_code=204)


@router.post('/orders/by-token/{order_token}/outboard')
async def outboard_order(
	background_tasks: BackgroundTasks,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	name: Annotated[str, Body()],
	HP: Annotated[str, Body()],
	birthday: Annotated[datetime.date, Body()],
	order_token: str, vender: str,
) -> Response:
	# TODO: make permission checking logic into the method

	signer = dependency.order_access_token_signer
	if oid := signer.unsign(order_token.encode()):
		order = model.Order.get(session, oid)
	else:
		logger.info("Invalid token")
		raise HTTPException(403)

	if not vender in ["kakao", "naver", "pass"]:
		raise HTTPException(403)
	if order.state != model.OrderStatusEnum.SHIPPING:
		logger.warning("Only shipping order can be outboarded")
		raise HTTPException(403)
	if not order.sender_role or not order.driver:
		logger.error("The order is shipping but sender or driver is not exist", order=order)
		raise HTTPException(403)

	if not order.get_contact(name, HP, model.OrderContactRole.RECEIVER):
		logger.warning("Invalid order contact", contact_name=name, contact_HP=HP)
		raise HTTPException(403)

	purpose = model.SignPurposeEnum.CONFIRM_OUTBOARD

	original_url = None
	if vender == 'pass':
		token = dependency.pass_access_signer.sign(order.did)
		original_url = f"/doc/{token.decode()}"

	vender_enum = model.CertVenderEnum[vender.upper()]

	background_tasks.add_task(background.sign_order,
		name, HP, birthday, order, purpose, vender_enum
	)
	return Response(status_code=204)

@router.post('/orders/{oid}/cancel')
async def cancel_order(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
) -> Response:
	# Lock objects

	user = model.User.get(session, user.id, lock=True)
	order = model.Order.get(session, order.id, lock=True)

	# Check permission

	Status = model.OrderStatusEnum
	if not order.state in [Status.REQUESTED, Status.ALLOCATED]:
		logger.warning("Only requested or allocated order can be canceled")
		raise HTTPException(403)
	if not user.is_sender:
		logger.warning("Only sender can cancel the order")
		raise HTTPException(403)

	# Execute action

	order_action = model.OrderAction(
		oid=order.id, uid=user.id, action=model.OrderActionEnum.CANCEL
	)
	session.add(order_action)

	order.state = Status.CANCELED
	order.driver_role_id = None

	session.commit()
	session.refresh(order)

	logger.info("Order has canceled", order=order)
	return Response(status_code=204)

@router.post('/orders/{oid}/set-failed')
async def set_order_failed(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
) -> Response:
	# Lock objects

	user = model.User.get(session, user.id, lock=True)
	order = model.Order.get(session, order.id, lock=True)

	# Check permission

	if order.state != model.OrderStatusEnum.SHIPPING:
		logger.warning("Only shipping order can be failed")
		raise HTTPException(403)
	if not user.is_sender:
		logger.warning("Only sender can make the order fail")
		raise HTTPException(403)
	if not order.can_be_failed:
		logger.warning("Only delayed order 48 hours or more can be failed")
		raise HTTPException(403)

	# Execute action

	order_action = model.OrderAction(
		oid=order.id, uid=user.id, action=model.OrderActionEnum.SET_FAILED
	)
	session.add(order_action)

	order.state = model.OrderStatusEnum.FAILED

	session.commit()
	session.refresh(order)

	logger.warning("Order has failed", order=order)
	return Response(status_code=204)
