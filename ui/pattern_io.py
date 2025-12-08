import customtkinter as ctk
import csv
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING
from app.entity import PatternItem

if TYPE_CHECKING:
    from studio import SubtitleStudioApp


class PatternIOWindow(ctk.CTkToplevel):
    def __init__(self, app: 'SubtitleStudioApp'):
        super().__init__(app)
        self.app = app
        self.title("Import / Eksport Wzorców")
        self.geometry("500x350")
        self.resizable(False, False)

        # Okno modalne
        self.transient(app)
        self.grab_set()

        # Zakładki dla Importu i Eksportu
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_import = self.tabview.add("Import")
        self.tab_export = self.tabview.add("Eksport")

        self._setup_import_tab()
        self._setup_export_tab()

    def _setup_import_tab(self):
        # 1. Wybór pliku
        ctk.CTkLabel(self.tab_import, text="1. Wybierz plik CSV:", font=("", 13, "bold")).pack(anchor="w", padx=10,
                                                                                               pady=(10, 5))

        file_frame = ctk.CTkFrame(self.tab_import, fg_color="transparent")
        file_frame.pack(fill="x", padx=5, pady=0)

        self.ent_import_path = ctk.CTkEntry(file_frame, placeholder_text="Ścieżka do pliku...")
        self.ent_import_path.pack(side="left", fill="x", expand=True, padx=(5, 5))

        ctk.CTkButton(file_frame, text="Wybierz", width=80, command=self._browse_file).pack(side="right", padx=5)

        # 2. Wybór typu
        ctk.CTkLabel(self.tab_import, text="2. Rodzaj wzorców (cel):", font=("", 13, "bold")).pack(anchor="w", padx=10,
                                                                                                   pady=(20, 5))
        self.seg_import_type = ctk.CTkSegmentedButton(self.tab_import,
                                                      values=["Napisy (Czyszczenie)", "TTS (Podmiana)"])
        self.seg_import_type.set("TTS (Podmiana)")
        self.seg_import_type.pack(fill="x", padx=10)

        # 3. Akcja
        self.btn_import = ctk.CTkButton(self.tab_import, text="IMPORTUJ", height=40, fg_color="green",
                                        hover_color="darkgreen",
                                        command=self._perform_import)
        self.btn_import.pack(side="bottom", fill="x", padx=20, pady=20)

    def _setup_export_tab(self):
        # 1. Wybór typu
        ctk.CTkLabel(self.tab_export, text="1. Rodzaj wzorców do eksportu:", font=("", 13, "bold")).pack(anchor="w",
                                                                                                         padx=10,
                                                                                                         pady=(10, 5))
        self.seg_export_type = ctk.CTkSegmentedButton(self.tab_export,
                                                      values=["Napisy (Czyszczenie)", "TTS (Podmiana)"])
        self.seg_export_type.set("TTS (Podmiana)")
        self.seg_export_type.pack(fill="x", padx=10)

        # 2. Info
        ctk.CTkLabel(self.tab_export,
                     text="Eksport utworzy plik CSV zawierający:\n- Wzorzec\n- Zamiennik\n- Ustawienie wielkości znaków",
                     justify="left", text_color="gray").pack(pady=20, padx=10)

        # 3. Akcja
        self.btn_export = ctk.CTkButton(self.tab_export, text="EKSPORTUJ...", height=40,
                                        command=self._perform_export)
        self.btn_export.pack(side="bottom", fill="x", padx=20, pady=20)

    def _browse_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("Text", "*.txt")])
        if file_path:
            self.ent_import_path.delete(0, "end")
            self.ent_import_path.insert(0, file_path)

    def _perform_import(self):
        path = self.ent_import_path.get().strip()
        if not path:
            messagebox.showwarning("Błąd", "Wybierz plik do importu.", parent=self)
            return

        target_type = self.seg_import_type.get()
        target_list = self.app.custom_remove if target_type == "Napisy (Czyszczenie)" else self.app.custom_replace

        try:
            count = 0
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 1:
                        # Format: Pattern, Replace (opt), CaseSensitive (0/1, opt)
                        pat = row[0].strip()
                        if not pat: continue

                        repl = row[1].strip() if len(row) > 1 else ""

                        # Domyślnie case_sensitive = True, chyba że w pliku jest 0
                        cs = True
                        if len(row) > 2:
                            try:
                                cs = bool(int(row[2].strip()))
                            except ValueError:
                                pass

                        # Dodaj do listy (unikanie duplikatów można dodać opcjonalnie, tu dodajemy wszystko)
                        new_item = PatternItem(pat, repl, cs)
                        if new_item not in target_list:
                            target_list.append(new_item)
                            count += 1

            self.app.mark_as_unsaved()
            self.app._refresh_custom_lists()
            messagebox.showinfo("Sukces", f"Zaimportowano {count} wzorców.", parent=self)
            self.destroy()

        except Exception as e:
            messagebox.showerror("Błąd importu", str(e), parent=self)

    def _perform_export(self):
        source_type = self.seg_export_type.get()
        source_list = self.app.custom_remove if source_type == "Napisy (Czyszczenie)" else self.app.custom_replace

        if not source_list:
            messagebox.showinfo("Info", "Wybrana lista wzorców jest pusta.", parent=self)
            return

        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                for p in source_list:
                    # Zapis: Wzorzec, Zamiennik, CaseSensitive (1/0)
                    writer.writerow([p.pattern, p.replace, int(p.case_sensitive)])

            messagebox.showinfo("Sukces", f"Wyeksportowano {len(source_list)} wzorców do:\n{path}", parent=self)
            self.destroy()

        except Exception as e:
            messagebox.showerror("Błąd eksportu", str(e), parent=self)