from rich.console import Console
from rich.markup import escape
from rich.table import Table
from sqlalchemy import desc, select

from src.storage import ListingModel, get_session


async def get_listings_from_db(status_filter: str | None = None, limit: int | None = None) -> list[ListingModel]:
    async with get_session() as session:
        stmt = select(ListingModel).order_by(
            desc(ListingModel.is_qualified),
            desc(ListingModel.qualification_score),
            desc(ListingModel.created_at),
        )
        if status_filter and status_filter.upper() != "ALL":
            sf = status_filter.upper()
            if sf == "QUALIFIED":
                stmt = stmt.where(ListingModel.is_qualified.is_(True))
            elif sf in ("FAVORITE", "TO_VISIT", "REJECTED", "NEW"):
                stmt = stmt.where(ListingModel.user_status == sf)
            else:
                stmt = stmt.where(ListingModel.qualification_status == sf)
        if limit:
            stmt = stmt.limit(limit)

        res = await session.execute(stmt)
        return list(res.scalars().all())


async def print_terminal_view(status_filter: str | None = "QUALIFIED", limit: int = 20):
    """Print an aesthetic Rich table of listings to the terminal."""
    listings = await get_listings_from_db(status_filter=status_filter, limit=limit)
    console = Console()

    table = Table(
        title=f"🏡 Pobrane Oferty Nieruchomości (Status: {status_filter or 'ALL'}, Limit: {len(listings)})",
        show_lines=True,
    )
    table.add_column("ID", justify="center", style="cyan", no_wrap=True)
    table.add_column("Portal", justify="center", style="magenta")
    table.add_column("Status / Score", justify="center")
    table.add_column("Cena / m²", justify="right", style="green")
    table.add_column("Metraż / Działka", justify="center")
    table.add_column("Typ / Droga", justify="left")
    table.add_column("Lokalizacja & Tytuł (Link)", justify="left")

    for item in listings:
        status_color = (
            "green" if "WHITELIST" in item.qualification_status else ("blue" if item.is_qualified else "yellow")
        )
        status_display = (
            f"[{status_color}]{item.qualification_status}\n({item.qualification_score:.0f} pkt)[/{status_color}]"
        )

        price_display = f"{item.price:,.0f} zł\n{item.price_per_m2:,.0f} zł/m²".replace(",", " ")
        plot_str = f"{item.area_plot:.0f} m²" if item.area_plot else "b/d"
        area_display = f"{item.area_home:.1f} m²\ndz: {plot_str}"

        type_road = (
            f"{escape(item.building_type)}\n({escape(item.segment_subtype)})\ndroga: {escape(item.access_road_type)}"
        )
        clean_loc = escape(f"{item.street or ''} {item.district or ''} {item.city or ''}".strip() or item.location_raw)
        clean_title = escape(item.title[:65])
        clean_url = escape(item.url)
        loc_and_title = f"[bold]{clean_loc}[/bold]\n{clean_title}...\n{clean_url}"

        table.add_row(
            str(item.id),
            item.portal,
            status_display,
            price_display,
            area_display,
            type_road,
            loc_and_title,
        )

    console.print(table)
    console.print(
        "\n💡 [dim]Aby otworzyć interaktywny dashboard w przeglądarce, uruchom: [bold]python main.py dashboard[/bold][/dim]\n"
    )


__all__ = ["get_listings_from_db", "print_terminal_view"]
