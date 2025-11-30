import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import Callable, List
from app.entity import PatternItem
from app.builtin_patterns import BUILTIN_PATTERNS


class SelectBuiltinDialog(ctk.CTkToplevel):
    def __init__(self, master, ptype: str, callback: Callable[[List[PatternItem]], None]):
        super().__init__(master)
        self.title("Wybierz wzorce wbudowane")
        self.geometry("400x500")
        self.callback = callback
        self.ptype = ptype  # 'subtitle' or 'tts'
        self.selected_vars = []
        self.items_to_show = BUILTIN_PATTERNS.get(ptype, [])

        ctk.CTkLabel(self, text="Zaznacz wzorce do dodania:", font=("", 14, "bold")).pack(pady=10)

        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        for item in self.items_to_show:
            var = tk.BooleanVar(value=False)
            chk = ctk.CTkCheckBox(self.scroll, text=item.name, variable=var)
            chk.pack(anchor="w", pady=2)
            self.selected_vars.append((var, item))

        ctk.CTkButton(self, text="Dodaj wybrane", command=self.on_confirm).pack(pady=10)

    def on_confirm(self):
        to_add = [item for var, item in self.selected_vars if var.get()]
        self.callback(to_add)
        self.destroy()


class CommitDialog(ctk.CTkToplevel):
    def __init__(self, master, stats: dict, on_commit: Callable):
        super().__init__(master)
        self.title("Zatwierdzanie zmian (GIT)")
        self.geometry("600x450")
        self.on_commit = on_commit

        ctk.CTkLabel(self, text="Podsumowanie zmian", font=("", 16, "bold")).pack(pady=10)

        info_frame = ctk.CTkFrame(self)
        info_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(info_frame, text=f"Liczba linii: {stats['lines_count']}").pack(anchor="w", padx=5)
        ctk.CTkLabel(info_frame, text=f"Zmiany Git: {stats['diff_stat']}").pack(anchor="w", padx=5)
        ctk.CTkLabel(info_frame, text=f"Audio status: {stats['audio_affected']}", text_color="orange").pack(anchor="w",
                                                                                                            padx=5)

        self.txt_diff = ctk.CTkTextbox(self, height=200)
        self.txt_diff.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_diff.insert("1.0", stats['full_diff'])
        self.txt_diff.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Zatwierdź (Commit)", command=self.confirm, fg_color="green").pack(side="right",
                                                                                                         padx=5)

    def confirm(self):
        self.on_commit()
        self.destroy()


class TTSGenerationDialog(ctk.CTkToplevel):
    def __init__(self, master, count: int, model_name: str, on_generate: Callable):
        super().__init__(master)
        self.title("Generowanie TTS")
        self.geometry("400x300")
        self.on_generate = on_generate

        ctk.CTkLabel(self, text="Konfiguracja Generowania", font=("", 16, "bold")).pack(pady=10)

        ctk.CTkLabel(self, text=f"Liczba linii do przetworzenia: {count}").pack(pady=5)
        ctk.CTkLabel(self, text=f"Model TTS: {model_name}", text_color="cyan").pack(pady=5)

        self.var_clear = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Usuń wcześniej wygenerowane audio", variable=self.var_clear).pack(pady=10)

        ctk.CTkButton(self, text="Generuj", command=self.confirm, fg_color="green").pack(pady=20)

    def confirm(self):
        self.on_generate(self.var_clear.get())
        self.destroy()


class ConversionDialog(ctk.CTkToplevel):
    def __init__(self, master, count: int, on_convert: Callable):
        super().__init__(master)
        self.title("Konwersja Audio")
        self.geometry("400x400")
        self.on_convert = on_convert

        ctk.CTkLabel(self, text="Opcje Konwersji", font=("", 16, "bold")).pack(pady=10)
        ctk.CTkLabel(self, text=f"Plików do konwersji: {count}").pack(pady=5)

        self.var_out1 = tk.BooleanVar(value=True)
        self.var_out2 = tk.BooleanVar(value=False)
        self.var_clear = tk.BooleanVar(value=False)

        chk_frame = ctk.CTkFrame(self)
        chk_frame.pack(pady=10, padx=20, fill="x")

        ctk.CTkCheckBox(chk_frame, text="Generuj output1 (Główny)", variable=self.var_out1).pack(anchor="w", pady=5,
                                                                                                 padx=5)
        ctk.CTkCheckBox(chk_frame, text="Generuj output2 (Radio/Efekt)", variable=self.var_out2).pack(anchor="w",
                                                                                                      pady=5, padx=5)
        ctk.CTkCheckBox(chk_frame, text="Wyczyść folder ready przed startem", variable=self.var_clear).pack(anchor="w",
                                                                                                            pady=5,
                                                                                                            padx=5)

        ctk.CTkLabel(self, text="Filtry pobrane z ustawień globalnych.", font=("", 10)).pack(pady=5)

        ctk.CTkButton(self, text="Rozpocznij Konwersję", command=self.confirm).pack(pady=20)

    def confirm(self):
        self.on_convert({
            "out1": self.var_out1.get(),
            "out2": self.var_out2.get(),
            "clear": self.var_clear.get()
        })
        self.destroy()