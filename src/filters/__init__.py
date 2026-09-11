import re
import time
from typing import Any

from loguru import logger

from src.models.enums import (
    BuildingType,
    FinishCondition,
    HeatingType,
    PropertyCategory,
    QualificationStatus,
    SegmentSubtype,
    SewerageType,
)
from src.models.listing import FilterResult, ListingSchema

from .fingerprint import extract_street_token, generate_property_fingerprint
from .llm_analyzer import LLMAnalyzer
from .stage1_hard_rules import Stage1Filter
from .stage2_semantic import Stage2SemanticFilter


class QualificationEngine:
    """
    Two-stage filtration and qualification engine:
    1. Stage I: Hard numerical thresholds (budget, house area, plot area) and geographic Whitelist/Blacklist.
    2. Stage II: Semantic description evaluation (corner vs middle segment, dirt roads, parking, slope/clay).
    3. Score computation and status assignment.
    """

    def __init__(self, llm_enabled: bool | None = None):
        self.stage1 = Stage1Filter()
        self.stage2 = Stage2SemanticFilter()
        self.llm = LLMAnalyzer(enabled=llm_enabled)
        self.llm_calls = 0

    async def evaluate_listing(
        self,
        listing: ListingSchema,
        profile: Any | None = None,
        skip_llm: bool = False,
    ) -> FilterResult:
        """
        Runs the multi-stage qualification pipeline on a single listing.
        """
        p = profile
        if not p and getattr(listing, "profile_name", None):
            from src.services.config_manager import config_manager

            p = config_manager.get_profile(listing.profile_name)

        # Step 1: Stage I (Hard rules & Geo)
        passed_stage1, stage1_reasons, matched_wl = self.stage1.evaluate(listing, profile=p)

        borderline_reasons: list[str] = []
        if not passed_stage1:
            borderline_reasons = self.stage1.borderline_margins(listing, profile=p)
            if not borderline_reasons:
                return FilterResult(
                    is_qualified=False,
                    status=QualificationStatus.REJECTED_STAGE1,
                    score=0.0,
                    passed_stage1=False,
                    stage1_reasons=stage1_reasons,
                    passed_stage2=False,
                    stage2_reasons=[],
                    pros=[],
                    cons=[],
                    is_corner=False,
                    has_parking_or_garage=False,
                    matched_whitelist_area=None,
                    finish_condition=listing.finish_condition,
                    has_visualisations=listing.has_visualisations,
                    sewerage=listing.sewerage,
                    heating=listing.heating,
                    has_fiber=listing.has_fiber,
                )

        # Step 2: Stage II (Semantic analysis) — runs before the LLM so that listings
        # rejected by cheap regex rules never consume LLM calls.
        (
            passed_stage2,
            stage2_reasons,
            pros,
            cons,
            detected_subtype,
            is_corner,
            has_parking,
            detected_finish,
            has_visualisations,
            detected_sewerage,
            detected_heating,
            has_fiber,
        ) = self.stage2.analyze(listing, profile=p)

        # Update listing subtype, finish condition, visualisations, and utilities
        if detected_subtype != SegmentSubtype.NIEOKRESLONY:
            listing.segment_subtype = detected_subtype
        if detected_finish != FinishCondition.NIEOKRESLONY:
            listing.finish_condition = detected_finish
        listing.has_visualisations = has_visualisations
        if detected_sewerage != SewerageType.NIEZNANA:
            listing.sewerage = detected_sewerage
        if detected_heating != HeatingType.NIEZNANE:
            listing.heating = detected_heating
        listing.has_fiber = has_fiber

        # Borderline handling: an offer is borderline when it fails Stage I only by
        # small margins, or when its only Stage II failure is a "do remontu" finish.
        finish_only_borderline = False
        if not passed_stage2:
            finish_only_borderline = (
                detected_finish == FinishCondition.DO_REMONTU
                and bool(stage2_reasons)
                and all(r.startswith("Stan wykończenia") for r in stage2_reasons)
            )

        # Hard Stage II failures (road access, terrain, plot size, visualisations)
        # reject the offer outright — no LLM call, even for Stage I borderline.
        if not passed_stage2 and not finish_only_borderline:
            return FilterResult(
                is_qualified=False,
                status=QualificationStatus.REJECTED_STAGE2,
                score=10.0,
                passed_stage1=passed_stage1,
                stage1_reasons=borderline_reasons,
                passed_stage2=False,
                stage2_reasons=stage2_reasons,
                pros=pros,
                cons=cons,
                is_corner=is_corner,
                has_parking_or_garage=has_parking,
                matched_whitelist_area=matched_wl,
                finish_condition=listing.finish_condition,
                has_visualisations=listing.has_visualisations,
                sewerage=listing.sewerage,
                heating=listing.heating,
                has_fiber=listing.has_fiber,
            )

        is_borderline = bool(borderline_reasons) or finish_only_borderline

        # Step 3: Optional LLM Enrichment (only for listings that passed Stage II or
        # are borderline — never for definitive rejections)
        ai_summary = None
        ai_verdict = None
        worth_interest = None
        ai_questions: list[str] = []
        contact_phone = None
        contact_person = None

        if not skip_llm:
            from src.services.progress import global_tracker

            logger.info(f"🤖 [AI Audit] Weryfikacja LLM dla: '{listing.title[:45]}'")
            global_tracker.add_log(
                f"🤖 [AI Audit] Weryfikacja LLM dla: {listing.title[:32]}...",
                level="info",
                category="ai",
            )
            t_llm_start = time.perf_counter()
            self.llm_calls += 1
            llm_insights = await self.llm.analyze_description(listing)
            t_llm_sec = time.perf_counter() - t_llm_start
            if llm_insights:
                v_tag = (
                    "warty uwagi"
                    if llm_insights.get("worth_interest") is True
                    else ("nie warty" if llm_insights.get("worth_interest") is False else "zakończono")
                )
                logger.info(f"🤖 [AI Audit] Gotowe dla: '{listing.title[:45]}' ({t_llm_sec:.1f}s, werdykt: {v_tag})")
                global_tracker.add_log(
                    f"🤖 [AI Audit] Gotowe dla {listing.title[:28]} ({t_llm_sec:.1f}s, werdykt: {v_tag})",
                    level="info",
                    category="ai",
                )
                if llm_insights.get("is_corner"):
                    is_corner = True
                    listing.segment_subtype = SegmentSubtype.SKRAJNY
                elif llm_insights.get("is_middle"):
                    listing.segment_subtype = SegmentSubtype.SRODKOWY
                if llm_insights.get("road_is_bad") and passed_stage2:
                    passed_stage2 = False
                    stage2_reasons.append("LLM: Wykryto nieutwardzoną / polną drogę dojazdową")
                if llm_insights.get("has_parking_or_garage"):
                    has_parking = True
                if llm_insights.get("terrain_risk"):
                    cons.append("⚠️ [LLM] Wykryto ryzyko ukształtowania terenu (skarpa / osuwisko / podmokłość)")
                if llm_insights.get("extracted_plot_m2") and not listing.area_plot:
                    try:
                        listing.area_plot = float(llm_insights["extracted_plot_m2"])
                    except (ValueError, TypeError):
                        pass

                finish_raw = str(llm_insights.get("finish_condition") or "").lower()
                finish_map = {
                    "deweloperski": FinishCondition.DEWELOPERSKI,
                    "pod_klucz": FinishCondition.DO_ZAMIESZKANIA,
                    "do_wykonczenia": FinishCondition.DO_WYKONCZENIA,
                    "surowy_zamkniety": FinishCondition.SUROWY_ZAMKNIETY,
                    "surowy_otwarty": FinishCondition.SUROWY_OTWARTY,
                    "do_remontu": FinishCondition.DO_REMONTU,
                }
                if finish_raw in finish_map:
                    new_condition = finish_map[finish_raw]
                    if (
                        new_condition == FinishCondition.DO_ZAMIESZKANIA
                        and listing.finish_condition != FinishCondition.DO_ZAMIESZKANIA
                    ):
                        # Clean up any obsolete "Do wykończenia" con from stage 2 regex
                        cons = [c for c in cons if not c.startswith("Do wykończenia")]
                        if "Standard wykończenia: gotowy do zamieszkania / pod klucz" not in pros:
                            pros.append("Standard wykończenia: gotowy do zamieszkania / pod klucz")
                    listing.finish_condition = new_condition

                finish_note = str(llm_insights.get("finish_note") or "").strip()
                if finish_note:
                    if listing.finish_condition == FinishCondition.DO_ZAMIESZKANIA:
                        pros.append(f"✨ [Stan] {finish_note}")
                    else:
                        cons.append(f"🔧 [LLM] Stan: {finish_note}")

                if llm_insights.get("has_visualisations") and not has_visualisations:
                    listing.has_visualisations = True
                    has_visualisations = True
                    vis_note = str(llm_insights.get("visualisation_note") or "").strip()
                    cons.append(
                        "🖼️ [LLM] Wizualizacje / zdjęcia poglądowe"
                        + (f": {vis_note}" if vis_note else " (brak realnych zdjęć tej nieruchomości)")
                    )

                sewer_raw = str(llm_insights.get("sewerage") or "").lower()
                sewer_map = {
                    "miejska": SewerageType.MIEJSKA,
                    "szambo": SewerageType.SZAMBO,
                    "oczyszczalnia": SewerageType.OCZYSZCZALNIA,
                }
                if sewer_raw in sewer_map:
                    listing.sewerage = sewer_map[sewer_raw]
                elif sewer_raw == "brak":
                    cons.append("⚠️ [LLM] Brak przyłącza kanalizacyjnego na działce / w budynku")

                for hc in llm_insights.get("hidden_costs", []):
                    cons.append(f"⚠️ [Ukryty koszt] {hc}")
                for lr in llm_insights.get("legal_risks", []):
                    cons.append(f"⚖️ [Ryzyko prawne] {lr}")
                for d in llm_insights.get("discrepancies", []):
                    cons.append(f"🔍 [LLM] Rozbieżność portal vs opis: {d}")
                for p in llm_insights.get("pros", []):
                    if p not in pros:
                        pros.append(f"[LLM] {p}")
                for c in llm_insights.get("cons", []):
                    if c not in cons:
                        cons.append(f"[LLM] {c}")

                # AI Due Diligence fields
                ai_summary = llm_insights.get("summary") or None
                ai_verdict = llm_insights.get("verdict") or None
                worth_interest = llm_insights.get("worth_interest")
                if worth_interest is not None:
                    worth_interest = bool(worth_interest)
                ai_questions = llm_insights.get("questions_for_agent") or []
                contact_phone = llm_insights.get("contact_phone") or None
                contact_person = llm_insights.get("contact_person") or None

        # Fallback: regex extraction for Polish phone numbers if LLM didn't find one
        if not contact_phone and listing.raw_description:
            phone_match = re.search(
                r"(?:\+?48[\s-]?)?([5-8]\d{2})[\s-]?(\d{3})[\s-]?(\d{3})",
                listing.raw_description,
            )
            if phone_match:
                digits = phone_match.group(1) + phone_match.group(2) + phone_match.group(3)
                contact_phone = f"+48{digits}"

        # Borderline offers land in a dedicated review category (no notifications).
        if is_borderline:
            return FilterResult(
                is_qualified=False,
                status=QualificationStatus.NEEDS_REVIEW_BORDERLINE,
                score=10.0,
                passed_stage1=passed_stage1,
                stage1_reasons=borderline_reasons if borderline_reasons else stage1_reasons,
                passed_stage2=passed_stage2,
                stage2_reasons=stage2_reasons,
                pros=pros,
                cons=cons,
                is_corner=is_corner,
                has_parking_or_garage=has_parking,
                matched_whitelist_area=matched_wl,
                finish_condition=listing.finish_condition,
                has_visualisations=listing.has_visualisations,
                sewerage=listing.sewerage,
                heating=listing.heating,
                has_fiber=listing.has_fiber,
                ai_summary=ai_summary,
                ai_verdict=ai_verdict,
                worth_interest=worth_interest,
                ai_questions=ai_questions,
                contact_phone=contact_phone,
                contact_person=contact_person,
            )

        if not passed_stage2:
            return FilterResult(
                is_qualified=False,
                status=QualificationStatus.REJECTED_STAGE2,
                score=10.0,
                passed_stage1=True,
                stage1_reasons=[],
                passed_stage2=False,
                stage2_reasons=stage2_reasons,
                pros=pros,
                cons=cons,
                is_corner=is_corner,
                has_parking_or_garage=has_parking,
                matched_whitelist_area=matched_wl,
                finish_condition=listing.finish_condition,
                has_visualisations=listing.has_visualisations,
                sewerage=listing.sewerage,
                heating=listing.heating,
                has_fiber=listing.has_fiber,
                ai_summary=ai_summary,
                ai_verdict=ai_verdict,
                worth_interest=worth_interest,
                ai_questions=ai_questions,
                contact_phone=contact_phone,
                contact_person=contact_person,
            )

        # Step 4: Scoring & Status resolution
        score = 50.0
        if matched_wl:
            score += 50.0
            pros.insert(0, f"Priorytetowa lokalizacja na Whiteliście: {matched_wl}")
        if is_corner:
            score += 25.0
        if has_parking:
            score += 15.0
        elif listing.category == PropertyCategory.DOM:
            score -= 10.0
        if detected_subtype == SegmentSubtype.SRODKOWY:
            score -= 5.0
        if listing.area_plot and listing.area_plot >= 350.0:
            score += 10.0

        # Price per m2 gradient
        ppm2 = listing.price_per_m2
        if ppm2 > 0:
            if ppm2 <= 6000.0:
                score += 20.0
            elif ppm2 <= 7500.0:
                score += 10.0
            elif ppm2 > 9000.0:
                score -= 10.0

        # Budget bonus: well below the configured max price
        max_price = getattr(p, "max_price", None) if p else None
        if not max_price:
            max_price = getattr(self.stage1, "max_price", None)
        if max_price and 0 < listing.price <= 0.85 * max_price:
            score += 5.0

        # Finish condition scoring
        if listing.finish_condition == FinishCondition.DO_ZAMIESZKANIA:
            score += 15.0
        elif listing.finish_condition == FinishCondition.DEWELOPERSKI:
            score += 5.0
        elif listing.finish_condition == FinishCondition.SUROWY_ZAMKNIETY:
            score -= 10.0
        elif listing.finish_condition == FinishCondition.SUROWY_OTWARTY:
            score -= 20.0

        # Building type scoring
        if listing.building_type == BuildingType.WOLNOSTOJACY:
            score += 10.0
        elif listing.building_type == BuildingType.BLIZNIAK:
            score -= 5.0
        elif listing.building_type == BuildingType.SZEREGOWIEC:
            score -= 10.0

        # Year built scoring: 2 pts per decade below 2000 (capped at -25)
        if listing.year_built and listing.year_built < 2000:
            score -= min(25.0, (2000 - listing.year_built) // 10 * 2)

        # Visualisations penalty
        if listing.has_visualisations:
            score -= 10.0

        # Utilities scoring
        if listing.sewerage == SewerageType.MIEJSKA:
            score += 10.0
        elif listing.sewerage == SewerageType.OCZYSZCZALNIA:
            score += 5.0
        elif listing.sewerage == SewerageType.SZAMBO:
            score -= 10.0

        if listing.heating == HeatingType.POMPA_CIEPLA:
            score += 10.0
        elif listing.heating in (HeatingType.GAZOWE, HeatingType.MIEJSKIE):
            score += 5.0
        elif listing.heating == HeatingType.PELLET_WEGIEL:
            score -= 15.0
        elif listing.heating == HeatingType.ELEKTRYCZNE:
            score -= 5.0

        if listing.has_fiber:
            score += 5.0

        score = min(100.0, max(0.0, score))

        if matched_wl:
            status = QualificationStatus.QUALIFIED_WHITELIST
        elif (
            listing.area_plot is None
            or listing.area_plot == 0
            or (
                listing.finish_condition == FinishCondition.NIEOKRESLONY
                and listing.sewerage == SewerageType.NIEZNANA
                and listing.heating == HeatingType.NIEZNANE
            )
        ):
            status = QualificationStatus.NEEDS_REVIEW
        else:
            status = QualificationStatus.QUALIFIED

        return FilterResult(
            is_qualified=True,
            status=status,
            score=score,
            passed_stage1=True,
            stage1_reasons=[],
            passed_stage2=True,
            stage2_reasons=[],
            pros=pros,
            cons=cons,
            is_corner=is_corner,
            has_parking_or_garage=has_parking,
            matched_whitelist_area=matched_wl,
            finish_condition=listing.finish_condition,
            has_visualisations=listing.has_visualisations,
            sewerage=listing.sewerage,
            heating=listing.heating,
            has_fiber=listing.has_fiber,
            ai_summary=ai_summary,
            ai_verdict=ai_verdict,
            worth_interest=worth_interest,
            ai_questions=ai_questions,
            contact_phone=contact_phone,
            contact_person=contact_person,
        )


__all__ = [
    "Stage1Filter",
    "Stage2SemanticFilter",
    "LLMAnalyzer",
    "QualificationEngine",
    "generate_property_fingerprint",
    "extract_street_token",
]
