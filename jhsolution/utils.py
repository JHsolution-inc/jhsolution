from typing import Any, Literal, Optional
from types import SimpleNamespace
from collections import namedtuple
import base64, datetime, itsdangerous, json, requests, smtplib, ssl, structlog, time

#from asn1crypto import cms
#from oscrypto import asymmetric

import barocert
from barocert import BarocertException

import sqlalchemy as sa
from sqlalchemy import orm

from fastapi import HTTPException

from starlette.config import Config
from starlette.requests import Request
from starlette.datastructures import URL

from authlib.integrations.starlette_client import OAuth

from jhsolution import env, model

logger = structlog.get_logger("JHsolution")

################################################################################
# Non-interactive utils
################################################################################

def num_pages(count: int, page_size: int) -> int :
	return (count - 1) // page_size + 1

class TokenSigner:
	def __init__(self, token_type: str, max_age: int):
		self.token_type = token_type
		self.max_age = max_age
		self.signer = itsdangerous.TimestampSigner(env.SESSION_SECRET_KEY)

	def sign(self, data: Any) -> bytes:
		wrapped_data = {self.token_type: data}
		encoded_data = base64.urlsafe_b64encode(json.dumps(wrapped_data).encode())
		return self.signer.sign(encoded_data)

	def unsign(self, token: bytes) -> Any:
		try:
			unsigned_data = self.signer.unsign(token, max_age=self.max_age)
			decoded_data = json.loads(base64.urlsafe_b64decode(unsigned_data))
			return decoded_data[self.token_type]
		except Exception as e:
			logger.warning("Failed to unsign token", token=token)
			return None

################################################################################
# Email
################################################################################

def send_email(receiver_address: str, message: str, headers: dict[str, str] = {}) -> None:
	context = ssl.create_default_context()
	with smtplib.SMTP(env.EMAIL_SMTP_SERVER, 587) as server:
		server.starttls(context=context)
		server.login(env.EMAIL_ADDRESS, env.EMAIL_PASSWORD)

		headers = {"From": env.EMAIL_ADDRESS, "To": receiver_address, **headers}

		row_message = ''
		for header, value in headers.items():
			row_message += f'{header}: {value}\r\n'
		row_message += '\r\n'
		row_message += message

		server.sendmail(env.EMAIL_ADDRESS, receiver_address, row_message.encode())
		logger.info(f"Mail has sent to address [{receiver_address}]", email_address=receiver_address)

def register_email(email_address: str, password: str, auth_url: str) -> None:
	with orm.Session(model.engine) as session:
		if user := model.User.get_user_or_none(session, email=email_address):
			logger.warning(
				"Email register has denied because it already exists",
				email=email_address
			)
			raise HTTPException(403)

		sender_role = model.SenderRole()

		auth = model.UserAuth(email=email_address)
		auth.set_password(password)

		user = model.User.create_user(
			session, auth, commit=True, sender_role=sender_role
		)

		logger.info("Create new user (email registration)", user=user)

	subject = "JH솔루션 이메일 인증 링크 (noreply)"
	message = f"인증 링크 - {auth_url}"

	send_email(email_address, message, {"Subject": subject})

################################################################################
# Google oauth
################################################################################

class GoogleAuthenticator:
	def __init__(self) -> None:
		self.oauth = OAuth(Config())
		self.oauth.register(
			name='google',
			client_kwargs={'scope': 'openid email profile'},
			server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
		)

	async def auth_redirect(self, request: Request, uri: URL) -> Any:
		return await self.oauth.google.authorize_redirect(request, uri)

	async def auth_token(self, request: Request) -> Any:
		return await self.oauth.google.authorize_access_token(request)

	def request_auth_token(self, id_token: str) -> requests.Response:
		url = "https://www.googleapis.com/oauth2/v3/tokeninfo"
		return requests.get(url,  params={'id_token': id_token})

def google_userinfo_to_user(
	session: orm.Session, userinfo: dict[str, str]
) -> model.User:
	try:
		name = userinfo['name']
		google_id = userinfo['sub']
	except:
		logger.error("Failed to parse information from the google", userinfo=userinfo)
		raise HTTPException(500)

	user = model.User.get_user_or_none(session, google_id=google_id)
	if not user:
		sender_role = model.SenderRole()

		auth = model.UserAuth(google_id=google_id)
		user = model.User.create_user(
			session, auth, commit=True, sender_role=sender_role
		)

		logger.info("Create a new user", user=user, login_method="google")

	return user

################################################################################
# barocert
################################################################################

CertResult = namedtuple("CertResult", ["receiptID", "state", "signedData", "ci"])

# Pure barocert wrapper, does not depend on our code
# TODO: Add signature verification
class BarocertService:
	def __init__(
		self,
		vender: Literal["kakao", "naver", "pass"],
		certPurpose: Literal["CMS", "Identity", "Sign"],
		clientCode: str, linkid: str, secretkey: str,
		callCenterNum: str,
		expireIn: int
	):
		self.vender = vender
		self.clientCode = clientCode
		self.certPurpose = certPurpose
		self.callCenterNum = callCenterNum
		self.expireIn = expireIn 

		if self.vender == "kakao":
			self.service = barocert.KakaocertService(linkid, secretkey)
		elif self.vender == "naver":
			self.service = barocert.NavercertService(linkid, secretkey)
		elif self.vender == "pass":
			self.service = barocert.PasscertService(linkid, secretkey)
		else:
			raise NotImplementedError()
	
	def encrypt(self, **kwargs: Any) -> dict[str, Any]:
		encrypted_arguments = [
			"receiverName",
			"receiverHP",
			"receiverBirthday",
			"token",
			"reqMessage",
			"extraMessage",
		]

		for key, arg in kwargs.items():
			if key in encrypted_arguments:
				kwargs[key] = self.service._encrypt(arg)

		return kwargs

	def request(self, **kwargs: Any) -> Any:
		kwargs["expireIn"] = self.expireIn
		if self.vender != "kakao":
			kwargs["callCenterNum"] = self.callCenterNum

		kwargs = self.encrypt(**kwargs)
		method = getattr(self.service, f"request{self.certPurpose}")
		return method(self.clientCode, SimpleNamespace(**kwargs))
	
	def getStatus(self, receipt_id: str) -> Any:
		method = getattr(self.service, f"get{self.certPurpose}Status")
		return method(self.clientCode, receipt_id)

	def verify(self, receipt_id: str, **kwargs: Any) -> Any:
		method = getattr(self.service, f'verify{self.certPurpose}')
		if self.vender == "pass":
			kwargs = self.encrypt(**kwargs)
			return method(self.clientCode, receipt_id, SimpleNamespace(**kwargs))
		else:
			return method(self.clientCode, receipt_id)

	def try_request(self, **kwargs: Any) -> CertResult:
		# Request stage

		response = self.request(**kwargs)
		receipt_id = response.receiptID

		# Status check stage

		status = self.getStatus(receipt_id)
		expire = datetime.datetime.now() + datetime.timedelta(seconds=self.expireIn)

		while status.state == 0 and datetime.datetime.now() < expire:
			status = self.getStatus(receipt_id)
			time.sleep(1)

		# Verification stage
		# 0: standby
		# 1: completed
		# 2: expired
		# 3: denied
		# 4: failed
		# 5: not processed

		if status.state == 1:
			pass_kwargs = {}
			if self.vender == "pass":
				pass_kwargs = {k:kwargs[k] for k in ['receiverHP', 'receiverName']}
			result = self.verify(receipt_id, **kwargs)

			signed_data = result.signedData
			try:
				ci = result.ci
			except:
				ci = None
		else:
			signed_data, ci = None, None

		return CertResult(
			receiptID=receipt_id,
			state=status.state,
			signedData=signed_data,
			ci=ci
		)
