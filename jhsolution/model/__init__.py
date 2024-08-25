from __future__ import annotations
from typing import Any, Generic, Optional, Type, TypeVar, Union
import enum, datetime

import sqlalchemy as sa
from sqlalchemy import orm

from jhsolution import env
url = env.DATABASE_URL

engine = sa.create_engine(url, echo=env.DATABASE_ECHO)
CLS = TypeVar("CLS", bound="Base")

class Base(orm.DeclarativeBase):
	id: orm.Mapped[int] = orm.mapped_column(primary_key=True)

	@classmethod
	def get(
		cls: Type[CLS],
		session: orm.Session,
		id: int,
		*args: Any,
		exception: Exception = sa.exc.NoResultFound(),
		**kwargs: Any
	) -> CLS:
		if ret := cls.get_or_none(session, id, *args, **kwargs):
			return ret
		raise exception

	@classmethod
	def get_or_none(
		cls: Type[CLS], session: orm.Session, id: int, lock: bool = False
	) -> Optional[CLS]:
		stmt = sa.select(cls).where(cls.id == id)
		if lock: stmt = stmt.with_for_update()
		return session.scalars(stmt).one_or_none()

	def to_dict(self) -> dict[str, Any]:
		ret: dict[str, Any] = {}
		for column in self.__table__.columns:
			if column_value := getattr(self, column.name):
				if isinstance(column_value, enum.Enum):
					ret[column.name] = column_value.name
				elif isinstance(column_value, datetime.date):
					ret[column.name] = column_value.isoformat()
				else:
					ret[column.name] = column_value
		return ret

class PageBoard(Generic[CLS]):
	def __init__(self,
		Table: Type[CLS],
		condition: sa.ColumnExpressionArgument[bool],
		session: orm.Session
	):
		self.Table = Table
		self.condition = condition
		self.session = session

	@property
	def count(self) -> int:
		stmt = sa.select(sa.func.count()).select_from(self.Table).where(self.condition)
		return self.session.scalars(stmt).one()

	def pages(
		self,
		index: int,
		size: int,
		sort_key: sa.ColumnExpressionArgument[Any],
		desc: bool = True
	) -> list[CLS]:
		order_func = sa.desc if desc else sa.asc
		stmt = sa.select(self.Table).where(self.condition)
		stmt = stmt.offset((index-1) * size).limit(size)
		stmt = stmt.order_by(order_func(sort_key))
		rows = self.session.execute(stmt).all()
		return [row._t[0] for row in rows]

from .user import *
from .company import *
from .order import *
from .role import *
from .cert import *
from .dto import *
