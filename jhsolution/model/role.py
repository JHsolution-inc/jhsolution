from __future__ import annotations
from typing import Any, Optional, TYPE_CHECKING
import datetime, enum

import sqlalchemy as sa
from sqlalchemy import orm
from jhsolution import model

if TYPE_CHECKING:
	from .user import User
	from .company import Company

# Enums

class VehicleType(enum.Enum):
	TRUCK_1T = "TRUCK_1T"
	TRUCK_1_4T = "TRUCK_1_4T"
	TRUCK_2_5T = "TRUCK_2_5T"
	TRUCK_3_5T = "TRUCK_3_5T"
	TRUCK_5T = "TRUCK_5T"
	TRUCK_11T = "TRUCK_11T"
	TRUCK_18T = "TRUCK_18T"
	TRUCK_25T = "TRUCK_25T"

# Models

class DriverRole(model.Base):
	__tablename__ = "driver_role"
	__table_args__ = (
		sa.UniqueConstraint("uid"),
		sa.UniqueConstraint("HP"),
		sa.UniqueConstraint("vehicle_id"),
	)

	# Columns or Relations

	uid: orm.Mapped[int] = orm.mapped_column(sa.ForeignKey("user.id"))

	name: orm.Mapped[str]
	HP: orm.Mapped[str]
	birthday: orm.Mapped[datetime.date]

	vehicle_id: orm.Mapped[str]
	vehicle_type: orm.Mapped[VehicleType] = orm.mapped_column(sa.Enum(VehicleType, name="vehicle_type"))

	user: orm.Mapped[User] = orm.relationship(back_populates="driver_role")

	# Class Methods

	@classmethod
	def get_driver_role_or_none(cls,
		session: orm.Session,
		HP: Optional[str] = None,
		vehicle_id: Optional[str] = None,
	) -> Optional[DriverRole]:
		if not HP and not vehicle_id:
			return None

		stmt = sa.select(cls)
		if HP:
			stmt = stmt.where(cls.HP == HP)
		if vehicle_id:
			stmt = stmt.where(cls.vehicle_id == vehicle_id)

		return session.execute(stmt).scalar_one_or_none()

	@classmethod
	def get_driver_role(cls, *args: Any, **kwargs: Any) -> DriverRole:
		if driver_role := cls.get_driver_role_or_none(*args, **kwargs):
			return driver_role
		raise sa.exc.NoResultFound()

	# Object Methods

	def can_access(self, order: model.Order) -> bool:
		return order.driver_role == self

class SenderRole(model.Base):
	__tablename__ = "sender_role"

	company_name: orm.Mapped[str] = orm.mapped_column(nullable=True)
	company_address: orm.Mapped[str] = orm.mapped_column(nullable=True)

	def can_access(self, order: model.Order) -> bool:
		return order.sender_role == self
