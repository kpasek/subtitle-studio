import customtkinter as ctk
import tkinter as tk
from typing import Callable, Dict, Optional


class FilterWindow(ctk.CTkToplevel):
    """Non-modal filter window. Calls callback(filters_dict) on Apply."""

    def __init__(self, master, current_filters: Dict = None, apply_callback: Callable[[Dict], None] = None):
        super().__init__(master)
        self.title("Filtracja")
        self.geometry("380x280")
        self.transient(master)
        self.apply_callback = apply_callback
        self.current_filters = current_filters or {}

        self._build()

    def _build(self):
        frm = ctk.CTkFrame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        # CPS
        ctk.CTkLabel(frm, text="CPS (min/max):").grid(row=0, column=0, sticky="w")
        self.min_cps = tk.StringVar(value=str(self.current_filters.get('min_cps', '')))
        self.max_cps = tk.StringVar(value=str(self.current_filters.get('max_cps', '')))
        ctk.CTkEntry(frm, textvariable=self.min_cps, width=60).grid(row=0, column=1, sticky="w", padx=(6,0))
        ctk.CTkEntry(frm, textvariable=self.max_cps, width=60).grid(row=0, column=2, sticky="w", padx=(6,0))

        # Text length
        ctk.CTkLabel(frm, text="Długość tekstu (min/max):").grid(row=1, column=0, sticky="w", pady=(8,0))
        self.min_len = tk.StringVar(value=str(self.current_filters.get('min_len', '')))
        self.max_len = tk.StringVar(value=str(self.current_filters.get('max_len', '')))
        ctk.CTkEntry(frm, textvariable=self.min_len, width=60).grid(row=1, column=1, sticky="w", padx=(6,0), pady=(8,0))
        ctk.CTkEntry(frm, textvariable=self.max_len, width=60).grid(row=1, column=2, sticky="w", padx=(6,0), pady=(8,0))

        # Similarity
        ctk.CTkLabel(frm, text="Similarity (min/max):").grid(row=2, column=0, sticky="w", pady=(8,0))
        self.min_sim = tk.StringVar(value=self._display_percentage(self.current_filters.get('min_sim')))
        self.max_sim = tk.StringVar(value=self._display_percentage(self.current_filters.get('max_sim')))
        ctk.CTkEntry(frm, textvariable=self.min_sim, width=60).grid(row=2, column=1, sticky="w", padx=(6,0), pady=(8,0))
        ctk.CTkEntry(frm, textvariable=self.max_sim, width=60).grid(row=2, column=2, sticky="w", padx=(6,0), pady=(8,0))

        # Show audio dropdown
        ctk.CTkLabel(frm, text="Pokaż: ").grid(row=3, column=0, sticky="w", pady=(8,0))
        self.show_option = tk.StringVar(value=self.current_filters.get('show', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.show_option, values=["Wszystkie", "Wygenerowane", "Niewygenerowane"]).grid(row=3, column=1, columnspan=2, sticky="w", padx=(6,0), pady=(8,0))

        # Hallucination filter
        ctk.CTkLabel(frm, text="Halucynacje: ").grid(row=4, column=0, sticky="w", pady=(8,0))
        self.hal_option = tk.StringVar(value=self.current_filters.get('halucination', 'Wszystkie'))
        ctk.CTkOptionMenu(frm, variable=self.hal_option, values=["Wszystkie", "Tylko halucynacje", "Bez halucynacji", "Nieweryfikowane"]).grid(row=4, column=1, columnspan=2, sticky="w", padx=(6,0), pady=(8,0))

        # Buttons
        btn_frame = ctk.CTkFrame(frm, fg_color="transparent")
        btn_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12,0))
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
        self.show_option.set('Wszystkie')
        self.hal_option.set('Wszystkie')
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
