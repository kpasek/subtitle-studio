from typing import TYPE_CHECKING, Optional
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import re

from app.entity import PatternItem

if TYPE_CHECKING:
    from gui import SubtitleStudioApp


class PatternEditorWindow(ctk.CTkToplevel):
    """
    Nowe okno modalne do dodawania lub edycji wzorców (usuwających i podmieniających).
    """

    def __init__(self,
                 parent,
                 pattern_type: str,
                 callback,
                 existing_pattern: Optional[PatternItem] = None):
        super().__init__(parent)
        self.parent_app = parent
        self.pattern_type = pattern_type
        self.callback = callback
        self.existing_pattern = existing_pattern

        title = "Edytuj wzorzec" if existing_pattern else "Dodaj wzorzec"
        title += " wycinający" if pattern_type == 'remove' else " podmieniający"
        self.title(title)
        self.geometry("600x450")
        self.resizable(False, False)

        # Zablokuj okno nadrzędne
        # self.grab_set()
        self.transient(parent)

        self.grid_columnconfigure(0, weight=1)

        # --- Pola wejściowe ---
        ctk.CTkLabel(self, text="Wzorzec (Regex)").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        self.ent_pattern = ctk.CTkEntry(self, placeholder_text="regexp")
        self.ent_pattern.grid(row=1, column=0, sticky="ew", padx=10)

        ctk.CTkLabel(self, text="Zamień na").grid(
            row=2, column=0, sticky="w", padx=10, pady=(10, 2))
        self.ent_replace = ctk.CTkEntry(
            self, placeholder_text="tekst zastępujący")
        self.ent_replace.grid(row=3, column=0, sticky="ew", padx=10)

        self.var_case_sensitive = tk.BooleanVar(value=True)
        self.chk_case_sensitive = ctk.CTkCheckBox(
            self, text="Uwzględnij wielkość liter (Aa)", variable=self.var_case_sensitive)
        self.chk_case_sensitive.grid(
            row=4, column=0, sticky="w", padx=10, pady=10)

        # --- Sekcja testowania ---
        separator = ctk.CTkFrame(self, height=2)
        separator.grid(row=5, column=0, sticky="ew", padx=10, pady=10)

        ctk.CTkLabel(self, text="Tekst testowy").grid(
            row=6, column=0, sticky="w", padx=10, pady=(0, 2))
        self.ent_test_text = ctk.CTkEntry(
            self, placeholder_text="Wpisz tekst do przetestowania wzorca...")
        self.ent_test_text.grid(row=7, column=0, sticky="ew", padx=10)

        ctk.CTkLabel(self, text="Wynik testu:").grid(
            row=8, column=0, sticky="w", padx=10, pady=(5, 2))
        self.lbl_test_result = ctk.CTkLabel(
            self, text="", text_color="gray", anchor="w", justify="left")
        self.lbl_test_result.grid(row=9, column=0, sticky="ew", padx=10)

        test_frame = ctk.CTkFrame(self)
        test_frame.grid(row=10, column=0, sticky="ew", padx=10, pady=5)
        self.btn_test = ctk.CTkButton(
            test_frame, text="Testuj", command=self.test_pattern)
        self.btn_test.pack(side="left", padx=(0, 5))
        self.btn_check = ctk.CTkButton(
            test_frame, text="Sprawdź poprawność", command=self.check_pattern)
        self.btn_check.pack(side="left")

        # --- Przyciski akcji ---
        action_frame = ctk.CTkFrame(self)
        action_frame.grid(row=11, column=0, sticky="ew",
                          padx=10, pady=(20, 10))

        self.btn_add = ctk.CTkButton(
            action_frame, text="Zapisz i zamknij" if existing_pattern else "Dodaj", command=self.add_pattern)
        self.btn_add.pack(side="right", padx=5)
        self.btn_cancel = ctk.CTkButton(
            action_frame, text="Anuluj", command=self.destroy, fg_color="gray")
        self.btn_cancel.pack(side="right")

        # Jeśli edytujemy, wypełnij pola
        if self.existing_pattern:
            self.populate_fields()

        # Jeśli to wzorzec 'remove', domyślnie wyłącz pole 'replace'
        if self.pattern_type == 'remove' and not self.existing_pattern:
            self.ent_replace.insert(0, "")
            self.ent_replace.configure(state="disabled")

    def populate_fields(self):
        """Wypełnia pola danymi z istniejącego wzorca."""
        if not self.existing_pattern:
            return
        self.ent_pattern.insert(0, self.existing_pattern.pattern)
        self.ent_replace.insert(0, self.existing_pattern.replace)
        self.var_case_sensitive.set(self.existing_pattern.case_sensitive)
        if self.pattern_type == 'remove':
            self.ent_replace.configure(state="disabled")

    def check_pattern(self) -> bool:
        """Sprawdza poprawność składniową regex."""
        pattern = self.ent_pattern.get()
        if not pattern:
            messagebox.showerror(
                "Błąd", "Wzorzec nie może być pusty.", parent=self)
            return False
        try:
            re.compile(pattern)
            self.lbl_test_result.configure(
                text="Wzorzec jest poprawny.", text_color="green")
            return True
        except re.error as e:
            messagebox.showerror(
                "Błąd Regex", f"Niepoprawny wzorzec:\n{e}", parent=self)
            self.lbl_test_result.configure(
                text=f"Błąd: {e}", text_color="red")
            return False
        except Exception as e:
            messagebox.showerror("Błąd", f"Wystąpił błąd: {e}", parent=self)
            return False

    def test_pattern(self):
        """Testuje wzorzec na tekście testowym."""
        if not self.check_pattern():
            return

        pattern_str = self.ent_pattern.get()
        replace_str = self.ent_replace.get()
        test_str = self.ent_test_text.get()
        flags = re.IGNORECASE if not self.var_case_sensitive.get() else 0

        try:
            pattern = re.compile(pattern_str, flags)
            result = pattern.sub(replace_str, test_str)
            self.lbl_test_result.configure(
                text=f'"{result}"', text_color="cyan")
        except Exception as e:
            self.lbl_test_result.configure(
                text=f"Błąd testowania: {e}", text_color="red")

    def add_pattern(self):
        """Waliduje i przekazuje wzorzec do aplikacji głównej."""
        if not self.check_pattern():
            return

        pattern_str = self.ent_pattern.get()
        replace_str = self.ent_replace.get(
        ) if self.pattern_type == 'replace' else ""
        case_sensitive = self.var_case_sensitive.get()

        new_pattern = PatternItem(pattern_str, replace_str, case_sensitive)

        # Wywołaj callback w głównym oknie
        self.callback(new_pattern, self.existing_pattern, self.pattern_type)
        self.destroy()
