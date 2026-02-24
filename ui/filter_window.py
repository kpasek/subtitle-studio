import customtkinter as ctk
import tkinter as tk
from typing import Callable, Dict, Optional


class FilterWindow(ctk.CTkToplevel):
    """Non-modal filter window. Calls callback(filters_dict) on Apply."""

    def __init__(self, master, current_filters: Dict = None, apply_callback: Callable[[Dict], None] = None):
        super().__init__(master)
        self.title("Filtracja")
        self.geometry("600x500")
        self.transient(master)
        self.apply_callback = apply_callback
        self.current_filters = current_filters or {}

        self._build()

    def _build(self):
        frm = ctk.CTkFrame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Configure columns for expansion
        frm.grid_columnconfigure(1, weight=1)
        frm.grid_columnconfigure(2, weight=1)

        # CPS
        ctk.CTkLabel(frm, text="CPS (min/max):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.min_cps = tk.StringVar(value=str(self.current_filters.get('min_cps', '')))
        self.max_cps = tk.StringVar(value=str(self.current_filters.get('max_cps', '')))
        ctk.CTkEntry(frm, textvariable=self.min_cps).grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ctk.CTkEntry(frm, textvariable=self.max_cps).grid(row=0, column=2, sticky="ew", padx=5, pady=5)

        # Text length
        ctk.CTkLabel(frm, text="Długość tekstu (min/max):").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.min_len = tk.StringVar(value=str(self.current_filters.get('min_len', '')))
        self.max_len = tk.StringVar(value=str(self.current_filters.get('max_len', '')))
        ctk.CTkEntry(frm, textvariable=self.min_len).grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        ctk.CTkEntry(frm, textvariable=self.max_len).grid(row=1, column=2, sticky="ew", padx=5, pady=5)

        # Similarity
        ctk.CTkLabel(frm, text="Similarity (min/max):").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.min_sim = tk.StringVar(value=self._display_percentage(self.current_filters.get('min_sim')))
        self.max_sim = tk.StringVar(value=self._display_percentage(self.current_filters.get('max_sim')))
        ctk.CTkEntry(frm, textvariable=self.min_sim).grid(row=2, column=1, sticky="ew", padx=5, pady=5)
        ctk.CTkEntry(frm, textvariable=self.max_sim).grid(row=2, column=2, sticky="ew", padx=5, pady=5)

        # Show audio dropdown
        ctk.CTkLabel(frm, text="Pokaż: ").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.show_option = tk.StringVar(value=self.current_filters.get('show', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.show_option, values=["Wszystkie", "Wygenerowane", "Niewygenerowane"]).grid(row=3, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # Hallucination filter
        ctk.CTkLabel(frm, text="Halucynacje: ").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        self.hal_option = tk.StringVar(value=self.current_filters.get('halucination', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.hal_option, values=["Wszystkie", "Tylko halucynacje", "Bez halucynacji", "Nieweryfikowane"]).grid(row=4, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # Status filter
        ctk.CTkLabel(frm, text="Status: ").grid(row=5, column=0, sticky="w", padx=5, pady=5)
        self.status_option = tk.StringVar(value=self.current_filters.get('status', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.status_option, values=["Wszystkie", "Gotowe", "Błędne", "Bez flagi"]).grid(row=5, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # SI Status filter
        ctk.CTkLabel(frm, text=" Przetworzone: ").grid(row=6, column=0, sticky="w", padx=5, pady=5)
        self.ai_option = tk.StringVar(value=self.current_filters.get('ai_status', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.ai_option, values=["Wszystkie", "Tak", "Nie"]).grid(row=6, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # Diff Status filter (Text != TTS)
        ctk.CTkLabel(frm, text="Zmiany (Text vs TTS): ").grid(row=7, column=0, sticky="w", padx=5, pady=5)
        self.diff_option = tk.StringVar(value=self.current_filters.get('diff_status', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.diff_option, values=["Wszystkie", "Tylko zmienione", "Bez zmian"]).grid(row=7, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # AI Quality (min/max)
        ctk.CTkLabel(frm, text="Jakość SI (min/max):").grid(row=8, column=0, sticky="w", padx=5, pady=5)
        self.min_ai_qual = tk.StringVar(value=str(self.current_filters.get('min_ai_quality', '')))
        self.max_ai_qual = tk.StringVar(value=str(self.current_filters.get('max_ai_quality', '')))
        ctk.CTkEntry(frm, textvariable=self.min_ai_qual).grid(row=8, column=1, sticky="ew", padx=5, pady=5)
        ctk.CTkEntry(frm, textvariable=self.max_ai_qual).grid(row=8, column=2, sticky="ew", padx=5, pady=5)

        # Has Suggestion
        ctk.CTkLabel(frm, text="Posiada sugestię: ").grid(row=9, column=0, sticky="w", padx=5, pady=5)
        self.has_sug_option = tk.StringVar(value=self.current_filters.get('has_ai_suggestion', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.has_sug_option, values=["Wszystkie", "Tak", "Nie"]).grid(row=9, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # Buttons
        btn_frame = ctk.CTkFrame(frm, fg_color="transparent")
        btn_frame.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(12,0))
        ctk.CTkButton(btn_frame, text="Wyczyść", command=self._on_clear).pack(side="left", padx=6)
        ctk.CTkButton(btn_frame, text="Zastosuj", command=self._on_apply).pack(side="right", padx=6)

    def _on_apply(self):
        filters = {}
        try:
            if self.min_cps.get(): filters['min_cps'] = float(self.min_cps.get())
        except Exception:
            pass
        try:
            if self.max_cps.get(): filters['max_cps'] = float(self.max_cps.get())
        except Exception:
            pass
        try:
            if self.min_len.get(): filters['min_len'] = int(self.min_len.get())
        except Exception:
            pass
        try:
            if self.max_len.get(): filters['max_len'] = int(self.max_len.get())
        except Exception:
            pass
        sim_min = self._parse_percentage(self.min_sim.get())
        sim_max = self._parse_percentage(self.max_sim.get())
        if sim_min is not None:
            filters['min_sim'] = sim_min
        if sim_max is not None:
            filters['max_sim'] = sim_max
        filters['show'] = self.show_option.get()
        filters['halucination'] = self.hal_option.get()
        status_v = self.status_option.get()
        if status_v != "Wszystkie":
            filters['status'] = status_v
        
        ai_v = self.ai_option.get()
        if ai_v != "Wszystkie":
            filters['ai_status'] = ai_v
            
        diff_v = self.diff_option.get()
        if diff_v != "Wszystkie":
            filters['diff_status'] = diff_v

        # AI Filters
        try:
            if self.min_ai_qual.get(): filters['min_ai_quality'] = int(self.min_ai_qual.get())
        except: pass
        try:
            if self.max_ai_qual.get(): filters['max_ai_quality'] = int(self.max_ai_qual.get())
        except: pass
        
        has_sug_v = self.has_sug_option.get()
        if has_sug_v != "Wszystkie":
             filters['has_ai_suggestion'] = has_sug_v

        if callable(self.apply_callback):
            self.apply_callback(filters)
        self.destroy()

    def _on_clear(self):
        self.min_cps.set('')
        self.max_cps.set('')
        self.min_len.set('')
        self.max_len.set('')
        self.min_sim.set('')
        self.max_sim.set('')
        self.min_ai_qual.set('')
        self.max_ai_qual.set('')
        self.show_option.set('Wszystkie')
        self.hal_option.set('Wszystkie')
        self.status_option.set('Wszystkie')
        self.has_sug_option.set('Wszystkie')
        if callable(self.apply_callback):
            self.apply_callback({})

    def _display_percentage(self, value: Optional[float]) -> str:
        if value is None or value == '':
            return ''
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return ''
        percent = numeric * 100 if numeric <= 1 else numeric
        percent = max(0.0, min(percent, 100.0))
        if percent.is_integer():
            return str(int(percent))
        return f"{percent:.1f}"

    def _parse_percentage(self, text: str) -> Optional[float]:
        if not text:
            return None
        try:
            val = float(text)
        except ValueError:
            return None
        if val > 1:
            val = val / 100.0
        val = max(0.0, min(val, 1.0))
        return val
