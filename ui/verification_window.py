import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import threading
import time
from pathlib import Path
from dataclasses import asdict

from audio.verification_manager import VerificationManager
from app.tooltip import CreateToolTip
from app.io import update_line_in_csv, get_primary_audio_path, get_audio_candidates

class VerificationWindow(ctk.CTkToplevel):
    """Window with Start / Stop / Ignore cache and progress bar for verification."""

    def __init__(self, master_app):
        super().__init__(master_app)
        self.master_app = master_app
        self.subtitle_panel = getattr(master_app, 'subtitle_panel', None)
        self.title('Weryfikacja audio')
        self.geometry('550x300')
        self.transient(master_app)

        self.force_refresh = tk.BooleanVar(value=False)

        self._build()
        self._running = False
        self._poll_job = None

    def _build(self):
        frm = ctk.CTkFrame(self)
        frm.pack(fill='both', expand=True, padx=10, pady=10)

        btn_frame = ctk.CTkFrame(frm, fg_color='transparent')
        btn_frame.pack(fill='x')

        self.start_btn = ctk.CTkButton(btn_frame, text='Start', width=80, command=self._on_start)
        self.start_btn.pack(side='left', padx=6)
        self.stop_btn = ctk.CTkButton(btn_frame, text='Stop', width=80, command=self._on_stop)
        self.stop_btn.pack(side='left', padx=6)

        # Progress
        prog_frame = ctk.CTkFrame(frm)
        prog_frame.pack(fill='x', pady=(12,0))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(prog_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(fill='x', padx=6, pady=6)
        self.status_label = ctk.CTkLabel(frm, text='Status: idle')
        self.status_label.pack(anchor='w', padx=6)

        # Options: list of checkboxes
        opts_frame = ctk.CTkFrame(frm, fg_color='transparent')
        opts_frame.pack(fill='x', padx=6, pady=(10,0))

        # Row 0: Ignore cache
        row_ignore = ctk.CTkFrame(opts_frame, fg_color='transparent')
        row_ignore.pack(fill='x', pady=2)
        self.ignore_cb = ctk.CTkCheckBox(row_ignore, text='Ignoruj cache (wymuś ponowną weryfikację)', variable=self.force_refresh)
        self.ignore_cb.pack(side='left', padx=(0,8))

        # Row 1: Duration
        row1 = ctk.CTkFrame(opts_frame, fg_color='transparent')
        row1.pack(fill='x', pady=2)
        self.verify_duration_var = tk.BooleanVar(value=True)
        cb_dur = ctk.CTkCheckBox(row1, text='Weryfikuj długość audio', variable=self.verify_duration_var)
        cb_dur.pack(side='left', padx=(0,8))
        lbl_dur_i = ctk.CTkLabel(row1, text='(i)', cursor='hand2')
        lbl_dur_i.pack(side='left')
        CreateToolTip(lbl_dur_i, text='Sprawdza długość pliku audio i oblicza CPS (znaki na sekundę).')

        # Row 2: Similarity
        row2 = ctk.CTkFrame(opts_frame, fg_color='transparent')
        row2.pack(fill='x', pady=2)
        self.verify_similarity_var = tk.BooleanVar(value=False)
        cb_sim = ctk.CTkCheckBox(row2, text='Weryfikuj podobieństwo', variable=self.verify_similarity_var)
        cb_sim.pack(side='left', padx=(0,8))
        lbl_sim_i = ctk.CTkLabel(row2, text='(i)', cursor='hand2')
        lbl_sim_i.pack(side='left')
        CreateToolTip(lbl_sim_i, text='Uruchamia rozpoznawanie mowy (Whisper) i porównanie tekstu. Proces jest powolny.')

        # Row 3: Hallucination
        row3 = ctk.CTkFrame(opts_frame, fg_color='transparent')
        row3.pack(fill='x', pady=2)
        self.verify_hallucination_var = tk.BooleanVar(value=True)
        cb_hal = ctk.CTkCheckBox(row3, text='Weryfikuj halucynacje', variable=self.verify_hallucination_var)
        cb_hal.pack(side='left', padx=(0,8))
        lbl_hal_i = ctk.CTkLabel(row3, text='(i)', cursor='hand2')
        lbl_hal_i.pack(side='left')
        CreateToolTip(lbl_hal_i, text='Wykrywa ciszę lub zawieszenia modelu TTS (wymaga ffmpeg).')

    def _on_start(self):
        if not self.subtitle_panel:
            return
        # start verification in background thread (local implementation)
        def run_verification():
            try:
                panel = self.subtitle_panel
                # initialize state
                panel.ver_running = True
                panel.ver_stop_event.clear()
                force = self.force_refresh.get()

                if force:
                    panel.ver_analysis_results = []
                    panel.ver_processed_indices = set()
                    panel.ver_cache = {}

                lines = getattr(self.master_app, 'lines', [])
                total = len(lines)
                panel.ver_analysis_results = [{} for _ in range(total)]
                
                # Diagnostyka: sprawdź ile linii ma audio_transcribed_text
                with_transcribed = sum(1 for line in lines if getattr(line, 'audio_transcribed_text', ''))
                with_filename = sum(1 for line in lines if getattr(line, 'audio_filename', ''))
                with_similarity = sum(1 for line in lines if getattr(line, 'audio_similarity', 0))
                print(f"[DIAGNOSTICS] Linie wczytane: {total}, z transkrypcją: {with_transcribed}, z audio: {with_filename}, z similarity: {with_similarity}")
                
                # Pokaż pierwsze 3 linie z ich danymi
                for idx in range(min(3, total)):
                    line = lines[idx]
                    print(f"[SAMPLE] Linia {idx+1}: audio_filename={repr(getattr(line, 'audio_filename', ''))}, audio_transcribed_text={repr(getattr(line, 'audio_transcribed_text', '')[:50])}, audio_similarity={getattr(line, 'audio_similarity', 0)}")

                # Counter for UI refresh throttling (update every 20 files)
                update_counter = 0
                update_interval = 20

                for i, line in enumerate(lines):
                    if panel.ver_stop_event.is_set():
                        break

                    # If not forcing refresh and line already has audio_filename or transcribed text, skip verification
                    force = self.force_refresh.get()
                    has_audio_filename = getattr(line, 'audio_filename', '')
                    has_transcribed_text = getattr(line, 'audio_transcribed_text', '')
                    has_audio_duration = getattr(line, 'audio_duration', 0)
                    has_audio_similarity = getattr(line, 'audio_similarity', 0)
                    
                    print(f"[CHECK] Linia {i+1}: filename={repr(has_audio_filename)}, transcribed={repr(has_transcribed_text[:30] if has_transcribed_text else '')}, duration={has_audio_duration}, similarity={has_audio_similarity}, force={force}")
                    
                    # Flaga czy linia została zmodyfikowana (do zapisania do CSV)
                    line_was_modified = False
                    
                    # Jeśli już ma transkrybowany tekst, całkowite pominięcie
                    if not force and has_transcribed_text:
                        print(f"[SKIP_FULL] Linia {i+1}: już zweryfikowana")
                        # Szybkie pominięcie - tylko skopiuj dane z Line
                        res = {
                            'id': i + 1,
                            'text': line.get_tts_text(),
                            'duration': line.audio_duration,
                            'similarity': line.audio_similarity,
                            'transcribed_text': line.audio_transcribed_text,
                            'hallucination': line.audio_hallucination,
                            'display_status': line.audio_status or ('OK' if line.audio_duration > 0 else 'MISSING'),
                            'ext': line.audio_format,
                            'raw_status': 'OK' if line.audio_duration > 0 else 'MISSING'
                        }
                        
                        # Pobierz ścieżkę do pliku
                        audio_path_obj, _ = VerificationManager._find_audio_for_uid(Path(getattr(self.master_app, 'audio_dir', '.')), line.uid)
                        res['path'] = str(audio_path_obj) if audio_path_obj else None
                        
                        line_was_modified = False
                    # Jeśli ma audio_filename ale brak transkrypcji, i similarity jest włączony - pominąć verify_line, ale zweryfikować similarity
                    elif not force and has_audio_filename and not has_transcribed_text and self.verify_similarity_var.get():
                        print(f"[SKIP_VERIFY_LINE] Linia {i+1}: ma audio, weryfikuję tylko similarity")
                        # Pominąć verify_line ale bezpośrednio przejść do apply_similarity_to_line
                        path_obj = get_primary_audio_path(line.uid)
                        res = {
                            'id': i + 1,
                            'text': line.tts_text or '',
                            'duration': float(getattr(line, 'audio_duration', 0) or 0.0),
                            'raw_status': 'OK' if getattr(line, 'audio_duration', 0) else 'MISSING',
                            'path': str(path_obj) if path_obj else None,
                            'ext': (path_obj.suffix.lstrip('.') if path_obj else '') or getattr(line, 'audio_format', ''),
                            'display_status': 'OK' if getattr(line, 'audio_duration', 0) else 'MISSING',
                            'similarity': 0.0,
                            'transcribed_text': '',
                            'hallucination': ''
                        }
                        # Będzie modyfikowana przez apply_similarity_to_line
                        line_was_modified = True
                    # Pełna weryfikacja
                    else:
                        print(f"[VERIFY] Linia {i+1}: weryfikuję")
                        
                        # Pobierz flagi
                        v_dur = self.verify_duration_var.get()
                        v_hal = self.verify_hallucination_var.get()
                        v_sim = self.verify_similarity_var.get()
                        
                        # Wykonaj weryfikację (bezpośrednio aktualizuje obiekt line)
                        VerificationManager.verify_line(
                            line=line,
                            audio_dir=str(getattr(self.master_app, 'audio_dir', Path('.'))),
                            ffprobe_path=getattr(panel, 'ver_ffprobe_path', None),
                            ignore_short=False,
                            verify_duration=v_dur,
                            verify_hallucination=v_hal,
                            verify_similarity=v_sim
                        )
                        
                        # Przygotowanie słownika wyniku dla panel.ver_analysis_results
                        # Zachowujemy kompatybilność z Treeview w subtitles.py
                        res = {
                            'id': i + 1,
                            'text': line.get_tts_text(),
                            'duration': line.audio_duration,
                            'similarity': line.audio_similarity,
                            'transcribed_text': line.audio_transcribed_text,
                            'hallucination': line.audio_hallucination,
                            'display_status': line.audio_status,
                            'ext': line.audio_format,
                            'raw_status': 'OK' if line.audio_duration > 0 else 'MISSING'
                        }
                        
                        # Bezwzględna ścieżka do audio do odtwarzania w GUI
                        audio_path_obj, _ = VerificationManager._find_audio_for_uid(Path(getattr(self.master_app, 'audio_dir', '.')), line.uid)
                        res['path'] = str(audio_path_obj) if audio_path_obj else None
                        
                        line_was_modified = True

                    panel.ver_analysis_results[i] = res
                    panel.ver_processed_indices.add(i)

                    # Persist single-line changes to the original CSV (if loaded) - TYLKO jeśli linia była modyfikowana
                    if line_was_modified:
                        try:
                            lp = getattr(self.master_app, 'loaded_path', None)
                            if lp:
                                update_line_in_csv(str(lp), i, line)
                        except Exception as e:
                            print(f"[WARNING] Failed to update CSV at line {i}: {e}")

                    # Update UI every 20 files to reduce rapid status updates
                    update_counter += 1
                    if update_counter >= update_interval:
                        update_counter = 0
                        # Force a UI update by calling _poll
                        try:
                            self.master_app.after(0, self._poll)
                        except Exception:
                            pass

                # Podsumowanie weryfikacji
                num_skipped = len(panel.ver_analysis_results) - len(panel.ver_processed_indices)
                num_verified = len(panel.ver_processed_indices)
                print(f"\n[SUMMARY] Weryfikacja zakończona: {num_verified} zweryfikowanych, {num_skipped} pominiętych (razem: {total})")
                
                panel.ver_running = False

                # results persisted per-line into the original CSV during processing
            except Exception:
                try:
                    panel.ver_running = False
                except Exception:
                    pass

        threading.Thread(target=run_verification, daemon=True).start()
        self._running = True
        self._start_poll()

    def _on_stop(self):
        if not self.subtitle_panel:
            return
        try:
            self.subtitle_panel.ver_stop_event.set()
            self.subtitle_panel.ver_running = False
        except Exception:
            pass
        self._running = False
        self._stop_poll()
        self.status_label.configure(text='Status: stopped')

    def _start_poll(self):
        if self._poll_job:
            return
        self._poll()

    def _stop_poll(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

    def _poll(self):
        try:
            total = len(getattr(self.subtitle_panel, 'ver_analysis_results', []))
            processed = len(getattr(self.subtitle_panel, 'ver_processed_indices', set()))
            running = getattr(self.subtitle_panel, 'ver_running', False)
            pct = 0.0
            if total > 0:
                pct = min(100.0, (processed / total) * 100.0)
            self.progress_var.set(pct)
            st = f"Weryfikowano: {processed}/{total} ({pct:.1f}%)"
            if running:
                st = 'Weryfikacja: ' + st
            else:
                st = 'Idle: ' + st
            self.status_label.configure(text=st)
        except Exception:
            pass
        # Update UI every 1 second instead of 500ms to reduce rapid status updates
        self._poll_job = self.after(1000, self._poll)

    def destroy(self):
        self._stop_poll()
        super().destroy()
