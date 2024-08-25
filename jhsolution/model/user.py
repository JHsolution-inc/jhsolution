from __future__ import annotations
from typing import Any, Optional, TYPE_CHECKING
import datetime, enum, hashlib, secrets, string

import sqlalchemy as sa
from sqlalchemy import orm
from jhsolution import model

if TYPE_CHECKING:
	from .company import Company, CompanyMembership
	from .role import DriverRole, SenderRole, VehicleType

class User(model.Base):
	__tablename__ = "user"

	# Columns

	register_time: orm.Mapped[datetime.datetime] = orm.mapped_column(
		sa.DateTime(timezone=True), server_default=sa.func.now()
	)
	sender_role_id: orm.Mapped[Optional[int]] = orm.mapped_column(
		sa.ForeignKey("sender_role.id", name="user_sender_role_fkey")
	)

	# Relations

	auth: orm.Mapped[UserAuth] = orm.relationship(back_populates="user")
	driver_role: orm.Mapped[Optional[DriverRole]] = orm.relationship(back_populates="user")
	sender_role: orm.Mapped[Optional[SenderRole]] = orm.relationship()
	membership: orm.Mapped[Optional[CompanyMembership]] = orm.relationship(back_populates="user")

	# Properties

	## Common Properties

	@property
	def email(self) -> Optional[str]:
		return self.auth.email

	@property
	def is_sender(self) -> bool:
		return self.sender_role is not None

	@property
	def is_driver(self) -> bool:
		return self.driver_role is not None

	@property
	def has_email_verified(self) -> bool:
		return self.auth.has_email_verified

	@property
	def has_verified(self) -> bool:
		if self.is_driver: return True
		if self.is_sender: return self.has_email_verified
		return False

	## Sender Properties

	@property
	def company(self) -> Optional[Company]:
		if not self.membership: return None
		return self.membership.company

	@property
	def is_owner(self) -> bool:
		return self.company is not None and self.company.owner == self

	@property
	def company_name(self) -> Optional[str]:
		if self.company and self.company.owner != self:
			return self.company.owner.company_name
		elif self.sender_role:
			return self.sender_role.company_name
		else:
			return None

	@property
	def company_address(self) -> Optional[str]:
		if self.company and self.company.owner != self:
			return self.company.owner.company_address
		elif self.sender_role:
			return self.sender_role.company_address
		else:
			return None

	## Driver Properties

	@property
	def name(self) -> Optional[str]:
		if not self.driver_role: return None
		return self.driver_role.name

	@property
	def HP(self) -> Optional[str]:
		if not self.driver_role: return None
		return self.driver_role.HP

	@property
	def birthday(self) -> Optional[datetime.date]:
		if not self.driver_role: return None
		return self.driver_role.birthday

	@property
	def vehicle_id(self) -> Optional[str]:
		if not self.driver_role: return None
		return self.driver_role.vehicle_id

	@property
	def vehicle_type(self) -> Optional[VehicleType]:
		if not self.driver_role: return None
		return self.driver_role.vehicle_type

	# Object Methods

	def to_dict(self) -> dict[str, Any]:
		ret = super().to_dict()
		ret.pop("password_salt", None)
		ret.pop("password_sha512", None)
		return ret

	def has_valid_password(self, password: str) -> bool:
		return self.auth.is_valid_password(password)

	def can_access(self, order: model.Order) -> bool:
		if self.can_modify(order): return True
		if self.driver_role and self.driver_role.can_access(order): return True
		return False

	def can_modify(self, order: model.Order) -> bool:
		if self.sender_role == order.sender_role: return True
		if self.company and self.company.sender_role == order.sender_role: return True
		return False

	def has_deallocated(self, order: model.Order) -> bool:
		for action in order.actions:
			DEALLOCATE = model.OrderActionEnum.DEALLOCATE
			if self == action.user and action.action == DEALLOCATE:
				return True
		return False

	# Class methods

	@classmethod
	def get_user_or_none(cls,
		session: orm.Session,
		email: Optional[str] = None,
		google_id: Optional[str] = None,
		HP: Optional[str] = None,
		vehicle_id: Optional[str] = None,
	) -> Optional[User]:
		stmt = sa.select(cls)

		kwarg_list = [email, google_id, HP, vehicle_id]
		num_kwarg = len([kwarg for kwarg in kwarg_list if kwarg is not None])

		if num_kwarg != 1:
			return None

		if email is not None:
			stmt = stmt.where(model.UserAuth.uid == cls.id)
			stmt = stmt.where(model.UserAuth.email == email)
		elif google_id is not None:
			stmt = stmt.where(model.UserAuth.uid == cls.id)
			stmt = stmt.where(model.UserAuth.google_id == google_id)
		elif HP is not None:
			stmt = stmt.where(model.DriverRole.uid == cls.id)
			stmt = stmt.where(model.DriverRole.HP == HP)
		elif vehicle_id is not None:
			stmt = stmt.where(model.DriverRole.uid == cls.id)
			stmt = stmt.where(model.DriverRole.vehicle_id == vehicle_id)
		else:
			return None

		return session.scalars(stmt).one_or_none()

	@classmethod
	def get_user(cls, *args: Any, **kwargs: Any) -> User:
		if user := cls.get_user_or_none(*args, **kwargs): return user
		raise sa.exc.NoResultFound()

	@classmethod
	def create_user(cls,
		session: orm.Session,
		auth: UserAuth,
		commit: bool = False,
		sender_role: Optional[SenderRole] = None,
		driver_role: Optional[DriverRole] = None,
	) -> User:
		if not sender_role and not driver_role:
			raise ValueError()
		if sender_role and driver_role:
			raise ValueError()
		if not auth.is_valid_auth:
			raise ValueError()

		user = User()
		session.add(user)

		if sender_role:
			session.add(sender_role)
			session.flush([sender_role])
			user.sender_role_id = sender_role.id

		session.flush([user])
		auth.uid = user.id
		session.add(auth)

		if driver_role:
			driver_role.uid = user.id
			session.add(driver_role)

		if commit: session.commit()
		session.refresh(user)

		return user

class UserAuth(model.Base):
	__tablename__ = "user_auth"
	__table_args__ = (sa.UniqueConstraint("google_id"),)

	# Columns

	uid: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey("user.id"))
	google_id: orm.Mapped[Optional[str]] = orm.mapped_column(nullable=True)
	email: orm.Mapped[Optional[str]] = orm.mapped_column(nullable=True)
	has_email_verified: orm.Mapped[bool] = orm.mapped_column(server_default=sa.sql.false())
	password_salt: orm.Mapped[Optional[bytes]] = orm.mapped_column(nullable=True)
	password_sha512: orm.Mapped[Optional[bytes]] = orm.mapped_column(nullable=True)

	# Relations or Properties

	user: orm.Mapped[User] = orm.relationship(back_populates="auth")

	@property
	def is_valid_auth(self) -> bool:
		if self.google_id:
			return True
		if self.password_salt and self.password_sha512:
			return True
		return False

	@property
	def password(self) -> str:
		raise AttributeError()

	@password.setter
	def password(self, pw: str) -> None:
		self.set_password(pw)

	# Methods

	def __init__(self, *args: Any, password: Optional[str] = None, **kwargs: Any) -> None:
		super().__init__(*args, **kwargs)
		if password is not None: self.set_password(password)

	def set_password(self, password: str) -> None:
		base = string.ascii_letters + string.digits
		self.password_salt = "".join([secrets.choice(base) for _ in range(16)]).encode()
		self.password_sha512 = hashlib.sha512(self.password_salt + password.encode()).digest()

	def is_valid_password(self, password: str) -> bool:
		if not self.password_salt or not self.password_sha512: return False
		return self.password_sha512 == hashlib.sha512(self.password_salt + password.encode()).digest()
