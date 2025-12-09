import customtkinter as ctk
import tkinter as tk
from typing import Callable, Optional
import re

from app.entity import PatternItem


class PatternEditorWindow(ctk.CTkToplevel):
    """
    Modalne okno do dodawania lub edycji pojedynczego wzorca (PatternItem).
    """

    def __init__(self, master, pattern_type: str, callback: Callable[[PatternItem, Optional[PatternItem], str], None],
                 existing_pattern: Optional[PatternItem] = None):
        """
        Args:
            master: Rodzic (np. SubtitleStudioApp).
            pattern_type: 'remove' lub 'replace' (decyduje o widoczności pola Replace).
            callback: Funkcja wywoływana po zatwierdzeniu (new_item, old_item, type).
            existing_pattern: Obiekt PatternItem przy edycji, None przy dodawaniu.
        """
        super().__init__(master)
        self.callback = callback
        self.pattern_type = pattern_type
        self.existing_pattern = existing_pattern

        title_prefix = "Edytuj" if existing_pattern else "Dodaj"
        type_label = "wycinający" if pattern_type == 'remove' else "podmieniający"
        self.title(f"{title_prefix} wzorzec {type_label}")
        self.geometry("500x450")

        self.transient(master)
        self.grab_set()

        self._create_widgets()
        self._populate_fields()

    def _create_widgets(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # -- Nazwa (Opcjonalna) --
        ctk.CTkLabel(main_frame, text="Nazwa (opcjonalna opisowa):").pack(anchor="w", pady=(5, 0))
        self.ent_name = ctk.CTkEntry(main_frame, placeholder_text="np. Usuń komentarze w nawiasach")
        self.ent_name.pack(fill="x", pady=(0, 10))

        # -- Wzorzec Regex --
        ctk.CTkLabel(main_frame, text="Wzorzec (Regex):").pack(anchor="w")
        self.ent_pattern = ctk.CTkEntry(main_frame, placeholder_text="np. \\[.*?\\]")
        self.ent_pattern.pack(fill="x", pady=(0, 10))

        # -- Zamiennik (tylko dla replace) --
        self.lbl_replace = ctk.CTkLabel(main_frame, text="Zamień na:")
        self.ent_replace = ctk.CTkEntry(main_frame, placeholder_text="Zostaw puste aby usunąć")

        if self.pattern_type == 'replace':
            self.lbl_replace.pack(anchor="w")
            self.ent_replace.pack(fill="x", pady=(0, 10))

        # -- Opcje --
        self.var_case_sensitive = tk.BooleanVar(value=True)
        cb_case = ctk.CTkCheckBox(main_frame, text="Uwzględnij wielkość znaków (Case Sensitive)",
                                  variable=self.var_case_sensitive)
        cb_case.pack(anchor="w", pady=10)

        # -- Przyciski --
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=20)

        ctk.CTkButton(btn_frame, text="Anuluj", fg_color="gray", command=self.destroy).pack(side="left", expand=True,
                                                                                            padx=5)
        ctk.CTkButton(btn_frame, text="Zapisz", command=self.save).pack(side="right", expand=True, padx=5)

    def _populate_fields(self):
        if self.existing_pattern:
            # Nazwa
            if self.existing_pattern.name:
                self.ent_name.insert(0, self.existing_pattern.name)

            # Wzorzec
            self.ent_pattern.insert(0, self.existing_pattern.pattern)

            # Zamiennik
            if self.pattern_type == 'replace':
                self.ent_replace.insert(0, self.existing_pattern.replace)

            # Case sensitive
            self.var_case_sensitive.set(self.existing_pattern.case_sensitive)

    def save(self):
        name = self.ent_name.get().strip()
        pattern = self.ent_pattern.get()

        # Jeśli type='remove', replace jest zawsze pustym stringiem
        replace = ""
        if self.pattern_type == 'replace':
            replace = self.ent_replace.get()

        case_sensitive = self.var_case_sensitive.get()

        if not pattern:
            return  # Walidacja: wzorzec nie może być pusty

        # Walidacja poprawności regex
        try:
            re.compile(pattern)
        except re.error as e:
            tk.messagebox.showerror("Błąd Regex", f"Niepoprawne wyrażenie regularne:\n{e}", parent=self)
            return

        # Pusta nazwa to None
        final_name = name if name else None

        new_item = PatternItem(
            pattern=pattern,
            replace=replace,
            case_sensitive=case_sensitive,
            name=final_name,
            enabled=True if not self.existing_pattern else self.existing_pattern.enabled
        )

        self.callback(new_item, self.existing_pattern, self.pattern_type)
        self.destroy()