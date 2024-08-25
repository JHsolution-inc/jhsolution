from typing import Annotated, Optional
import base64, datetime, hashlib, structlog, urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import model

from jhsolution.env import (
	CAR365_INSTT_CODE,
	CAR365_SVC_CODE,
	CAR365_SITE_URL,
	CAR365_SITE_NAME,
)

from . import dependency

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="templates")
logger = structlog.get_logger("JHsolution")

@router.get("/car365-api-test")
async def car365_api_test(
	request: Request,
	user: Annotated[model.User, Depends(dependency.get_user)],
	result: Optional[str] = None,
	token: Optional[str] = None,
) -> Response:
	if not user.is_driver:
		raise HTTPException(404)

	if result in ["accepted", "denied"]:
		if not token: raise HTTPException(403)

		return_token = base64.urlsafe_b64decode(token)
		token_uid = dependency.car365_api_signer.unsign(return_token)

		logger.debug(await request.body())
		if token_uid != user.id:
			logger.warning("token and uid mismatch")
			raise HTTPException(403)
		
		return templates.TemplateResponse(request, "car-api.jinja", {
			"user": user, "result": result
		})

	hash_salt = b"ts2020"
	time_stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
	hash_input = CAR365_INSTT_CODE.encode() + time_stamp.encode() + hash_salt
	hash_value = hashlib.sha256(hash_input).hexdigest()

	url = request.url
	return_token = dependency.car365_api_signer.sign(user.id)
	token_str = urllib.parse.quote(base64.urlsafe_b64encode(return_token).decode())
	success_url = f"{url.scheme}://{url.netloc}/car365-api-test/accepted?token={token_str}"
	failure_url = f"{url.scheme}://{url.netloc}/car365-api-test/denied?token={token_str}"

	assert user.name is not None
	assert user.vehicle_id is not None

	api_request_parameters = {
		"hashValue": hash_value,
		"timeStamp": time_stamp,
		"svcCodeArr": CAR365_SVC_CODE,
		"siteURL": CAR365_SITE_URL,
		"siteName": CAR365_SITE_NAME.encode("euckr").decode("utf8", "ignore"),
		"carOwner": user.name.encode("euckr").decode("utf8", "ignore"),
		"carRegNo": user.vehicle_id.encode("euckr").decode("utf8", "ignore"),
		"returnURLA": success_url,
		"returnURLD": failure_url,
	}

	return templates.TemplateResponse(request, "car-api.jinja", {
		"user": user, "request_params": api_request_parameters
	})
