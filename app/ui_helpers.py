import tkinter as tk
import customtkinter as ctk
from ui.shortcuts import ShortcutsWindow


def open_shortcuts_window(app):
    ShortcutsWindow(app)


def show_about_window(app):
    help_win = ctk.CTkToplevel(app)
    help_win.title("Pomoc i O Programie")
    help_win.geometry("700x550")
    help_win.transient(app)
    help_win.lift()
    help_win.focus_force()

    # Kontener z zakładkami
    tabview = ctk.CTkTabview(help_win)
    tabview.pack(fill="both", expand=True, padx=10, pady=10)

    # Definicja zakładek
    tab_intro = tabview.add("Start")
    tab_edit = tabview.add("Edycja i Dialogi")
    tab_tts = tabview.add("Audio i TTS")
    tab_about = tabview.add("O Programie")

    # --- Zakładka 1: Start (Import, Wprowadzenie) ---
    _create_help_section(tab_intro, "Wprowadzenie", 
        "Subtitle Studio to narzędzie do zarządzania, edycji i generowania ścieżek lektorskich (TTS) do filmów.\n"
        "Pozwala na pracę z plikami wideo i napisami, umożliwiając tworzenie dubbingu AI.")
    
    _create_help_section(tab_intro, "Menu Projekt", 
        "• Nowy projekt: Tworzy czystą przestrzeń roboczą.\n"
        "• Otwórz projekt: Wczytuje wcześniej zapisany stan pracy (.json).\n"
        "• Zapisz projekt (Ctrl+S): Zapisuje postępy w pliku .json.")

    _create_help_section(tab_intro, "Pobieranie napisów",
        "W menu 'Dialogi' znajdziesz opcje pobierania:\n"
        "• Pobierz napisy: Zapisuje czyste napisy (oryginalne).\n"
        "• Pobierz napisy TTS: Zapisuje napisy z treścią przeznaczoną dla lektora.")

    # --- Zakładka 2: Edycja i Dialogi ---
    _create_help_section(tab_edit, "Tabela Dialogów",
        "Główny widok listy napisów. Kliknij wiersz, aby go zaznaczyć.\n"
        "• Prawy przycisk myszy: Menu kontekstowe (wytnij, kopiuj, usuń).\n"
        "• Dwuklik: Odtwarza oryginał (jeśli dostępny).")

    _create_help_section(tab_edit, "Statusy i Flagi",
        "Przyciski nad tabelą pozwalają oznaczać stan linii:\n"
        "✅ Gotowe - linia zatwierdzona (blokada edycji).\n"
        "⚠️ Błędne - linia wymaga poprawy.\n"
        "⚪ Wyczyść - resetuje status.")

    _create_help_section(tab_edit, "Wzorce (Ctrl+R)",
        "Menu 'Wzorce' pozwala zarządzać automatycznymi zamianami tekstu (np. skrótów na pełne słowa).\n"
        "Możesz też importować i eksportować reguły do plików CSV.")

    # --- Zakładka 3: Audio i TTS ---
    _create_help_section(tab_tts, "Generowanie (Ctrl+Shift+G)",
        "Opcja 'Generuj dialogi' (w menu lub przycisk nad tabelą) tworzy pliki audio dla zaznaczonych linii korzystając z wybranego modelu TTS (skonfigurowanego w Ustawieniach).")

    _create_help_section(tab_tts, "Weryfikacja",
        "W programie istnieją dwa tryby weryfikacji:\n"
        "1. Przycisk '✓ Weryfikuj' (nad tabelą): Uruchamia automatyczną, programową weryfikację plików audio dla zaznaczonych wierszy.\n"
        "2. Menu 'Dialogi -> Weryfikacja' (Ctrl+Shift+Y): Otwiera okno 'Manualnej Weryfikacji', gdzie możesz przesłuchać i porównać oryginał z TTS.")

    _create_help_section(tab_tts, "Eksport Presetów",
        "Opcja 'Dialogi -> Generuj preset' otwiera okno eksportu (Game Reader Export), które pozwala przygotować paczkę plików do użycia w zewnętrznych narzędziach.")

    # --- Zakładka 4: O Programie ---
    ctk.CTkLabel(tab_about, text=getattr(app, 'APP_TITLE', 'Subtitle Studio'), font=("", 24, "bold")).pack(pady=(40, 10))
    ctk.CTkLabel(tab_about, text=f"Wersja: {getattr(app, 'APP_VERSION', 'Unknown')}").pack(pady=5)
    ctk.CTkLabel(tab_about, text="Autor: Kamil Pasek").pack(pady=5)
    ctk.CTkLabel(tab_about, text="Copyright © 2025-2026").pack(pady=20)
    
    ctk.CTkButton(tab_about, text="Skróty klawiszowe", command=lambda: open_shortcuts_window(app)).pack(pady=20)
    ctk.CTkButton(tab_about, text="Zamknij", command=help_win.destroy, fg_color="gray").pack(pady=10)


def _create_help_section(parent, title, content):
    """Helper do tworzenia sekcji tekstu w zakładce."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="x", padx=10, pady=(10, 0), anchor="n")
    
    ctk.CTkLabel(frame, text=title, font=("", 16, "bold"), anchor="w").pack(fill="x")
    ctk.CTkLabel(frame, text=content, font=("", 13), anchor="w", justify="left", wraplength=450).pack(fill="x", pady=(2, 0))


def show_editor_context_menu(app, event):
    menu = tk.Menu(app, tearoff=0)
    menu.add_command(label="Wytnij", command=lambda: app.subtitle_panel.editor.entry.event_generate("<<Cut>>"))
    menu.add_command(label="Kopiuj", command=lambda: app.subtitle_panel.editor.entry.event_generate("<<Copy>>"))
    menu.add_command(label="Wklej", command=lambda: app.subtitle_panel.editor.entry.event_generate("<<Paste>>"))
    menu.tk_popup(event.x_root, event.y_root)
