from datetime import datetime, timezone
from typing import List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    BuildingType,
    FinishCondition,
    HeatingType,
    MarketType,
    OwnerType,
    PropertyCategory,
    QualificationStatus,
    RoadType,
    SegmentSubtype,
    SewerageType,
)


class Coordinates(BaseModel):
    latitude: float
    longitude: float


class FilterResult(BaseModel):
    is_qualified: bool
    status: QualificationStatus
    score: float = 0.0
    passed_stage1: bool
    stage1_reasons: List[str] = Field(default_factory=list)
    passed_stage2: bool
    stage2_reasons: List[str] = Field(default_factory=list)
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    is_corner: bool = False
    has_parking_or_garage: bool = False
    matched_whitelist_area: Optional[str] = None
    finish_condition: FinishCondition = FinishCondition.NIEOKRESLONY
    has_visualisations: bool = False
    sewerage: SewerageType = SewerageType.NIEZNANA
    heating: HeatingType = HeatingType.NIEZNANE
    has_fiber: bool = False


class ListingSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str
    portal: str
    title: str
    url: str
    price: float
    price_per_m2: float
    area_home: float
    area_plot: Optional[float] = None
    building_type: BuildingType = BuildingType.INNY
    segment_subtype: SegmentSubtype = SegmentSubtype.NIEOKRESLONY
    location_raw: str
    street: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    coordinates: Optional[Tuple[float, float]] = None
    access_road_type: RoadType = RoadType.NIEZNANA
    market: MarketType = MarketType.NIEOKRESLONY
    finish_condition: FinishCondition = FinishCondition.NIEOKRESLONY
    has_visualisations: bool = False
    sewerage: SewerageType = SewerageType.NIEZNANA
    heating: HeatingType = HeatingType.NIEZNANE
    has_fiber: bool = False
    category: PropertyCategory = PropertyCategory.DOM
    rooms: Optional[int] = None
    floor: Optional[int] = None
    floors_in_building: Optional[int] = None
    is_private_owner: Optional[bool] = None
    profile_name: Optional[str] = None
    year_built: Optional[int] = None
    raw_description: str = ""
    main_image_url: Optional[str] = None
    gallery_images: List[str] = Field(default_factory=list)
    property_fingerprint: Optional[str] = None
    parcel_id: Optional[str] = None
    cadastral_area: Optional[float] = None
    geoportal_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    skip_detail: bool = False

    @field_validator("price", "price_per_m2", "area_home", mode="before")
    @classmethod
    def parse_float_values(cls, v):
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            cleaned = (
                v.replace("zł", "")
                .replace("PLN", "")
                .replace("m²", "")
                .replace("m2", "")
                .replace(" ", "")
                .replace("\xa0", "")
                .replace(",", ".")
                .strip()
            )
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        return 0.0

    @field_validator("area_plot", mode="before")
    @classmethod
    def parse_area_plot(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v) if v > 0 else None
        if isinstance(v, str):
            cleaned = (
                v.replace("m²", "")
                .replace("m2", "")
                .replace("ar", "")
                .replace(" ", "")
                .replace("\xa0", "")
                .replace(",", ".")
                .strip()
            )
            try:
                val = float(cleaned)
                return val if val > 0 else None
            except ValueError:
                return None
        return None


class RawListing(BaseModel):
    """Raw intermediate schema before normalization."""
    portal: str
    portal_id: str
    title: str
    url: str
    price_val: Optional[float] = None
    price_per_m2_val: Optional[float] = None
    area_home_val: Optional[float] = None
    area_plot_val: Optional[float] = None
    location_str: str = ""
    street_str: Optional[str] = None
    district_str: Optional[str] = None
    city_str: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    building_type_str: Optional[str] = None
    access_road_str: Optional[str] = None
    market_str: Optional[str] = None
    finish_condition_str: Optional[str] = None
    has_visualisations_val: Optional[bool] = None
    sewerage_str: Optional[str] = None
    heating_str: Optional[str] = None
    has_fiber_val: Optional[bool] = None
    year_built_val: Optional[int] = None
    description_html: str = ""
    images: List[str] = Field(default_factory=list)
    created_at_dt: Optional[datetime] = None
