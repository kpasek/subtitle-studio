from tkinter import messagebox
import customtkinter as ctk
from pathlib import Path
from typing import List
import tkinter as tk
import re
import os

from app.entity import PatternItem
from app.tooltip import CreateToolTip
from app.utils import compile_pattern


class AudioDeleterWindow(ctk.CTkToplevel):
    """
    A modal window for batch-deleting audio files based on regex patterns
    matched against dialog lines.
    """

    def __init__(self, master, dialogs: List[str], audio_path: str):
        """
        Initializes the AudioDeleterWindow.

        Args:
            master: The parent window (SubtitleStudioApp).
            dialogs: The list of processed dialog strings.
            audio_path: The path to the main audio directory.
        """
        super().__init__(master)
        self.dialogs = dialogs
        self.audio_dir = Path(audio_path)
        self.custom_remove: List[PatternItem] = []
        self.files_to_delete: List[Path] = []

        self.title("Masowe usuwanie plików audio")
        self.geometry("800x600")

        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showerror(
                "Błąd",
                "Katalog audio nie jest ustawiony lub nie istnieje.\nUstaw go w przeglądarce dialogów.",
                parent=self
            )
            self.after(100, self.destroy)
            return

        self._create_widgets()
        self.recalculate_stats()

    def _create_widgets(self):
        """Creates and places all UI widgets for this window."""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(main_frame, text="Wzorce REGEX do dopasowania linii dialogowych").grid(row=0, column=0, sticky="w",
                                                                                            padx=6)

        self.custom_remove_frame = ctk.CTkScrollableFrame(main_frame)
        self.custom_remove_frame.grid(
            row=1, column=0, sticky="nsew", padx=6, pady=(2, 6))

        clean_inline_frame = ctk.CTkFrame(main_frame)
        clean_inline_frame.grid(row=2, column=0, sticky="ew", pady=(4, 4))

        self.ent_remove_pattern = ctk.CTkEntry(
            clean_inline_frame, placeholder_text="regexp")
        self.ent_remove_pattern.pack(
            side="left", fill="x", expand=True, padx=(4, 2))

        self.var_remove_case_sensitive = tk.BooleanVar(value=True)
        checkbox = ctk.CTkCheckBox(
            clean_inline_frame, text="Aa", variable=self.var_remove_case_sensitive)
        checkbox.pack(side="left", padx=(2, 4))
        CreateToolTip(checkbox, 'Uwzględnij wielkość znaków')

        ctk.CTkButton(clean_inline_frame, text="Dodaj",
                      command=self.add_inline_remove).pack(side="left", padx=2)

        stats_frame = ctk.CTkFrame(main_frame)
        stats_frame.grid(row=3, column=0, sticky="ew", pady=10)
        stats_frame.grid_columnconfigure(1, weight=1)

        self.lbl_lines = ctk.CTkLabel(stats_frame, text="Pasujące linie: 0")
        self.lbl_lines.grid(row=0, column=0, columnspan=2, sticky="w", padx=10)

        self.lbl_files = ctk.CTkLabel(
            stats_frame, text="Pliki do usunięcia: 0")
        self.lbl_files.grid(row=1, column=0, columnspan=2, sticky="w", padx=10)

        ctk.CTkButton(stats_frame, text="Przelicz", command=self.recalculate_stats).grid(row=2, column=0, padx=10,
                                                                                         pady=10)
        ctk.CTkButton(stats_frame, text="❌ Usuń pliki", command=self.execute_deletion, fg_color="red",
                      hover_color="darkred").grid(row=2, column=1, sticky="e", padx=10, pady=10)

    def add_inline_remove(self):
        """Adds a new regex pattern from the input field to the list."""
        pattern = self.ent_remove_pattern.get()
        case_sensitive = self.var_remove_case_sensitive.get()
        if not pattern:
            return

        new_pattern = PatternItem(pattern, "", not case_sensitive)
        self.custom_remove.append(new_pattern)
        self.add_row(self.custom_remove_frame, new_pattern, self.custom_remove)

        self.ent_remove_pattern.delete(0, "end")
        self.recalculate_stats()

    def add_row(self, frame, pattern_item: PatternItem, target_list: List[PatternItem]):
        """
        Adds a UI row for a pattern to the scrollable frame.

        Args:
            frame: The parent CTkScrollableFrame.
            pattern_item: The PatternItem data object.
            target_list: The list (self.custom_remove) to remove the item from.
        """
        row = ctk.CTkFrame(frame)
        row.pack(fill="x", pady=2, padx=2)

        lbl = ctk.CTkLabel(row,
                           text=f"[{pattern_item.pattern}] {'' if not pattern_item.case_sensitive else '(Aa)'}")
        lbl.pack(side="left", fill="x", expand=False, padx=4)

        def on_delete():
            try:
                target_list.remove(pattern_item)
            except ValueError:
                pass
            row.destroy()
            self.recalculate_stats()

        btnX = ctk.CTkButton(row, text="X", width=60, command=on_delete)
        btnX.pack(side="right", padx=4)

    def _find_audio_files(self, identifier: str) -> List[tuple[Path, bool]]:
        """
        Finds all audio files associated with a given dialog identifier.

        Args:
            identifier: The dialog line number (e.g., "123").

        Returns:
            A list of tuples, each containing a Path object and a boolean (True if in /ready/).
        """
        candidates = [
            (self.audio_dir / f"output1 ({identifier}).wav", False),
            (self.audio_dir / f"output1 ({identifier}).ogg", False),
            # Dodano mp3 na wszelki wypadek
            (self.audio_dir / f"output1 ({identifier}).mp3", False),
            (self.audio_dir / "ready" / f"output1 ({identifier}).ogg", True),
            (self.audio_dir / "ready" / f"output2 ({identifier}).ogg", True)
        ]
        return [(f, ready) for f, ready in candidates if f.exists()]

    def recalculate_stats(self):
        """
        Recalculates which files will be deleted based on the current regex patterns.
        Updates the UI labels with the count of matched lines and files.
        """
        if not self.custom_remove:
            self.lbl_lines.configure(text="Pasujące linie: 0")
            self.lbl_files.configure(text="Pliki do usunięcia: 0")
            self.files_to_delete = []
            return

        try:
            compiled_patterns = [compile_pattern(
                p) for p in self.custom_remove]
        except re.error as e:
            messagebox.showerror(
                "Błąd regex", f"Błąd w wyrażeniu regularnym:\n{e}", parent=self)
            return

        matched_lines_count = 0
        files_set = set()

        for i, line in enumerate(self.dialogs):
            identifier = str(i + 1)
            is_match = False
            for pat in compiled_patterns:
                if pat.search(line):  # Any match in the line
                    is_match = True
                    break

            if is_match:
                matched_lines_count += 1
                found_files = self._find_audio_files(identifier)
                for f, _ in found_files:
                    files_set.add(f)

        self.files_to_delete = list(files_set)
        self.lbl_lines.configure(text=f"Pasujące linie: {matched_lines_count}")
        self.lbl_files.configure(
            text=f"Pliki do usunięcia: {len(self.files_to_delete)}")

    def execute_deletion(self):
        """
        Performs the actual file deletion after a final confirmation prompt.
        """
        self.recalculate_stats()  # Ensure the list is up-to-date

        if not self.files_to_delete:
            messagebox.showinfo(
                "Brak plików", "Brak plików do usunięcia.", parent=self)
            return

        file_count = len(self.files_to_delete)
        if not messagebox.askyesno("Potwierdź usunięcie",
                                   f"Czy na pewno chcesz trwale usunąć {file_count} plików audio?\n\nTa operacja jest nieodwracalna.",
                                   parent=self):
            return

        deleted_count = 0
        errors = []
        for f in self.files_to_delete:
            try:
                os.remove(f)
                deleted_count += 1
            except Exception as e:
                errors.append(str(e))

        if errors:
            messagebox.showerror("Błąd usuwania",
                                 f"Usunięto {deleted_count} z {file_count} plików.\n\nWystąpiły błędy:\n{'; '.join(errors[:5])}",
                                 parent=self)
        else:
            messagebox.showinfo(
                "Gotowe", f"Pomyślnie usunięto {deleted_count} plików.", parent=self)

        self.recalculate_stats()  # Refresh stats (should be 0)
