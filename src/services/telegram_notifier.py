import httpx
from loguru import logger

from config import settings
from src.models.enums import QualificationStatus
from src.models.listing import FilterResult, ListingSchema


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
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def format_message(self, listing: ListingSchema, filter_result: FilterResult) -> str:
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

        if filter_result.pros:
            lines.append("\n🌟 <b>Zalety z opisu:</b>")
            for p in filter_result.pros[:4]:
                lines.append(f"  • {p}")

        if filter_result.cons:
            lines.append("\n⚠️ <b>Uwagi / Wady:</b>")
            for c in filter_result.cons[:3]:
                lines.append(f"  • {c}")

        if getattr(listing, "geoportal_url", None):
            p_nr = listing.parcel_id.split(".")[-1] if getattr(listing, "parcel_id", None) else "mapa"
            lines.append(f"🗺️ <a href='{listing.geoportal_url}'>Działka w Geoportalu (nr {p_nr})</a>")
        lines.append(f"\n🔗 <a href='{listing.url}'>Zobacz ogłoszenie na {listing.portal}</a>")
        return "\n".join(lines)

    async def send_notification(self, listing: ListingSchema, filter_result: FilterResult) -> bool:
        if not self.is_configured():
            return False

        text = self.format_message(listing, filter_result)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    logger.info(f"[TelegramNotifier] Alert sent for: {listing.title[:40]}")
                    return True
                logger.error(f"[TelegramNotifier] Error {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"[TelegramNotifier] Exception sending alert: {e}")

        return False
