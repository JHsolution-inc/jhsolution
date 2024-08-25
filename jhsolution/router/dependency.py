from __future__ import annotations
from typing import Annotated, Any, Optional, Type
import base64, datetime, requests, structlog, urllib.parse

from fastapi import BackgroundTasks, Depends, HTTPException, Request, UploadFile, WebSocket
from fastapi.security.utils import get_authorization_scheme_param

import sqlalchemy as sa
from sqlalchemy import orm
from jhsolution import model, utils

MINUTES = 60
HOURS = 60 * MINUTES
DAYS = 24 * HOURS
MONTHS = 30 * DAYS

logger = structlog.get_logger("JHsolution")
google_authenticator = utils.GoogleAuthenticator()
register_token_signer = utils.TokenSigner('register', 1 * HOURS)
api_access_token_signer = utils.TokenSigner('api_access_token', 1 * MONTHS)
order_access_token_signer = utils.TokenSigner('order_access_token', 1 * HOURS)
pass_access_signer = utils.TokenSigner('pass_access', 5 * MINUTES)
car365_api_signer = utils.TokenSigner('car365', 5 * MINUTES)

################################################################################
# ORM Dependencies
################################################################################

async def get_db_session(request: Request) -> orm.Session:
	session: orm.Session = request.scope["database_session"]
	return session

async def get_user(
	request: Request,
	session: Annotated[orm.Session, Depends(get_db_session)]
) -> model.User:
	authorization = request.headers.get("Authorization")
	scheme, param = get_authorization_scheme_param(authorization)

	if authorization and scheme.lower() == 'bearer':
		uid = api_access_token_signer.unsign(param.encode()) # Header token
	else:
		uid = request.session.get('uid', None) # Cookie token

	if user := model.User.get_or_none(session, uid):
		structlog.contextvars.bind_contextvars(user=user)
		return user
	else:
		logger.warning("Failed to unsign the token")
		raise HTTPException(401)

async def get_order(
	session: Annotated[orm.Session, Depends(get_db_session)],
	user: Annotated[model.User, Depends(get_user)],
	oid: int,
) -> model.Order:
	order = model.Order.get_or_none(session, oid)
	if order and user.can_access(order):
		structlog.contextvars.bind_contextvars(order=order)
		return order

	logger.warning("Given order is not exist or user have no permission", oid=oid)
	raise HTTPException(403)

async def get_order_contact(
	session: Annotated[orm.Session, Depends(get_db_session)],
	user: Annotated[model.User, Depends(get_user)],
	order: Annotated[model.Order, Depends(get_order)],
	cid: int,
) -> model.OrderContact:
	logger = structlog.get_logger("JHsolution")
	logger = logger.bind(cid=cid)

	order_contact = model.OrderContact.get_or_none(session, cid)

	if not user.can_modify(order):
		logger.warning("Access on order contact is allowed only for sender")
		raise HTTPException(403)
	if not order_contact:
		logger.warning("Order contact is not exist")
		raise HTTPException(403)
	if order_contact.oid != order.id:
		logger.warning("Order contact is not linked to the order")
		raise HTTPException(403)

	structlog.contextvars.bind_contextvars(order_contact=order_contact)
	return order_contact

################################################################################
# google oauth dependencies
################################################################################

async def google_redirect_token_to_user( # pragma: no cover
	request: Request,
	session: Annotated[orm.Session, Depends(get_db_session)],
) -> model.User:
	try:
		google_token = await google_authenticator.auth_token(request)
	except:
		logger.warning("Failed to auth google token (might be a CSRF attack)")
		raise HTTPException(401)

	try:
		return utils.google_userinfo_to_user(session, google_token['userinfo'])
	except:
		logger.error(
			"Failed to parse information from the google",
			google_token=google_token
		)
		raise HTTPException(500)

async def google_access_token_to_user( # pragma: no cover
	session: Annotated[orm.Session, Depends(get_db_session)],
	token: str,
) -> model.User:
	response = google_authenticator.request_auth_token(token)

	if response.status_code != 200:
		logger.warning("Failed to get token information by requested token", token=token)
		raise HTTPException(response.status_code)

	try:
		return utils.google_userinfo_to_user(session, response.json() )
	except:
		raise HTTPException(500)
