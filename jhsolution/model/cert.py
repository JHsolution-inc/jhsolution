from __future__ import annotations
from typing import Optional, TYPE_CHECKING
import datetime, enum

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import model

if TYPE_CHECKING:
	from .user import User
	from .order import Document

# Enums

class CertVenderEnum(enum.Enum):
	KAKAO = 'KAKAO'
	NAVER = 'NAVER'
	PASS = 'PASS'

class CertStateEnum(enum.Enum):
	STANDBY = 'STANDBY'
	COMPLETED = 'COMPLETED'
	EXPIRED = 'EXPIRED'
	FAILED = 'FAILED'

class CertErrorStageEnum(enum.Enum):
	REQUEST = 'REQUEST'
	GET_STATUS = 'GET_STATUS'
	VERIFY = 'VERIFY'

# Cert Result

class CertResult(model.Base):
	__tablename__ = 'cert_result'

	# Columns

	state: orm.Mapped[CertStateEnum] = orm.mapped_column(
		sa.Enum(CertStateEnum, name='cert_state'), nullable=False,
		server_default=CertStateEnum.STANDBY.value
	)
	vender: orm.Mapped[CertVenderEnum] = orm.mapped_column(
		sa.Enum(CertVenderEnum, name='cert_vender'), nullable=False
	)

	receipt_id: orm.Mapped[str] = orm.mapped_column(nullable=True)
	signed_data: orm.Mapped[str] = orm.mapped_column(nullable=True, deferred=True)

	cert_time: orm.Mapped[datetime.datetime] = orm.mapped_column(
		sa.DateTime(timezone=True), server_default=sa.func.now()
	)

	error_stage: orm.Mapped[CertErrorStageEnum] = orm.mapped_column(
		sa.Enum(CertErrorStageEnum, name='cert_error_stage'), nullable=True
	)
	error_code: orm.Mapped[int] = orm.mapped_column(nullable=True)
	error_message: orm.Mapped[str] = orm.mapped_column(nullable=True)

class Signature(model.Base):
	__tablename__ = 'signature'

	# Columns

	did: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey('document.id'))
	cert_result_id: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey('cert_result.id'))

	# Relations

	document: orm.Mapped[Document] = orm.relationship()
	cert_result: orm.Mapped[CertResult] = orm.relationship()

	# Properties

	@property
	def vender(self) -> CertVenderEnum:
		return self.cert_result.vender

	@property
	def state(self) -> CertStateEnum:
		return self.cert_result.state

	@property
	def signed_data(self) -> Optional[str]:
		return self.cert_result.signed_data

	@property
	def error_stage(self) -> Optional[CertErrorStageEnum]:
		return self.cert_result.error_stage

	@property
	def error_code(self) -> Optional[int]:
		return self.cert_result.error_code

	@property
	def error_message(self) -> Optional[str]:
		return self.cert_result.error_message
