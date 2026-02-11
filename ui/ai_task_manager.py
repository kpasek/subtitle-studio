import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import List
import copy

from app.ai_core import AITask, BUILTIN_TASKS
from app.tooltip import CreateToolTip

class AITaskManagerWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.title("Menedżer Zadań AI")
        self.geometry("800x600")
        
        # Load custom tasks from config
        self.custom_tasks: List[AITask] = []
        saved_tasks = self.master.global_config.get('custom_ai_tasks', [])
        for t_data in saved_tasks:
            try:
                self.custom_tasks.append(AITask.from_dict(t_data))
            except:
                pass

        self.all_tasks = BUILTIN_TASKS + self.custom_tasks
        self.selected_task: AITask | None = None

        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self):
        # Layout: Left (List), Right (Details)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left Panel
        self.frame_left = ctk.CTkFrame(self, width=250)
        self.frame_left.grid(row=0, column=0, sticky="ns", padx=10, pady=10)
        self.frame_left.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(self.frame_left, text="Dostępne Zadania", font=("", 14, "bold")).pack(pady=5)
        
        self.scroll_list = ctk.CTkScrollableFrame(self.frame_left)
        self.scroll_list.pack(fill="both", expand=True, padx=5, pady=5)

        btn_add = ctk.CTkButton(self.frame_left, text="+ Nowe Zadanie", command=self._add_task)
        btn_add.pack(pady=10, padx=10, fill="x")

        # Right Panel
        self.frame_right = ctk.CTkFrame(self)
        self.frame_right.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        
        ctk.CTkLabel(self.frame_right, text="Szczegóły Zadania", font=("", 14, "bold")).pack(pady=5)

        self.entry_name = ctk.CTkEntry(self.frame_right, placeholder_text="Nazwa zadania")
        self.entry_name.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(self.frame_right, text="System Prompt:", anchor="w").pack(fill="x", padx=10)
        self.text_prompt = ctk.CTkTextbox(self.frame_right, height=300)
        self.text_prompt.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.lbl_readonly = ctk.CTkLabel(self.frame_right, text="Tylko do odczytu (wbudowane)", text_color="orange")
        # Don't pack initially

        # Buttons
        self.btn_save = ctk.CTkButton(self.frame_right, text="Zapisz zmiany", command=self._save_current_task, fg_color="green")
        self.btn_save.pack(side="right", padx=10, pady=10)
        
        self.btn_delete = ctk.CTkButton(self.frame_right, text="Usuń", command=self._delete_current_task, fg_color="red")
        self.btn_delete.pack(side="right", padx=10, pady=10)

    def _refresh_list(self):
        # Clear list
        for widget in self.scroll_list.winfo_children():
            widget.destroy()

        self.all_tasks = BUILTIN_TASKS + self.custom_tasks

        for task in self.all_tasks:
            btn = ctk.CTkButton(
                self.scroll_list, 
                text=f"{task.name} {'(Wbudowane)' if task.is_readonly else ''}",
                command=lambda t=task: self._select_task(t),
                fg_color="gray" if task == self.selected_task else "transparent",
                text_color="white", # assume dark theme by default or let ctk handle
                anchor="w"
            )
            # Override default button color behavior for "list item" look
            if task == self.selected_task:
                btn.configure(fg_color=["#3B8ED0", "#1F6AA5"]) 
            else:
                btn.configure(fg_color="transparent")
                
            btn.pack(fill="x", padx=2, pady=2)

    def _select_task(self, task: AITask):
        self.selected_task = task
        self._refresh_list() # To update selection highlight
        
        self.entry_name.delete(0, "end")
        self.entry_name.insert(0, task.name)
        
        self.text_prompt.delete("1.0", "end")
        self.text_prompt.insert("1.0", task.system_prompt)

        if task.is_readonly:
            self.entry_name.configure(state="disabled")
            self.text_prompt.configure(state="disabled")
            self.btn_save.configure(state="disabled")
            self.btn_delete.configure(state="disabled")
            self.lbl_readonly.pack(pady=5)
        else:
            self.entry_name.configure(state="normal")
            self.text_prompt.configure(state="normal")
            self.btn_save.configure(state="normal")
            self.btn_delete.configure(state="normal")
            self.lbl_readonly.pack_forget()

    def _add_task(self):
        new_task = AITask(name="Nowe zadanie", system_prompt="Opisz tutaj rolę modelu...")
        self.custom_tasks.append(new_task)
        self._save_to_config()
        self._select_task(new_task)

    def _save_current_task(self):
        if not self.selected_task or self.selected_task.is_readonly:
            return

        self.selected_task.name = self.entry_name.get()
        self.selected_task.system_prompt = self.text_prompt.get("1.0", "end").strip()
        
        self._save_to_config()
        self._refresh_list()
        messagebox.showinfo("Zapisano", "Zadanie zostało zaktualizowane.")

    def _delete_current_task(self):
        if not self.selected_task or self.selected_task.is_readonly:
            return
        
        if messagebox.askyesno("Potwierdzenie", "Czy na pewno usunąć to zadanie?"):
            self.custom_tasks.remove(self.selected_task)
            self.selected_task = None
            self._save_to_config()
            self._refresh_list()
            # Clear inputs
            self.entry_name.delete(0, "end")
            self.text_prompt.delete("1.0", "end")

    def _save_to_config(self):
        # Serializacja zadań
        data = [t.to_dict() for t in self.custom_tasks]
        self.master.global_config['custom_ai_tasks'] = data
        self.master.save_global_config(self.master.global_config)
