import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import List, TYPE_CHECKING
import time

from app.entity import Line
from app.ai_core import AITask, BUILTIN_TASKS, OllamaService
from app.tooltip import CreateToolTip

if TYPE_CHECKING:
    from app.gui import SubtitleStudioApp

class AITaskRunnerWindow(ctk.CTkToplevel):
    def __init__(self, master: 'SubtitleStudioApp', selected_lines: List[Line]):
        super().__init__(master)
        self.master = master
        self.selected_lines = selected_lines
        self.title("Uruchom Zadania AI")
        self.geometry("700x550")
        
        # Load tasks
        saved_tasks = self.master.global_config.get('custom_ai_tasks', [])
        custom_tasks = [AITask.from_dict(t) for t in saved_tasks]
        self.all_tasks = BUILTIN_TASKS + custom_tasks
        
        self.execution_queue: List[AITask] = []

        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0) # buttons middle
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        ctk.CTkLabel(self, text=f"Wybrano {len(self.selected_lines)} wierszy", font=("", 16)).grid(row=0, column=0, columnspan=3, pady=10)

        # Left: Available Tasks
        ctk.CTkLabel(self, text="Dostępne Zadania").grid(row=0, column=0, sticky="s")
        self.list_available = tk.Listbox(self, selectmode="single", bg="#2b2b2b", fg="white", borderwidth=0, highlightthickness=0)
        self.list_available.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        
        for t in self.all_tasks:
            self.list_available.insert("end", t.name)

        # Middle: Buttons
        frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        frame_btns.grid(row=1, column=1, padx=5)
        
        ctk.CTkButton(frame_btns, text=">", width=40, command=self._add_task).pack(pady=5)
        ctk.CTkButton(frame_btns, text="<", width=40, command=self._remove_task).pack(pady=5)
        ctk.CTkButton(frame_btns, text="^", width=40, command=self._move_up).pack(pady=20)
        ctk.CTkButton(frame_btns, text="v", width=40, command=self._move_down).pack(pady=5)

        # Right: Execution Queue
        ctk.CTkLabel(self, text="Kolejka Wykonywania").grid(row=0, column=2, sticky="s")
        self.list_queue = tk.Listbox(self, selectmode="single", bg="#2b2b2b", fg="white", borderwidth=0, highlightthickness=0)
        self.list_queue.grid(row=1, column=2, sticky="nsew", padx=10, pady=5)

        # Options
        frame_opts = ctk.CTkFrame(self)
        frame_opts.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=10)
        
        ctk.CTkLabel(frame_opts, text="Cel modyfikacji:").pack(side="left", padx=10)
        
        self.target_var = tk.StringVar(value="tts")
        ctk.CTkRadioButton(frame_opts, text="Tekst TTS (Domyślne)", variable=self.target_var, value="tts").pack(side="left", padx=10)
        ctk.CTkRadioButton(frame_opts, text="Tekst Oryginalny (Napisy)", variable=self.target_var, value="text").pack(side="left", padx=10)

        # Info about Ollama
        url = self.master.global_config.get('ollama_url', 'http://localhost:11434')
        model = self.master.global_config.get('ollama_model', 'gemma2:2b')
        ctk.CTkLabel(frame_opts, text=f"Ollama: {url} | Model: {model}", font=("", 10)).pack(side="right", padx=10)

        # Action Buttons
        frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        frame_actions.grid(row=3, column=0, columnspan=3, pady=10)
        
        ctk.CTkButton(frame_actions, text="Anuluj", fg_color="gray", command=self.destroy).pack(side="left", padx=10)
        ctk.CTkButton(frame_actions, text="Uruchom Zadanie", fg_color="green", command=self._run_process).pack(side="left", padx=10)

    def _add_task(self):
        sel = self.list_available.curselection()
        if not sel: return
        idx = sel[0]
        task = self.all_tasks[idx]
        self.execution_queue.append(task)
        self._refresh_queue()

    def _remove_task(self):
        sel = self.list_queue.curselection()
        if not sel: return
        idx = sel[0]
        self.execution_queue.pop(idx)
        self._refresh_queue()
        
    def _move_up(self):
        sel = self.list_queue.curselection()
        if not sel: return
        idx = sel[0]
        if idx > 0:
            self.execution_queue[idx], self.execution_queue[idx-1] = self.execution_queue[idx-1], self.execution_queue[idx]
            self._refresh_queue()
            self.list_queue.selection_set(idx-1)

    def _move_down(self):
        sel = self.list_queue.curselection()
        if not sel: return
        idx = sel[0]
        if idx < len(self.execution_queue) - 1:
            self.execution_queue[idx], self.execution_queue[idx+1] = self.execution_queue[idx+1], self.execution_queue[idx]
            self._refresh_queue()
            self.list_queue.selection_set(idx+1)

    def _refresh_queue(self):
        self.list_queue.delete(0, "end")
        for t in self.execution_queue:
            self.list_queue.insert("end", t.name)

    def _run_process(self):
        if not self.execution_queue:
            messagebox.showwarning("Brak zadań", "Dodaj zadania do kolejki.")
            return

        # Prepare parameters
        target = self.target_var.get()
        tasks = list(self.execution_queue) # clone
        
        ollama_url = self.master.global_config.get('ollama_url', 'http://localhost:11434')
        ollama_model = self.master.global_config.get('ollama_model', 'gemma2:2b')
        
        service = OllamaService(ollama_url, ollama_model)
        
        if not service.check_connection():
            messagebox.showerror("Błąd", f"Nie można połączyć z Ollama pod adresem {ollama_url}.\nUpewnij się, że serwer działa.")
            return

        # Close window and start worker
        self.destroy()
        
        # Define callback logic
        def on_task_finish(count):
            if hasattr(self.master, '_update_subtitle_panel_content'):
                self.master.after(0, self.master._update_subtitle_panel_content)
            messagebox.showinfo("Zakończono", f"Przetworzono {count} wierszy.")

        # Define the job
        self.master.worker.add_task(
            func=run_ai_pipeline,
            lines=self.selected_lines,
            tasks=tasks,
            target_field=target,
            service=service,
            app_ref=self.master, 
            on_complete=on_task_finish
        )


def run_ai_pipeline(lines: List[Line], tasks: List[AITask], target_field: str, service: OllamaService, app_ref, task_ctl=None):
    """
    To jest funkcja uruchamiana w wątku Workera.
    task_ctl - object/dict injected by Worker to check for stop/pause (if supported)
    """
    processed_count = 0
    total = len(lines)
    
    for i, line in enumerate(lines):
        # Determine input text
        current_text = line.get_tts_text() if target_field == "tts" else line.get_text()
        
        if not current_text:
            continue
            
        # Pętla po zadaniach
        try:
            temp_text = current_text
            for task in tasks:
                # Update progress detail
                if app_ref:
                    # Not entirely thread safe to call tk methods directly, but often works for simple status updates 
                    # OR worker handles the callback on main thread. 
                    # Let's assume on_progress callback is used for UI.
                    pass
                
                temp_text = service.process_text(temp_text, task.system_prompt)
            
            # Save result
            if target_field == "tts":
                line.set_tts_text(temp_text)
            else:
                line.set_text(temp_text)
                
            processed_count += 1
            
        except Exception as e:
            print(f"Error processing line {line.uid}: {e}")
            # Continue to next line
            
        # Progress report via yield or return? 
        # The Custom Worker implementation in app/worker.py supports on_progress callback.
        # But we need access to it properly inside the function execution if we want granular updates.
        # The worker implementation provided earlier does not inject 'task_ctl' or 'callback' into the func args freely 
        # unless passed as args.
        # We passed 'on_progress' to add_task, but 'app/worker.py' usually calls this callback 
        # *if the process function calls it* or *manages it*.
        # Looking at worker.py again...
        pass
        
    return processed_count
# Note: The worker.py implementation I read earlier calls process_func(*args, **kwargs). 
# It doesn't auto-inject a progress callback. 
# So I should adapt logic to accept a progress callback if I modify worker, 
# OR use a shared object. 
# Simplest: Update the UI via `app_ref` (using `after` to be safe) inside the loop.

