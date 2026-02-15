import re
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Optional

from app.entity import PatternItem
from app.patterns import apply_processing

if TYPE_CHECKING:
    from studio import SubtitleStudioApp


class PatternManagerWindow(ctk.CTkToplevel):
    """
    Osobne okno do zarządzania wzorcami.
    Zoptymalizowane przy użyciu ttk.Treeview dla wysokiej wydajności przy dużej liczbie wzorców.
    Wersja Compact z naprawionym renderowaniem wierszy (rowheight).
    """

    def __init__(self, master: 'SubtitleStudioApp'):
        super().__init__(master)
        self.master_app = master
        self.title("Menedżer Wzorców")
        self.geometry("1100x750")
        self.transient(master)

        # Konfiguracja stylu dla Treeview (aby pasował do ciemnego motywu)
        self._setup_treeview_style()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Zmienna do wyszukiwania
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)

        self._create_layout()
        self.refresh_ui()

    def _setup_treeview_style(self):
        """Konfiguruje wygląd ttk.Treeview, aby pasował do CustomTkinter."""
        style = ttk.Style()
        style.theme_use("clam")

        # Pobranie kolorów z motywu ctk (przybliżone dla trybu dark/light)
        bg_color = "#2b2b2b"  # Ciemne tło
        fg_color = "#ffffff"  # Biały tekst
        field_bg = "#2b2b2b"
        selected_bg = "#1f538d"  # Kolor zaznaczenia (niebieski ctk)

        if ctk.get_appearance_mode() == "Light":
            bg_color = "#ffffff"
            fg_color = "#000000"
            field_bg = "#ffffff"

        # POPRAWKA: Dodano 'rowheight=30' aby zapobiec nachodzeniu wierszy na siebie
        style.configure("Treeview",
                        background=bg_color,
                        foreground=fg_color,
                        fieldbackground=field_bg,
                        borderwidth=0,
                        font=("Segoe UI", 10),
                        rowheight=30)  # <-- Kluczowa zmiana naprawiająca overlap

        style.configure("Treeview.Heading",
                        background="#3a3a3a",
                        foreground="white",
                        relief="flat",
                        font=("Segoe UI", 10, "bold"))

        style.map("Treeview",
                  background=[("selected", selected_bg)],
                  foreground=[("selected", "white")])

    def _create_layout(self):
        # === LEWA KOLUMNA: WŁASNE WZORCE ===
        self.left_frame = ctk.CTkFrame(self)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.left_frame.grid_columnconfigure(0, weight=1)
        self.left_frame.grid_rowconfigure(2, weight=1)  # Tree Remove
        self.left_frame.grid_rowconfigure(5, weight=1)  # Tree Replace

        # -- Wyszukiwarka (Compact) --
        search_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        search_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 2))

        ctk.CTkLabel(search_frame, text="🔍", width=20).pack(side="left", padx=(0, 2))
        self.ent_search = ctk.CTkEntry(search_frame, textvariable=self.search_var, placeholder_text="Filtruj...",
                                       height=28)
        self.ent_search.pack(side="left", fill="x", expand=True)

        # -- Sekcja Custom Remove --
        ctk.CTkLabel(self.left_frame, text="Twoje wzorce wycinające (Napisy)", font=("", 13, "bold")).grid(
            row=1, column=0, sticky="w", padx=5, pady=(2, 2))

        # === ZATWIERDŹ ZMIANY (Button) ===
        ctk.CTkButton(search_frame, text="Zatwierdź zmiany", 
                      command=lambda: apply_processing(self.master_app),
                      fg_color="#2E8B57", hover_color="#1E613B", 
                      height=28).pack(side="right", padx=5)

        self.tree_custom_remove = self._create_treeview(self.left_frame, ["Status", "Wzorzec"])
        self.tree_custom_remove.grid(row=2, column=0, sticky="nsew", padx=5, pady=0)
        self._bind_tree_events(self.tree_custom_remove, is_custom=True, list_ref=self.master_app.custom_remove)

        # Panel przycisków Remove
        self._create_action_buttons(self.left_frame, row=3,
                                    tree=self.tree_custom_remove,
                                    list_ref=self.master_app.custom_remove,
                                    add_cmd=self.master_app.open_add_remove_pattern,
                                    clear_type='remove')

        # -- Sekcja Custom Replace --
        ctk.CTkLabel(self.left_frame, text="Twoje wzorce podmieniające (TTS)", font=("", 13, "bold")).grid(
            row=4, column=0, sticky="w", padx=5, pady=(10, 2))

        self.tree_custom_replace = self._create_treeview(self.left_frame, ["Status", "Wzorzec"])
        self.tree_custom_replace.grid(row=5, column=0, sticky="nsew", padx=5, pady=0)
        self._bind_tree_events(self.tree_custom_replace, is_custom=True, list_ref=self.master_app.custom_replace)

        # Panel przycisków Replace
        self._create_action_buttons(self.left_frame, row=6,
                                    tree=self.tree_custom_replace,
                                    list_ref=self.master_app.custom_replace,
                                    add_cmd=self.master_app.open_add_replace_pattern,
                                    clear_type='replace')

        # === PRAWA KOLUMNA: BIBLIOTEKA WBUDOWANYCH ===
        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.right_frame.grid_columnconfigure(0, weight=1)

        # POPRAWKA: Ustawienie wag dla wierszy z tabelami (1 i 4), aby się poprawnie rozciągały
        self.right_frame.grid_rowconfigure(1, weight=1)
        self.right_frame.grid_rowconfigure(4, weight=1)

        # -- Builtin Remove --
        ctk.CTkLabel(self.right_frame, text="Biblioteka: Wycinanie", font=("", 13, "bold")).grid(
            row=0, column=0, sticky="w", padx=5, pady=(5, 2))

        self.tree_builtin_remove = self._create_treeview(self.right_frame, ["Wzorzec"])
        self.tree_builtin_remove.grid(row=1, column=0, sticky="nsew", padx=5, pady=0)
        self._bind_tree_events(self.tree_builtin_remove, is_custom=False, target_type='remove')

        # Przycisk dodawania
        ctk.CTkButton(self.right_frame, text="➕ Dodaj do moich", height=24,
                      command=lambda: self._add_selected_builtin(self.tree_builtin_remove, 'remove')).grid(
            row=2, column=0, sticky="ew", padx=5, pady=5)

        # -- Builtin Replace --
        ctk.CTkLabel(self.right_frame, text="Biblioteka: Podmiana", font=("", 13, "bold")).grid(
            row=3, column=0, sticky="w", padx=5, pady=(5, 2))

        self.tree_builtin_replace = self._create_treeview(self.right_frame, ["Wzorzec"])
        self.tree_builtin_replace.grid(row=4, column=0, sticky="nsew", padx=5, pady=0)
        self._bind_tree_events(self.tree_builtin_replace, is_custom=False, target_type='replace')

        # Przycisk dodawania
        ctk.CTkButton(self.right_frame, text="➕ Dodaj do moich", height=24,
                      command=lambda: self._add_selected_builtin(self.tree_builtin_replace, 'replace')).grid(
            row=5, column=0, sticky="ew", padx=5, pady=5)

    def _create_treeview(self, parent, columns):
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")

        if "Status" in columns:
            tree.heading("Status", text="Stan")
            tree.column("Status", width=40, anchor="center", stretch=False)

        tree.heading("Wzorzec", text="Opis / Wzorzec")
        tree.column("Wzorzec", anchor="w")

        return tree

    def _create_action_buttons(self, parent, row, tree, list_ref, add_cmd, clear_type):
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=row, column=0, sticky="ew", padx=5, pady=2)

        # Mniejsze przyciski
        ctk.CTkButton(btn_frame, text="Nowy", width=50, height=24, command=add_cmd).pack(side="left", padx=2)

        ctk.CTkButton(btn_frame, text="Edytuj", width=50, height=24,
                      command=lambda: self._edit_selected(tree, list_ref)).pack(side="left", padx=2)

        ctk.CTkButton(btn_frame, text="On/Off", width=50, height=24,
                      command=lambda: self._toggle_selected(tree, list_ref)).pack(side="left", padx=2)

        ctk.CTkButton(btn_frame, text="Usuń", width=50, height=24, fg_color="red", hover_color="darkred",
                      command=lambda: self._delete_selected(tree, list_ref)).pack(side="right", padx=2)

        ctk.CTkButton(btn_frame, text="Czyść", width=50, height=24, fg_color="gray",
                      command=lambda: self._clear_all(clear_type)).pack(side="right", padx=2)

    def _on_search_change(self, *args):
        if hasattr(self, '_search_job') and self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(200, self.refresh_ui)

    def refresh_ui(self):
        """Przerysowuje wszystkie listy."""
        search = self.search_var.get()

        self._populate_tree(self.tree_custom_remove, self.master_app.custom_remove, is_custom=True, search=search)
        self._populate_tree(self.tree_custom_replace, self.master_app.custom_replace, is_custom=True, search=search)

        self._populate_tree(self.tree_builtin_remove, self.master_app.builtin_remove, is_custom=False, search=search)
        self._populate_tree(self.tree_builtin_replace, self.master_app.builtin_replace, is_custom=False, search=search)

    def _get_display_text(self, p: PatternItem) -> str:
        """Tworzy tekst do wyświetlenia w liście (bezpiecznie)."""
        name_val = p.name
        if not isinstance(name_val, str):
            name_val = None

        display_rule = f"[{p.pattern}] ➜ [{p.replace}]"

        if name_val and name_val.strip():
            return f"{name_val}   |   {display_rule}"
        return display_rule

    def _populate_tree(self, tree, data_list, is_custom, search=""):
        for item in tree.get_children():
            tree.delete(item)

        # Decyzja o trybie wyszukiwania
        search_regex = None
        use_simple_search = True
        
        if search:
            # Jeśli user użył znaków kotwic, zakładamy świadomy Regex
            if search.startswith('^') or search.endswith('$'):
                use_simple_search = False
                try:
                    search_regex = re.compile(search, re.IGNORECASE)
                except re.error:
                    # Błędny regex -> fallback to simple
                    use_simple_search = True
            
            # W przeciwnym razie prosty tekst

        for i, p in enumerate(data_list):
            try:
                display_text = self._get_display_text(p)
                
                # Filtrowanie
                if search:
                    name_str = str(p.name) if p.name else ""
                    pat_str = str(p.pattern) if p.pattern else ""
                    rep_str = str(p.replace) if p.replace else ""
                    
                    if use_simple_search:
                        # Proste wyszukiwanie (containment)
                        s_lower = search.lower()
                        if (s_lower not in pat_str.lower() and 
                            s_lower not in rep_str.lower() and 
                            s_lower not in name_str.lower()):
                            continue
                    elif search_regex:
                        # Wyszukiwanie Regex
                        if not (search_regex.search(pat_str) or 
                                search_regex.search(rep_str) or 
                                search_regex.search(name_str)):
                            continue

                item_iid = str(id(p))

                if is_custom:
                    status_icon = "✅" if p.enabled else "❌"
                    tags = ('disabled',) if not p.enabled else ()
                    tree.insert("", "end", iid=item_iid, values=(status_icon, display_text), tags=tags)
                else:
                    tree.insert("", "end", iid=item_iid, values=(display_text,))
            except Exception as e:
                from app.logger import Logger
                Logger.error(f"Error displaying pattern item {i}: {e}")
                continue

        tree.tag_configure('disabled', foreground='gray')

    # --- OBSŁUGA ZDARZEŃ ---

    def _bind_tree_events(self, tree, is_custom, list_ref=None, target_type=None):
        if is_custom:
            tree.bind("<Double-1>", lambda e: self._edit_selected(tree, list_ref))
            tree.bind("<Delete>", lambda e: self._delete_selected(tree, list_ref))
        else:
            tree.bind("<Double-1>", lambda e: self._add_selected_builtin(tree, target_type))

    def _find_item_by_iid(self, iid, data_list) -> Optional[PatternItem]:
        for p in data_list:
            if str(id(p)) == iid:
                return p
        return None

    def _edit_selected(self, tree, list_ref):
        selected = tree.selection()
        if not selected: return
        iid = selected[0]
        item = self._find_item_by_iid(iid, list_ref)
        if item:
            self.master_app.open_edit_pattern(item, list_ref)

    def _toggle_selected(self, tree, list_ref):
        selected = tree.selection()
        if not selected: return
        iid = selected[0]
        item = self._find_item_by_iid(iid, list_ref)
        if item:
            item.enabled = not item.enabled
            self.master_app.mark_as_unsaved()
            self.refresh_ui()

    def _delete_selected(self, tree, list_ref):
        selected = tree.selection()
        if not selected: return
        iid = selected[0]
        item = self._find_item_by_iid(iid, list_ref)
        if item:
            list_ref.remove(item)
            self.master_app.mark_as_unsaved()
            self.refresh_ui()

    def _clear_all(self, clear_type):
        self.master_app._clear_custom_list(clear_type)

    def _add_selected_builtin(self, tree, target_type):
        selected = tree.selection()
        if not selected: return
        iid = selected[0]

        source_list = self.master_app.builtin_remove if target_type == 'remove' else self.master_app.builtin_replace
        item = self._find_item_by_iid(iid, source_list)

        if item:
            new_item = PatternItem(
                pattern=item.pattern,
                replace=item.replace,
                case_sensitive=item.case_sensitive,
                name=item.name if isinstance(item.name, str) else None,
                enabled=True
            )

            target_list = self.master_app.custom_remove if target_type == 'remove' else self.master_app.custom_replace
            target_list.append(new_item)

            self.master_app.mark_as_unsaved()
            self.refresh_ui()