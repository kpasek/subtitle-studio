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
        self.geometry("900x700")
        
        # Load tasks initial
        self.all_tasks = []
        self._load_tasks()
        self.execution_queue: List[AITask] = []

        self._setup_ui()

    def _load_tasks(self):
        saved_tasks = self.master.global_config.get('custom_ai_tasks', [])
        custom_tasks = [AITask.from_dict(t) for t in saved_tasks]
        self.all_tasks = BUILTIN_TASKS + custom_tasks

    def _refresh_available_list(self):
        self._load_tasks()
        self.list_available.delete(0, "end")
        for t in self.all_tasks:
            self.list_available.insert("end", t.name)

    def _open_manager(self):
        from ui.ai_task_manager import AITaskManagerWindow
        win = AITaskManagerWindow(self.master)
        # Refresh logic after close
        def on_close():
             self._refresh_available_list()
             win.destroy()
             
        win.protocol("WM_DELETE_WINDOW", on_close)

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0) # buttons middle
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(2, weight=1) # queue list expands

        # Header
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.grid(row=0, column=0, columnspan=3, pady=5, sticky="ew")
        
        ctk.CTkLabel(top_frame, text=f"Wybrano {len(self.selected_lines)} wierszy", font=("", 16)).pack(side="top", pady=2)
        
        btn_manage = ctk.CTkButton(top_frame, text="Zarządzaj Zadaniami", width=140, command=self._open_manager)
        btn_manage.pack(side="top", pady=5)

        # Left: Available Tasks
        ctk.CTkLabel(self, text="Dostępne Zadania").grid(row=1, column=0, sticky="s")
        self.list_available = tk.Listbox(self, selectmode="single", bg="#2b2b2b", fg="white", borderwidth=0, highlightthickness=0)
        self.list_available.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        
        self._refresh_available_list()

        # Middle: Buttons
        frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        frame_btns.grid(row=2, column=1, padx=5)
        
        ctk.CTkButton(frame_btns, text=">", width=40, command=self._add_task).pack(pady=5)
        ctk.CTkButton(frame_btns, text="<", width=40, command=self._remove_task).pack(pady=5)
        ctk.CTkButton(frame_btns, text="^", width=40, command=self._move_up).pack(pady=20)
        ctk.CTkButton(frame_btns, text="v", width=40, command=self._move_down).pack(pady=5)

        # Right: Execution Queue
        ctk.CTkLabel(self, text="Kolejka Wykonywania").grid(row=1, column=2, sticky="s")
        self.list_queue = tk.Listbox(self, selectmode="single", bg="#2b2b2b", fg="white", borderwidth=0, highlightthickness=0)
        self.list_queue.grid(row=2, column=2, sticky="nsew", padx=10, pady=5)

        # Options
        frame_opts = ctk.CTkFrame(self)
        frame_opts.grid(row=3, column=0, columnspan=3, sticky="ew", padx=10, pady=10)
        
        ctk.CTkLabel(frame_opts, text="Cel modyfikacji:").pack(side="left", padx=10)
        
        self.target_var = tk.StringVar(value="tts")
        ctk.CTkRadioButton(frame_opts, text="Tekst TTS (Domyślne)", variable=self.target_var, value="tts").pack(side="left", padx=10)
        ctk.CTkRadioButton(frame_opts, text="Tekst Oryginalny (Napisy)", variable=self.target_var, value="text").pack(side="left", padx=10)

        # Info about Ollama
        url = self.master.global_config.get('ollama_url', 'http://localhost:11434')
        model = self.master.global_config.get('ollama_model', 'gemma2:2b')
        ctk.CTkLabel(frame_opts, text=f"Ollama: {url} | Model: {model}", font=("", 10)).pack(side="right", padx=10)

        # Action Buttons
        self.frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_actions.grid(row=4, column=0, columnspan=3, pady=10)
        
        self.btn_cancel = ctk.CTkButton(self.frame_actions, text="Zamknij", fg_color="gray", command=self.destroy)
        self.btn_cancel.pack(side="left", padx=10)
        
        self.btn_run = ctk.CTkButton(self.frame_actions, text="Uruchom Zadanie", fg_color="green", command=self._run_process)
        self.btn_run.pack(side="left", padx=10)

        # Progress Bar Area (Initially Hidden)
        self.frame_progress = ctk.CTkFrame(self)
        # Grid row 5
        self.progress_bar = ctk.CTkProgressBar(self.frame_progress, width=600)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)
        
        self.lbl_progress = ctk.CTkLabel(self.frame_progress, text="Oczekiwanie na start...")
        self.lbl_progress.pack(pady=5)


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

        # Switch UI to Progress Mode
        self.frame_actions.grid_remove() # Hide buttons
        self.frame_progress.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")
        
        # Setup Progress Bar
        total_lines = len(self.selected_lines)
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        
        # Callback for worker updates
        def progress_callback(current, total, message):
            # Run on UI thread
            def _update():
                if not self.winfo_exists(): return
                ratio = current / total if total > 0 else 0
                self.progress_bar.set(ratio)
                self.lbl_progress.configure(text=f"{message} ({current}/{total})")
                
                # If complete, show close button
                if current >= total:
                   self.lbl_progress.configure(text="Zakończono przetwarzanie.")
                   btn_close = ctk.CTkButton(self.frame_progress, text="Zamknij", fg_color="green", command=self.destroy)
                   btn_close.pack(pady=5)
                   
                   # Trigger refresh in main window
                   if hasattr(self.master, '_update_subtitle_panel_content'):
                        self.master._update_subtitle_panel_content()

            self.after(0, _update)

        # Define the job
        self.master.worker.add_task(
            func=run_ai_pipeline,
            lines=self.selected_lines,
            tasks=tasks,
            target_field=target,
            service=service,
            app_ref=self.master, 
            progress_callback=progress_callback
        )


def run_ai_pipeline(lines: List[Line], tasks: List[AITask], target_field: str, service: OllamaService, app_ref, progress_callback=None):
    """
    To jest funkcja uruchamiana w wątku Workera.
    """
    processed_count = 0
    total = len(lines)
    
    # Notify start
    if progress_callback: progress_callback(0, total, "Startowanie...")
    
    for i, line in enumerate(lines):
        # Notify progress
        if progress_callback: progress_callback(i, total, f"Przetwarzanie linii {line.uid}")

        # Determine input text
        current_text = line.get_tts_text() if target_field == "tts" else line.get_text()
        
        if not current_text:
            continue
            
        try:
            temp_text = current_text
            for task in tasks:
                temp_text = service.process_text(temp_text, task.system_prompt)
            
            # Update Object
            if target_field == "tts":
                line.set_tts_text(temp_text)
            else:
                line.set_text(temp_text)
            
            # Save to CSV immediately (Persistence)
            if hasattr(app_ref, 'io_manager'):
                # status_flag should be preserved or updated? Let's just update text.
                # update_line_in_csv(self, uid, text, tts_text, status_flag, start_time, end_time, character_id, audio_path)
                app_ref.io_manager.update_line_in_csv(
                    line.uid, 
                    line.text, 
                    line.tts_text, 
                    line.status_flag, 
                    line.start_time, 
                    line.end_time, 
                    line.character_id, 
                    line.audio_path
                )

            processed_count += 1
            
        except Exception as e:
            print(f"Error processing line {line.uid}: {e}")
            
    # Final update
    if progress_callback: progress_callback(total, total, "Zakończono")
        
    return processed_count
# logic ends

