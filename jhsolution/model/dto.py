from __future__ import annotations
from typing import Any, Optional
import datetime
from pydantic import BaseModel, ConfigDict
from jhsolution import model

class UserInfo(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: Optional[int] = None
	company_name: Optional[str] = None
	company_address: Optional[str] = None
	name: Optional[str] = None
	HP: Optional[str] = None
	birthday: Optional[datetime.date] = None
	vehicle_id: Optional[str] = None
	vehicle_type: Optional[model.VehicleType] = None

	@classmethod
	def model_validate(cls, user: Any, *,
		strict: Optional[bool] = None,
		from_attributes: Optional[bool] = None,
		context: Optional[dict[str, Any]] = None,
	) -> UserInfo:
		assert isinstance(user, model.User)
		user_info = super().model_validate(
			user, strict=strict, from_attributes=from_attributes, context=context
		)

		if user.sender_role:
			user_info.company_name = user.sender_role.company_name
			user_info.company_address = user.sender_role.company_address

		if user.driver_role:
			user_info.name = user.driver_role.name
			user_info.HP = user.driver_role.HP
			user_info.birthday = user.driver_role.birthday
			user_info.vehicle_id = user.driver_role.vehicle_id
			user_info.vehicle_type = user.driver_role.vehicle_type

		return user_info

class OrderInfo(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: int
	ordered_time: datetime.datetime
	state: model.OrderStatusEnum
	driver_id: Optional[int] = None

	@classmethod
	def model_validate(cls, order: Any, *,
		strict: Optional[bool] = None,
		from_attributes: Optional[bool] = None,
		context: Optional[dict[str, Any]] = None,
	) -> OrderInfo:
		assert isinstance(order, model.Order)
		order_info = super().model_validate(
			order, strict=strict, from_attributes=from_attributes, context=context
		)

		return order_info

class OrderContactInfo(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	role: model.OrderContactRole
	id: Optional[int] = None
	name: str = ""
	HP: str = ""
