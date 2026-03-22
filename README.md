# Subtitle Studio

**Subtitle Studio** to zaawansowane narzędzie okienkowe stworzone do edycji napisów, zarządzania nimi oraz automatyzacji procesu generowania dubbingu (TTS) do gier. Aplikacja pozwala na wygodną pracę z plikami napisów, mapowanie głosów postaci oraz masowe generowanie i konwersję plików audio.

---

## 🚀 Główne funkcje

### 📂 Zarządzanie Projektem (Menu: Projekt)

Zarządzanie stanem pracy odbywa się poprzez pliki projektów `.json`.
* **Otwórz projekt (.json)** – Wczytuje wcześniej zapisany stan pracy (ustawienia, ścieżki, mapowanie głosów).
* **Otwórz ostatni... (Ctrl+E)** – Szybki dostęp do listy ostatnio edytowanych projektów.
* **Zapisz projekt (Ctrl+S)** – Zapisuje bieżące postępy.
* **Zapisz jako** – Pozwala zapisać kopię projektu pod nową nazwą.
* **Zamknij projekt** – Czyści bieżący widok i resetuje ustawienia do domyślnych.
* **Zamknij** – Wyłącza aplikację.

### 💬 Dialogi i Audio (Menu: Dialogi)

To serce aplikacji, gdzie odbywa się praca z plikami.
* **Wczytaj napisy** – Importuje plik z napisami (obsługa formatów tekstowych).
* **Wybierz katalog audio** – Wskazuje folder, do którego będą trafiać wygenerowane pliki dźwiękowe.
* **Pokaż kolejkę zadań (Ctrl+Q)** – Otwiera okno menedżera, który w tle przetwarza generowanie TTS i konwersję plików.
* **Generuj dialogi (Ctrl+Shift+G)** – Rozpoczyna proces generowania audio dla wszystkich linii (lub brakujących).
* **Konwertuj audio (Ctrl+Shift+R)** – Uruchamia przetwarzanie plików (np. formatowanie do OGG/MP3, normalizacja) przy użyciu FFmpeg.
* **Usuń przekonwertowane pliki** – Czyści folder `ready` (gotowe pliki), przydatne przy regeneracji.
* **Pobierz napisy / Pobierz napisy TTS** – Eksportuje przetworzone napisy:
    * *Clean* – Czyste napisy wyświetlane w grze.
    * *TTS* – Napisy przygotowane pod syntezator mowy (np. z rozwiniętymi skrótami "100 zł" -> "sto złotych").

### 🧩 Wzorce i Regex (Menu: Wzorce)

Automatyzacja czyszczenia i zamiany tekstu.
* **Menedżer wzorców (Ctrl+R)** – Pozwala definiować reguły zamiany tekstu (np. usuwanie tagów HTML, zamiana literówek). Dzieli się na:
    * *Napisy (Czyszczenie)* – Modyfikacje widoczne dla gracza.
    * *TTS (Podmiana)* – Modyfikacje słyszalne (wymowa).
* **Importuj/Eksportuj wzorce z CSV** – Możliwość przenoszenia bazy wzorców między projektami. Format CSV obsługuje: `Wzorzec, Zamiennik, CzyWielkośćLiterMaZnaczenie`.
* **Usuwanie dialogów** – Narzędzie do masowego usuwania plików audio dla konkretnych wzorców (np. usunięcie wszystkich kwestii Narratora).

### ⚙️ Ustawienia (Menu: Ustawienia)

* **Ustawienia aplikacji** – Globalne konfiguracje (wygląd, domyślne ścieżki).
* **Ustawienia projektu** – Konfiguracja specyficzna dla danej gry/filmu (wybrany silnik TTS).

---

## 🖥️ Okno Główne i Edycja

### Lista Napisów
Główna część okna wyświetla listę linii dialogowych.
* **Interakcja:** Kliknięcie na linię ładuje ją do edytora na dole.

### Edytor Linii
Znajduje się pod listą napisów. Pozwala na ręczną modyfikację tekstu wybranej linii bez ingerencji w plik źródłowy na dysku (zmiany są w pamięci projektu).
* Przydatne do poprawiania literówek lub zmiany fonetycznej pisowni dla TTS (np. wpisanie "Dżi-ti-ej" zamiast "GTA").

### 🔍 Wyszukiwarka (Regex)
Pasek wyszukiwania obsługuje wyrażenia regularne (Regex), co pozwala na zaawansowane filtrowanie.

**Przykłady wyszukiwania:**
1.  **Zwykły tekst:**
    * Wpisz: `zamek`
    * *Znajdzie wszystkie linie zawierające słowo "zamek".*
2.  **Początek linii (`^`):**
    * Wpisz: `^Hej`
    * *Znajdzie linie zaczynające się od "Hej".*
3.  **Koniec linii (`$`):**
    * Wpisz: `koniec\.$`
    * *Znajdzie linie kończące się słowem "koniec." (kropka musi być poprzedzona backslashem).*
4.  **Alternatywa (`|`):**
    * Wpisz: `(Tak|Nie)`
    * *Znajdzie linie zawierające słowo "Tak" LUB "Nie".*
5.  **Długość znaku (`.`):**
    * Wpisz: `^...$`
    * *Znajdzie linie mające dokładnie 3 znaki.*

---

## 🔊 Generowanie Audio

Aplikacja wspiera różne silniki TTS. Konfiguracja odbywa się w ustawieniach projektu.
* **Google Cloud TTS** – Wysoka jakość, wymaga pliku credentials JSON.
* **ElevenLabs** – Najwyższa jakość (głosy AI), wymaga klucza API.
* **Local API (XTTS)** – Współpraca z lokalnymi serwerami generowania mowy.

Dla zaawansowanej obsługi lokalnej, Subtitle Studio współpracuje z repozytorium:
👉 **[TTS Dialog Generator](https://github.com/kpasek/tts-dialog-generator)**

---

## ⌨️ Skróty Klawiszowe

Pełna lista skrótów dostępna w menu **Pomoc -> Skróty klawiszowe**.

| Kategoria | Skrót | Akcja |
| :--- | :--- | :--- |
| **Ogólne** | `Ctrl + S` | Zapisz projekt |
| | `Ctrl + E` | Otwórz ostatnie projekty |
| | `Ctrl + F` | Szukaj (aktywacja paska szukania) |
| | `Ctrl + Q` | Pokaż kolejkę zadań (Queue) |
| | `Tab` | Przełącz widok (Tekst Napisów <-> Tekst TTS) |
| **Edycja** | `Ctrl + C` | Kopiuj tekst zaznaczonej linii |
| | `Ctrl + K` | Zatwierdź zmiany w edytorze |
| | `Ctrl + R` | Otwórz Menedżer Wzorców |
| **Audio (Globalne)** | `Ctrl + Shift + G` | Generuj wszystkie brakujące audio |
| | `Ctrl + Shift + R` | Konwertuj pliki audio |
| **Audio (Linia)** | `Ctrl + Spacja` | Odtwórz audio dla wybranej linii |
| | `Ctrl + G` | Generuj audio tylko dla tej linii |
| | `Ctrl + X` | Usuń audio dla tej linii |
| | `Del` | Wyczyść treść linii |