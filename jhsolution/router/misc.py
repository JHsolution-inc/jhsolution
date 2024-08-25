from typing import Annotated
import base64, structlog

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import model, utils
from . import dependency

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="templates")
logger = structlog.get_logger("JHsolution")

@router.get("/verify_email/{token_str}")
async def verify_email(
	token_str: str, request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
) -> Response:
	try:
		token = base64.urlsafe_b64decode(token_str)
		email_address = dependency.register_token_signer.unsign(token)['email']
	except:
		logger.warning("Failed to verify email")
		raise HTTPException(401)

	if user := model.User.get_user_or_none(session, email=email_address):
		logger.info("Create a new user", user=user, login_method="email")
		user.auth.has_email_verified = True
		session.commit()
	else:
		logger.fatal(
			"Email has verified, but the user with given email does not exist!!! "
			"User has deleted before verification or TOKEN SECURITY HAS BROKEN!",
			user=user, email=email_address, token=token
		)
		raise HTTPException(500)

	return templates.TemplateResponse(request, "auth/verified.jinja")

@router.get("/doc/{token}")
async def pass_document_view(
	request: Request,
	session: Annotated[orm.Session, Depends(dependency.get_db_session)],
	user: Annotated[model.User, Depends(dependency.get_user)],
	token: str,
) -> Response:
	did = dependency.pass_access_signer.unsign(token.encode())

	if document := model.Document.get_or_none(session, did):
		return StreamingResponse(iter([document.content]))
	else:
		raise HTTPException(403)
