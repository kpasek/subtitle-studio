import tkinter as tk
import customtkinter as ctk
from ui.shortcuts import ShortcutsWindow


def open_shortcuts_window(app):
    ShortcutsWindow(app)


def show_about_window(app):
    about_win = ctk.CTkToplevel(app)
    about_win.title("O programie")
    about_win.geometry("400x200")
    about_win.transient(app)
    about_win.lift()
    about_win.focus_force()

    ctk.CTkLabel(about_win, text=app.APP_TITLE, font=("", 20, "bold")).pack(pady=10)
    ctk.CTkLabel(about_win, text=f"Wersja: {app.APP_VERSION}").pack()
    ctk.CTkLabel(about_win, text="Autor: Kamil Pasek").pack()

    ctk.CTkButton(about_win, text="Zamknij", command=about_win.destroy).pack(pady=20)


def show_editor_context_menu(app, event):
    menu = tk.Menu(app, tearoff=0)
    menu.add_command(label="Wytnij", command=lambda: app.subtitle_panel.editor.entry.event_generate("<<Cut>>"))
    menu.add_command(label="Kopiuj", command=lambda: app.subtitle_panel.editor.entry.event_generate("<<Copy>>"))
    menu.add_command(label="Wklej", command=lambda: app.subtitle_panel.editor.entry.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Dodaj do imion", command=lambda: add_selected_text_to_names(app))
    menu.tk_popup(event.x_root, event.y_root)


def add_selected_text_to_names(app):
    try:
        selected_text = app.subtitle_panel.editor.entry.selection_get()
        selected_text = selected_text.strip()

        if not selected_text:
            return

        if selected_text in app.names_list:
            app.set_status(f"Ignoruję: Imię '{selected_text}' już jest na liście.")
        else:
            app.names_list.append(selected_text)
            app.mark_as_unsaved()
            app.set_status(f"Dodano '{selected_text}' do listy imion.")
    except Exception:
        # Broader except to swallow selection errors
        pass
