from __future__ import annotations
from typing import Any, Optional, TYPE_CHECKING
import datetime, enum, hashlib, secrets, string

import sqlalchemy as sa
from sqlalchemy import orm
from jhsolution import model

if TYPE_CHECKING:
	from .user import User
	from .order import OrderActionEnum
	from .role import SenderRole

class MemberPermissionEnum(enum.Enum):
	MANAGE_ORDER = "MANAGE_ORDER"
	MANAGE_MEMBER = "MANAGE_MEMBER"

class Company(model.Base):
	__tablename__ = "company"
	__table_args__ = (sa.UniqueConstraint("name", name="company_unique_name"),)

	# Columns
	
	name: orm.Mapped[str] = orm.mapped_column()
	owner_id: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey("user.id"))
	sender_role_id: orm.Mapped[Optional[int]] = orm.mapped_column(
		sa.ForeignKey("sender_role.id", name="company_sender_role_id_fkey")
	)

	# Relations

	owner: orm.Mapped[User] = orm.relationship()
	sender_role: orm.Mapped[Optional[SenderRole]] = orm.relationship()
	memberships: orm.Mapped[list[CompanyMembership]] = orm.relationship(back_populates="company")

	# Properties

	@property
	def members(self) -> list[User]:
		return [membership.user for membership in self.memberships]

	# Class Methods

	@classmethod
	def get_company_or_none(cls,
		session: orm.Session,
		name: Optional[str] = None,
		owner_id: Optional[int] = None,
	) -> Optional[Company]:
		stmt = sa.select(cls)

		if name is not None and owner_id is not None:
			return None

		if name:
			stmt = stmt.where(cls.name == name)
		elif owner_id:
			stmt = stmt.where(cls.owner_id == owner_id)
		else:
			return None
		
		return session.scalars(stmt).one_or_none()

	@classmethod
	def get_company(cls, *args: Any, **kwargs: Any) -> Company:
		if company := cls.get_company_or_none(*args, **kwargs): return company
		raise sa.exc.NoResultFound()

	# Object Methods

	def can_modify(self, order: model.Order) -> bool:
		return order.sender_role == self.sender_role

class CompanyMembership(model.Base):
	__tablename__ = "company_membership"
	__table_args__ = (sa.UniqueConstraint("member_id", name="unique_member"),)

	# Columns

	company_id: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey("company.id"))
	member_id: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey("user.id"))

	# Relations

	company: orm.Mapped[Company] = orm.relationship(back_populates="memberships")
	user: orm.Mapped[User] = orm.relationship(back_populates="membership")
	permissions: orm.Mapped[list[CompanyMemberPermission]] = orm.relationship(
		back_populates="membership"
	)

class CompanyMemberPermission(model.Base):
	__tablename__ = "company_member_permission"

	# Columns

	company_membership_id: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey("company_membership.id"))
	permission: orm.Mapped[MemberPermissionEnum] = orm.mapped_column(
		sa.Enum(MemberPermissionEnum, name="member_permission")
	)

	# Relations

	membership: orm.Mapped[CompanyMembership] = orm.relationship(back_populates="permissions")
