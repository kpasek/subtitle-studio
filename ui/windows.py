import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import List, Callable
from app.entity import PatternItem
from app.text_processing import apply_remove_patterns
from ui.dialogs import SelectBuiltinDialog


class AboutWindow(ctk.CTkToplevel):
    def __init__(self, master, version):
        super().__init__(master)
        self.title("O programie")
        self.geometry("400x300")
        self.transient(master)

        self.lift()
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))

        ctk.CTkLabel(self, text="Subtitle Studio", font=("Arial", 20, "bold")).pack(pady=20)
        ctk.CTkLabel(self, text=f"Wersja: {version}").pack()
        ctk.CTkLabel(self, text="Autor: Kamil Pasek").pack(pady=5)

        ctk.CTkLabel(self, text="Narzędzie do tworzenia lektora w grach\nz wykorzystaniem AI TTS.",
                     justify="center").pack(pady=20)

        ctk.CTkButton(self, text="OK", command=self.destroy).pack(pady=10)


class RecentProjectsWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.app = master
        self.title("Ostatnie projekty")
        self.geometry("600x400")
        self.transient(master)
        self.grab_set()

        self.lift()
        self.focus_force()

        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(header, text="Historia projektów", font=("", 16, "bold")).pack(side="left", padx=10)
        ctk.CTkButton(header, text="Wyczyść całą listę", fg_color="red", width=120,
                      command=self.clear_all).pack(side="right", padx=5)

        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        self.refresh_list()

        ctk.CTkButton(self, text="Zamknij", command=self.destroy, fg_color="gray").pack(pady=10)

    def refresh_list(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        recent = self.app.global_config.get("recent_projects", [])

        if not recent:
            ctk.CTkLabel(self.scroll, text="Brak ostatnich projektów.", text_color="gray").pack(pady=20)
            return

        for path_str in recent:
            row = ctk.CTkFrame(self.scroll)
            row.pack(fill="x", pady=2)

            btn_open = ctk.CTkButton(row, text=path_str, anchor="w", fg_color="transparent", border_width=1,
                                     text_color=("black", "white"),
                                     command=lambda p=path_str: self.open_and_close(p))
            btn_open.pack(side="left", fill="x", expand=True, padx=2)

            btn_del = ctk.CTkButton(row, text="X", width=30, fg_color="#550000", hover_color="red",
                                    command=lambda p=path_str: self.remove_entry(p))
            btn_del.pack(side="right", padx=2)

    def open_and_close(self, path):
        from pathlib import Path
        self.app.open_project(Path(path))
        self.destroy()

    def remove_entry(self, path):
        recent = self.app.global_config.get("recent_projects", [])
        if path in recent:
            recent.remove(path)
            self.app.save_global_config({"recent_projects": recent})
            self.refresh_list()

    def clear_all(self):
        if messagebox.askyesno("Potwierdź", "Czy na pewno chcesz wyczyścić całą historię?"):
            self.app.save_global_config({"recent_projects": []})
            self.refresh_list()


class PatternWindow(ctk.CTkToplevel):
    def __init__(self, master, title: str, patterns_list: List[PatternItem], pattern_type: str,
                 on_close_callback: Callable):
        super().__init__(master)
        self.master_app = master
        self.title(title)
        self.geometry("600x500")
        self.transient(master)
        self.grab_set()

        # Wymuszamy pojawienie się na wierzchu
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))

        self.patterns = patterns_list
        self.pattern_type = pattern_type
        self.on_close_callback = on_close_callback

        top_frame = ctk.CTkFrame(self)
        top_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(top_frame, text="Dodaj Nowy", command=self.add_new).pack(side="left", padx=5)
        ctk.CTkButton(top_frame, text="Wybierz z wbudowanych", command=self.add_builtin).pack(side="left", padx=5)
        ctk.CTkButton(top_frame, text="Zamknij", fg_color="gray", command=self.close).pack(side="right", padx=5)

        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        self.refresh_list()

    def refresh_list(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        if not self.patterns:
            ctk.CTkLabel(self.scroll, text="Brak wzorców.").pack(pady=20)
            return

        for idx, pat in enumerate(self.patterns):
            row = ctk.CTkFrame(self.scroll)
            row.pack(fill="x", pady=2)

            var = tk.BooleanVar(value=pat.enabled)
            cb = ctk.CTkCheckBox(row, text="", width=20, variable=var,
                                 command=lambda p=pat, v=var: self.toggle_pattern(p, v))
            cb.pack(side="left", padx=5)

            info = f"[{pat.name}]" if pat.name else f"RegEx: {pat.pattern}"
            lbl = ctk.CTkLabel(row, text=info, anchor="w")
            lbl.pack(side="left", padx=5, fill="x", expand=True)

            if pat.replacement:
                ctk.CTkLabel(row, text=f"-> '{pat.replacement}'", text_color="gray").pack(side="left", padx=5)

            ctk.CTkButton(row, text="Edytuj", width=50, command=lambda p=pat: self.edit_pattern(p)).pack(side="right",
                                                                                                         padx=2)
            ctk.CTkButton(row, text="Usuń", width=50, fg_color="red",
                          command=lambda p=pat: self.delete_pattern(p)).pack(side="right", padx=2)

            if idx > 0:
                ctk.CTkButton(row, text="▲", width=30, command=lambda i=idx: self.move_pattern(i, -1)).pack(
                    side="right", padx=1)
            if idx < len(self.patterns) - 1:
                ctk.CTkButton(row, text="▼", width=30, command=lambda i=idx: self.move_pattern(i, 1)).pack(side="right",
                                                                                                           padx=1)

    def toggle_pattern(self, pat, var):
        pat.enabled = var.get()
        self.master_app.project.save_data()

    def move_pattern(self, index, direction):
        new_index = index + direction
        if 0 <= new_index < len(self.patterns):
            self.patterns[index], self.patterns[new_index] = self.patterns[new_index], self.patterns[index]
            self.master_app.project.save_data()
            self.refresh_list()

    def delete_pattern(self, pat):
        if messagebox.askyesno("Potwierdź", "Usunąć ten wzorzec?"):
            self.patterns.remove(pat)
            self.master_app.project.save_data()
            self.refresh_list()

    def add_new(self):
        from audio.pattern_editor import PatternEditorWindow
        def on_save(name, pattern, repl):
            # Tu tworzymy nowy obiekt, a nie używamy callbacku app
            item = PatternItem(None, name, pattern, repl, True, self.pattern_type)
            self.patterns.append(item)
            self.master_app.project.save_data()
            self.refresh_list()

        # Tworzymy okno edytora jako dziecko tego okna (PatternWindow)
        win = PatternEditorWindow(self, self.pattern_type, on_save, None)
        win.wait_visibility()
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)  # MUSI być nad oknem listy

    def edit_pattern(self, pat):
        from audio.pattern_editor import PatternEditorWindow
        def on_save(name, pattern, repl):
            pat.name = name
            pat.pattern = pattern
            pat.replacement = repl
            self.master_app.project.save_data()
            self.refresh_list()

        win = PatternEditorWindow(self, self.pattern_type, on_save, pat)
        win.wait_visibility()
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)

    def add_builtin(self):
        def on_selected(items):
            for item in items:
                new_item = PatternItem(str(item.id), item.name, item.pattern, item.replacement, True, item.type)
                self.patterns.append(new_item)
            self.master_app.project.save_data()
            self.refresh_list()

        win = SelectBuiltinDialog(self, self.pattern_type, on_selected)
        win.wait_visibility()
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)

    def close(self):
        self.on_close_callback()
        self.destroy()


class AppliedPatternsPreviewWindow(ctk.CTkToplevel):
    def __init__(self, master, lines, patterns):
        super().__init__(master)
        self.title("Podgląd zastosowania wzorców")
        self.geometry("1000x600")
        self.transient(master)
        self.lift()
        self.focus_force()

        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=6, bg="#2b2b2b")
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        f1 = ctk.CTkFrame(paned)
        paned.add(f1)
        ctk.CTkLabel(f1, text="Oryginał (Edytor)", font=("bold", 12)).pack(pady=5)
        txt1 = ctk.CTkTextbox(f1, wrap="none")
        txt1.pack(fill="both", expand=True, padx=2, pady=2)

        f2 = ctk.CTkFrame(paned)
        paned.add(f2)
        ctk.CTkLabel(f2, text="Po zastosowaniu wzorców (To zostanie zatwierdzone)", font=("bold", 12),
                     text_color="orange").pack(pady=5)
        txt2 = ctk.CTkTextbox(f2, wrap="none")
        txt2.pack(fill="both", expand=True, padx=2, pady=2)

        orig_content = []
        clean_content = []

        for i, line in enumerate(lines):
            orig_content.append(f"{i + 1:03} | {line.text}")
            clean = apply_remove_patterns([line.text], patterns)
            res = clean[0] if clean else "[USUNIĘTA]"
            clean_content.append(f"{i + 1:03} | {res}")

        txt1.insert("1.0", "\n".join(orig_content))
        txt1.configure(state="disabled")

        txt2.insert("1.0", "\n".join(clean_content))
        txt2.configure(state="disabled")

        # Sync
        txt1._textbox.configure(yscrollcommand=lambda *a: (txt1._scrollbar.set(*a), txt2.yview_moveto(a[0])))
        txt2._textbox.configure(yscrollcommand=lambda *a: (txt2._scrollbar.set(*a), txt1.yview_moveto(a[0])))

        def mouse_scroll(event):
            if hasattr(event, "delta") and event.delta:  # Windows
                delta = int(-1 * (event.delta / 120))
                txt1.yview_scroll(delta, "units")
                txt2.yview_scroll(delta, "units")
                return "break"

        txt1.bind("<MouseWheel>", mouse_scroll)
        txt2.bind("<MouseWheel>", mouse_scroll)