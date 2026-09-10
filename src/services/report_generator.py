import html
import os
import webbrowser
from pathlib import Path

from loguru import logger
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
        "\n💡 [dim]Aby otworzyć interaktywny raport wizualny w przeglądarce, uruchom: [bold]python main.py report[/bold][/dim]\n"
    )


async def generate_html_dashboard(
    output_path: str = "listings_report.html",
    auto_open: bool = True,
) -> str:
    """Generate a modern HTML dashboard showcasing all listings with photos and direct links."""
    listings = await get_listings_from_db(status_filter="ALL")

    total_count = len(listings)
    qualified_count = sum(1 for l in listings if l.is_qualified)
    whitelist_count = sum(1 for l in listings if l.qualification_status == "QUALIFIED_WHITELIST")
    avg_price_m2 = sum(l.price_per_m2 for l in listings if l.price_per_m2 > 0) / len(listings) if listings else 0

    cards_html = []
    for item in listings:
        status_class = (
            "status-whitelist"
            if item.qualification_status == "QUALIFIED_WHITELIST"
            else (
                "status-qualified"
                if item.is_qualified
                else ("status-review" if item.qualification_status == "NEEDS_REVIEW" else "status-rejected")
            )
        )

        badge_text = (
            "Whitelist"
            if item.qualification_status == "QUALIFIED_WHITELIST"
            else (
                "Zakwalifikowana"
                if item.is_qualified
                else ("Do weryfikacji" if item.qualification_status == "NEEDS_REVIEW" else "Odrzucona")
            )
        )

        plot_text = f"{item.area_plot:.0f} m²" if item.area_plot else "b/d"
        gallery = item.gallery_images or []
        img_src = item.main_image_url or (
            gallery[0]
            if gallery
            else "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=600&q=80"
        )
        gallery_badge = (
            f"<span class='badge' style='background:rgba(0,0,0,0.65);color:#e2e8f0;top:auto;bottom:8px;left:auto;right:8px;'>📷 {len(gallery)}</span>"
            if len(gallery) > 1
            else ""
        )

        thumbs_html = ""
        if len(gallery) > 1:
            thumb_elems = []
            for g_url in gallery[:5]:
                esc_url = html.escape(g_url)
                thumb_elems.append(
                    f'<img src="{esc_url}" class="card-thumb" alt="Miniaturka" loading="lazy" onmouseenter="this.closest(\'.card\').querySelector(\'.main-card-img\').src=\'{esc_url}\'" onclick="window.open(\'{esc_url}\', \'_blank\')" onerror="this.style.display=\'none\'">'
                )
            more_count = len(gallery) - 5
            more_html = f'<span class="thumb-more">+{more_count}</span>' if more_count > 0 else ""
            thumbs_html = f'<div class="gallery-strip">{"".join(thumb_elems)}{more_html}</div>'

        pros_lis = "".join([f"<li>✓ {html.escape(p)}</li>" for p in (item.pros or [])[:2]])
        cons_lis = "".join([f"<li class='con'>⚠ {html.escape(c)}</li>" for c in (item.cons or [])[:1]])

        market_text = (
            html.escape(item.market) if getattr(item, "market", None) and item.market != "nieokreślony" else ""
        )
        finish_val = getattr(item, "finish_condition", None)
        finish_text = html.escape(finish_val) if finish_val and finish_val != "nieokreślony" else ""
        sew_val = getattr(item, "sewerage", None)
        sew_text = html.escape(sew_val) if sew_val and sew_val != "nieznana" else ""
        heat_val = getattr(item, "heating", None)
        heat_text = html.escape(heat_val) if heat_val and heat_val != "nieznane" else ""
        has_fiber = bool(getattr(item, "has_fiber", False))
        fiber_badge = "<span class='sep'>·</span><span>🌐 Światłowód</span>" if has_fiber else ""
        has_vis = bool(getattr(item, "has_visualisations", False))
        vis_badge = (
            "<span class='badge' style='background:#d97706;color:#fff;left:auto;right:12px;'>⚠️ Wizualizacje</span>"
            if has_vis
            else ""
        )
        road_text = (
            html.escape(item.access_road_type)
            if getattr(item, "access_road_type", None) and item.access_road_type != "nieznana"
            else ""
        )

        card = f"""
        <div class="card {status_class}" data-status="{item.qualification_status}">
            <div class="card-img-wrapper">
                <img class="main-card-img" src="{html.escape(img_src)}" alt="Zdjęcie oferty" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=600&q=80'">
                <span class="badge {status_class}">{badge_text}</span>
                {vis_badge}
                {gallery_badge}
            </div>
            {thumbs_html}
            <div class="card-body">
                <div class="meta-row">
                    <span class="portal-tag">{html.escape(item.portal).upper()} · #{html.escape(item.portal_id)}</span>
                    <span class="score-tag">Score: <strong>{item.qualification_score:.0f}</strong>/150</span>
                </div>
                <h3 class="card-title">
                    <a href="{html.escape(item.url)}" target="_blank" rel="noopener noreferrer">{html.escape(item.title)}</a>
                </h3>
                <div class="price-row">
                    <span class="price">{item.price:,.0f} zł</span>
                    <span class="price-m2">· {item.price_per_m2:,.0f} zł/m²</span>
                </div>
                <div class="location-row">
                    {html.escape(item.street or item.district or item.city or item.location_raw or "")}
                </div>
                <div class="specs-row">
                    <span><strong>{item.area_home:.1f}</strong> m²</span>
                    <span class="sep">·</span>
                    <span>Działka: <strong>{plot_text}</strong></span>
                    <span class="sep">·</span>
                    <span>{html.escape(item.building_type)}</span>
                    {f"<span class='sep'>·</span><span>{market_text}</span>" if market_text else ""}
                    {f"<span class='sep'>·</span><span>{finish_text}</span>" if finish_text else ""}
                    {f"<span class='sep'>·</span><span>Ścieki: {sew_text}</span>" if sew_text else ""}
                    {f"<span class='sep'>·</span><span>Ogrzewanie: {heat_text}</span>" if heat_text else ""}
                    {fiber_badge}
                    {f"<span class='sep'>·</span><span>{road_text}</span>" if road_text else ""}
                </div>
                {f"<div class='insights'><ul>{pros_lis}{cons_lis}</ul></div>" if (pros_lis or cons_lis) else ""}
                <div class="card-actions">
                    <a href="{html.escape(item.url)}" class="btn-visit" target="_blank" rel="noopener noreferrer">
                        Otwórz ogłoszenie ↗
                    </a>
                    {f'''<a href="{html.escape(getattr(item, "geoportal_url", None) or f"https://mapy.geoportal.gov.pl/imap/Imgp_2.html?identifyParcel={item.parcel_id}" if getattr(item, "parcel_id", None) else f"https://mapy.geoportal.gov.pl/imap/Imgp_2.html?locale=pl&gui=new&session=%7B%22actions%22%3A%5B%7B%22name%22%3A%22locatePoint%22%2C%22params%22%3A%7B%22x%22%3A{item.longitude}%2C%22y%22%3A{item.latitude}%2C%22srid%22%3A4326%7D%7D%5D%7D")}" class="btn-geoportal" target="_blank" rel="noopener noreferrer">🗺️ Geoportal ↗</a>''' if (getattr(item, "latitude", None) and getattr(item, "longitude", None)) else ""}
                </div>
            </div>
        </div>
        """
        cards_html.append(card)

    html_content = f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universal Real Estate Hunter — Raport Analityczny</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #090a0f;
            --surface: #111318;
            --surface-card: #14171f;
            --surface-hover: #181d26;
            --border: #222631;
            --border-hover: #323846;
            --text-primary: #f4f5f7;
            --text-secondary: #9da4b2;
            --text-muted: #656c7a;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-amber: #f59e0b;
            --accent-rose: #f43f5e;
            --radius-sm: 4px;
            --radius-md: 6px;
            --radius-lg: 8px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--text-primary);
            padding: 20px;
            font-size: 13px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 16px;
        }}
        h1 {{ font-size: 16px; font-weight: 600; color: var(--text-primary); }}
        .header p {{ color: var(--text-muted); font-size: 12px; margin-top: 2px; }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 8px;
            margin-bottom: 16px;
        }}
        .stat-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 10px 14px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .stat-card:hover {{ border-color: var(--border-hover); }}
        .stat-card.active {{ border-color: var(--accent-blue); background: rgba(59, 130, 246, 0.08); }}
        .stat-card .label {{ font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 2px; }}
        .stat-card .num {{ font-size: 18px; font-weight: 700; color: var(--text-primary); font-variant-numeric: tabular-nums; }}

        .filters-bar {{
            display: flex;
            gap: 4px;
            margin-bottom: 16px;
            flex-wrap: wrap;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 3px;
        }}
        .filter-btn {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 5px 12px;
            border-radius: var(--radius-sm);
            cursor: pointer;
            font-weight: 500;
            font-size: 12px;
            transition: all 0.15s;
            font-family: inherit;
        }}
        .filter-btn.active, .filter-btn:hover {{
            background: #1e2430;
            color: var(--text-primary);
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
            gap: 14px;
        }}
        .card {{
            background: var(--surface-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: border-color 0.15s;
        }}
        .card:hover {{
            border-color: var(--border-hover);
        }}

        .card-img-wrapper {{
            position: relative;
            width: 100%;
            aspect-ratio: 16 / 9;
            background: #000;
            overflow: hidden;
        }}
        .card-img-wrapper img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        .badge {{
            position: absolute;
            top: 8px;
            left: 8px;
            padding: 2px 7px;
            border-radius: var(--radius-sm);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            backdrop-filter: blur(8px);
        }}
        .badge.status-whitelist {{ background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); }}
        .badge.status-qualified {{ background: rgba(59, 130, 246, 0.18); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.35); }}
        .badge.status-review {{ background: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }}
        .badge.status-rejected {{ background: rgba(244, 63, 94, 0.18); color: #f87171; border: 1px solid rgba(244, 63, 94, 0.35); }}

        .gallery-strip {{
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 5px 12px 2px 12px;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            overflow-x: auto;
        }}
        .card-thumb {{
            width: 44px;
            height: 30px;
            object-fit: cover;
            border-radius: var(--radius-xs);
            border: 1px solid var(--border);
            cursor: pointer;
            transition: all 0.15s ease;
            flex-shrink: 0;
        }}
        .card-thumb:hover {{
            border-color: var(--accent-blue);
            transform: scale(1.05);
        }}
        .thumb-more {{
            font-size: 10px;
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-muted);
            padding: 2px 4px;
            border-radius: 3px;
            background: var(--surface-card);
            border: 1px solid var(--border);
            flex-shrink: 0;
        }}

        .card-body {{
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
            gap: 6px;
        }}
        .meta-row {{
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: var(--text-muted);
        }}
        .portal-tag {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
        }}
        .score-tag {{
            font-size: 11px;
            color: var(--text-secondary);
        }}
        .score-tag strong {{
            color: var(--text-primary);
        }}
        .card-title {{
            font-size: 13px;
            font-weight: 600;
            line-height: 1.35;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .card-title a {{
            color: var(--text-primary);
            text-decoration: none;
        }}
        .card-title a:hover {{
            color: var(--accent-blue);
        }}
        .price-row {{
            display: flex;
            align-items: baseline;
            gap: 6px;
        }}
        .price {{ font-size: 17px; font-weight: 700; color: #ffffff; font-variant-numeric: tabular-nums; }}
        .price-m2 {{ font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }}

        .location-row {{
            font-size: 11px;
            color: var(--text-secondary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .specs-row {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
            font-size: 11px;
            color: var(--text-secondary);
            padding: 6px 0;
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            margin: 2px 0;
        }}
        .specs-row strong {{ color: var(--text-primary); font-variant-numeric: tabular-nums; }}
        .specs-row .sep {{ color: var(--text-muted); font-size: 10px; }}

        .insights {{
            font-size: 11px;
            color: var(--text-secondary);
            margin-top: 2px;
            flex-grow: 1;
        }}
        .insights ul {{ list-style: none; display: flex; flex-direction: column; gap: 2px; }}
        .insights li {{ color: #a7f3d0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .insights li.con {{ color: #fca5a5; }}

        .card-actions {{
            display: flex;
            gap: 6px;
            margin-top: auto;
        }}
        .btn-visit {{
            flex: 1;
            text-align: center;
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-primary);
            padding: 6px 10px;
            border-radius: var(--radius-sm);
            text-decoration: none;
            font-weight: 500;
            font-size: 11px;
            transition: all 0.15s;
        }}
        .btn-visit:hover {{
            background: var(--surface-hover);
            border-color: var(--border-hover);
        }}
        .btn-geoportal {{
            text-align: center;
            background: rgba(16, 185, 129, 0.08);
            border: 1px solid rgba(16, 185, 129, 0.25);
            color: #34d399;
            padding: 6px 10px;
            border-radius: var(--radius-sm);
            text-decoration: none;
            font-weight: 600;
            font-size: 11px;
            transition: all 0.15s;
            white-space: nowrap;
        }}
        .btn-geoportal:hover {{
            background: rgba(16, 185, 129, 0.18);
            border-color: #34d399;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Universal Real Estate Hunter — Raport Analityczny</h1>
                <p>Zestawienie zakwalifikowanych i odrzuconych ofert sprzedaży domów</p>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card active" onclick="filterCards('ALL', this)">
                <div class="label">Wszystkie w bazie</div>
                <div class="num">{total_count}</div>
            </div>
            <div class="stat-card" onclick="filterCards('QUALIFIED_WHITELIST', this)">
                <div class="label">⭐ Whitelist</div>
                <div class="num" style="color: #34d399;">{whitelist_count}</div>
            </div>
            <div class="stat-card" onclick="filterCards('QUALIFIED', this)">
                <div class="label">✅ Zakwalifikowane</div>
                <div class="num" style="color: #60a5fa;">{qualified_count}</div>
            </div>
            <div class="stat-card">
                <div class="label">Średnia Cena / m²</div>
                <div class="num" style="font-size: 16px;">{avg_price_m2:,.0f} zł</div>
            </div>
        </div>

        <div class="grid" id="cardsGrid">
            {"".join(cards_html)}
        </div>
    </div>

    <script>
        function filterCards(status, el) {{
            document.querySelectorAll('.stat-card').forEach(c => c.classList.remove('active'));
            if (el) el.classList.add('active');

            const cards = document.querySelectorAll('#cardsGrid .card');
            cards.forEach(card => {{
                const cardStatus = card.getAttribute('data-status');
                if (status === 'ALL') {{
                    card.style.display = 'flex';
                }} else if (status === 'QUALIFIED') {{
                    if (cardStatus === 'QUALIFIED' || cardStatus === 'QUALIFIED_WHITELIST') {{
                        card.style.display = 'flex';
                    }} else {{
                        card.style.display = 'none';
                    }}
                }} else if (status === 'REJECTED') {{
                    if (cardStatus && cardStatus.startsWith('REJECTED')) {{
                        card.style.display = 'flex';
                    }} else {{
                        card.style.display = 'none';
                    }}
                }} else {{
                    if (cardStatus === status) {{
                        card.style.display = 'flex';
                    }} else {{
                        card.style.display = 'none';
                    }}
                }}
            }});
        }}
    </script>
</body>
</html>
"""

    abs_path = Path(output_path).resolve()
    abs_path.write_text(html_content, encoding="utf-8")

    logger.info(f"HTML Dashboard generated successfully at: {abs_path}")
    if auto_open:
        try:
            webbrowser.open(f"file:///{str(abs_path).replace(os.sep, '/')}")
        except Exception as e:
            logger.debug(f"Could not automatically open browser: {e}")

    return abs_path
