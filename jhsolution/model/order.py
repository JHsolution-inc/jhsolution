from __future__ import annotations
from typing import Any, Optional, TYPE_CHECKING
import enum, datetime, hashlib

import sqlalchemy as sa
from sqlalchemy import orm
from jhsolution import model
import structlog

if TYPE_CHECKING:
	from .user import User
	from .role import DriverRole, SenderRole

# Enums

class OrderStatusEnum(enum.Enum):
	REQUESTED = 'REQUESTED'
	CANCELED = 'CANCELED'
	ALLOCATED = 'ALLOCATED'
	SHIPPING = 'SHIPPING'
	COMPLETED = 'COMPLETED'
	FAILED = 'FAILED'

class OrderActionEnum(enum.Enum):
	ALLOCATE = "ALLOCATE"
	DEALLOCATE = "DEALLOCATE"
	ONBOARD = "ONBOARD"
	OUTBOARD = "OUTBOARD"
	CANCEL = "CANCEL"
	SET_FAILED = "SET_FAILED"

class OrderContactRole(enum.Enum):
	SENDER = 'SENDER'
	RECEIVER = 'RECEIVER'

class DocumentType(enum.Enum):
	PDF = 'PDF'
	JSON = 'JSON'

class SignPurposeEnum(enum.Enum):
	CONFIRM_ONBOARD = 'CONFIRM_ONBOARD'
	CONFIRM_OUTBOARD = 'CONFIRM_OUTBOARD'

# Models

class Order(model.Base):
	__tablename__ = 'order'

	# Columns

	did: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey('document.id'))
	sender_role_id: orm.Mapped[Optional[int]] = orm.mapped_column(
		sa.ForeignKey('sender_role.id', name='order_sender_role_id_fkey'),
		nullable=True, server_default=sa.null()
	)
	driver_role_id: orm.Mapped[Optional[int]] = orm.mapped_column(
		sa.ForeignKey('driver_role.id', name='order_driver_role_id_fkey'),
		nullable=True, server_default=sa.null()
	)
	ordered_time: orm.Mapped[datetime.datetime] = orm.mapped_column(
		sa.DateTime(timezone=True), server_default=sa.func.now()
	)
	state: orm.Mapped[OrderStatusEnum] = orm.mapped_column(
		sa.Enum(OrderStatusEnum, name='order_state'), nullable=False,
		server_default=OrderStatusEnum.REQUESTED.name
	)

	# Relations

	document: orm.Mapped[Document] = orm.relationship(back_populates='order')
	contacts: orm.Mapped[list[OrderContact]] = orm.relationship(back_populates='order')
	sender_role: orm.Mapped[Optional[SenderRole]] = orm.relationship()
	driver_role: orm.Mapped[Optional[DriverRole]] = orm.relationship()
	actions: orm.Mapped[list[OrderAction]] = orm.relationship(back_populates='order')

	# Properties

	@property
	def shipped_time(self) -> Optional[datetime.datetime]:
		for action in self.actions:
			if action.action == OrderActionEnum.ONBOARD:
				return action.timestamp
		return None

	@property
	def driver(self) -> Optional[User]:
		return self.driver_role.user if self.driver_role else None

	@property
	def has_finished(self) -> bool:
		return self.state in [
			model.OrderStatusEnum.COMPLETED,
			model.OrderStatusEnum.CANCELED,
			model.OrderStatusEnum.FAILED,
		]

	@property
	def can_be_failed(self) -> bool:
		now = datetime.datetime.now(tz=self.ordered_time.tzinfo)
		if not self.shipped_time:
			return False
		if now - self.shipped_time < datetime.timedelta(days=2):
			return False
		if self.state != model.OrderStatusEnum.SHIPPING:
			return False
		return True

	# Object methods

	def get_contact(
		self, name: str, HP: str, role: Optional[OrderContactRole] = None
	) -> Optional[OrderContact]:
		for contact in self.contacts:
			if contact.name == name and contact.HP == HP and (not role or role == contact.role):
				return contact
		return None

	# Class Methods

	@classmethod
	def can_user_access(cls, user: model.User) -> sa.BooleanClauseList:
		"""Used for order page query"""
		# ???: Should consider when user is both sender and driver?

		condition = sa.true() == sa.true()
		condition &= sa.true() == sa.true()

		# Check sender access permission

		assert user.is_sender or user.is_driver

		if user.is_sender:
			if user.company:
				sub_condition = cls.sender_role_id == model.Company.sender_role_id
				sub_condition &= model.Company.id == model.CompanyMembership.company_id
				sub_condition &= model.CompanyMembership.member_id == user.id
				# TODO: Make sender can select its role and check the role of the order
				#sub_condition |= cls.sender_role_id == user.sender_role_id
			else:
				sub_condition = cls.sender_role_id == user.sender_role_id
			condition &= sub_condition

		# Check driver access permission

		if user.is_driver:
			condition &= cls.driver_role_id == model.DriverRole.id
			condition &= model.DriverRole.uid == user.id

		return condition

class Document(model.Base):
	__tablename__ = 'document'

	# Columns

	doc_type: orm.Mapped[DocumentType] = orm.mapped_column(
		sa.Enum(DocumentType, name='document_type')
	)
	content: orm.Mapped[bytes] = orm.mapped_column(deferred=True)
	sha256: orm.Mapped[bytes]
	sha512: orm.Mapped[bytes]
	upload_time: orm.Mapped[datetime.datetime] = orm.mapped_column(
		sa.DateTime(timezone=True), server_default=sa.func.now()
	)

	# Relations

	order: orm.Mapped[Order] = orm.relationship(back_populates='document', uselist=False)

	# Methods

	def __init__(self, **kwargs: Any) -> None:
		super().__init__(**kwargs)
		self.sha256 = hashlib.sha256(self.content).digest()
		self.sha512 = hashlib.sha512(self.content).digest()

class OrderAction(model.Base):
	__tablename__ = 'order_action_history'

	# Columns

	oid: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey('order.id'))
	uid: orm.Mapped[Optional[int]] = orm.mapped_column(sa.ForeignKey('user.id'), nullable=True)
	action: orm.Mapped[OrderActionEnum] = orm.mapped_column(
		sa.Enum(OrderActionEnum, name='order_action')
	)
	description: orm.Mapped[Optional[str]] = orm.mapped_column(nullable=True)
	timestamp: orm.Mapped[datetime.datetime] = orm.mapped_column(
		sa.DateTime(timezone=True), server_default=sa.func.now()
	)

	# Relations

	order: orm.Mapped[Order] = orm.relationship(back_populates='actions', uselist=False)
	user: orm.Mapped[User] = orm.relationship()

class OrderContact(model.Base):
	__tablename__ = 'order_contact'

	oid: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey('order.id'))
	name: orm.Mapped[str]
	HP: orm.Mapped[str]
	role: orm.Mapped[OrderContactRole] = orm.mapped_column(
		sa.Enum(OrderContactRole, name='order_contact_role')
	)

	order: orm.Mapped[Order] = orm.relationship(back_populates='contacts')
