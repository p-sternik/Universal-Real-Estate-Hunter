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

        prompt = f"""Wyodrębnij stan faktyczny z poniższego ogłoszenia nieruchomości i zwróć obiekt JSON.

Reguły rozstrzygania stanu faktycznego:
1. Stan wliczony w cenę: Klasyfikuj wyłącznie stan nieruchomości objęty aktualną ceną z ogłoszenia. Opcje dostępne za dopłatą traktuj jako nieobecne.
2. Ostatni odcinek dojazdu: O jakości dojazdu decyduje bezpośredni wjazd na posesję. Jeśli ostatni odcinek jest polny/nieutwardzony, dojazd jest zły.
3. Media i instalacje: Klasyfikuj jako obecne tylko przy bezpośrednim przyłączu na działce/w budynku. Media "w drodze", "w planach" lub "w trakcie projektowania" traktuj jako brak przyłącza.
4. Koszty i status prawny: Wyodrębnij każdą dopłatę niewliczoną w cenę główną oraz wszelkie ograniczenia prawne (służebności, brak odbioru, cena netto).

Dane nieruchomości:
Tytuł: {listing.title}
Lokalizacja: {listing.location_raw}
Metraż domu: {listing.area_home} m², Działka: {listing.area_plot} m²
Treść ogłoszenia:
{listing.raw_description[:2500]}

Zwróć poprawny JSON o schemacie:
{{
  "finish_condition": "deweloperski" | "pod_klucz" | "surowy_zamkniety" | "surowy_otwarty" | "do_remontu" | "do_wykonczenia" | null,
  "is_corner": boolean | null,         // true wyłącznie dla segmentu skrajnego/narożnego w szeregówce; null jeśli to dom wolnostojący/bliźniak
  "is_middle": boolean | null,         // true dla segmentu środkowego w szeregówce; null jeśli to nie szeregówka
  "has_parking_or_garage": boolean,    // true jeśli w cenie jest garaż lub min. 2 wyznaczone miejsca postojowe na posesji
  "road_is_bad": boolean,              // true jeśli bezpośredni dojazd to droga gruntowa, polna, nieutwardzona lub w planach
  "terrain_risk": boolean,             // true jeśli występuje skarpa, osuwisko, podmokłość lub wysoki spadek
  "sewerage": "miejska" | "szambo" | "oczyszczalnia" | "brak" | null, // stan faktyczny przyłącza na działce/w domu
  "extracted_plot_m2": float | null,   // powierzchnia działki/ogródka w m² podana w tekście (np. 3.2 ara -> 320.0), inaczej null
  "hidden_costs": [string],            // dopłaty nieuwzględnione w cenie (np. "udział w drodze 20 000 zł", "cena netto + 23% VAT", "brak pieca")
  "legal_risks": [string],             // ryzyka prawne/formalne (np. "brak odbioru technicznego", "samowola", "służebność przejazdu")
  "pros": [string],                    // do 4 kluczowych atutów technicznych wliczonych w cenę (np. "pompa ciepła", "podłogówka", "światłowód")
  "cons": [string]                     // do 4 kluczowych mankamentów technicznych, lokalizacyjnych lub kosztowych
}}"""

        # 1. Try OpenRouter if key is present
        if self.openrouter_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=self.openrouter_key,
                    base_url="https://openrouter.ai/api/v1",
                    timeout=15.0,
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
                kwargs = {"api_key": self.openai_key, "timeout": 15.0}
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
