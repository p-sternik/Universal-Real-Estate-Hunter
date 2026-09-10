from typing import Any, Optional
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

    def __init__(self):
        self.stage1 = Stage1Filter()
        self.stage2 = Stage2SemanticFilter()
        self.llm = LLMAnalyzer()

    async def evaluate_listing(
        self,
        listing: ListingSchema,
        profile: Optional[Any] = None,
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

        if not passed_stage1:
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

        # Step 2: Stage II (Semantic analysis)
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

        # Step 3: Optional LLM Enrichment
        if not skip_llm:
            llm_insights = await self.llm.analyze_description(listing)
            if llm_insights:
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
                if llm_insights.get("extracted_plot_m2") and not listing.area_plot:
                    try:
                        listing.area_plot = float(llm_insights["extracted_plot_m2"])
                    except (ValueError, TypeError):
                        pass
                for hc in llm_insights.get("hidden_costs", []):
                    cons.append(f"⚠️ [Ukryty koszt] {hc}")
                for p in llm_insights.get("pros", []):
                    if p not in pros:
                        pros.append(f"[LLM] {p}")
                for c in llm_insights.get("cons", []):
                    if c not in cons:
                        cons.append(f"[LLM] {c}")

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
        elif listing.area_plot is None or listing.area_plot == 0:
            status = QualificationStatus.NEEDS_REVIEW
        elif (
            listing.finish_condition == FinishCondition.NIEOKRESLONY
            and listing.sewerage == SewerageType.NIEZNANA
            and listing.heating == HeatingType.NIEZNANE
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
        )


__all__ = [
    "Stage1Filter",
    "Stage2SemanticFilter",
    "LLMAnalyzer",
    "QualificationEngine",
    "generate_property_fingerprint",
    "extract_street_token",
]
