from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from loguru import logger
from sqlalchemy import delete, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.listing import FilterResult, ListingSchema
from .models import ListingModel, PriceHistoryModel


class ListingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_portal_id(self, portal: str, portal_id: str) -> Optional[ListingModel]:
        stmt = select(ListingModel).where(
            ListingModel.portal == portal,
            ListingModel.portal_id == portal_id,
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_by_url(self, url: str) -> Optional[ListingModel]:
        stmt = select(ListingModel).where(ListingModel.url == url)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_fresh_urls(self, portals: List[str], within_hours: int = 24) -> List[str]:
        """URLs of listings with complete, recently scraped detail data."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
        stmt = select(ListingModel.url).where(
            ListingModel.portal.in_(portals),
            ListingModel.last_scraped_at.isnot(None),
            ListingModel.last_scraped_at >= cutoff,
            ListingModel.raw_description != "",
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def find_duplicate_by_fingerprint(
        self,
        fingerprint: str,
        within_days: int = 45,
    ) -> Optional[ListingModel]:
        """Check if an identical house was already listed (cross-portal/multi-agency deduplication)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
        stmt = (
            select(ListingModel)
            .where(
                ListingModel.property_fingerprint == fingerprint,
                ListingModel.created_at >= cutoff,
            )
            .order_by(desc(ListingModel.created_at))
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def save_or_update(
        self,
        listing: ListingSchema,
        filter_result: FilterResult,
        is_exact_coords: bool = True,
    ) -> Tuple[ListingModel, bool, bool]:
        """
        Saves new listing or updates existing.
        Returns (listing_model, is_new, price_changed).
        """
        existing = await self.get_by_portal_id(listing.portal, listing.id)
        if not existing:
            existing = await self.get_by_url(listing.url)

        lat, lon = (None, None)
        if listing.coordinates:
            lat, lon = listing.coordinates

        if existing:
            # Check price change
            price_changed = abs(existing.price - listing.price) >= 1.0
            old_price = existing.price

            existing.title = listing.title
            existing.price = listing.price
            existing.price_per_m2 = listing.price_per_m2
            existing.area_home = listing.area_home
            existing.area_plot = listing.area_plot
            existing.category = (
                listing.category.value
                if hasattr(listing.category, "value")
                else str(listing.category)
            )
            if listing.rooms is not None:
                existing.rooms = listing.rooms
            if listing.floor is not None:
                existing.floor = listing.floor
            if listing.floors_in_building is not None:
                existing.floors_in_building = listing.floors_in_building
            if listing.is_private_owner is not None:
                existing.is_private_owner = listing.is_private_owner
            if listing.profile_id:
                existing.profile_id = listing.profile_id
            if listing.profile_name:
                existing.profile_name = listing.profile_name
            existing.building_type = listing.building_type.value
            existing.segment_subtype = listing.segment_subtype.value
            existing.location_raw = listing.location_raw
            existing.street = listing.street or existing.street
            existing.district = listing.district or existing.district
            existing.city = listing.city or existing.city
            if lat and lon:
                existing.latitude = lat
                existing.longitude = lon
            existing.access_road_type = listing.access_road_type.value
            existing.market = listing.market.value
            existing.finish_condition = (
                listing.finish_condition.value
                if hasattr(listing.finish_condition, "value")
                else str(listing.finish_condition)
            )
            if listing.has_visualisations:
                existing.has_visualisations = True
            existing.sewerage = (
                listing.sewerage.value
                if hasattr(listing.sewerage, "value")
                else str(listing.sewerage)
            )
            existing.heating = (
                listing.heating.value
                if hasattr(listing.heating, "value")
                else str(listing.heating)
            )
            if listing.has_fiber:
                existing.has_fiber = True
            if listing.year_built:
                existing.year_built = listing.year_built
            if listing.main_image_url:
                existing.main_image_url = listing.main_image_url
            if listing.gallery_images:
                existing.gallery_images = listing.gallery_images
            if listing.raw_description:
                existing.raw_description = listing.raw_description
            if listing.parcel_id:
                existing.parcel_id = listing.parcel_id
            if listing.cadastral_area:
                existing.cadastral_area = listing.cadastral_area
            if listing.geoportal_url:
                existing.geoportal_url = listing.geoportal_url

            # Update qualification
            existing.is_qualified = filter_result.is_qualified
            existing.qualification_status = filter_result.status.value
            existing.qualification_score = filter_result.score
            existing.filter_reasons = filter_result.stage1_reasons + filter_result.stage2_reasons
            existing.pros = filter_result.pros
            existing.cons = filter_result.cons
            existing.updated_at = datetime.now(timezone.utc)
            existing.last_scraped_at = datetime.now(timezone.utc)

            if price_changed:
                logger.info(
                    f"Price changed for [{existing.portal}] {existing.title}: {old_price:,.0f} -> {listing.price:,.0f} PLN"
                )
                history_entry = PriceHistoryModel(
                    listing_id=existing.id,
                    price=listing.price,
                    price_per_m2=listing.price_per_m2,
                    recorded_at=datetime.now(timezone.utc),
                )
                self.session.add(history_entry)

            await self.session.flush()
            return existing, False, price_changed

        # Brand new listing
        new_model = ListingModel(
            portal=listing.portal,
            portal_id=listing.id,
            url=listing.url,
            property_fingerprint=listing.property_fingerprint or "unknown",
            title=listing.title,
            price=listing.price,
            price_per_m2=listing.price_per_m2,
            area_home=listing.area_home,
            area_plot=listing.area_plot,
            category=(
                listing.category.value
                if hasattr(listing.category, "value")
                else str(listing.category)
            ),
            rooms=listing.rooms,
            floor=listing.floor,
            floors_in_building=listing.floors_in_building,
            is_private_owner=listing.is_private_owner,
            profile_id=listing.profile_id,
            profile_name=listing.profile_name,
            building_type=listing.building_type.value,
            segment_subtype=listing.segment_subtype.value,
            location_raw=listing.location_raw,
            street=listing.street,
            district=listing.district,
            city=listing.city,
            latitude=lat,
            longitude=lon,
            is_exact_coords=is_exact_coords,
            parcel_id=listing.parcel_id,
            cadastral_area=listing.cadastral_area,
            geoportal_url=listing.geoportal_url,
            access_road_type=listing.access_road_type.value,
            market=listing.market.value,
            finish_condition=(
                listing.finish_condition.value
                if hasattr(listing.finish_condition, "value")
                else str(listing.finish_condition)
            ),
            has_visualisations=bool(listing.has_visualisations),
            sewerage=(
                listing.sewerage.value
                if hasattr(listing.sewerage, "value")
                else str(listing.sewerage)
            ),
            heating=(
                listing.heating.value
                if hasattr(listing.heating, "value")
                else str(listing.heating)
            ),
            has_fiber=bool(listing.has_fiber),
            year_built=listing.year_built,
            raw_description=listing.raw_description,
            main_image_url=listing.main_image_url,
            is_qualified=filter_result.is_qualified,
            qualification_status=filter_result.status.value,
            qualification_score=filter_result.score,
            created_at=listing.created_at,
            updated_at=datetime.now(timezone.utc),
            last_scraped_at=datetime.now(timezone.utc),
        )
        new_model.filter_reasons = filter_result.stage1_reasons + filter_result.stage2_reasons
        new_model.pros = filter_result.pros
        new_model.cons = filter_result.cons
        if listing.gallery_images:
            new_model.gallery_images = listing.gallery_images

        self.session.add(new_model)
        await self.session.flush()

        # Add initial price history entry
        initial_history = PriceHistoryModel(
            listing_id=new_model.id,
            price=listing.price,
            price_per_m2=listing.price_per_m2,
            recorded_at=listing.created_at,
        )
        self.session.add(initial_history)
        await self.session.flush()

        return new_model, True, False

    async def mark_as_notified(self, listing_id: int) -> None:
        stmt = select(ListingModel).where(ListingModel.id == listing_id)
        res = await self.session.execute(stmt)
        item = res.scalars().first()
        if item:
            item.notified_at = datetime.now(timezone.utc)
            await self.session.flush()

    async def get_unnotified_qualified(self, limit: int = 50) -> List[ListingModel]:
        stmt = (
            select(ListingModel)
            .where(
                ListingModel.is_qualified == True,
                ListingModel.notified_at.is_(None),
            )
            .order_by(desc(ListingModel.qualification_score), desc(ListingModel.created_at))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_user_status(self, listing_id: int, status: str) -> Optional[ListingModel]:
        stmt = select(ListingModel).where(ListingModel.id == listing_id)
        res = await self.session.execute(stmt)
        listing = res.scalars().first()
        if listing:
            listing.user_status = status
            listing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
        return listing

    async def update_user_notes(self, listing_id: int, notes: Optional[str]) -> Optional[ListingModel]:
        stmt = select(ListingModel).where(ListingModel.id == listing_id)
        res = await self.session.execute(stmt)
        listing = res.scalars().first()
        if listing:
            listing.user_notes = notes
            listing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
        return listing

    async def delete_by_profile(self, profile_id: str, profile_name: Optional[str] = None) -> int:
        """Delete all listings and their price histories associated with a given profile ID or profile name."""
        conditions = [ListingModel.profile_id == profile_id]
        if profile_name:
            conditions.append(ListingModel.profile_name == profile_name)
        conditions.append(ListingModel.profile_name == profile_id)

        stmt = select(ListingModel.id).where(or_(*conditions))
        res = await self.session.execute(stmt)
        listing_ids = list(res.scalars().all())
        if not listing_ids:
            return 0

        # Delete related price histories first
        await self.session.execute(
            delete(PriceHistoryModel).where(PriceHistoryModel.listing_id.in_(listing_ids))
        )
        # Delete listings
        await self.session.execute(
            delete(ListingModel).where(ListingModel.id.in_(listing_ids))
        )
        await self.session.commit()
        logger.info(f"[ListingRepository] Deleted {len(listing_ids)} listings associated with profile '{profile_id}'")
        return len(listing_ids)


