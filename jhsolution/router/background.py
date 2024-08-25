from typing import Literal, Optional
import base64, datetime, enum, structlog, time

#from asn1crypto import cms
#from oscrypto import asymmetric

from fastapi import HTTPException
import sqlalchemy as sa
from sqlalchemy import orm
import barocert

from jhsolution import env, model
from jhsolution.utils import BarocertService, CertResult
from . import dependency

logger = structlog.get_logger("JHsolution")

################################################################################
# Cert logic
################################################################################

def sign_document_hash(
	name: str, HP: str, birthday: datetime.date,
	title: str, message: str, sha256token: str,
	vender: model.CertVenderEnum,
	original_url: Optional[str] = None
) -> CertResult:
	logger = structlog.get_logger("JHsolution")
	logger = logger.bind(
		name=name, HP=HP, birthday=birthday,
		title=title, message=message,
		sha256token=sha256token,
	)
	logger.debug("Sign task has started")

	# Prepare api kwargs

	kwargs = {
		'receiverName':     name,
		'receiverHP':       HP,
		'receiverBirthday': birthday.strftime('%Y%m%d'),

		'token':            sha256token,
		'tokenType':        'HASH',
	}

	if vender.name == "KAKAO":
		kwargs = {**kwargs,
			'signTitle':    title,
			'extraMessage': message,
		}

	if vender.name == "NAVER":
		kwargs = {**kwargs,
			'reqTitle':      title,
			'reqMessage':    message,
		}

	if vender.name == "PASS":
		if original_url is None: raise ValueError()
		kwargs = {**kwargs,
			'reqMessage':         message,
			'originalURL':        original_url,
			'originalTypeCode':   'CT',
			'originalFormatCode': 'DOWNLOAD_DOCUMENT',
		}

	# Execute cert request

	vender_name: Literal["kakao", "naver", "pass"]
	if vender.name == "KAKAO":
		vender_name, client_code = "kakao", env.BAROCERT_KAKAO_CLIENTCODE
	elif vender.name == "NAVER":
		vender_name, client_code = "naver", env.BAROCERT_NAVER_CLIENTCODE
	elif vender.name == "PASS":
		vender_name, client_code = "pass", env.BAROCERT_PASS_CLIENTCODE

	expire_in = dependency.pass_access_signer.max_age
	cert_service = BarocertService(
		vender_name, "Sign", client_code, env.BAROCERT_LINKID,
		env.BAROCERT_SECRETKEY, env.CALL_CENTER_NUM, expire_in
	)

	return cert_service.try_request(**kwargs)

def sign_order(
	name: str, HP: str, birthday: datetime.date,
	order: model.Order, purpose: model.SignPurposeEnum,
	vender: model.CertVenderEnum,
	original_url: Optional[str] = None,
) -> None:
	# TODO: make permission check logic into method
	# TODO: Lock object on the session block

	# Check permission

	if purpose == model.SignPurposeEnum.CONFIRM_ONBOARD:
		if order.state != model.OrderStatusEnum.ALLOCATED:
			logger.warning("Only allocated order can be onboarded")
			raise HTTPException(403)
	elif purpose == model.SignPurposeEnum.CONFIRM_OUTBOARD:
		if order.state != model.OrderStatusEnum.SHIPPING:
			logger.warning("Only shipping order can be outboarded")
			raise HTTPException(403)

	# Try to sign the order

	request_title = 'JH솔루션 전자서명 요청'
	if purpose == model.SignPurposeEnum.CONFIRM_ONBOARD:
		request_message = "화주의 화물을 상차했음을 확인합니다."
	elif purpose == model.SignPurposeEnum.CONFIRM_OUTBOARD:
		request_message = "기사님이 하차를 완료했음을 확인합니다."
	else:
		raise HTTPException(403)

	if not env.IS_PRODUCTION:
		request_title = f"[테스트] {request_title}"
		request_message= f"[테스트] {request_message}"

	with orm.Session(model.engine) as session:
		order = model.Order.get(session, order.id)
		sha256token = base64.urlsafe_b64encode(order.document.sha256).decode('utf-8')

	try:
		cert_result_response = sign_document_hash(
			name, HP, birthday,
			request_title, request_message,
			sha256token, vender, original_url

		)

		StateEnum = model.CertStateEnum
		state_code_to_state = [
			StateEnum.STANDBY,
			StateEnum.COMPLETED,
			StateEnum.EXPIRED,
			StateEnum.FAILED,
			StateEnum.FAILED,
			StateEnum.FAILED,
		]

		try:
			state = state_code_to_state[cert_result_response.state]
		except:
			state = StateEnum.FAILED

		cert_result = model.CertResult(
			state=state,
			vender=vender,
			receipt_id=cert_result_response.receiptID,
			signed_data=cert_result_response.signedData
		)
	except barocert.BarocertException as be:
		logger.warning(
			"Failed to sign the order",
			error_code=be.code, error_message=be.message
		)
		cert_result = model.CertResult(
			state=model.CertStateEnum.FAILED,
			error_code=be.code, error_message=be.message
		)

	# Save results into the database

	with orm.Session(model.engine) as session:
		session.add(cert_result)

		if cert_result.state == model.CertStateEnum.COMPLETED:
			logger.info("Sign has completed")
			session.flush([cert_result])
			signature = model.Signature(did=order.did, cert_result_id=cert_result.id)
			session.add(signature)

			order = model.Order.get(session, order.id)
			action = model.OrderAction(oid=order.id)
			session.add(action)

			if purpose == model.SignPurposeEnum.CONFIRM_ONBOARD:
				action.action = model.OrderActionEnum.ONBOARD
				order.state = model.OrderStatusEnum.SHIPPING
			elif purpose == model.SignPurposeEnum.CONFIRM_OUTBOARD:
				action.action = model.OrderActionEnum.OUTBOARD
				order.state = model.OrderStatusEnum.COMPLETED

		else:
			logger.warning("Sign has failed")
			signature = None

		session.commit()
