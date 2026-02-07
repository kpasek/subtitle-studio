import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import threading
import time
from pathlib import Path

from audio.verification_manager import VerificationManager
from app.tooltip import CreateToolTip
from app.io import update_line_in_csv

class VerificationWindow(ctk.CTkToplevel):
    """Window with Start / Stop / Ignore cache and progress bar for verification."""

    def __init__(self, master_app):
        super().__init__(master_app)
        self.master_app = master_app
        self.subtitle_panel = getattr(master_app, 'subtitle_panel', None)
        self.title('Weryfikacja audio')
        self.geometry('420x160')
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
        self.ignore_cb = ctk.CTkCheckBox(btn_frame, text='Ignoruj cache', variable=self.force_refresh)
        self.ignore_cb.pack(side='left', padx=12)

        # Progress
        prog_frame = ctk.CTkFrame(frm)
        prog_frame.pack(fill='x', pady=(12,0))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(prog_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(fill='x', padx=6, pady=6)
        self.status_label = ctk.CTkLabel(frm, text='Status: idle')
        self.status_label.pack(anchor='w', padx=6)

        # Options: verify duration and verify similarity
        opts_frame = ctk.CTkFrame(frm, fg_color='transparent')
        opts_frame.pack(fill='x', padx=6, pady=(4,0))

        self.verify_duration_var = tk.BooleanVar(value=True)
        cb_dur = ctk.CTkCheckBox(opts_frame, text='Weryfikuj długość audio', variable=self.verify_duration_var)
        cb_dur.pack(side='left', padx=(0,8))
        lbl_dur_i = ctk.CTkLabel(opts_frame, text='(i)')
        lbl_dur_i.pack(side='left')
        CreateToolTip(lbl_dur_i, text='Sprawdza długość pliku audio i oblicza CPS (znaki na sekundę).')

        self.verify_similarity_var = tk.BooleanVar(value=False)
        cb_sim = ctk.CTkCheckBox(opts_frame, text='Weryfikuj podobieństwo', variable=self.verify_similarity_var)
        cb_sim.pack(side='left', padx=(12,8))
        lbl_sim_i = ctk.CTkLabel(opts_frame, text='(i)')
        lbl_sim_i.pack(side='left')
        CreateToolTip(lbl_sim_i, text='Uruchamia rozpoznawanie mowy (Whisper) i porównanie tekstu. Proces jest powolny.')

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

                for i, line in enumerate(lines):
                    if panel.ver_stop_event.is_set():
                        break

                    # perform verification (respect verify duration option)
                    res = VerificationManager.verify_line(
                        line=line,
                        audio_dir=str(getattr(self.master_app, 'audio_dir', Path('.'))),
                        line_id=i+1,
                        ffprobe_path=getattr(panel, 'ver_ffprobe_path', None),
                        ignore_short=False,
                        verify_duration=self.verify_duration_var.get()
                    )

                    # if OK and similarity enabled, attempt similarity (may be slow)
                    if self.verify_similarity_var.get() and res.get('path') and res.get('raw_status') == 'OK':
                        try:
                            line = VerificationManager.apply_similarity_to_line(line, res.get('path'))
                            res['similarity'] = getattr(line, 'audio_similarity', 0.0)
                            res['transcribed_text'] = getattr(line, 'audio_transcribed_text', '')
                        except Exception:
                            res['similarity'] = 0.0
                            res['transcribed_text'] = ''

                    # store result and mark processed
                    # update Line fields so they persist to main CSV
                    if res.get('duration') is not None:
                        line.audio_duration = round(float(res.get('duration')) * 1000, 3) / 1000
                    if res.get('path'):
                        line.audio_filename = Path(res.get('path')).name
                    line.audio_format = res.get('ext', '') or ''
                    # transcribed text stored by apply_similarity_to_line
                    if res.get('transcribed_text'):
                        line.audio_transcribed_text = res.get('transcribed_text')

                    panel.ver_analysis_results[i] = res
                    panel.ver_processed_indices.add(i)

                    # Persist single-line changes to the original CSV (if loaded)
                    try:
                        lp = getattr(self.master_app, 'loaded_path', None)
                        if lp:
                            update_line_in_csv(str(lp), i, line)
                    except Exception:
                        pass

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
        self._poll_job = self.after(500, self._poll)

    def destroy(self):
        self._stop_poll()
        super().destroy()
