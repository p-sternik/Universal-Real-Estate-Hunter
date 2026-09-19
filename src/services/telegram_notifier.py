from typing import Any

import httpx
from loguru import logger

from config import settings
from src.models.enums import QualificationStatus
from src.models.listing import FilterResult, ListingSchema
from src.services.market_analyzer import NegotiationAdvice


class TelegramNotifier:
    """
    Telegram Bot Notifier:
    Sends clean, structured HTML messages for qualified property listings.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self.last_error: str | None = None

    @property
    def bot_token(self) -> str | None:
        return self._bot_token or self.get_effective_bot_token()

    @property
    def chat_id(self) -> str | None:
        return self._chat_id or self.get_effective_chat_id()

    def _cfg_val(self, explicit: str | None, attr: str, env_val: str | None) -> str:
        if explicit:
            return explicit
        try:
            from src.services.config_manager import config_manager

            val = getattr(getattr(config_manager.get_config(), "notifications", None), attr, None)
            if val:
                return str(val)
        except Exception:
            pass
        return env_val or ""

    def get_effective_bot_token(self) -> str:
        return self._cfg_val(self._bot_token, "telegram_bot_token", settings.TELEGRAM_BOT_TOKEN)

    def get_effective_chat_id(self) -> str:
        return self._cfg_val(self._chat_id, "telegram_chat_id", settings.TELEGRAM_CHAT_ID)

    def is_configured(self) -> bool:
        return bool(self.get_effective_bot_token() and self.get_effective_chat_id())

    def format_message(
        self,
        listing: ListingSchema,
        filter_result: FilterResult,
        negotiation_advice: NegotiationAdvice | None = None,
    ) -> str:
        status_tag = (
            "⭐ <b>WHITELIST</b>"
            if filter_result.status == QualificationStatus.QUALIFIED_WHITELIST
            else "✅ <b>KWALIFIKACJA</b>"
        )

        price_fmt = f"{listing.price:,.0f} zł".replace(",", " ")
        price_m2_fmt = f"{listing.price_per_m2:,.0f} zł/m²".replace(",", " ")
        plot_fmt = f"{listing.area_plot:.0f} m²" if listing.area_plot else "b/d (analiza opisu)"

        sew_val = listing.sewerage.value if hasattr(listing.sewerage, "value") else str(listing.sewerage)
        heat_val = listing.heating.value if hasattr(listing.heating, "value") else str(listing.heating)
        fiber_str = " | 🌐 Światłowód" if listing.has_fiber else ""
        vis_tag = " | ⚠️ Wizualizacje 3D" if listing.has_visualisations else ""

        lines = [
            f"🏠 <b><a href='{listing.url}'>{listing.title}</a></b>",
            f"Status: {status_tag} (Score: <b>{filter_result.score:.1f}</b>)",
            "",
            f"💰 Cena: <b>{price_fmt}</b> ({price_m2_fmt})",
            f"📐 Dom: <b>{listing.area_home:.1f} m²</b> | Działka: <b>{plot_fmt}</b>",
            f"🏡 Typ: <b>{listing.building_type.value} ({listing.segment_subtype.value})</b>",
            f"🔨 Stan: <b>{listing.finish_condition.value}</b> | Rynek: <b>{listing.market.value}</b>{vis_tag}",
            f"⚡ Media: <b>{sew_val}</b> (ścieki), <b>{heat_val}</b> (ogrzewanie){fiber_str}",
            f"📍 Lokalizacja: <b>{listing.location_raw}</b>",
            f"🚗 Droga: <b>{listing.access_road_type.value}</b>",
        ]

        if getattr(listing, "relist_count", 0) > 0:
            relist_drop = ""
            init_p = getattr(listing, "initial_price", None)
            if init_p and init_p > listing.price:
                diff = init_p - listing.price
                pct = (diff / init_p) * 100
                relist_drop = f" (obniżka o {diff:,.0f} zł / -{pct:.1f}%)"
            lines.insert(
                2,
                f"🔁 <b>POZORNY RE-LISTING ({listing.relist_count}x):</b> pierwotnie {init_p:,.0f} zł{relist_drop}",
            )

        if filter_result.pros:
            lines.append("\n🌟 <b>Zalety z opisu:</b>")
            for p in filter_result.pros[:4]:
                lines.append(f"  • {p}")

        if filter_result.cons:
            lines.append("\n⚠️ <b>Uwagi / Wady:</b>")
            for c in filter_result.cons[:3]:
                lines.append(f"  • {c}")

        if filter_result.ai_verdict:
            lines.append(f"\n⚖️ <b>Werdykt AI {filter_result.verdict_icon}:</b> {filter_result.ai_verdict}")

        if negotiation_advice and (
            negotiation_advice.price_deviation_pct is not None
            or negotiation_advice.suggested_opening_offer
            or negotiation_advice.negotiation_leverage == "WYSOKA"
        ):
            leverage_icon = {"WYSOKA": "🟢", "ŚREDNIA": "🟡", "NISKA": "⚪"}.get(
                negotiation_advice.negotiation_leverage, "⚪"
            )
            lines.append(
                f"\n💼 <b>Negocjacje:</b> Pozycja {leverage_icon} <b>{negotiation_advice.negotiation_leverage}</b>"
            )
            if negotiation_advice.market_median_m2 and negotiation_advice.price_deviation_pct is not None:
                med_fmt = f"{negotiation_advice.market_median_m2:,.0f} zł/m²".replace(",", " ")
                dev = (
                    negotiation_advice.price_deviation_adjusted_pct
                    if negotiation_advice.price_deviation_adjusted_pct is not None
                    else negotiation_advice.price_deviation_pct
                )
                lines.append(f"  • Rynek: <b>{med_fmt}</b> ({dev:+.1f}% po korekcie o stan)")
            if negotiation_advice.suggested_opening_offer:
                offer_fmt = f"{negotiation_advice.suggested_opening_offer:,.0f} zł".replace(",", " ")
                lines.append(f"  • Sugerowane otwarcie: <b>{offer_fmt}</b>")
            if negotiation_advice.arguments:
                lines.append(f"  • Argument: <i>{negotiation_advice.arguments[0]}</i>")

        parcel_id = getattr(listing, "parcel_id", None)
        if getattr(listing, "geoportal_url", None):
            p_nr = parcel_id.split(".")[-1] if parcel_id else "mapa"
            lines.append(f"🗺️ <a href='{listing.geoportal_url}'>Działka w Geoportalu (nr {p_nr})</a>")
        if getattr(listing, "mpzp_zone", None):
            lines.append(f"🏛️ MPZP: <b>{listing.mpzp_zone}</b>")
        if getattr(listing, "flood_risk_zone", None):
            f_icon = "🌊" if listing.flood_risk_zone == "ZAGROŻENIE_POWODZIOWE" else "🛡️"
            lines.append(f"{f_icon} Powódź: <b>{listing.flood_risk_zone}</b>")
        if getattr(listing, "landslide_risk", None) and listing.landslide_risk in ("OSUWISKO", "ZAGROŻENIE_OSUWISKIEM"):
            lines.append(f"🚨 Osuwisko (SOPO): <b>{listing.landslide_risk}</b>")
        nz = getattr(listing, "noise_zone", None)
        if nz and "WYSOKI" in nz:
            db_val = f"{listing.noise_level_db:.0f}" if getattr(listing, "noise_level_db", None) is not None else ">65"
            lines.append(f"🔊 Hałas: <b>{db_val} dB Lden ({nz})</b>")
        if getattr(listing, "cemetery_buffer_zone", None) and listing.cemetery_buffer_zone in ("<50m", "50-150m"):
            lines.append(f"⚰️ Cmentarz: <b>{listing.cemetery_buffer_zone}</b>")
        if getattr(listing, "monument_zone", None):
            lines.append(f"🏛️ Zabytek (NID): <b>{listing.monument_zone}</b>")
        lines.append(f"\n🔗 <a href='{listing.url}'>Zobacz ogłoszenie na {listing.portal}</a>")
        return "\n".join(lines)

    async def _post_html(
        self,
        text: str,
        bot_token: str | None = None,
        chat_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[bool, str]:
        token = bot_token or self.get_effective_bot_token()
        chat = chat_id or self.get_effective_chat_id()
        if not token or not chat:
            return False, "Brak skonfigurowanego tokenu bota lub ID czatu Telegram."

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            if client is not None:
                res = await client.post(url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=10.0) as local_client:
                    res = await local_client.post(url, json=payload)
            if res.status_code == 200:
                return True, "OK"
            err_msg = f"HTTP {res.status_code}: {res.text}"
            logger.error(f"[TelegramNotifier] Error {err_msg}")
            return False, err_msg
        except Exception as e:
            logger.error(f"[TelegramNotifier] Exception sending message: {e}")
            return False, str(e)

    async def send_notification(
        self,
        listing: ListingSchema,
        filter_result: FilterResult,
        negotiation_advice: NegotiationAdvice | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        if not self.is_configured():
            return False

        text = self.format_message(listing, filter_result, negotiation_advice=negotiation_advice)
        ok, _ = await self._post_html(text, client=client)
        if ok:
            logger.info(f"[TelegramNotifier] Alert sent for: {listing.title[:40]}")
        return ok

    async def send_test_message(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends a verification message to Telegram to test bot credentials."""
        text = (
            "🔔 <b>Test połączenia — Universal Real Estate Hunter</b>\n\n"
            "System powiadomień Telegram działa prawidłowo! "
            "Pomyślnie skonfigurowano komunikację z botem."
        )
        ok, err = await self._post_html(text, bot_token=bot_token, chat_id=chat_id, client=client)
        self.last_error = None if ok else err
        return ok

    async def send_cycle_summary(
        self,
        summary: dict[str, Any],
        elapsed_seconds: float,
        profile_name: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends a structured scraping cycle completion summary."""
        if not self.is_configured():
            return False

        prof_title = f" ({profile_name})" if profile_name else ""
        m, s = divmod(int(elapsed_seconds), 60)
        elapsed_str = f"{m}m {s}s" if m > 0 else f"{elapsed_seconds:.1f}s"

        total_scraped = summary.get("total_scraped", 0)
        new_listings = summary.get("new_listings", 0)
        price_changes = summary.get("price_changes", 0)
        qualified = summary.get("qualified", 0)
        notified = summary.get("notified", 0)
        llm_success = summary.get("llm_successes", 0)
        llm_calls = summary.get("llm_calls", 0)

        lines = [
            f"🏁 <b>Podsumowanie cyklu scrapingu{prof_title}</b>",
            f"⏱️ Czas trwania: <b>{elapsed_str}</b>",
            "",
            f"📊 Przeszukano łącznie: <b>{total_scraped}</b> ofert",
            f"🆕 Nowe oferty: <b>{new_listings}</b>",
            f"📉 Zmiany cen: <b>{price_changes}</b>",
            f"⭐ Zakwalifikowane: <b>{qualified}</b>",
            f"🔔 Wysłane powiadomienia: <b>{notified}</b>",
        ]
        if llm_calls > 0:
            lines.append(f"🤖 Audyty AI: <b>{llm_success}</b>/{llm_calls} udanych")

        text = "\n".join(lines)
        ok, _ = await self._post_html(text, client=client)
        return ok

    async def send_price_drop(
        self,
        listing: ListingSchema,
        old_price: float,
        new_price: float,
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends an instant alert when a tracked listing has a price drop."""
        if not self.is_configured():
            return False

        diff = old_price - new_price
        pct = (diff / old_price) * 100 if old_price > 0 else 0.0
        old_fmt = f"{old_price:,.0f} zł".replace(",", " ")
        new_fmt = f"{new_price:,.0f} zł".replace(",", " ")
        diff_fmt = f"{diff:,.0f} zł".replace(",", " ")

        lines = [
            f"📉 <b>OBNIŻKA CENY: <a href='{listing.url}'>{listing.title}</a></b>",
            "",
            f"💰 Nowa cena: <b>{new_fmt}</b> (było {old_fmt})",
            f"🔻 Spadek o: <b>{diff_fmt} (-{pct:.1f}%)</b>",
            f"📍 Lokalizacja: <b>{listing.location_raw}</b>",
            f"📐 Powierzchnia: <b>{listing.area_home:.1f} m²</b>",
            f"\n🔗 <a href='{listing.url}'>Zobacz ofertę na {listing.portal}</a>",
        ]
        ok, _ = await self._post_html("\n".join(lines), client=client)
        return ok

    async def send_system_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
        client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Sends a system warning or critical alert (e.g. portal block or DB lock)."""
        if not self.is_configured():
            return False

        icon = "🚨" if level == "error" else "⚠️"
        text = f"{icon} <b>ALERT SYSTEMOWY: {title}</b>\n\n{message}"
        ok, _ = await self._post_html(text, client=client)
        return ok
