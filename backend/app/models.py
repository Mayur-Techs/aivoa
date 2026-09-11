from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ComplaintRecord(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    batch_lot_number: Mapped[str | None] = mapped_column(String(120), index=True)
    complaint_data: Mapped[dict] = mapped_column(JSON)
    risk_data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
