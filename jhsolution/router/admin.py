from typing import Annotated, Optional
import datetime, structlog

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import model, utils
from jhsolution.env import ADMIN_SECRET_KEY
from . import dependency

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="templates")
logger = structlog.get_logger("JHsolution")

# Auth dependency

async def check_admin(request: Request)-> None:
	if not request.session.get("admin", False):
		logger.info("Admin access has failed")
		raise HTTPException(404)

async def get_company(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	company_id: int,
) -> model.Company:
	if company := model.Company.get_or_none(session, company_id):
		structlog.contextvars.bind_contextvars(company=company)
		return company

	logger.warning("Company does not exist", company_id=company_id)
	raise HTTPException(404)

def failed_redirection(path: str, reason: str) -> RedirectResponse:
	return RedirectResponse(f"/ADMIN{path}?failed_reason={reason}", status_code=302)

# Auth pages

@router.get('')
async def admin(request: Request) -> Response:
	if request.session.get('admin', False):
		return RedirectResponse('/ADMIN/drivers', status_code=302)
	return templates.TemplateResponse(request, "admin/auth.jinja")

@router.post("/auth")
async def auth(request: Request, password: Annotated[str, Form()]) -> Response:
	if password == ADMIN_SECRET_KEY:
		logger.warning("Admin access has granted")
		request.session['admin'] = True
	return RedirectResponse('/ADMIN', status_code=302)

@router.get("/logout", dependencies=[Depends(check_admin)])
async def logout(request: Request) -> Response:
	request.session.pop('admin', None)
	return RedirectResponse('/', status_code=302)

# Sender management pages

@router.get("/senders", dependencies=[Depends(check_admin)])
async def sender_list(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	page: int = 1, page_size: int = 50
) -> Response:
	condition = model.User.sender_role_id != None
	board = model.PageBoard(model.User, condition, session)
	max_page = utils.num_pages(board.count, page_size)
	senders = board.pages(page, page_size, model.User.register_time)

	return templates.TemplateResponse(request, "admin/senders.jinja", {
		"admin": True, "senders": senders, "page": page, "is_last_page": page >= max_page
	})

# Driver management pages

@router.get("/drivers", dependencies=[Depends(check_admin)])
async def driver_list(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	page: int = 1, page_size: int = 50, failed_reason: Optional[str] = None
) -> Response:
	condition = model.User.id == model.DriverRole.uid
	board = model.PageBoard(model.User, condition, session)
	max_page = utils.num_pages(board.count, page_size)
	drivers = board.pages(page, page_size, model.User.register_time)

	return templates.TemplateResponse(request, "admin/drivers.jinja", {
		"admin": True, "drivers": drivers, "page": page,
		"is_last_page": page >= max_page, "failed_reason": failed_reason,
	})

@router.post("/drivers", dependencies=[Depends(check_admin)])
async def post_driver(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	name: Annotated[str, Form()],
	HP: Annotated[str, Form()],
	birthday: Annotated[datetime.date, Form()],
	vehicle_id: Annotated[str, Form()],
	vehicle_type: Annotated[model.VehicleType, Form()],
	password: Annotated[str, Form()],
) -> Response:
	if model.DriverRole.get_driver_role_or_none(session, HP=HP):
		return RedirectResponse("/ADMIN/drivers?failed_reason=HP_EXIST", status_code=302)

	if model.DriverRole.get_driver_role_or_none(session, vehicle_id=vehicle_id):
		return RedirectResponse("/ADMIN/drivers?failed_reason=VEHICLE_ID_EXIST", status_code=302)

	auth = model.UserAuth()
	auth.set_password(password)
	driver_role = model.DriverRole(
		name=name, HP=HP, birthday=birthday,
		vehicle_id=vehicle_id, vehicle_type=vehicle_type
	)
	driver = model.User.create_user(
		session, auth, driver_role=driver_role, commit=True
	)

	return RedirectResponse("/ADMIN/drivers", status_code=302)

# User management pages

@router.get("/users/{uid}", dependencies=[Depends(check_admin)])
async def driver_page(
	request: Request, uid: int,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	failed_reason: Optional[str] = None
) -> Response:
	user = model.User.get_or_none(session, uid)
	if not user: raise HTTPException(404)

	return templates.TemplateResponse(request, "admin/user.jinja", {
		"admin":True, "user": user, "failed_reason": failed_reason
	})

@router.post("/users/{uid}", dependencies=[Depends(check_admin)])
async def edit_user_info(
	uid: int,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	company_name: Annotated[Optional[str], Form()] = None,
	company_address: Annotated[Optional[str], Form()] = None,
	name: Annotated[Optional[str], Form()] = None,
	HP: Annotated[Optional[str], Form()] = None,
	birthday: Annotated[Optional[datetime.date], Form()] = None,
	vehicle_id: Annotated[Optional[str], Form()] = None,
	vehicle_type: Annotated[Optional[model.VehicleType], Form()] = None,
) -> Response:
	user = model.User.get_or_none(session, uid)
	if user is None: raise HTTPException(404)

	if sender_role := user.sender_role:
		logger.debug("sender fields", company_name=company_name, company_address=company_address)
		if company_name: sender_role.company_name = company_name
		if company_address: sender_role.company_address = company_address
		session.commit()

	elif driver_role := user.driver_role:
		# Check duplicated field

		get_driver_role_or_none = model.DriverRole.get_driver_role_or_none

		other_driver_role = get_driver_role_or_none(session, HP=HP)
		if other_driver_role and other_driver_role != driver_role:
			return failed_redirection(f"/users/{uid}", "HP_EXIST")
		other_driver_role = get_driver_role_or_none(session, vehicle_id=vehicle_id)
		if other_driver_role and other_driver_role != driver_role:
			return failed_redirection(f"/users/{uid}", "VEHICLE_ID_EXIST")

		# Update driver information

		if name: driver_role.name = name
		if HP: driver_role.HP = HP
		if birthday: driver_role.birthday = birthday
		if vehicle_id: driver_role.vehicle_id = vehicle_id
		if vehicle_type: driver_role.vehicle_type = vehicle_type
		session.commit()

	else:
		return failed_redirection(f"users/{uid}", "NEITHER_SENDER_NOR_DRIVER")

	return RedirectResponse(f"/ADMIN/users/{user.id}", status_code=302)

@router.post("/users/{uid}/password", dependencies=[Depends(check_admin)])
async def change_driver_password(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	uid: int, password: Annotated[str, Form()]
) -> Response:
	user = model.User.get_or_none(session, uid)
	if user is None: raise HTTPException(404)
	user.auth.set_password(password)
	session.commit()
	return RedirectResponse(f"/ADMIN/users/{user.id}", status_code=302)

# Company management pages

@router.get("/companies", dependencies=[Depends(check_admin)])
async def company_list(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	page: int = 1, page_size: int = 50, failed_reason: Optional[str] = None
) -> Response:
	board = model.PageBoard(model.Company, sa.true(), session)
	max_page = utils.num_pages(board.count, page_size)
	companies = board.pages(page, page_size, model.Company.id)

	return templates.TemplateResponse(request, "admin/companies.jinja", {
		"admin": True, "companies": companies, "failed_reason": failed_reason,
		"page": page, "is_last_page": page >= max_page,
	})

@router.post("/companies", dependencies=[Depends(check_admin)])
async def post_company(
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	name: Annotated[str, Form()],
	owner_id: Annotated[int, Form()],
) -> Response:
	# Check constraints

	if model.Company.get_company_or_none(session, name=name):
		return RedirectResponse("/ADMIN/companies?failed_reason=NAME_EXIST", status_code=302)

	owner = model.User.get_or_none(session, owner_id)
	if owner is None or owner.sender_role is None:
		return RedirectResponse("/ADMIN/companies?failed_reason=USER_NOT_EXIST", status_code=302)
	if owner.company is not None:
		return RedirectResponse("/ADMIN/companies?failed_reason=USER_HAS_COMPANY", status_code=302)

	# Add company

	sender_role = model.SenderRole(company_name=owner.company_name, company_address=owner.company_address)
	session.add(sender_role)
	session.flush([sender_role])
	company = model.Company(name=name, owner_id=owner_id, sender_role_id=sender_role.id)
	session.add(company)
	session.flush([company])

	membership = model.CompanyMembership(company_id=company.id, member_id=owner_id)
	session.add(membership)
	session.commit()

	return RedirectResponse(f"/ADMIN/companies/{company.id}", status_code=302)

@router.get("/companies/{company_id}", dependencies=[Depends(check_admin)])
async def company_page(
	request: Request,
	company: Annotated[model.Company, Depends(get_company)],
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	page: int = 1, page_size: int = 50
) -> Response:
	sub_stmt = sa.select(model.CompanyMembership)
	sub_stmt = sub_stmt.where(model.CompanyMembership.member_id == model.User.id)
	condition = sa.not_(sa.exists(sub_stmt)) & (model.User.sender_role_id != None)

	board = model.PageBoard(model.User, condition, session)
	max_page = utils.num_pages(board.count, page_size)
	others = board.pages(page, page_size, model.User.register_time)

	return templates.TemplateResponse(request, "admin/company.jinja", {
		"admin": True, "company": company, "others": others, "page": page, "is_last_page": True
	})


@router.post("/companies/{company_id}/add-member", dependencies=[Depends(check_admin)])
async def add_member(
	uid: Annotated[int, Form()],
	company: Annotated[model.Company, Depends(get_company)],
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	user = model.User.get_or_none(session, uid)

	if user is None:
		return failed_redirection(f"companies/{company.id}", "USER_NOT_EXIST")
	if user.company is not None:
		return failed_redirection(f"companies/{company.id}", "USER_HAS_COMPANY")

	membership = model.CompanyMembership(company_id=company.id, member_id=user.id)
	session.add(membership)
	session.commit()

	return RedirectResponse(f"/ADMIN/companies/{company.id}", status_code=302)

@router.post("/companies/{company_id}/delete-member", dependencies=[Depends(check_admin)])
async def delete_member(
	uid: Annotated[int, Form()],
	company: Annotated[model.Company, Depends(get_company)],
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	user = model.User.get_or_none(session, uid)

	if user is None:
		return failed_redirection(f"companies/{company.id}", "USER_NOT_EXIST")
	if user.company is None or user.company != company:
		return failed_redirection(f"companies/{company.id}", "USER_NOT_EXIST")
	if user.company.owner == user:
		return failed_redirection(f"companies/{company.id}", "USER_IS_OWNER")

	session.delete(user.membership)
	session.commit()

	return RedirectResponse(f"/ADMIN/companies/{company.id}", status_code=302)

@router.post("/companies/{company_id}/set-owner", dependencies=[Depends(check_admin)])
async def set_owner(
	uid: Annotated[int, Form()],
	company: Annotated[model.Company, Depends(get_company)],
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	user = model.User.get_or_none(session, uid)

	if user is None or user.sender_role is None:
		return failed_redirection(f"companies/{company.id}", "USER_NOT_EXIST")
	if user.company is None or user.company != company:
		return failed_redirection(f"companies/{company.id}", "USER_NOT_EXIST")
	if user.company.owner == user:
		return failed_redirection(f"companies/{company.id}", "USER_IS_OWNER")

	company.owner_id = user.id

	session.commit()

	return RedirectResponse(f"/ADMIN/companies/{company.id}", status_code=302)
