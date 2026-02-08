import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import shutil
import json
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple
from app.utils import ready_dir_from_audio_dir
from app.entity import Line
from app.io import get_audio_candidates, get_primary_audio_path

if TYPE_CHECKING:
    from studio import SubtitleStudioApp


LineList = List[Line]


class GameReaderExportWindow(ctk.CTkToplevel):
    def __init__(self, app: 'SubtitleStudioApp'):
        super().__init__(app)
        self.app = app
        self.title("Eksport - Game Reader")
        self.geometry("500x550")
        self.resizable(False, False)

        # Ustawienie okna jako modalne
        self.transient(app)
        self.wait_visibility()
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)

        # --- SEKCJA 1: Status Plików ---
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.status_frame, text="Status plików audio", font=("", 14, "bold")).pack(pady=5)

        # Status Generowania
        self.gen_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.gen_frame.pack(fill="x", padx=5, pady=2)

        self.lbl_gen_status = ctk.CTkLabel(self.gen_frame, text="Generowanie (WAV/MP3): Sprawdzanie...", width=250,
                                           anchor="w")
        self.lbl_gen_status.pack(side="left", padx=5)

        self.btn_generate = ctk.CTkButton(self.gen_frame, text="Generuj teraz", width=100,
                                          command=self._run_generation, state="disabled", fg_color="orange")
        self.btn_generate.pack(side="right", padx=5)

        # Status Konwersji
        self.conv_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.conv_frame.pack(fill="x", padx=5, pady=2)

        self.lbl_conv_status = ctk.CTkLabel(self.conv_frame, text="Konwersja (OGG/MP3): Sprawdzanie...", width=250,
                                            anchor="w")
        self.lbl_conv_status.pack(side="left", padx=5)

        self.btn_convert = ctk.CTkButton(self.conv_frame, text="Konwertuj teraz", width=100,
                                         command=self._run_conversion, state="disabled", fg_color="orange")
        self.btn_convert.pack(side="right", padx=5)

        # --- SEKCJA 2: Konfiguracja Eksportu ---
        self.config_frame = ctk.CTkFrame(self)
        self.config_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.config_frame, text="Konfiguracja eksportu", font=("", 14, "bold")).pack(pady=5)

        # Wybór katalogu
        ctk.CTkLabel(self.config_frame, text="Folder docelowy:").pack(anchor="w", padx=10)
        self.dir_frame = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        self.dir_frame.pack(fill="x", padx=5, pady=(0, 10))

        self.ent_dest_dir = ctk.CTkEntry(self.dir_frame)
        self.ent_dest_dir.pack(side="left", fill="x", expand=True, padx=(5, 5))

        ctk.CTkButton(self.dir_frame, text="Wybierz", width=80, command=self._choose_directory).pack(side="right",
                                                                                                     padx=5)

        # Checkbox kopiowania
        self.var_copy_audio = tk.BooleanVar(value=True)
        self.cb_copy_audio = ctk.CTkCheckBox(self.config_frame, text="Kopiuj pliki audio (do podkatalogu 'audio')",
                                             variable=self.var_copy_audio)
        self.cb_copy_audio.pack(anchor="w", padx=15, pady=10)

        # --- SEKCJA 3: Postęp i Akcja ---
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.lbl_progress_info = ctk.CTkLabel(self.action_frame, text="Gotowy do eksportu", text_color="gray")
        self.lbl_progress_info.pack(pady=(5, 5))

        self.progress_bar = ctk.CTkProgressBar(self.action_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=20, pady=5)

        self.btn_export = ctk.CTkButton(self.action_frame, text="GENERUJ PRESET", height=40,
                                        font=("", 14, "bold"), fg_color="green", hover_color="darkgreen",
                                        command=self._start_export)
        self.btn_export.pack(fill="x", padx=20, pady=20)

        # Inicjalizacja stanu
        self._check_files_status()

    def _get_target_file_info(self, uid: str, ready_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
        """Zwraca ścieżkę do przekonwertowanego pliku po uid (preferuje OGG, potem MP3) i jego rozszerzenie."""
        candidates = get_audio_candidates(uid)
        # Filtrujemy tylko te z ready_dir i z odpowiednimi rozszerzeniami
        # get_audio_candidates zwraca (Path, is_ready)
        
        # Preferencja: ogg w ready, potem mp3 w ready
        for ext in ['.ogg', '.mp3']:
            for p, is_ready in candidates:
                if is_ready and p.suffix.lower() == ext:
                    return p, ext
                    
        return None, None

    def _check_files_status(self):
        """Sprawdza stan plików i aktualizuje etykiety oraz przyciski."""
        if not self.app.audio_dir or not self.app.audio_dir.exists():
            self.lbl_gen_status.configure(text="Błąd: Brak folderu audio", text_color="red")
            self.lbl_conv_status.configure(text="---")
            return

        lines: LineList = self.app.lines
        expected_count = len(lines)

        # 1. Sprawdź generowanie (WAV/MP3)
        generated_count = 0
        for i, line in enumerate(lines):
            uid = line.uid
            # Sprawdź czy istnieje jakikolwiek kandydat w folderze generated
            if any(not is_ready for p, is_ready in get_audio_candidates(uid)):
                generated_count += 1

        is_gen_ok = generated_count >= expected_count and expected_count > 0
        gen_color = "green" if is_gen_ok else "orange" if generated_count > 0 else "red"
        gen_text = f"Wygenerowano: {generated_count} / {expected_count}"

        self.lbl_gen_status.configure(text=gen_text, text_color=gen_color)
        self.btn_generate.configure(state="disabled" if is_gen_ok else "normal")

        # 2. Sprawdź konwersję (OGG/MP3 w ready)
        ready_dir = ready_dir_from_audio_dir(self.app.audio_dir)
        converted_count = 0
        if ready_dir.exists():
            for i, line in enumerate(lines):
                uid = line.uid
                # Sprawdź czy istnieje jakikolwiek kandydat w folderze ready
                if any(is_ready for p, is_ready in get_audio_candidates(uid)):
                    converted_count += 1

        is_conv_ok = converted_count >= expected_count and expected_count > 0
        conv_color = "green" if is_conv_ok else "orange" if converted_count > 0 else "red"
        conv_text = f"Skonwertowano: {converted_count} / {expected_count}"

        self.lbl_conv_status.configure(text=conv_text, text_color=conv_color)
        self.btn_convert.configure(state="disabled" if is_conv_ok else "normal")

    def _run_generation(self):
        from app.generation import enqueue_generate_all
        enqueue_generate_all(self.app)
        messagebox.showinfo("Info", "Uruchomiono proces generowania. Dokończ go, a następnie wróć tutaj.", parent=self)

    def _run_conversion(self):
        from app.generation import enqueue_convert_all
        enqueue_convert_all(self.app)
        messagebox.showinfo("Info", "Uruchomiono proces konwersji. Dokończ go, a następnie wróć tutaj.", parent=self)

    def _choose_directory(self):
        d = filedialog.askdirectory(title="Wybierz folder docelowy dla presetu")
        if d:
            self.ent_dest_dir.delete(0, tk.END)
            self.ent_dest_dir.insert(0, d)

    def _start_export(self):
        dest_dir_str = self.ent_dest_dir.get().strip()
        if not dest_dir_str:
            messagebox.showwarning("Błąd", "Wybierz folder docelowy.", parent=self)
            return

        dest_dir = Path(dest_dir_str)
        if not dest_dir.exists():
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie można utworzyć katalogu:\n{e}", parent=self)
                return

        copy_files = self.var_copy_audio.get()

        # Zablokuj UI
        self.btn_export.configure(state="disabled", text="PRZETWARZANIE...")
        self.progress_bar.set(0)
        self.lbl_progress_info.configure(text="Przygotowywanie...", text_color="blue")

        # Uruchom w wątku
        threading.Thread(target=self._export_task, args=(dest_dir, copy_files), daemon=True).start()

    def _export_task(self, dest_dir: Path, copy_files: bool):
        try:
            lines: LineList = self.app.lines
            # 1. Zapisz napisy (processed_clean) do subtitlesPL.txt
            clean_lines = [line.get_text() for line in lines]
            subtitles_file = dest_dir / "subtitles.txt"

            with open(subtitles_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(clean_lines))

            self._update_status_safe("Zapisano subtitles.txt", "blue")

            # 2. Kopiowanie plików audio do podkatalogu 'audio'
            ready_dir = ready_dir_from_audio_dir(self.app.audio_dir)
            target_audio_dir = dest_dir / "audio"

            if copy_files:
                if not ready_dir.exists():
                    raise FileNotFoundError("Brak folderu 'ready'. Wykonaj konwersję.")

                # Utwórz podkatalog audio
                target_audio_dir.mkdir(parents=True, exist_ok=True)

                # Lista plików do skopiowania
                files_to_copy = []
                # Szukamy plikow po uid, zapisujemy jako output1 (i).ext
                for i, line in enumerate(lines):
                    uid = line.uid
                    src_file, ext = self._get_target_file_info(uid, ready_dir)
                    if src_file and ext:
                        dst_name = f"output1 ({i + 1}){ext}"
                        files_to_copy.append((src_file, dst_name))

                total_files = len(files_to_copy)

                if total_files == 0:
                    self._update_status_safe("Ostrzeżenie: Brak plików audio do skopiowania!", "orange")
                else:
                    self._update_status_safe(f"Kopiowanie {total_files} plików do katalogu 'audio'...", "blue")

                    update_step = max(10, int(total_files / 100))

                    copied_count = 0
                    for src, dst_name in files_to_copy:
                        dst = target_audio_dir / dst_name
                        shutil.copy2(src, dst)
                        copied_count += 1

                        if copied_count % update_step == 0 or copied_count == total_files:
                            progress = copied_count / total_files
                            percent = int(progress * 100)

                            self.app.queue.put(lambda p=progress: self.progress_bar.set(p))
                            self.app.queue.put(
                                lambda txt=f"Kopiowanie audio: {percent}%": self.lbl_progress_info.configure(text=txt))

            # 3. Generowanie pliku preset.json
            self._update_status_safe("Generowanie preset.json...", "blue")

            # Wzorzec JSON
            preset_data = {
                "monitor": {
                    "top": 900,
                    "left": 375,
                    "width": 1170,
                    "height": 120
                },
                "resolution": "1920x1080",
                "selected_screen_monitor": 1,
                "CENTER_LINE_MARGIN": 100,
                "CENTER_LINE_2_START": 1,
                "CENTER_LINE_3_START_RATIO": 0.3,
                "RESOLUTION_DOWNSCALE": 0.45,
                "CAPTURE_INTERVAL": 0.5,
                "MIN_HEIGHT": 10,
                "MAX_HEIGHT": 100,
                "ENABLE_REMOVE_CHARACTER_NAME": False,
                "ENABLE_SCREENSHOTS": False,
                "ENABLE_OUTPUT2_SYSTEM": False,
                "ENABLE_DYNAMIC_SPEED": True,
                "BASE_PLAYBACK_SPEED": 1.2,
                "OVERLAP_PLAYBACK_SPEED": 1.35,
                "USE_CENTER_LINE_1": False,
                "USE_CENTER_LINE_2": False,
                "USE_CENTER_LINE_3": False,
                "audio_dir": "audio",
                "text_file_path": "subtitlesPL.txt",
                "screenshot_dir": "",
                "key_bindings": {
                    "toggle_on": "home",
                    "toggle_off": "end",
                    "volume_up": "page_up",
                    "volume_down": "page_down",
                    "switch_monitor_toggle": "alt+1",
                    "test_sound": "insert",
                    "open_settings": "alt+`",
                    "interrupt_audio": "delete",
                    "base_speed_up": "shift+z",
                    "base_speed_down": "shift+x",
                    "overlap_speed_up": "shift+c",
                    "overlap_speed_down": "shift+v",
                    "debug_console": "alt+d",
                    "toggle_areas": "alt+2"
                },
                "monitor2_enabled": False,
                "monitor2_top": 100,
                "monitor2_left": 375,
                "monitor2_width": 1170,
                "monitor2_height": 120,
                "VOLUME_REDUCTION_LEVEL": 0.2,
                "AUDIO_QUEUE_SIZE": 1
            }

            preset_file = dest_dir / "preset.json"
            with open(preset_file, 'w', encoding='utf-8') as f:
                json.dump(preset_data, f, indent=4)

            self._update_status_safe("Eksport zakończony sukcesem!", "green")
            self.app.queue.put(lambda: messagebox.showinfo("Sukces", f"Preset i pliki zapisano w:\n{dest_dir}"))

        except Exception as e:
            self._update_status_safe(f"Błąd: {e}", "red")
            print(f"Export error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.app.queue.put(lambda: self.btn_export.configure(state="normal", text="GENERUJ PRESET"))

    def _update_status_safe(self, text, color):
        self.app.queue.put(lambda: self.lbl_progress_info.configure(text=text, text_color=color))
