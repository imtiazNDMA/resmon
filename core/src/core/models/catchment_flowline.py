"""``catchment_flowline`` — durable drainage vectors clipped to each reservoir catchment.

These are static hydrologic map features, separate from time-varying forcing. They can
come from HydroRIVERS or MERIT-derived stream vectors and are served through the
hydrologic GeoJSON API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CatchmentFlowline(Base):
    __tablename__ = "catchment_flowline"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    flowline_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    downstream_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stream_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upstream_area_km2: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    length_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    is_main_stem: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    geom: Mapped[object] = mapped_column(
        Geometry("MULTILINESTRING", srid=4326, spatial_index=False), nullable=False
    )
    source_dataset: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_catchment_flowline_reservoir", "reservoir_id"),
        Index("idx_catchment_flowline_geom", "geom", postgresql_using="gist"),
    )
