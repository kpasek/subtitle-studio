import customtkinter as ctk
import tkinter as tk
from tkinter import ttk

from app.tooltip import CreateToolTip

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

        # Pobieramy ustawienia z UI
        force_refresh = self.force_refresh.get()
        verify_duration = self.verify_duration_var.get()
        verify_similarity = self.verify_similarity_var.get()
        verify_hallucination = self.verify_hallucination_var.get()
        
        # Uruchamiamy weryfikację przez panel (który używa VerificationManager -> Worker)
        self.subtitle_panel.start_verification(
            force_refresh=force_refresh,
            verify_options={
                'verify_duration': verify_duration,
                'verify_similarity': verify_similarity,
                'verify_hallucination': verify_hallucination
            }
        )
        
        self._running = True
        self._start_poll()

    def _on_stop(self):
        if not self.subtitle_panel:
            return
        
        # Prawidłowe zatrzymanie przez metodę panelu, która komunikuje się z Managerem
        if hasattr(self.subtitle_panel, 'stop_verification'):
            self.subtitle_panel.stop_verification()
            
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
            total = len(getattr(self.master_app, 'lines', []))
            processed = getattr(self.subtitle_panel, 'ver_processed_count', 0)
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
            
            if not running and self._running and processed >= total:
                 self._running = False
                 
        except Exception:
            pass
        # Update UI every 1 second
        self._poll_job = self.after(1000, self._poll)

    def destroy(self):
        self._stop_poll()
        super().destroy()
