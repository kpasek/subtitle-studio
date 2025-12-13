import customtkinter as ctk
from tkinter import messagebox, simpledialog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studio import SubtitleStudioApp


class NamesManagerWindow(ctk.CTkToplevel):
    def __init__(self, app: 'SubtitleStudioApp'):
        super().__init__(app)
        self.app = app
        self.title("Menedżer Imion")
        self.geometry("400x500")
        self.resizable(False, True)

        self.transient(app)
        self.wait_visibility()
        self.grab_set()

        # Header
        self.header = ctk.CTkFrame(self)
        self.header.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.header, text="Lista imion (do wycinania)", font=("", 14, "bold")).pack(side="left", padx=10)
        ctk.CTkButton(self.header, text="+ Dodaj", width=80, command=self._add_name).pack(side="right", padx=10)

        # List
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._refresh_list()

    def _refresh_list(self):
        # Wyczyść widok
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        # Sortuj alfabetycznie
        sorted_names = sorted(self.app.names_list, key=str.lower)

        for name in sorted_names:
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # Label z imieniem
            lbl = ctk.CTkLabel(row, text=name, anchor="w")
            lbl.pack(side="left", fill="x", expand=True, padx=5)

            # Edycja
            btn_edit = ctk.CTkButton(row, text="✎", width=30, fg_color="gray",
                                     command=lambda n=name: self._edit_name(n))
            btn_edit.pack(side="right", padx=2)

            # Usuwanie
            btn_del = ctk.CTkButton(row, text="🗑", width=30, fg_color="red", hover_color="darkred",
                                    command=lambda n=name: self._delete_name(n))
            btn_del.pack(side="right", padx=2)

    def _add_name(self):
        new_name = ctk.CTkInputDialog(text="Podaj imię:", title="Dodaj imię").get_input()
        if new_name:
            new_name = new_name.strip()
            if new_name:
                if new_name in self.app.names_list:
                    messagebox.showinfo("Info", "To imię już istnieje.", parent=self)
                else:
                    self.app.names_list.append(new_name)
                    self.app.mark_as_unsaved()
                    self._refresh_list()

    def _edit_name(self, old_name):
        new_name = ctk.CTkInputDialog(text="Edytuj imię:", title="Edycja").get_input()
        # InputDialog zwraca None przy anulowaniu, ale pusty string przy OK na pustym polu
        if new_name is not None:
            new_name = new_name.strip()
            if not new_name:
                return  # Puste, ignoruj

            if new_name == old_name:
                return  # Bez zmian

            if new_name in self.app.names_list:
                messagebox.showwarning("Błąd", "Takie imię już istnieje.", parent=self)
                return

            # Zamień
            index = self.app.names_list.index(old_name)
            self.app.names_list[index] = new_name
            self.app.mark_as_unsaved()
            self._refresh_list()

    def _delete_name(self, name):
        if messagebox.askyesno("Potwierdź", f"Usunąć '{name}'?", parent=self):
            self.app.names_list.remove(name)
            self.app.mark_as_unsaved()
            self._refresh_list()