import json
from typing import Any, Dict, Optional
from loguru import logger
import httpx

from config import settings
from src.models.listing import ListingSchema


class LLMAnalyzer:
    """
    Optional LLM analyzer for deep semantic description evaluation.
    Supports OpenRouter, OpenAI API, and local Ollama instances.
    Returns structured JSON with segment type, road conditions, parking, and terrain notes.
    """

    def __init__(self):
        self.enabled = settings.USE_LLM_ANALYSIS
        self.openrouter_key = settings.OPENROUTER_API_KEY
        self.openrouter_model = settings.OPENROUTER_MODEL
        self.openai_key = settings.OPENAI_API_KEY
        self.openai_model = settings.OPENAI_MODEL
        self.openai_base_url = settings.OPENAI_BASE_URL
        self.ollama_url = settings.OLLAMA_BASE_URL
        self.ollama_model = settings.OLLAMA_MODEL

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            return json.loads(cleaned)
        except Exception as e:
            logger.warning(f"[LLMAnalyzer] Failed to parse JSON: {e}. Raw content: {cleaned[:200]}")
            return None

    async def analyze_description(self, listing: ListingSchema) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        prompt = f"""Wyodrębnij fakty z poniższego ogłoszenia nieruchomości i zwróć obiekt JSON.
Zasady:
- Bazuj wyłącznie na faktach stwierdzonych wprost w tekście.
- Przy braku jednoznacznego potwierdzenia w tekście przypisz false lub null.
- Ignoruj marketingowe deklaracje przyszłości ("droga w planach", "możliwość garażu").

Dane nieruchomości:
Tytuł: {listing.title}
Lokalizacja: {listing.location_raw}
Metraż domu: {listing.area_home} m², Działka: {listing.area_plot} m²
Treść ogłoszenia:
{listing.raw_description[:2500]}

Zwróć poprawny JSON o schemacie:
{{
  "is_corner": boolean,              // true wyłącznie dla segmentu skrajnego, narożnego lub ostatniego w szeregu
  "is_middle": boolean,              // true wyłącznie dla segmentu środkowego lub wewnętrznego
  "has_parking_or_garage": boolean,  // true jeśli posiada garaż lub min. 2 dedykowane miejsca postojowe
  "road_is_bad": boolean,            // true jeśli dojazd to droga gruntowa, polna, nieutwardzona lub w planach
  "terrain_risk": boolean,           // true jeśli występuje skarpa, osuwisko, teren zalewowy lub podmokły
  "extracted_plot_m2": float | null, // metraż działki lub ogródka w m² wymieniony w opisie (np. 3.5 ara -> 350.0), inaczej null
  "hidden_costs": [string],          // wykryte dopłaty (np. "udział w drodze 25 000 zł", "cena netto + 23% VAT", "brak pieca")
  "pros": [string],                  // do 4 kluczowych atutów technicznych (np. "pompa ciepła", "podłogówka", "światłowód")
  "cons": [string]                   // do 4 kluczowych mankamentów technicznych lub prawnych
}}"""

        # 1. Try OpenRouter if key is present
        if self.openrouter_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=self.openrouter_key,
                    base_url="https://openrouter.ai/api/v1",
                    default_headers={
                        "HTTP-Referer": "https://github.com/p-sternik/Universal-Real-Estate-Hunter",
                        "X-Title": "Universal Real Estate Hunter",
                    },
                )
                response = await client.chat.completions.create(
                    model=self.openrouter_model,
                    messages=[
                        {"role": "system", "content": "Jesteś analitykiem rynku nieruchomości. Zwracaj wyłącznie poprawny obiekt JSON bez żadnego innego tekstu."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                )
                content = response.choices[0].message.content or "{}"
                result = self._parse_json(content)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"[LLMAnalyzer] OpenRouter error: {e}. Falling back to OpenAI or Ollama.")

        # 2. Try OpenAI if key is present
        if self.openai_key:
            try:
                from openai import AsyncOpenAI
                kwargs = {"api_key": self.openai_key}
                if self.openai_base_url:
                    kwargs["base_url"] = self.openai_base_url
                client = AsyncOpenAI(**kwargs)
                response = await client.chat.completions.create(
                    model=self.openai_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "Jesteś analitykiem rynku nieruchomości. Odpowiadasz w formacie JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                )
                content = response.choices[0].message.content or "{}"
                result = self._parse_json(content)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"[LLMAnalyzer] OpenAI error: {e}. Falling back to Ollama or regex.")

        # 3. Try Ollama if running
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
                    return self._parse_json(payload.get("response", "{}"))
        except Exception as e:
            logger.debug(f"[LLMAnalyzer] Ollama unavailable: {e}")

        return None
