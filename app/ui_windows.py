import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import csv
import webbrowser
from typing import List, Callable, Optional

from ui.dialogs import SelectBuiltinDialog
from app.entity import PatternItem


class PatternWindow(ctk.CTkToplevel):
    """
    Pływające okno do zarządzania listą wzorców.
    """

    def __init__(self, master, title: str, pattern_list: List[PatternItem],
                 pattern_type: str, on_update: Callable):
        super().__init__(master)
        self.title(title)
        self.geometry("450x600")
        self.transient(master)

        self.app = master
        self.pattern_list = pattern_list
        self.pattern_type = pattern_type
        self.on_update = on_update

        self._create_widgets()
        self.refresh_list()

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        btn_frame = ctk.CTkFrame(self)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkButton(btn_frame, text="Dodaj ręcznie", command=self.add_pattern).pack(side="left", expand=True,
                                                                                      fill="x", padx=2)
        ctk.CTkButton(btn_frame, text="Importuj CSV", command=self.import_csv).pack(side="left", expand=True, fill="x",
                                                                                    padx=2)
        ctk.CTkButton(btn_frame, text="Wybierz wbudowane", command=self.open_builtin).pack(side="left", expand=True,
                                                                                           fill="x", padx=2)
        ctk.CTkButton(btn_frame, text="Importuj CSV", command=self.import_csv).pack(side="left", expand=True, fill="x",
                                                                                    padx=2)

    def open_builtin(self):
        SelectBuiltinDialog(self, self.pattern_type, self._add_builtin_patterns)

    def _add_builtin_patterns(self, items):
        for item in items:
            # Unikaj duplikatów
            if not any(x.pattern == item.pattern for x in self.pattern_list):
                self.pattern_list.append(item)
        self.refresh_list()
        self.on_update()

    def refresh_list(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        for item in self.pattern_list:
            self._add_row_ui(item)

    def _add_row_ui(self, item: PatternItem):
        row = ctk.CTkFrame(self.scroll_frame)
        row.pack(fill="x", pady=2)

        chk_var = tk.BooleanVar(value=item.enabled)

        def toggle():
            item.enabled = chk_var.get()
            self.on_update()

        ctk.CTkCheckBox(row, text="", variable=chk_var, command=toggle, width=24).pack(side="left", padx=5)

        text = f"'{item.pattern}'"
        if item.replace:
            text += f" -> '{item.replace}'"
        if not item.case_sensitive:
            text += " (Aa)"

        ctk.CTkLabel(row, text=text, anchor="w").pack(side="left", padx=5, expand=True, fill="x")

        def delete():
            if item in self.pattern_list:
                self.pattern_list.remove(item)
            self.refresh_list()
            self.on_update()

        ctk.CTkButton(row, text="X", width=30, fg_color="#c42b1c", hover_color="#8f1f14", command=delete).pack(
            side="right", padx=2)

    def add_pattern(self):
        # Delegacja do metod z GUI (ze względu na kompatybilność z PatternEditorWindow)
        if self.pattern_type == 'remove':
            self.app.open_add_remove_pattern(callback=lambda: [self.refresh_list(), self.on_update()])
        else:
            self.app.open_add_replace_pattern(callback=lambda: [self.refresh_list(), self.on_update()])

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    count = 0
                    for row in reader:
                        if len(row) >= 1:
                            pat = row[0].strip()
                            rep = row[1].strip() if len(row) > 1 else ""
                            if pat:
                                self.pattern_list.append(PatternItem(pattern=pat, replace=rep))
                                count += 1
                messagebox.showinfo("Import", f"Zaimportowano {count} wzorców.")
                self.refresh_list()
                self.on_update()
            except Exception as e:
                messagebox.showerror("Błąd", str(e))


class AboutWindow(ctk.CTkToplevel):
    """Okno informacji o programie."""

    def __init__(self, master, version: str):
        super().__init__(master)
        self.title("O programie Subtitle Studio")
        self.geometry("400x250")
        self.transient(master)

        ctk.CTkLabel(self, text="Subtitle Studio", font=("", 20, "bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self, text=f"Wersja: {version}").pack(pady=5)
        ctk.CTkLabel(self, text="Twórca: Kamil Pasek").pack(pady=5)

        repo_lbl = ctk.CTkLabel(self, text="GitHub Repository", text_color="#3b8ed0", cursor="hand2")
        repo_lbl.pack(pady=5)
        repo_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/kpasek/subtitle-studio"))

        ctk.CTkButton(self, text="Zamknij", command=self.destroy).pack(pady=20)