import requests
import uuid
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

@dataclass
class AITask:
    name: str
    system_prompt: str
    is_readonly: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(data: dict):
        return AITask(
            name=data.get("name", "Unnamed Task"),
            system_prompt=data.get("system_prompt", ""),
            is_readonly=data.get("is_readonly", False),
            id=data.get("id", str(uuid.uuid4()))
        )

# Wbudowane prompty
BUILTIN_TASKS = [
    AITask(
        name="Liczby i daty na formę fonetyczną",
        system_prompt=(
            "Zamień wszystkie liczby i daty w tekście na ich pełną formę słowną w języku polskim (np. '123' -> 'sto dwadzieścia trzy', '1999' -> 'tysiąc dziewięćset dziewięćdziesiąty dziewiąty'). Resztę tekstu pozostaw bez zmian. Zwróć TYLKO przetworzony tekst.\n"
            "Jeśli masz wątpliwości co do tego jakiego typu liczby lub data jest lub nie jest to zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    ),
    AITask(
        name="Usuń onomatopeje",
        system_prompt=(
            "Twoim zadaniem jest usunięcie z tekstu wszelkich onomatopei (np. pf, ehh, yyy, wrr, westchnienie, płacz). Usuń także opisy dźwięków w nawiasach. Zwróć TYLKO wyczyszczony tekst dialogu.\n"
            "Jeśli masz wątpliwości co do tego czy dany ciąg jest onomatopeją lub nie zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    ),
    AITask(
        name="Usuń znaki specjalne (dla lektora)",
        system_prompt=(
            "Przygotuj tekst dla syntezatora mowy (TTS). Usuń znaki, których lektor nie powinien czytać (np. *, #, @, --). Pozostaw interpunkcję gramatyczną. Zwróć TYLKO gotowy tekst.\n"
            "Jeśli masz wątpliwości co do tego czy dany znak powinien zostać usunięty zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    ),
    AITask(
        name="Tłumaczenie na Polski",
        system_prompt=(
            "Jesteś profesjonalnym tłumaczem napisów filmowych. Przetłumacz podany tekst na język polski, zachowując kontekst i styl wypowiedzi. Zwróć TYLKO przetłumaczony tekst, bez żadnych dodatkowych komentarzy.\n"
            "Jeśli masz wątpliwości co do tego czy dany wyraz powinien zostać przełożony na inny sposób zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    ),
    AITask(
        name="Zamień obce słowa na fonetyczne odpowiedniki",
        system_prompt=(
            "Jesteś profesjonalnym tłumaczem napisów. Zamień obce słowa na ich fonetyczne odpowiedniki w języku polskim. Zwróć TYLKO gotowy tekst.\n"
            "Jeśli masz wątpliwości co do tego czy dany wyraz powinien zostać przełożony na inny sposób zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    ),
    AITask(
        name="Korekta językowa",
        system_prompt=(
            "Jesteś korektorem. Popraw błędy ortograficzne, interpunkcyjne i stylistyczne w podanym tekście. Nie zmieniaj sensu wypowiedzi. Zwróć TYLKO poprawiony tekst.\n"
            "Jeśli masz wątpliwości co do tego czy dany wyraz jest błędny zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    ),
    AITask(
        name="Usuń elementy interfejsu",
        system_prompt=(
            "Sprawdzasz napisy wyciągnięte z gry. Mogą one zawierać nazwy interfejsu lub inne elementy gry. Twoim zadaniem jest ustalić czy dany tekst jest elementem interfejsu czy nie. Jeżeli tak zwóć pusta odpowiedź bez żadnego formatowania, jeśli nie zwróć oryginalny tekst bez żadnych przeróbek i bez zmian.\n"
            "Jeśli masz wątpliwości co do tego czy dany wyraz jest elementem interfejsu zawsze lepiej zwrócić oryginalny tekst bez żadnych przeróbek."
        ),
        is_readonly=True
    )
]

class OllamaService:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip('/')
        self.model = model

    def check_connection(self) -> bool:
        """Sprawdza czy serwer Ollama jest dostępny."""
        try:
            # Endpoint /api/tags zwraca listę modeli, szybki test
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama connection error: {e}")
            return False

    def process_text(self, text: str, system_prompt: str) -> str:
        """Wysyła tekst do modelu i zwraca odpowiedź."""
        if not text or not text.strip():
            return ""

        url = f"{self.base_url}/api/generate"
        
        # Construct full prompt
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": text,
            "stream": False,
            "options": {
                "temperature": 0.3
            }
        }
        print("Wysyłanie do Ollama:", payload) 

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            print("Odpowiedź z Ollama:", data.get("response", ""))
            return data.get("response", "").strip().strip('`')
        except Exception as e:
            logger.error(f"AI Processing error: {e}")
            raise e
