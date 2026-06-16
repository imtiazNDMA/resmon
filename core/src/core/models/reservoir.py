"""``reservoir`` — config-driven core entity (minimal Phase 0 form).

Phase 0 lands only the columns the frozen-contract tables FK against and the
orbit/pass config the RS pipeline needs. The full entity (AOI/catchment geometry,
release thresholds, rating-curve config, capacity history) lands in Phase 1.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Reservoir(Base):
    __tablename__ = "reservoir"

    reservoir_id: Mapped[str] = mapped_column(Text, primary_key=True)  # slug
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    basin: Mapped[str] = mapped_column(Text, nullable=False)
    frl_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    live_capacity_bcm: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    orbit_relative: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_direction: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("frl_m > 0", name="ck_reservoir_frl_positive"),
        CheckConstraint("live_capacity_bcm > 0", name="ck_reservoir_capacity_positive"),
        CheckConstraint("pass_direction IN ('ASC','DESC')", name="ck_reservoir_pass_dir"),
    )
