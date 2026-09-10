import json
from typing import Any, Dict, Optional
from loguru import logger
import httpx

from config import settings
from src.models.listing import ListingSchema


class LLMAnalyzer:
    """
    Optional LLM analyzer for deep semantic description evaluation.
    Supports OpenAI API and local Ollama instances.
    Returns structured JSON with segment type, road conditions, parking, and terrain notes.
    """

    def __init__(self):
        self.enabled = settings.USE_LLM_ANALYSIS
        self.openai_key = settings.OPENAI_API_KEY
        self.openai_model = settings.OPENAI_MODEL
        self.ollama_url = settings.OLLAMA_BASE_URL
        self.ollama_model = settings.OLLAMA_MODEL

    async def analyze_description(self, listing: ListingSchema) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        prompt = f"""Przeanalizuj poniższe ogłoszenie nieruchomości w rejonie Rzeszowa i zwróć wyłącznie poprawny obiekt JSON.
Tytuł: {listing.title}
Lokalizacja: {listing.location_raw}
Metraż: {listing.area_home} m2, Działka: {listing.area_plot} m2
Opis:
{listing.raw_description[:2500]}

Odpowiedz wyłącznie poprawnym JSON-em o schemacie:
{{
  "is_corner": true/false (czy to segment skrajny/narożny/ostatni w rzędzie),
  "is_middle": true/false (czy to segment środkowy),
  "has_parking_or_garage": true/false (czy jest garaż lub min. 2 miejsca postojowe),
  "road_is_bad": true/false (czy droga to droga polna, gruntowa lub brak zjazdu),
  "terrain_risk": true/false (czy jest stroma skarpa, gliniaste podłoże lub osuwisko),
  "extracted_plot_m2": float lub null,
  "pros": ["zaleta 1", "zaleta 2"],
  "cons": ["wada 1", "wada 2"]
}}"""

        # 1. Try OpenAI if key is present
        if self.openai_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=self.openai_key)
                response = await client.chat.completions.create(
                    model=self.openai_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "Jesteś analitykiem rynku nieruchomości. Odpowiadasz w formacie JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                )
                content = response.choices[0].message.content
                return json.loads(content)
            except Exception as e:
                logger.warning(f"[LLMAnalyzer] OpenAI error: {e}. Falling back to Ollama or regex.")

        # 2. Try Ollama if running
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                    },
                )
                if res.status_code == 200:
                    payload = res.json()
                    return json.loads(payload.get("response", "{}"))
        except Exception as e:
            logger.debug(f"[LLMAnalyzer] Ollama unavailable: {e}")

        return None
