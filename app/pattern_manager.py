import customtkinter as ctk
import tkinter as tk
from typing import List,  TYPE_CHECKING

from app.entity import PatternItem

if TYPE_CHECKING:
    from gui import SubtitleStudioApp


class PatternManagerWindow(ctk.CTkToplevel):
    """
    Osobne okno (niemodalne) do zarządzania wzorcami wycinającymi i podmieniającymi.
    """

    def __init__(self, master: 'SubtitleStudioApp'):
        super().__init__(master)
        self.master_app = master
        self.title("Menedżer Wzorców")
        self.geometry("1000x700")

        # Okno nie blokuje rodzica (niemodalne)
        self.transient(master)

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._create_layout()
        self.refresh_ui()

    def _create_layout(self):
        """Tworzy szkielet interfejsu (kolumny dla Custom i Builtin)."""

        # === LEWA KOLUMNA: WŁASNE WZORCE ===
        self.left_frame = ctk.CTkFrame(self)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.left_frame.grid_columnconfigure(0, weight=1)
        self.left_frame.grid_rowconfigure(1, weight=1)  # Remove list
        self.left_frame.grid_rowconfigure(4, weight=1)  # Replace list

        # -- Sekcja Custom Remove --
        ctk.CTkLabel(self.left_frame, text="Własne wzorce wycinające", font=("", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 5))

        self.custom_remove_frame = ctk.CTkScrollableFrame(self.left_frame)
        self.custom_remove_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=2)

        rem_btn_frame = ctk.CTkFrame(self.left_frame)
        rem_btn_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        ctk.CTkButton(rem_btn_frame, text="Dodaj wzorzec",
                      command=self.master_app.open_add_remove_pattern).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(rem_btn_frame, text="Wyczyść listę",
                      command=lambda: self.master_app._clear_custom_list('remove'),
                      fg_color="gray").pack(side="right", padx=5, expand=True, fill="x")

        # -- Sekcja Custom Replace --
        ctk.CTkLabel(self.left_frame, text="Własne wzorce podmieniające", font=("", 14, "bold")).grid(
            row=3, column=0, sticky="w", padx=10, pady=(15, 5))

        self.custom_replace_frame = ctk.CTkScrollableFrame(self.left_frame)
        self.custom_replace_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=2)

        rep_btn_frame = ctk.CTkFrame(self.left_frame)
        rep_btn_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=5)
        ctk.CTkButton(rep_btn_frame, text="Dodaj wzorzec",
                      command=self.master_app.open_add_replace_pattern).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(rep_btn_frame, text="Wyczyść listę",
                      command=lambda: self.master_app._clear_custom_list('replace'),
                      fg_color="gray").pack(side="right", padx=5, expand=True, fill="x")

        # === PRAWA KOLUMNA: WBUDOWANE WZORCE ===
        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(1, weight=1)
        self.right_frame.grid_rowconfigure(3, weight=1)

        # -- Sekcja Builtin Remove --
        ctk.CTkLabel(self.right_frame, text="Wbudowane wzorce wycinające", font=("", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 5))

        self.builtin_remove_frame = ctk.CTkScrollableFrame(self.right_frame)
        self.builtin_remove_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=2)

        # -- Sekcja Builtin Replace --
        ctk.CTkLabel(self.right_frame, text="Wbudowane wzorce podmieniające", font=("", 14, "bold")).grid(
            row=2, column=0, sticky="w", padx=10, pady=(15, 5))

        self.builtin_replace_frame = ctk.CTkScrollableFrame(self.right_frame)
        self.builtin_replace_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=2)

    def refresh_ui(self):
        """Odświeża zawartość wszystkich list na podstawie danych z App."""
        if not self.winfo_exists():
            return

        # 1. Wyczyść custom lists
        for child in self.custom_remove_frame.winfo_children():
            child.destroy()
        for child in self.custom_replace_frame.winfo_children():
            child.destroy()

        # 2. Wypełnij custom lists
        for p in self.master_app.custom_remove:
            self._add_custom_row(self.custom_remove_frame, p, self.master_app.custom_remove)

        for p in self.master_app.custom_replace:
            self._add_custom_row(self.custom_replace_frame, p, self.master_app.custom_replace)

        # 3. Wyczyść i wypełnij builtin lists (one też mogą zmieniać stan enabled)
        for child in self.builtin_remove_frame.winfo_children():
            child.destroy()
        self._fill_builtin_list(self.builtin_remove_frame,
                                self.master_app.builtin_remove,
                                self.master_app.builtin_remove_state)

        for child in self.builtin_replace_frame.winfo_children():
            child.destroy()
        self._fill_builtin_list(self.builtin_replace_frame,
                                self.master_app.builtin_replace,
                                self.master_app.builtin_replace_state)

    def _add_custom_row(self, frame, pattern_item: PatternItem, target_list: List[PatternItem]):
        """Dodaje wiersz dla własnego wzorca (z opcją edycji i usuwania)."""
        row = ctk.CTkFrame(frame)
        row.pack(fill="x", pady=2, padx=2)

        def on_edit_click(event):
            # Ctrl+Click lub Double Click
            if (
                    event.type == '4' and event.state & 0x0004) or event.type == '4':  # ButtonPress + Ctrl or just check double
                pass
                # Logika otwierania edytora jest w master_app
            self.master_app.open_edit_pattern(pattern_item, target_list)

        def on_delete():
            try:
                target_list.remove(pattern_item)
            except ValueError:
                pass
            row.destroy()
            self.master_app.mark_as_unsaved()

        def on_edit():
            self.master_app.open_edit_pattern(pattern_item, target_list)

        def on_toggle():
            pattern_item.enabled = enabled_var.get()
            self.master_app.mark_as_unsaved()
            color = ctk.ThemeManager.theme["CTkLabel"]["text_color"] if pattern_item.enabled else "gray50"
            lbl.configure(text_color=color)

        enabled_var = tk.BooleanVar(value=pattern_item.enabled)
        cb = ctk.CTkCheckBox(row, text="", variable=enabled_var, command=on_toggle, width=20)
        cb.pack(side="left", padx=(4, 0))

        btnX = ctk.CTkButton(row, text="❌", width=20, command=on_delete, fg_color="transparent", text_color="red",
                             hover_color=("gray85", "gray25"))
        btnX.pack(side="left", padx=2)

        btnEdit = ctk.CTkButton(row, text="✏️", width=20, command=on_edit, fg_color="transparent",
                                text_color=("gray10", "gray90"), hover_color=("gray85", "gray25"))
        btnEdit.pack(side="left", padx=2)

        lbl_text = f"{'' if not pattern_item.case_sensitive else '(Aa)'} [{pattern_item.pattern}] -> [{pattern_item.replace}]"
        lbl = ctk.CTkLabel(row, text=lbl_text, anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=4)

        # Wiązania zdarzeń do edycji
        lbl.bind("<Double-Button-1>", lambda e: on_edit())
        row.bind("<Double-Button-1>", lambda e: on_edit())

        if not pattern_item.enabled:
            lbl.configure(text_color="gray50")

    def _fill_builtin_list(self, frame, patterns, states):
        """Wypełnia listę wbudowanych wzorców (tylko CheckBoxy)."""
        for i, p in enumerate(patterns):
            text = f"{p.pattern} -> {p.replace}" if p.name is None else p.name
            cb = ctk.CTkCheckBox(frame, text=text, variable=states[i])
            cb.pack(anchor="w", pady=2, padx=4)