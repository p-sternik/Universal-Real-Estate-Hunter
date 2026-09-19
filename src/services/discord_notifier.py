import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from config import settings
from src.models.enums import QualificationStatus
from src.models.listing import FilterResult, ListingSchema
from src.services.market_analyzer import NegotiationAdvice


class DiscordNotifier:
    """
    Discord Webhook Notifier:
    Sends aesthetically structured rich Embeds for qualified house listings.
    Supports color coding based on whitelist priority and robust error handling.
    """

    COLOR_WHITELIST = 0x2ECC71  # Vibrant Green
    COLOR_QUALIFIED = 0x3498DB  # Nice Blue
    COLOR_REVIEW = 0xF39C12  # Gold/Orange
    COLOR_DEFAULT = 0x95A5A6  # Gray

    def __init__(self, webhook_url: str | None = None):
        self._webhook_url = webhook_url
        self.last_error: str | None = None

    @property
    def webhook_url(self) -> str | None:
        return self._webhook_url or self.get_effective_webhook_url()

    def get_effective_webhook_url(self) -> str:
        if self._webhook_url:
            return self._webhook_url
        try:
            from src.services.config_manager import config_manager

            val = getattr(getattr(config_manager.get_config(), "notifications", None), "discord_webhook_url", None)
            if val:
                return str(val)
        except Exception:
            pass
        return settings.DISCORD_WEBHOOK_URL or ""

    def is_configured(self) -> bool:
        return bool(self.get_effective_webhook_url())

    def _get_color_for_status(self, status: QualificationStatus) -> int:
        if status == QualificationStatus.QUALIFIED_WHITELIST:
            return self.COLOR_WHITELIST
        if status == QualificationStatus.QUALIFIED:
            return self.COLOR_QUALIFIED
        if status == QualificationStatus.NEEDS_REVIEW:
            return self.COLOR_REVIEW
        return self.COLOR_DEFAULT

    def format_embed(
        self,
        listing: ListingSchema,
        filter_result: FilterResult,
        negotiation_advice: NegotiationAdvice | None = None,
    ) -> dict[str, Any]:
        """Format listing and filtration details into Discord Embed JSON."""
        color = self._get_color_for_status(filter_result.status)

        # Status badge
        if filter_result.status == QualificationStatus.QUALIFIED_WHITELIST:
            status_header = f"⭐ WHITELIST PRIORYTET ({filter_result.matched_whitelist_area or 'Rzeszów'})"
        elif filter_result.status == QualificationStatus.QUALIFIED:
            status_header = "✅ OFERTA SPEŁNIAJĄCA KRYTERIA"
        else:
            status_header = "🔍 WYMAGA WERYFIKACJI RĘCZNEJ"

        # Price formatting
        price_fmt = f"**{listing.price:,.0f} zł**".replace(",", " ")
        price_m2_fmt = f"{listing.price_per_m2:,.0f} zł/m²".replace(",", " ") if listing.price_per_m2 > 0 else "b/d"

        # Plot formatting
        plot_fmt = f"{listing.area_plot:.0f} m²" if listing.area_plot else "b/d w nagłówku (analiza opisu)"

        # Building & segment
        b_type = listing.building_type.value.capitalize()
        s_type = listing.segment_subtype.value
        building_info = f"{b_type} ({s_type})"

        # Location
        loc_parts = []
        if listing.street:
            loc_parts.append(f"ul. {listing.street}")
        if listing.district:
            loc_parts.append(listing.district)
        if listing.city:
            loc_parts.append(listing.city)
        location_display = ", ".join(loc_parts) or listing.location_raw or "Rzeszów i okolice"

        # Road and parking
        road_parking = f"Droga: **{listing.access_road_type.value}**"
        if filter_result.has_parking_or_garage:
            road_parking += " | 🚗 Parking/Garaż: **TAK**"
        else:
            road_parking += " | 🚗 Parking: niejednoznaczny"

        # Market, Finish Condition and Visualisations
        market_val = listing.market.value if hasattr(listing.market, "value") else str(listing.market)
        market_str = market_val.capitalize()
        finish_val = (
            listing.finish_condition.value
            if hasattr(listing.finish_condition, "value")
            else str(listing.finish_condition)
        )
        finish_str = finish_val.capitalize()
        vis_badge = " | ⚠️ **Wizualizacje 3D / brak zdjęć**" if listing.has_visualisations else ""
        standard_info = f"Stan: **{finish_str}** | Rynek: **{market_str}**{vis_badge}"

        # Media & Utilities
        sew_val = listing.sewerage.value if hasattr(listing.sewerage, "value") else str(listing.sewerage)
        heat_val = listing.heating.value if hasattr(listing.heating, "value") else str(listing.heating)
        fiber_str = "TAK" if listing.has_fiber else "b/d"
        media_info = f"Ścieki: **{sew_val}** | Ogrzewanie: **{heat_val}** | Światłowód: **{fiber_str}**"

        # Category-aware metrics line
        cat_val = (
            listing.category.value if hasattr(listing.category, "value") else str(getattr(listing, "category", "dom"))
        )
        if cat_val == "mieszkanie":
            area_line = f"Mieszkanie: **{listing.area_home:.1f} m²**"
            if listing.rooms:
                area_line += f" | Pokoje: **{listing.rooms}**"
            if listing.floor is not None:
                area_line += f" | Piętro: **{listing.floor}**"
        elif cat_val == "dzialka":
            effective_plot = listing.area_plot or listing.area_home
            area_line = f"Działka: **{effective_plot:.0f} m²**"
        else:
            area_line = f"Dom: **{listing.area_home:.1f} m²** | Działka: **{plot_fmt}**"

        title_display = f"[{listing.profile_name}] {listing.title}" if listing.profile_name else listing.title

        fields = [
            {
                "name": "💰 Cena & Metraż",
                "value": f"{price_fmt} ({price_m2_fmt})\n{area_line}",
                "inline": False,
            },
            {
                "name": "🏡 Typ budynku & Lokalizacja",
                "value": f"Typ: **{building_info}**\n📍 **{location_display}**",
                "inline": False,
            },
            {
                "name": "🔨 Standard wykończenia i Rynek",
                "value": standard_info,
                "inline": False,
            },
            {
                "name": "⚡ Media i Ogrzewanie",
                "value": media_info,
                "inline": False,
            },
            {
                "name": "🚗 Dojazd i Parkowanie",
                "value": road_parking,
                "inline": False,
            },
        ]

        if getattr(listing, "relist_count", 0) > 0:
            relist_drop = ""
            init_p = getattr(listing, "initial_price", None)
            if init_p and init_p > listing.price:
                diff = init_p - listing.price
                pct = (diff / init_p) * 100
                relist_drop = f"\n📉 Pierwotnie: **{init_p:,.0f} zł** (spadek o **{diff:,.0f} zł** / -{pct:.1f}%)"
            days_txt = ""
            first_seen = getattr(listing, "first_seen_at", None)
            if first_seen:
                fs_utc = first_seen.replace(tzinfo=UTC) if first_seen.tzinfo is None else first_seen
                days = max(1, (datetime.now(UTC) - fs_utc).days)
                days_txt = f" | Łącznie na rynku: **{days} dni**"
            fields.insert(
                0,
                {
                    "name": "🔁 WYKRYTO POZORNY RE-LISTING",
                    "value": f"Nieruchomość powraca na rynek ({listing.relist_count}x){days_txt}{relist_drop}\n⚠️ *Sprzedający pod silną presją czasu i negocjacji!*",
                    "inline": False,
                },
            )

        parcel_id = getattr(listing, "parcel_id", None)
        if getattr(listing, "geoportal_url", None) and parcel_id:
            area_str = f" ({listing.cadastral_area:.0f} m²)" if getattr(listing, "cadastral_area", None) else ""
            p_nr = parcel_id.split(".")[-1]
            geo_lines = [f"[Działka nr {p_nr}{area_str}]({listing.geoportal_url})"]
            if getattr(listing, "mpzp_zone", None):
                geo_lines.append(f"🏛️ **MPZP:** {listing.mpzp_zone}")
            if getattr(listing, "flood_risk_zone", None):
                flood_icon = "🌊" if listing.flood_risk_zone == "ZAGROŻENIE_POWODZIOWE" else "🛡️"
                geo_lines.append(f"{flood_icon} **Zagrożenie powodziowe:** {listing.flood_risk_zone}")
            if getattr(listing, "landslide_risk", None) and listing.landslide_risk in (
                "OSUWISKO",
                "ZAGROŻENIE_OSUWISKIEM",
            ):
                geo_lines.append(f"🚨 **Osuwisko (SOPO):** {listing.landslide_risk}")
            nz = getattr(listing, "noise_zone", None)
            if nz and "WYSOKI" in nz:
                db_val = (
                    f"{listing.noise_level_db:.0f}" if getattr(listing, "noise_level_db", None) is not None else ">65"
                )
                geo_lines.append(f"🔊 **Hałas:** {db_val} dB Lden")
            if getattr(listing, "cemetery_buffer_zone", None) and listing.cemetery_buffer_zone in ("<50m", "50-150m"):
                geo_lines.append(f"⚰️ **Strefa cmentarna:** {listing.cemetery_buffer_zone}")
            if getattr(listing, "monument_zone", None):
                geo_lines.append(f"🏛️ **Zabytek (NID):** {listing.monument_zone}")
            fields.append(
                {
                    "name": "🗺️ Geoportal / Ewidencja Gruntów",
                    "value": "\n".join(geo_lines),
                    "inline": False,
                }
            )

        # Key Pros & Cons
        if filter_result.pros:
            fields.append(
                {
                    "name": "✨ Kluczowe zalety",
                    "value": "\n".join([f"• {pro}" for pro in filter_result.pros[:6]]),
                    "inline": False,
                }
            )

        if filter_result.cons:
            fields.append(
                {
                    "name": "⚠️ Wykryte minusy / do weryfikacji",
                    "value": "\n".join([f"• {con}" for con in filter_result.cons[:5]]),
                    "inline": False,
                }
            )

        if filter_result.ai_verdict:
            fields.append(
                {
                    "name": f"⚖️ Werdykt AI {filter_result.verdict_icon}",
                    "value": filter_result.ai_verdict[:1024],
                    "inline": False,
                }
            )

        if filter_result.ai_summary:
            fields.append(
                {
                    "name": "📋 TL;DR",
                    "value": filter_result.ai_summary[:1024],
                    "inline": False,
                }
            )

        if negotiation_advice and (
            negotiation_advice.price_deviation_pct is not None
            or negotiation_advice.suggested_opening_offer
            or negotiation_advice.negotiation_leverage == "WYSOKA"
        ):
            leverage_icon = {"WYSOKA": "🟢", "ŚREDNIA": "🟡", "NISKA": "⚪"}.get(
                negotiation_advice.negotiation_leverage, "⚪"
            )
            neg_lines = [f"**Pozycja:** {leverage_icon} {negotiation_advice.negotiation_leverage}"]
            if negotiation_advice.market_median_m2 and negotiation_advice.price_deviation_pct is not None:
                med_fmt = f"{negotiation_advice.market_median_m2:,.0f} zł/m²".replace(",", " ")
                dev = (
                    negotiation_advice.price_deviation_adjusted_pct
                    if negotiation_advice.price_deviation_adjusted_pct is not None
                    else negotiation_advice.price_deviation_pct
                )
                neg_lines.append(f"**Mediana rynku:** {med_fmt} ({dev:+.1f}% po korekcie o stan)")
            if negotiation_advice.suggested_opening_offer:
                offer_fmt = f"{negotiation_advice.suggested_opening_offer:,.0f} zł".replace(",", " ")
                neg_lines.append(f"**Sugerowane otwarcie:** {offer_fmt}")
            if negotiation_advice.arguments:
                neg_lines.append(f"**Główny argument:** {negotiation_advice.arguments[0]}")

            fields.append(
                {
                    "name": "💼 Wywiad negocjacyjny",
                    "value": "\n".join(neg_lines),
                    "inline": False,
                }
            )

        embed = {
            "title": title_display[:256],
            "url": listing.url,
            "description": f"**Status:** {status_header} • **Score:** `{filter_result.score:.1f} pkt`",
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Portal: {listing.portal} • Fingerprint: {listing.physical_fingerprint} • {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            },
        }

        if listing.main_image_url and listing.main_image_url.startswith("http"):
            embed["image"] = {"url": listing.main_image_url}

        return embed

    async def _post_webhook(
        self,
        payload: dict[str, Any],
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        target_webhook = webhook_url or self.webhook_url
        if not target_webhook:
            self.last_error = "Brak skonfigurowanego URL webhooka Discord."
            logger.warning(f"[DiscordNotifier] {self.last_error}")
            return False

        for attempt in range(1, 4):
            try:
                if client is not None:
                    resp = await client.post(target_webhook, json=payload)
                else:
                    async with httpx.AsyncClient(timeout=15.0) as local_client:
                        resp = await local_client.post(target_webhook, json=payload)
                if resp.status_code in (200, 204):
                    self.last_error = None
                    return True
                if resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", 2.0)
                    logger.warning(f"[DiscordNotifier] Rate limited. Retrying after {retry_after}s...")
                    await asyncio.sleep(retry_after)
                else:
                    err_msg = f"HTTP {resp.status_code}: {resp.text}"
                    self.last_error = err_msg
                    logger.error(f"[DiscordNotifier] Error {err_msg}")
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"[DiscordNotifier] Failed sending webhook (attempt {attempt}/3): {e}")
                await asyncio.sleep(1.5)

        return False

    async def send_notification(
        self,
        listing: ListingSchema,
        filter_result: FilterResult,
        webhook_url: str | None = None,
        negotiation_advice: NegotiationAdvice | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Send rich Discord notification for a qualified listing."""
        embed = self.format_embed(listing, filter_result, negotiation_advice=negotiation_advice)
        payload = {
            "username": "Real Estate Hunter",
            "avatar_url": "https://img.icons8.com/fluency/96/real-estate.png",
            "embeds": [embed],
        }
        ok = await self._post_webhook(payload, webhook_url=webhook_url, client=client)
        if ok:
            logger.info(f"[DiscordNotifier] Alert sent successfully for: {listing.title[:50]}")
        return ok

    async def send_test_message(
        self,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends a verification message to Discord."""
        target_webhook = webhook_url or self.webhook_url
        if not target_webhook:
            self.last_error = "Brak adresu URL webhooka Discord."
            logger.error("[DiscordNotifier] No webhook URL configured.")
            return False

        payload = {
            "username": "Universal Real Estate Hunter (Test)",
            "embeds": [
                {
                    "title": "🔔 Test połączenia z systemem monitorowania ofert",
                    "description": "Webhook Discorda działa prawidłowo! System jest gotowy do monitorowania rynku nieruchomości.",
                    "color": self.COLOR_WHITELIST,
                    "fields": [
                        {"name": "Status", "value": "🟢 Aktywny", "inline": True},
                        {"name": "Czas testu", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": True},
                    ],
                }
            ],
        }
        return await self._post_webhook(payload, webhook_url=target_webhook, client=client)

    async def send_cycle_summary(
        self,
        summary: dict[str, Any],
        elapsed_seconds: float,
        profile_name: str | None = None,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends a scraping cycle summary embed to Discord."""
        prof_title = f" • Profil: {profile_name}" if profile_name else ""
        m, s = divmod(int(elapsed_seconds), 60)
        elapsed_str = f"{m}m {s}s" if m > 0 else f"{elapsed_seconds:.1f}s"

        total_scraped = summary.get("total_scraped", 0)
        new_listings = summary.get("new_listings", 0)
        price_changes = summary.get("price_changes", 0)
        qualified = summary.get("qualified", 0)
        notified = summary.get("notified", 0)
        llm_success = summary.get("llm_successes", 0)
        llm_calls = summary.get("llm_calls", 0)

        color = self.COLOR_WHITELIST if qualified > 0 else self.COLOR_QUALIFIED

        fields = [
            {"name": "⏱️ Czas trwania", "value": f"**{elapsed_str}**", "inline": True},
            {"name": "📊 Przeszukano", "value": f"**{total_scraped}** ofert", "inline": True},
            {"name": "⭐ Zakwalifikowano", "value": f"**{qualified}**", "inline": True},
            {"name": "🆕 Nowe oferty", "value": f"**{new_listings}**", "inline": True},
            {"name": "📉 Zmiany cen", "value": f"**{price_changes}**", "inline": True},
            {"name": "🔔 Wysłano powiadomień", "value": f"**{notified}**", "inline": True},
        ]
        if llm_calls > 0:
            fields.append({"name": "🤖 Audyty AI", "value": f"{llm_success}/{llm_calls} udanych", "inline": True})

        embed = {
            "title": f"🏁 Podsumowanie cyklu scrapingu{prof_title}",
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Universal Real Estate Hunter • {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            },
        }
        payload = {
            "username": "Real Estate Hunter",
            "avatar_url": "https://img.icons8.com/fluency/96/real-estate.png",
            "embeds": [embed],
        }
        return await self._post_webhook(payload, webhook_url=webhook_url, client=client)

    async def send_price_drop(
        self,
        listing: ListingSchema,
        old_price: float,
        new_price: float,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends an alert embed for a detected price drop."""
        diff = old_price - new_price
        pct = (diff / old_price) * 100 if old_price > 0 else 0.0
        old_fmt = f"{old_price:,.0f} zł".replace(",", " ")
        new_fmt = f"{new_price:,.0f} zł".replace(",", " ")
        diff_fmt = f"{diff:,.0f} zł".replace(",", " ")

        embed = {
            "title": f"📉 OBNIŻKA CENY: {listing.title[:200]}",
            "url": listing.url,
            "color": 0xE67E22,  # Orange
            "fields": [
                {"name": "💰 Nowa cena", "value": f"**{new_fmt}** (było {old_fmt})", "inline": True},
                {"name": "🔻 Obniżka", "value": f"**-{diff_fmt}** (-{pct:.1f}%)", "inline": True},
                {"name": "📍 Lokalizacja", "value": listing.location_raw or "b/d", "inline": False},
                {"name": "📐 Metraż", "value": f"{listing.area_home:.1f} m²", "inline": True},
            ],
            "footer": {
                "text": f"Portal: {listing.portal} • {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            },
        }
        if listing.main_image_url and listing.main_image_url.startswith("http"):
            embed["image"] = {"url": listing.main_image_url}

        payload = {
            "username": "Real Estate Hunter",
            "avatar_url": "https://img.icons8.com/fluency/96/real-estate.png",
            "embeds": [embed],
        }
        return await self._post_webhook(payload, webhook_url=webhook_url, client=client)

    async def send_system_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends a system warning or error alert embed to Discord."""
        color = 0xE74C3C if level == "error" else 0xF39C12
        icon = "🚨" if level == "error" else "⚠️"

        embed = {
            "title": f"{icon} Alert systemowy: {title}",
            "description": message[:2048],
            "color": color,
            "footer": {
                "text": f"Universal Real Estate Hunter • {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            },
        }
        payload = {
            "username": "Real Estate Hunter (System Alert)",
            "avatar_url": "https://img.icons8.com/fluency/96/warning.png",
            "embeds": [embed],
        }
        return await self._post_webhook(payload, webhook_url=webhook_url, client=client)
