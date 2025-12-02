import customtkinter as ctk
import tkinter as tk
import json
from tkinter import messagebox
from typing import Callable, List, Dict
from app.entity import PatternItem
from app.builtin_patterns import BUILTIN_PATTERNS


class SelectBuiltinDialog(ctk.CTkToplevel):
    def __init__(self, master, ptype: str, callback: Callable[[List[PatternItem]], None]):
        super().__init__(master)
        self.title(f"Wybierz wzorce ({ptype})")
        self.geometry("450x550")
        # Fix na chowanie się okna
        self.transient(master)
        self.lift()
        self.focus_force()

        self.callback = callback
        self.ptype = ptype  # 'subtitle' or 'tts'
        self.selected_vars = []

        # Pobieramy wzorce dla danego typu, jeśli brak - pusta lista
        self.items_to_show = BUILTIN_PATTERNS.get(ptype, [])

        ctk.CTkLabel(self, text=f"Dostępne wzorce wbudowane ({len(self.items_to_show)}):", font=("", 14, "bold")).pack(
            pady=10)

        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        if not self.items_to_show:
            ctk.CTkLabel(self.scroll, text="Brak zdefiniowanych wzorców dla tego typu.").pack(pady=20)
        else:
            for item in self.items_to_show:
                var = tk.BooleanVar(value=False)
                # Wyświetlamy nazwę lub pattern jeśli nazwa jest pusta
                label_text = item.name if item.name else item.pattern
                chk = ctk.CTkCheckBox(self.scroll, text=label_text, variable=var)
                chk.pack(anchor="w", pady=5, padx=5)
                self.selected_vars.append((var, item))

        ctk.CTkButton(self, text="Dodaj zaznaczone", command=self.on_confirm).pack(pady=10)

    def on_confirm(self):
        to_add = [item for var, item in self.selected_vars if var.get()]
        if not to_add and self.items_to_show:
            messagebox.showinfo("Info", "Nie zaznaczono żadnych wzorców.")
            return

        self.callback(to_add)
        self.destroy()


class CommitDialog(ctk.CTkToplevel):
    def __init__(self, master, stats: dict, on_commit: Callable):
        super().__init__(master)
        self.title("Zatwierdzanie zmian (GIT)")
        self.geometry("700x500")
        self.transient(master)
        self.lift()
        self.on_commit = on_commit

        ctk.CTkLabel(self, text="Podsumowanie zmian", font=("", 16, "bold")).pack(pady=10)

        info_frame = ctk.CTkFrame(self)
        info_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(info_frame, text=f"Liczba linii w projekcie: {stats.get('lines_count', 0)}").pack(anchor="w",
                                                                                                       padx=10, pady=2)
        ctk.CTkLabel(info_frame, text=f"Zmiany Git: {stats.get('diff_stat', 'Brak danych')}").pack(anchor="w", padx=10,
                                                                                                   pady=2)

        # Audio impact warning
        impact = stats.get('audio_affected', '')
        if impact:
            ctk.CTkLabel(info_frame, text=f"Audio: {impact}", text_color="orange").pack(anchor="w", padx=10, pady=2)

        ctk.CTkLabel(self, text="Szczegóły zmian (Diff):").pack(anchor="w", padx=10, pady=(10, 0))
        self.txt_diff = ctk.CTkTextbox(self, height=200, font=("Consolas", 12))
        self.txt_diff.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_diff.insert("1.0", stats.get('full_diff', 'Brak zmian w treści.'))
        self.txt_diff.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", padx=5,
                                                                                            expand=True)
        ctk.CTkButton(btn_frame, text="Zatwierdź (Commit)", command=self.confirm, fg_color="green").pack(side="right",
                                                                                                         padx=5,
                                                                                                         expand=True)

    def confirm(self):
        self.on_commit()
        self.destroy()


class TTSGenerationDialog(ctk.CTkToplevel):
    def __init__(self, master, count: int, model_name: str, on_generate: Callable):
        super().__init__(master)
        self.title("Generowanie TTS")
        self.geometry("400x350")
        self.transient(master)
        self.lift()
        self.on_generate = on_generate

        ctk.CTkLabel(self, text="Konfiguracja Generowania", font=("", 16, "bold")).pack(pady=10)

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text=f"Liczba linii do przetworzenia: {count}").pack(pady=5)
        ctk.CTkLabel(frame, text=f"Wybrany model: {model_name}", text_color="cyan").pack(pady=5)

        self.var_clear = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Usuń stare pliki audio przed startem", variable=self.var_clear).pack(pady=20)

        ctk.CTkButton(self, text="Generuj", command=self.confirm, fg_color="green").pack(pady=10)

    def confirm(self):
        self.on_generate(self.var_clear.get())
        self.destroy()


class ConversionDialog(ctk.CTkToplevel):
    def __init__(self, master, count: int, filters: dict, on_convert: Callable):
        super().__init__(master)
        self.title("Konwersja Audio")
        self.geometry("500x550")
        self.transient(master)
        self.lift()
        self.on_convert = on_convert

        ctk.CTkLabel(self, text="Opcje Konwersji (ffmpeg)", font=("", 16, "bold")).pack(pady=10)
        ctk.CTkLabel(self, text=f"Znaleziono plików źródłowych: {count}").pack(pady=5)

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.var_out1 = tk.BooleanVar(value=True)
        self.var_out2 = tk.BooleanVar(value=False)
        self.var_clear = tk.BooleanVar(value=False)

        ctk.CTkCheckBox(frame, text="output1 (Normalna prędkość)", variable=self.var_out1).pack(anchor="w", pady=5,
                                                                                                padx=10)
        ctk.CTkCheckBox(frame, text="output2 (Lekko przyspieszone - Lektor legacy)", variable=self.var_out2).pack(
            anchor="w", pady=5, padx=10)
        ctk.CTkCheckBox(frame, text="Wyczyść folder 'ready' przed startem", variable=self.var_clear).pack(anchor="w",
                                                                                                          pady=15,
                                                                                                          padx=10)

        ctk.CTkLabel(frame, text="Zastosowane filtry:", font=("", 12, "bold")).pack(anchor="w", padx=10, pady=(10, 2))

        # Wyświetlanie filtrów
        filter_text = json.dumps(filters, indent=2)
        txt = ctk.CTkTextbox(frame, height=100)
        txt.pack(fill="x", padx=10, pady=5)
        txt.insert("1.0", filter_text)
        txt.configure(state="disabled")

        ctk.CTkButton(self, text="Rozpocznij Konwersję", command=self.confirm).pack(pady=20)

    def confirm(self):
        self.on_convert({
            "out1": self.var_out1.get(),
            "out2": self.var_out2.get(),
            "clear": self.var_clear.get()
        })
        self.destroy()