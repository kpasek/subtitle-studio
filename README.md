# 🎬 Subtitle Studio – Przewodnik użytkownika

Subtitle Studio to aplikacja desktopowa do czyszczenia i przygotowywania napisów dialogowych dla systemów TTS (Text-to-Speech) i Game Reader.
Umożliwia wczytanie napisów, zastosowanie wzorców REGEX do usuwania lub poprawiania treści, generowanie dialogów głosowych oraz zarządzanie powiązanymi plikami audio.

## 🧭 Workflow – krok po kroku
### 1. Otwieranie napisów

Uruchom aplikację Subtitle Studio.

W menu górnym wybierz:
`Dialogi → Wczytaj napisy`

Wskaż plik `.txt` zawierający napisy (np. subtitles.txt).

Zawartość pojawi się w głównym oknie po prawej stronie.

💡 W każdej chwili możesz zapisać bieżący stan projektu wybierając `Projekt → Zapisz projekt`.
Aplikacja zapamięta wybrane pliki, wzorce oraz katalog audio.

### 2. Czyszczenie napisów – wzorce wycinające

Po lewej stronie znajdziesz sekcję Wbudowane wzorce wycinające.
Służą one do usuwania całych linii zawierających określone elementy (np. znaczniki \<i>, liczby, komentarze).

Zaznacz wybrane wzorce (np. Usuń całe linie [*-]).

Możesz dodać własne wzorce w sekcji Własne wzorce wycinające:

- wpisz wyrażenie regularne (regexp),

- opcjonalnie określ zamiennik,

- kliknij `Dodaj`.

- Kliknij przycisk `Zastosuj wzorce`, aby przetworzyć tekst.

✨ Linie usunięte zostaną oznaczone jako odrzucone, a widok w podglądzie zostanie zaktualizowany.

### 3. Poprawianie treści – wzorce podmieniające

Niżej znajduje się sekcja Wbudowane wzorce podmieniające – automatycznie poprawiają treść napisów, np.:

* zamieniają wielokrotne znaki interpunkcyjne,
* usuwają znaki specjalne,
* poprawiają trójkropki,
* zastępują białe znaki pojedynczymi spacjami.

Analogicznie możesz dodać własne wzorce podmieniające, by lepiej dopasować dane do modeli TTS.

🔍 Dobrze przygotowane napisy (bez znaków specjalnych, skrótów, oznaczeń scen) znacząco poprawiają jakość generowanego głosu.

### 4. Generowanie i odsłuchiwanie plików audio

Po przetworzeniu napisów możesz generować i przeglądać dialogi:

Wybierz katalog roboczy dla plików audio:
`Dialogi → Wybierz katalog audio`

W głównym oknie:

Każdy wiersz odpowiada jednej linii dialogowej.

Obok znajduje się przycisk `Odtwórz`, który umożliwia odsłuch wybranego pliku audio. Można też kliknąć 2x na liście dialogowej, aby odsługać audio.

Obok przycisku dostępna jest lista rozwijana z odnalezionymi plikami audio (jeśli istnieje kilka wersji).

Aby wygenerować nowy plik audio, kliknij przycisk `Generuj` przy danej linii.

## 🗣️ Obsługiwane modele TTS:

* ElevenLabs,
* Google Cloud TTS,
* XTTSv2 (lokalny model).
* STylish TTS (localny model)

### 5. Usuwanie plików audio

Subtitle Studio pozwala zarządzać nagraniami audio w sposób elastyczny:

🔸 Usuwanie pojedynczego pliku

Kliknij Usuń obok konkretnej linii – spowoduje to usunięcie odpowiadającego jej pliku audio.

🔸 Usuwanie wszystkich plików dla dialogu

Kliknij Usuń Wsz., aby skasować wszystkie warianty audio powiązane z daną linią.

🔸 Masowe usuwanie plików

W menu wybierz:
`Dialogi → Masowe usuwanie plików audio`

Wprowadź wzorce `REGEX` dopasowujące treść dialogów, których pliki chcesz usunąć.

Kliknij `Dodaj` aby dodać wzorzec do listy.

Wciśnij `Przelicz`, aby aplikacja wyświetliła liczbę pasujących linii i plików.

Kliknij `Usuń pliki`, aby wykonać operację.

## 6. Wyszukiwanie i podgląd

W górnej części okna znajduje się pole Szukaj – możesz tu wprowadzić dowolny wzorzec (także REGEX), by szybko odszukać konkretne linie w podglądzie.

## 7. Eksport napisów

Po zakończeniu pracy możesz zapisać wyniki:

`Pobierz – napisy dla TTS` → zapisuje oczyszczoną wersję do użycia z generatorami głosu.

`Pobierz – napisy dla Game Reader` → przygotowuje napisy w formacie zgodnym z Game Readerem.

## ⚙️ Ustawienia

W zakładce Ustawienia możesz określić m.in.:

* domyślne katalogi wejściowe i wyjściowe,
* model TTS do użycia,
* parametry generowania (głos, prędkość, język),
* parametry przetwarzania audio
* host i port do lokalnego modelu XTTSv2 (jeśli używasz wersji offline).
