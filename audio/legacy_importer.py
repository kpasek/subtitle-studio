import os
import shutil
import threading
import re
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.project import ProjectManager


class LegacyImporterWindow(ctk.CTkToplevel):
    def __init__(self, master, project_manager: 'ProjectManager'):
        super().__init__(master)
        self.project = project_manager
        self.title("Import Audio (Legacy)")
        self.geometry("600x450")
        self.transient(master)
        self.grab_set()

        # Zmienne stanu
        self.source_dir = None
        self.is_running = False
        self.stop_event = threading.Event()
        self.imported_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.total_files = 0

        self._create_layout()

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)

        # 1. Wybór folderu
        frame_src = ctk.CTkFrame(self)
        frame_src.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(frame_src, text="Katalog źródłowy z plikami 'output1 (N).wav':").pack(anchor="w", padx=5)

        self.lbl_path = ctk.CTkLabel(frame_src, text="Nie wybrano katalogu", text_color="gray", anchor="w")
        self.lbl_path.pack(fill="x", padx=5, pady=2)

        ctk.CTkButton(frame_src, text="Wybierz folder...", command=self.select_folder).pack(anchor="e", padx=5, pady=5)

        # 2. Opcje
        frame_opts = ctk.CTkFrame(self)
        frame_opts.pack(fill="x", padx=10, pady=5)

        self.var_overwrite = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame_opts, text="Nadpisz istniejące pliki w projekcie", variable=self.var_overwrite).pack(
            anchor="w", padx=10, pady=10)

        ctk.CTkLabel(frame_opts,
                     text="Domyślnie import pomija pliki, które już są w folderze audio projektu.\nPozwala to na przerwanie i wznowienie importu.",
                     font=("", 10), text_color="gray").pack(anchor="w", padx=35, pady=(0, 10))

        # 3. Postęp
        self.frame_progress = ctk.CTkFrame(self)
        self.frame_progress.pack(fill="both", expand=True, padx=10, pady=10)

        self.lbl_status = ctk.CTkLabel(self.frame_progress, text="Oczekiwanie...", anchor="w")
        self.lbl_status.pack(fill="x", padx=10, pady=(10, 5))

        self.progress_bar = ctk.CTkProgressBar(self.frame_progress)
        self.progress_bar.pack(fill="x", padx=10, pady=5)
        self.progress_bar.set(0)

        self.lbl_stats = ctk.CTkLabel(self.frame_progress, text="Zaimportowano: 0 | Pominięto: 0 | Błędy: 0")
        self.lbl_stats.pack(pady=5)

        # 4. Przyciski akcji
        frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        frame_btns.pack(fill="x", padx=10, pady=10)

        self.btn_cancel = ctk.CTkButton(frame_btns, text="Zamknij", command=self.on_close, fg_color="gray")
        self.btn_cancel.pack(side="left", padx=5)

        self.btn_start = ctk.CTkButton(frame_btns, text="Rozpocznij Import", command=self.start_import,
                                       state="disabled")
        self.btn_start.pack(side="right", padx=5)

    def select_folder(self):
        d = filedialog.askdirectory(title="Wybierz folder audio")
        if d:
            self.source_dir = Path(d)
            self.lbl_path.configure(text=str(self.source_dir), text_color=("black", "white"))
            self.btn_start.configure(state="normal")

    def start_import(self):
        if not self.source_dir: return

        self.is_running = True
        self.stop_event.clear()

        # UI update
        self.btn_start.configure(text="Zatrzymaj", fg_color="red", hover_color="darkred", command=self.stop_import)
        self.btn_cancel.configure(state="disabled")
        self.var_overwrite.set(
            self.var_overwrite.get())  # lock UI logic normally requires disabling widgets, keeping simple

        # Start Thread
        threading.Thread(target=self._import_thread, daemon=True).start()

    def stop_import(self):
        if self.is_running:
            self.lbl_status.configure(text="Zatrzymywanie...")
            self.stop_event.set()

    def _import_thread(self):
        try:
            self.update_ui_safe(status="Skanowanie plików źródłowych...", progress=0)

            # 1. Mapowanie linii: index (1-based) -> UUID
            # lines[0] -> ID linii 1, lines[1] -> ID linii 2...
            # Legacy audio: output1 (1).wav odpowiada lines[0]
            index_map = {i + 1: line.id for i, line in enumerate(self.project.subtitle_lines)}

            if not index_map:
                self.update_ui_safe(status="Błąd: Projekt nie zawiera linii dialogowych.")
                self.finish_thread()
                return

            # 2. Skanowanie folderu
            # Szukamy output1 (N).wav / mp3 / ogg
            pattern = re.compile(r"^output1\s*\((\d+)\)\.(wav|mp3|ogg)$", re.IGNORECASE)

            tasks = []  # Lista krotek: (source_path, dest_path)

            try:
                # Scandir jest szybki
                with os.scandir(self.source_dir) as it:
                    for entry in it:
                        if self.stop_event.is_set(): break
                        if entry.is_file():
                            match = pattern.match(entry.name)
                            if match:
                                num = int(match.group(1))
                                ext = match.group(2).lower()

                                # Sprawdź czy mamy taką linię w projekcie
                                if num in index_map:
                                    uuid = index_map[num]
                                    dest_name = f"output1 ({uuid}).{ext}"
                                    dest_path = self.project.audio_dir / dest_name
                                    tasks.append((Path(entry.path), dest_path))
            except Exception as e:
                self.update_ui_safe(status=f"Błąd skanowania: {e}")
                self.finish_thread()
                return

            self.total_files = len(tasks)
            self.update_ui_safe(status=f"Znaleziono {self.total_files} pasujących plików. Rozpoczynam kopiowanie...")

            overwrite = self.var_overwrite.get()

            # 3. Kopiowanie
            for i, (src, dst) in enumerate(tasks):
                if self.stop_event.is_set():
                    break

                try:
                    if dst.exists() and not overwrite:
                        self.skipped_count += 1
                    else:
                        shutil.copy2(src, dst)
                        self.imported_count += 1
                except Exception as e:
                    print(f"Błąd kopiowania {src}: {e}")
                    self.error_count += 1

                # Aktualizacja UI co 10 plików lub na koniec
                if i % 10 == 0 or i == self.total_files - 1:
                    prog = (i + 1) / self.total_files
                    self.update_ui_safe(progress=prog,
                                        stats=f"Zaimportowano: {self.imported_count} | Pominięto: {self.skipped_count} | Błędy: {self.error_count}")

            self.update_ui_safe(
                status="Zakończono." if not self.stop_event.is_set() else "Przerwano przez użytkownika.")

        except Exception as e:
            self.update_ui_safe(status=f"Wystąpił błąd krytyczny: {e}")
        finally:
            self.finish_thread()

    def finish_thread(self):
        self.is_running = False
        self.after(0, self._restore_ui)

    def _restore_ui(self):
        self.btn_start.configure(text="Rozpocznij Import", fg_color="#3a7ebf", hover_color="#325d88",
                                 command=self.start_import, state="normal")
        self.btn_cancel.configure(state="normal")
        if self.imported_count > 0:
            messagebox.showinfo("Import",
                                f"Proces zakończony.\nZaimportowano: {self.imported_count}\nPominięto: {self.skipped_count}")

    def update_ui_safe(self, status=None, progress=None, stats=None):
        self.after(0, lambda: self._update_ui_impl(status, progress, stats))

    def _update_ui_impl(self, status, progress, stats):
        if status is not None: self.lbl_status.configure(text=status)
        if progress is not None: self.progress_bar.set(progress)
        if stats is not None: self.lbl_stats.configure(text=stats)

    def on_close(self):
        if self.is_running:
            if messagebox.askyesno("Import trwa", "Importowanie w toku. Czy na pewno chcesz przerwać?"):
                self.stop_import()
                # Czekamy chwilę na wątek (opcjonalnie)
                self.destroy()
        else:
            self.destroy()