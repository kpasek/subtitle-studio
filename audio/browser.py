import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import re
from pathlib import Path
import pygame
from typing import Optional, TYPE_CHECKING, Dict, Any, List

import threading
import queue

from app.utils import is_installed
from audio.progress import GenerationProgressWindow
if is_installed('torch'):
    from generators.xtts import XTTSPolishTTS
from generators.google_cloud_tts import GoogleCloudTTS
from generators.elevenlabs_tts import ElevenLabsTTS

from audio.audio_converter import AudioConverter

if TYPE_CHECKING:
    from app.gui import SubtitleStudioApp


class AudioBrowserWindow(ctk.CTkToplevel):
    """
    Modal window for browsing, playing, and generating audio files for dialog lines.
    """

    def __init__(self, master: 'SubtitleStudioApp',
                 project_config: dict,
                 save_project_config,
                 cancel_event: threading.Event,
                 global_config: dict,
                 active_model: str):

        super().__init__(master)
        self.master: 'SubtitleStudioApp' = master
        self.save_project_config = save_project_config
        self.cancel_event = cancel_event
        self.project_config = project_config
        self.global_config = global_config
        self.active_model = active_model

        self.title(f"Przeglądaj i Generuj Dialogi (Model: {active_model})")
        self.geometry(master.geometry())
        self.audio_dir: Optional[Path] = None

        if project_config.get('audio_path'):
            self.audio_dir = Path(project_config.get("audio_path"))
        else:
            self.choose_audio_dir()

        if not self.audio_dir:
            messagebox.showerror("Błąd", "Katalog audio nie został wybrany. Zamykanie przeglądarki.", parent=self)
            self.after(100, self.destroy)
            return

        self.dialogs = master.processed_replace
        self.filtered_indices = []
        self.current_identifier = None

        self.progress_window: Optional[GenerationProgressWindow] = None
        self.queue = queue.Queue()

        try:
            pygame.mixer.init()
        except pygame.error as e:
            messagebox.showwarning("Błąd audio",
                                   f"Nie udało się zainicjować odtwarzacza audio (pygame.mixer):\n{e}\nOdtwarzanie nie będzie działać.",
                                   parent=self)

        self._create_widgets()
        self.check_queue()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        """Stops audio and destroys the window on close."""
        self.stop_audio()
        self.destroy()

    # =====================
    # UI
    # =====================
    def _create_widgets(self):
        """Creates and places all UI widgets in this window."""
        root = ctk.CTkFrame(self)
        root.pack(fill="both", expand=True, padx=10, pady=10)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(0, weight=1)

        # === LEWY PANEL ===
        left = ctk.CTkFrame(root)
        left.grid(row=0, column=0, sticky="nswe", padx=(0, 10))
        left.grid_rowconfigure(2, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Dialogi").grid(row=0, column=0, sticky="we", pady=4)
        self.search_entry = ctk.CTkEntry(left, placeholder_text="Szukaj (po tekście lub numerze linii)...")
        self.search_entry.grid(row=1, column=0, sticky="we", padx=4, pady=4)
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_dialog_list())

        list_frame = ctk.CTkFrame(left)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.dialog_list_scrollbar = ctk.CTkScrollbar(list_frame)
        self.dialog_list_scrollbar.grid(row=0, column=1, sticky="ns")

        self.dialog_list = tk.Listbox(list_frame, font=("", 12), borderwidth=0, highlightthickness=0,
                                      yscrollcommand=self.dialog_list_scrollbar.set)
        self.dialog_list.grid(row=0, column=0, sticky="nsew")
        self.dialog_list_scrollbar.configure(command=self.dialog_list.yview)
        self.dialog_list.bind("<<ListboxSelect>>", self.on_select_dialog)
        self.dialog_list.bind("<Double-Button-1>", self.on_double_click_dialog)

        self.refresh_dialog_list()

        # === PRAWY PANEL ===
        right = ctk.CTkFrame(root, width=500)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        top_frame = ctk.CTkFrame(right)
        top_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(top_frame, text="Zmień katalog audio", command=self.choose_audio_dir).pack(side="left", padx=4,
                                                                                                 pady=4)
        ctk.CTkButton(top_frame, text="Generuj wszystkie brakujące", command=self.start_generate_all).pack(side="left",
                                                                                                           padx=4,
                                                                                                           pady=4)
        self.audio_scroll = ctk.CTkScrollableFrame(right)
        self.audio_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        self.status_label = ctk.CTkLabel(right, text="", anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=6)

    # =====================
    # DIALOGS
    # =====================
    def refresh_dialog_list(self):
        """Updates the visible dialog list based on the search filter."""
        pattern = self.search_entry.get().lower()
        self.dialog_list.delete(0, tk.END)
        self.filtered_indices = []

        for i, line in enumerate(self.dialogs):
            line_number_str = str(i + 1)
            if not pattern:
                match = True
            else:
                try:
                    match = (re.search(pattern, line, re.IGNORECASE) or
                             (pattern in line_number_str))
                except re.error:
                    match = False

            if match:
                self.dialog_list.insert(tk.END, f"{line_number_str}: {line}")
                self.filtered_indices.append(i)

    def on_select_dialog(self, event):
        """Handles selection of a dialog in the listbox."""
        if not self.dialog_list.curselection():
            return
        list_index = self.dialog_list.curselection()[0]
        original_index = self.filtered_indices[list_index]
        self.current_identifier = str(original_index + 1)
        self.load_audio_files(self.current_identifier)

    def on_double_click_dialog(self, event):
        """Plays the first available audio file on double-click."""
        if not self.dialog_list.curselection():
            return
        list_index = self.dialog_list.curselection()[0]
        original_index = self.filtered_indices[list_index]
        identifier = str(original_index + 1)
        files = self._find_audio_files(identifier)
        if files:
            self.play_audio(files[0][0])

    # =====================
    # AUDIO
    # =====================
    def _find_audio_files(self, identifier: str) -> List[tuple[Path, bool]]:
        """Finds all existing audio files for a given dialog identifier."""
        if not self.audio_dir:
            return []
        candidates = [
            (self.audio_dir / f"output1 ({identifier}).wav", False),
            (self.audio_dir / f"output1 ({identifier}).ogg", False),
            (self.audio_dir / f"output1 ({identifier}).mp3", False),
            (self.audio_dir / "ready" / f"output1 ({identifier}).ogg", True),
            (self.audio_dir / "ready" / f"output2 ({identifier}).ogg", True)
        ]
        return [(f, ready) for f, ready in candidates if f.exists()]

    def load_audio_files(self, identifier: str):
        """Reloads the list of audio files for the selected dialog."""
        for widget in self.audio_scroll.winfo_children():
            widget.destroy()

        found = self._find_audio_files(identifier)

        if not found:
            block = ctk.CTkFrame(self.audio_scroll)
            block.pack(fill="x", pady=4, padx=6)
            ctk.CTkLabel(block, text="(Brak plików — można wygenerować)").pack(side="left", padx=6)
            ctk.CTkButton(block, text="Generuj", width=100,
                          command=lambda id=identifier: self.start_generate_single(id)).pack(side="right", padx=6)
        else:
            for file, ready in found:
                self._create_audio_block(file, ready)

    def _create_audio_block(self, file: Path, ready: bool):
        """Creates a single UI block for an audio file with play/delete buttons."""
        block = ctk.CTkFrame(self.audio_scroll)
        block.pack(fill="x", pady=4, padx=6)
        file_name = ("ready/" if ready else "") + str(file.name)
        lbl = ctk.CTkLabel(block, text=file_name, anchor="w")
        lbl.pack(fill="x", padx=6, pady=(4, 2))

        btn_frame = ctk.CTkFrame(block, fg_color="transparent")
        btn_frame.pack(fill="x", padx=6, pady=(0, 4))

        ctk.CTkButton(btn_frame, text="▶️ Odtwórz", width=80, command=lambda f=file: self.play_audio(f)).pack(
            side="left", padx=4)
        ctk.CTkButton(btn_frame, text="❌ Usuń", width=80, command=lambda f=file: self.delete_audio(f)).pack(
            side="left", padx=4)

    def stop_audio(self):
        """Stops and unloads any currently playing audio file to release the lock."""
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

    def play_audio(self, file: Path):
        """Plays the selected audio file."""
        if not file.exists():
            return

        self.stop_audio()

        try:
            pygame.mixer.music.load(str(file))
            pygame.mixer.music.play()
        except Exception as e:
            messagebox.showerror("Błąd odtwarzania", str(e), parent=self)

    def delete_audio(self, file: Path):
        """Deletes an audio file from disk after confirmation."""

        try:
            if pygame.mixer.music.get_busy():
                messagebox.showwarning("Plik w użyciu",
                                       "Nie można usunąć pliku podczas odtwarzania.\nZatrzymaj odtwarzanie (odtwarzając inny plik lub zamykając okno) i spróbuj ponownie.",
                                       parent=self)
                return
        except Exception:
            pass

        self.stop_audio()

        self.lift()
        self.focus_force()
        if os.path.exists(file) and messagebox.askyesno("Potwierdź", f"Usunąć plik?\n{file}", parent=self):
            try:
                os.remove(file)
                self.load_audio_files(self.current_identifier)
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie udało się usunąć pliku:\n{e}", parent=self)

    # =====================
    # ZARZĄDZANIE WĄTKAMI I KOLEJKĄ
    # =====================

    def check_queue(self):
        """Periodically checks the queue for tasks to run on the main thread."""
        try:
            update_callable = self.queue.get_nowait()
        except queue.Empty:
            pass
        else:
            update_callable()

        self.after(100, self.check_queue)

    def set_status_busy(self, text: str):
        """Sets the status label to indicate a busy state."""
        self.status_label.configure(text=text)

    def set_status_ready(self):
        """Clears the status label."""
        self.status_label.configure(text="")

    # =====================
    # LOGIKA GENEROWANIA
    # =====================

    def _load_tts_model(self):
        """
        Loads the active TTS model instance based on project settings.
        Sets self.master.tts_model to the loaded instance or None on failure.
        """
        try:
            # Wyczyść stary model, jeśli istnieje
            self.master.tts_model = None

            if self.active_model == 'XTTS':
                if not self.master.torch_installed:
                    raise RuntimeError("Pakiet 'torch' nie jest zainstalowany.")

                voice_path = self.global_config.get('xtts_voice_path')
                if not voice_path or not Path(voice_path).exists():
                    self.queue.put(lambda: messagebox.showwarning(
                        "Brak pliku głosu XTTS",
                        "Ścieżka do pliku głosu .wav nie jest ustawiona w Ustawieniach lub plik nie istnieje.\nUżywam domyślnego głosu (jeśli istnieje).",
                        parent=self
                    ))
                    voice_path = None

                self.master.tts_model = XTTSPolishTTS(voice_path=voice_path)

            elif self.active_model == 'ElevenLabs':
                api_key = self.global_config.get('elevenlabs_api_key')
                voice_id = self.global_config.get('elevenlabs_voice_id')
                if not api_key or not voice_id:
                    raise ValueError("Klucz API lub Voice ID dla ElevenLabs nie są ustawione w Ustawieniach.")
                self.master.tts_model = ElevenLabsTTS(api_key=api_key, voice_id=voice_id)

            elif self.active_model == 'Google Cloud TTS':
                creds_path = self.global_config.get('google_credentials_path')
                voice_name = self.global_config.get('google_voice_name')
                if not creds_path or not Path(creds_path).exists():
                    raise ValueError("Ścieżka do credentials .json dla Google TTS jest nieprawidłowa lub nie istnieje.")
                self.master.tts_model = GoogleCloudTTS(credentials_path=creds_path, voice_name=voice_name)

            else:
                raise ValueError(f"Nieznany model TTS: {self.active_model}")

        except Exception as e:
            self.master.tts_model = None
            # === POPRAWKA: Przekazanie 'e' do lambdy ===
            self.queue.put(lambda e=e: messagebox.showerror(
                f"Błąd modelu {self.active_model}",
                f"Nie udało się załadować modelu:\n{e}",
                parent=self
            ))
            # ==========================================
            if self.progress_window:
                self.queue.put(lambda: self.progress_window.destroy())

    def _run_converter(self, is_single_file=False, single_file_path: Optional[Path] = None):
        """
        Initializes and runs the AudioConverter.

        Args:
            is_single_file: If True, convert only the file at `single_file_path`.
            single_file_path: Path to the single .wav file to convert.
        """
        try:
            base_speed = float(self.project_config.get('base_audio_speed', 1.1))
        except ValueError:
            base_speed = 1.1
            self.queue.put(lambda: messagebox.showwarning(
                "Błędna wartość",
                f"Nieprawidłowa wartość 'base_audio_speed' w projekcie. Używam domyślnej: {base_speed}",
                parent=self
            ))

        filter_settings = self.global_config.get('ffmpeg_filters', {})

        converter = AudioConverter(
            base_speed=base_speed,
            filter_settings=filter_settings
        )

        output_dir = self.audio_dir / "ready"
        os.makedirs(output_dir, exist_ok=True)

        if is_single_file and single_file_path:
            output_file = converter.build_output_file_path(single_file_path.name, str(output_dir))
            converter.parse_ogg(str(single_file_path), output_file)
        else:
            converter.convert_dir(str(self.audio_dir), str(output_dir))

    # --- Generowanie pojedynczego pliku ---

    def start_generate_single(self, identifier: str):
        """Starts the generation of a single audio file in a new thread."""
        if not self.master.generation_lock.acquire(blocking=False):
            messagebox.showwarning("Zajęty", "Inny proces generowania jest już w toku.", parent=self)
            return

        self.cancel_event.clear()
        threading.Thread(target=self._task_generate_single, args=(identifier,), daemon=True).start()

    def _task_generate_single(self, identifier: str):
        """Worker thread task for generating a single file."""
        try:
            # 1. Załaduj model
            self.queue.put(lambda: self.set_status_busy(f"Ładowanie modelu {self.active_model}..."))
            self._load_tts_model()
            if self.master.tts_model is None: return
            if self.cancel_event.is_set(): return

            # 2. Generuj TTS
            self.queue.put(lambda: self.set_status_busy(f"Generowanie głosu dla dialogu {identifier}..."))
            text = self.dialogs[int(identifier) - 1]

            output_path = self.audio_dir / f"output1 ({identifier}).wav"
            self.master.tts_model.tts(text, str(output_path))

            # 3. Konwertuj audio
            self.queue.put(lambda: self.set_status_busy("Konwertowanie audio..."))
            self._run_converter(is_single_file=True, single_file_path=output_path)

            # 4. Odśwież GUI
            if self.current_identifier == identifier:
                self.queue.put(lambda: self.load_audio_files(identifier))
            self.queue.put(self.set_status_ready)

        except Exception as e:
            # === POPRAWKA: Przekazanie 'e' do lambdy ===
            self.queue.put(lambda e=e: messagebox.showerror("Błąd generowania", f"Wystąpił błąd: {e}", parent=self))
            # ==========================================
            self.queue.put(self.set_status_ready)
        finally:
            self.master.generation_lock.release()

    # --- Generowanie wszystkich plików ---

    def start_generate_all(self):
        """Starts the generation of all missing audio files in a new thread."""
        if not self.master.generation_lock.acquire(blocking=False):
            messagebox.showwarning("Zajęty", "Inny proces generowania jest już w toku.", parent=self)
            return

        self.cancel_event.clear()
        self.progress_window = GenerationProgressWindow(self, self.cancel_event)
        threading.Thread(target=self._task_generate_all, daemon=True).start()

    def _task_generate_all(self):
        """Worker thread task for generating all missing files."""
        generated_count = 0
        try:
            # 1. Załaduj model
            self.queue.put(
                lambda: self.progress_window.update_progress(0, len(self.dialogs),
                                                             f"Ładowanie modelu {self.active_model}..."))
            self._load_tts_model()
            if self.master.tts_model is None: return
            if self.cancel_event.is_set(): return

            # 2. Znajdź brakujące pliki
            dialogs_to_generate = []
            for i, text in enumerate(self.dialogs):
                identifier = str(i + 1)
                if not self._find_audio_files(identifier):
                    dialogs_to_generate.append((identifier, text))

            if not dialogs_to_generate:
                self.queue.put(lambda: self.progress_window.destroy())
                self.queue.put(lambda: messagebox.showinfo("Gotowe", "Wszystkie dialogi już istnieją.", parent=self))
                return

            # 3. Generuj TTS (pętla)
            total_to_gen = len(dialogs_to_generate)
            for i, (identifier, text) in enumerate(dialogs_to_generate):
                if self.cancel_event.is_set():
                    break

                generated_count = i + 1
                self.queue.put(
                    lambda i=generated_count, t=total_to_gen: self.progress_window.update_progress(i, t,
                                                                                                   "Generowanie TTS..."))

                output_path = self.audio_dir / f"output1 ({identifier}).wav"
                self.master.tts_model.tts(text, str(output_path))

            # 4. Konwertuj audio (wszystkie na raz)
            if self.cancel_event.is_set():
                self.queue.put(
                    lambda: self.progress_window.set_indeterminate("Anulowano. Kończenie konwersji audio..."))
            else:
                self.queue.put(
                    lambda: self.progress_window.set_indeterminate(
                        "Konwertowanie audio...\n(To może potrwać kilka minut)"))

            self._run_converter(is_single_file=False)

            # 5. Zakończ
            self.queue.put(lambda: self.progress_window.destroy())

            if self.cancel_event.is_set():
                self.queue.put(lambda: messagebox.showinfo("Anulowano",
                                                           f"Proces generowania został przerwany.\nPrzetworzono {generated_count} z {total_to_gen} plików.",
                                                           parent=self))
            else:
                self.queue.put(lambda: messagebox.showinfo("Gotowe",
                                                           f"Pomyślnie wygenerowano i przetworzono {generated_count} nowych plików audio.",
                                                           parent=self))

            if self.current_identifier:
                self.queue.put(lambda: self.load_audio_files(self.current_identifier))

        except Exception as e:
            if self.progress_window:
                self.queue.put(lambda: self.progress_window.destroy())

            self.queue.put(lambda e=e: messagebox.showerror("Błąd generowania", f"Wystąpił błąd: {e}", parent=self))

        finally:
            self.master.generation_lock.release()

    # =====================
    # KONFIGURACJA
    # =====================
    def choose_audio_dir(self):
        """Opens a dialog to choose the audio output directory."""
        self.lift()
        self.focus_force()
        initial_dir = self.master.global_config.get('start_directory')
        path = filedialog.askdirectory(title="Wybierz katalog audio", initialdir=initial_dir, parent=self)
        if path:
            self.audio_dir = Path(path)
            self.save_project()
            if self.current_identifier:
                self.load_audio_files(self.current_identifier)

    def save_project(self):
        """Saves the selected audio directory path to the project config."""
        if self.audio_dir:
            abs_dir = str(self.audio_dir.absolute())
            self.project_config["audio_path"] = abs_dir
            self.save_project_config('audio_path', abs_dir)