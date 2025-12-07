import customtkinter as ctk


class ShortcutsWindow(ctk.CTkToplevel):
    """Okno wyświetlające listę skrótów klawiszowych."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Skróty klawiszowe")
        self.geometry("500x600")  # Nieco wyższe okno
        self.transient(parent)

        ctk.CTkLabel(self, text="Dostępne skróty klawiszowe", font=("", 18, "bold")).pack(pady=15)

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=5)

        shortcuts = [
            ("Ogólne", [
                ("Ctrl + E", "Otwórz ostatnie projekty"),
                ("Ctrl + S", "Zapisz projekt"),
                ("Ctrl + F", "Szukaj (focus na wyszukiwarkę)"),
                ("Tab", "Przełącz widok (Napisy <-> TTS)"),
            ]),
            ("Edycja i Wybór", [
                ("Ctrl + C", "Kopiuj tekst zaznaczonej linii"),
                ("Ctrl + K", "Zatwierdź zmiany"),
                ("Ctrl + R", "Menedżer wzorców"),
            ]),
            ("Audio (Globalne)", [
                ("Ctrl + Shift + G", "Generuj wszystkie audio"),
                ("Ctrl + Shift + R", "Konwersja plików audio"),
            ]),
            ("Edycja linii (Zaznaczona linia)", [
                ("Ctrl + Spacja", "Odtwórz audio"),
                ("Ctrl + G", "Generuj audio (pojedyncze)"),
                ("Ctrl + X", "Usuń audio"),
                ("Del", "Wyczyść treść linii"),
            ])
        ]

        for section, items in shortcuts:
            ctk.CTkLabel(scroll, text=section, font=("", 14, "bold"), anchor="w").pack(fill="x", pady=(10, 5), padx=5)
            for keys, desc in items:
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)

                k_lbl = ctk.CTkLabel(row, text=keys, font=("", 12, "bold"), width=120, anchor="e", text_color="#4fa3d1")
                k_lbl.pack(side="left", padx=(0, 15))
                d_lbl = ctk.CTkLabel(row, text=desc, anchor="w")
                d_lbl.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(self, text="Zamknij", command=self.destroy, width=100).pack(pady=15)