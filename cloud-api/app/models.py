from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    role = Column(String(50), nullable=False, default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_admin(self) -> bool:
        return (self.role or "").lower() == "admin"

    @is_admin.setter
    def is_admin(self, value: bool) -> None:
        self.role = "admin" if value else "user"


class Layer(Base):
    __tablename__ = "layers"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "provider",
            "created_by_user_id",
            name="uq_layers_name_provider_user",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(50), nullable=False, default="postgis")
    uri = Column(String(1024), nullable=True)
    description = Column(Text, nullable=True)
    group_name = Column(String(255), nullable=True)
    schema = Column(String(255), nullable=True, default="public")
    srid = Column(Integer, nullable=True)
    epsg = Column(Integer, nullable=True)
    geom_type = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_by = relationship("User", backref="layers")
