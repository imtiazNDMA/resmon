"""``catchment_subbasin`` — the upstream catchment left un-dissolved.

``reservoir.catchment_geom`` stores the HydroBASINS upstream **union**; this table keeps
the individual basins that go into it, one row each, with the ``NEXT_DOWN`` topology and
an ``is_headwater`` flag marking the top of the catchment. Written by
``remote_sensing.gee_real.delineate_subbasins``, served to the map by
``/geojson/subbasins``. PK ``(reservoir_id, hybas_id)``.
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CatchmentSubbasin(Base):
    __tablename__ = "catchment_subbasin"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    hybas_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # HydroBASINS HYBAS_ID
    next_down: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 0 at the basin outlet
    is_headwater: Mapped[bool] = mapped_column(Boolean, nullable=False)  # nothing drains into it
    geom: Mapped[object] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )  # GIST index defined explicitly below, matching reservoir's geometry columns
    catchment_version: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. 'hybas7_v1'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_catchment_subbasin_geom", "geom", postgresql_using="gist"),)
