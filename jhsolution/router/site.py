from typing import Annotated, Any, Optional
import base64, datetime, structlog, urllib.parse

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import env, model, utils
from . import dependency

router =  APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="templates")
logger = structlog.get_logger("JHsolution")

################################################################################
# Static handlers
################################################################################

@router.get('/favicon.ico')
def favicon() -> Response:
	return FileResponse('static/assets/favicon.ico')

@router.get('/')
async def index(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	user = model.User.get_or_none(session, request.session.get('uid', None))
	return templates.TemplateResponse(request, "index.jinja", {
		'user': user, "test_mode": not env.IS_PRODUCTION
	})

@router.get('/terms')
async def term(
	request: Request, session: Annotated[orm.Session, Depends(dependency.get_db_session)]
) -> Response:
	user = model.User.get_or_none(session, request.session.get('uid', None))
	return templates.TemplateResponse(request, "terms/term.jinja", {'user': user})

################################################################################
# Auth and Account Page
################################################################################

@router.get("/login")
async def login(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	status: Optional[str] = None
) -> Response:
	if model.User.get_or_none(session, request.session.get('uid', None)):
		return RedirectResponse("/")
	return templates.TemplateResponse(request, "auth/login.jinja", {'status': status})

@router.get("/logout")
async def logout(request: Request) -> Response:
	request.session.pop('uid', None)
	return RedirectResponse('/', status_code=302)

@router.get("/register")
async def register(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	if model.User.get_or_none(session, request.session.get('uid', None)):
		return RedirectResponse("/")
	return templates.TemplateResponse(request, "auth/register.jinja")

# TODO: Move into api
@router.post("/register")
async def post_register(
	request: Request, background_tasks: BackgroundTasks,
	email: Annotated[str, Form()], password: Annotated[str, Form()],
) -> Response:
	url = request.url
	token = dependency.register_token_signer.sign({'email': email})
	token_str = urllib.parse.quote(base64.urlsafe_b64encode(token).decode())
	auth_url = f"{url.scheme}://{url.netloc}/verify_email/{token_str}"

	background_tasks.add_task(
		utils.register_email, email, password, auth_url
	)
	return RedirectResponse("/login?status=registered", status_code=302)

# TODO: Move this to api
@router.post('/login/password')
async def password_login(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	email_or_HP: Annotated[str, Form()],
	password: Annotated[str, Form()],
) -> Response:
	user: Optional[model.User] = None
	get_user = model.User.get_user_or_none

	if not user: user = get_user(session, HP=email_or_HP)
	if user and not user.has_verified: user = None
	if not user: user = get_user(session, email=email_or_HP)
	if user and not user.has_verified: user = None

	if user and user.has_valid_password(password):
		request.session['uid'] = user.id
		return RedirectResponse('/', status_code=302)

	return RedirectResponse('/login?status=failed', status_code=302)

@router.get('/login/google')
async def google_login(request: Request) -> Any:
	redirect_uri = request.url_for('google_auth')
	return await dependency.google_authenticator.auth_redirect(request, redirect_uri)

@router.get('/auth/google')
async def google_auth(request: Request,
	user: Annotated[model.User, Depends(dependency.google_redirect_token_to_user)]
) -> Response:
	request.session['uid'] = user.id
	return RedirectResponse('/', status_code=302)

@router.get('/account')
async def get_change_userinfo(
	request: Request,
	user: Annotated[model.User, Depends(dependency.get_user)],
) -> Response:
	return templates.TemplateResponse(request, "account.jinja", {'user': user})

################################################################################
# Order
################################################################################

@router.get('/orders/publish')
async def publish_order(
	request: Request,
	user: Annotated[model.User, Depends(dependency.get_user)],
) -> Response:
	return templates.TemplateResponse(request, "order/publish.jinja", {"user": user})

@router.get('/orders/requested')
async def requested_orders(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	page: int = 1, page_size: int = 10,
) -> Response:
	if page_size > 50: page_size = 50

	condition = model.Order.state == model.OrderStatusEnum.REQUESTED
	condition &= model.Order.can_user_access(user)
	board = model.PageBoard(model.Order, condition, session)

	orders = board.pages(page, page_size, model.Order.ordered_time)
	num_pages = utils.num_pages(board.count, page_size)

	return templates.TemplateResponse(request, "order/page.jinja", {
		'user': user, 'orders': orders, 'page_type': 'requested',
		'page': page, 'is_last_page': page >= num_pages,
		'timedelta': datetime.timedelta(hours=9),
	})

@router.get('/orders/ongoing')
async def ongoing_orders(
	request: Request,
	user: Annotated[model.User, Depends(dependency.get_user)],
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	condition = model.Order.state == model.OrderStatusEnum.ALLOCATED
	condition |= model.Order.state == model.OrderStatusEnum.SHIPPING
	condition &= model.Order.can_user_access(user)
	board = model.PageBoard(model.Order, condition, session)

	orders = board.pages(1, board.count, model.Order.ordered_time)

	return templates.TemplateResponse(request, "order/page.jinja", {
		'user': user, 'orders': orders, 'page_type': 'ongoing',
		'timedelta': datetime.timedelta(hours=9),
	})

@router.get('/orders/completed')
async def completed_orders(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	page: int = 1, page_size: int = 10,
) -> Response:
	if page_size > 50: page_size = 50

	condition = model.Order.state == model.OrderStatusEnum.COMPLETED
	condition &= model.Order.can_user_access(user)
	board = model.PageBoard(model.Order, condition, session)

	orders = board.pages(page, page_size, model.Order.ordered_time)
	num_pages = utils.num_pages(board.count, page_size)

	return templates.TemplateResponse(request, "order/page.jinja", {
		'user': user, 'orders': orders, 'page_type': 'completed',
		'page': page, 'is_last_page': page >= num_pages,
		'timedelta': datetime.timedelta(hours=9),
	})

@router.get("/orders/by-token/{order_token}")
async def external_order_view(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	order_token: str
) -> Response:
	signer = dependency.order_access_token_signer
	oid = signer.unsign(order_token.encode())
	if not oid: raise HTTPException(403)

	order = model.Order.get_or_none(session, oid)
	if not order: raise HTTPException(403)

	return templates.TemplateResponse(request, "order/viewer.jinja", {
		'order': order, 'token': order_token
	})

@router.get('/orders/{oid}')
async def order_view(
	request: Request,
	user: Annotated[model.User, Depends(dependency.get_user)],
	order: Annotated[model.Order, Depends(dependency.get_order)],
	status: Optional[str] = None,
) -> Response:
	signer = dependency.order_access_token_signer
	token = signer.sign(order.id).decode()

	return templates.TemplateResponse(request, "order/viewer.jinja", {
		'user': user, 'order': order, 'token': token, 'status': status
	})
