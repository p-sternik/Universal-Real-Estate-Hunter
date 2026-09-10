import json
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ListingModel(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portal: Mapped[str] = mapped_column(String(50), nullable=False)
    portal_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True, index=True)
    property_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_m2: Mapped[float] = mapped_column(Float, nullable=False)
    area_home: Mapped[float] = mapped_column(Float, nullable=False)
    area_plot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="dom", index=True)
    rooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    floor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    floors_in_building: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_private_owner: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    profile_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    building_type: Mapped[str] = mapped_column(String(50), default="inny")
    segment_subtype: Mapped[str] = mapped_column(String(50), default="nieokreślony")

    location_raw: Mapped[str] = mapped_column(String(500), default="")
    street: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    access_road_type: Mapped[str] = mapped_column(String(50), default="nieznana")
    market: Mapped[str] = mapped_column(String(50), default="nieokreślony")
    finish_condition: Mapped[str] = mapped_column(String(50), default="nieokreślony")
    has_visualisations: Mapped[bool] = mapped_column(Boolean, default=False)
    sewerage: Mapped[str] = mapped_column(String(50), default="nieznana")
    heating: Mapped[str] = mapped_column(String(50), default="nieznane")
    has_fiber: Mapped[bool] = mapped_column(Boolean, default=False)
    year_built: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    raw_description: Mapped[str] = mapped_column(Text, default="")
    main_image_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Location precision & Geoportal data
    is_exact_coords: Mapped[bool] = mapped_column(Boolean, default=True)
    parcel_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cadastral_area: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geoportal_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # CRM User Actions & Status
    user_status: Mapped[str] = mapped_column(String(30), default="NEW", index=True)
    user_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Qualification & Filtering Pipeline status
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    qualification_status: Mapped[str] = mapped_column(String(50), default="NEEDS_REVIEW", index=True)
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Serialized JSON lists of analysis insights
    _filter_reasons: Mapped[str] = mapped_column("filter_reasons", Text, default="[]")
    _pros: Mapped[str] = mapped_column("pros", Text, default="[]")
    _cons: Mapped[str] = mapped_column("cons", Text, default="[]")
    _gallery_images: Mapped[str] = mapped_column("gallery_images", Text, default="[]")

    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    price_history: Mapped[List["PriceHistoryModel"]] = relationship(
        "PriceHistoryModel",
        back_populates="listing",
        cascade="all, delete-orphan",
        order_by="PriceHistoryModel.recorded_at.desc()",
    )

    __table_args__ = (
        Index("ix_portal_and_portal_id", "portal", "portal_id"),
        Index("ix_qualification_notified", "is_qualified", "notified_at"),
    )

    @property
    def filter_reasons(self) -> List[str]:
        try:
            return json.loads(self._filter_reasons)
        except Exception:
            return []

    @filter_reasons.setter
    def filter_reasons(self, value: List[str]):
        self._filter_reasons = json.dumps(value or [], ensure_ascii=False)

    @property
    def pros(self) -> List[str]:
        try:
            return json.loads(self._pros)
        except Exception:
            return []

    @pros.setter
    def pros(self, value: List[str]):
        self._pros = json.dumps(value or [], ensure_ascii=False)

    @property
    def cons(self) -> List[str]:
        try:
            return json.loads(self._cons)
        except Exception:
            return []

    @cons.setter
    def cons(self, value: List[str]):
        self._cons = json.dumps(value or [], ensure_ascii=False)

    @property
    def gallery_images(self) -> List[str]:
        try:
            return json.loads(self._gallery_images)
        except Exception:
            return []

    @gallery_images.setter
    def gallery_images(self, value: List[str]):
        self._gallery_images = json.dumps(value or [], ensure_ascii=False)


class PriceHistoryModel(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_m2: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    listing: Mapped["ListingModel"] = relationship("ListingModel", back_populates="price_history")
 
 
class GeocacheModel(Base):
    __tablename__ = "geocache"

    query: Mapped[str] = mapped_column(String(300), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

