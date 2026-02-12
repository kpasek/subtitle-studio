import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import List, TYPE_CHECKING
import time
import threading

from app.builtin_tasks import BUILTIN_TASKS, AITask
from app.entity import Line
from app.ai_core import OllamaService
from app.io import update_lines_in_csv

if TYPE_CHECKING:
    from app.gui import SubtitleStudioApp

class AIControl:
    def __init__(self):
        self._paused = threading.Event()
        self._paused.set() # Start running (True = running, False = paused)
        self._stopped = threading.Event()

    @property
    def is_paused(self):
        return not self._paused.is_set()

    @property
    def is_stopped(self):
        return self._stopped.is_set()

    def pause(self):
        self._paused.clear()

    def resume(self):
        self._paused.set()

    def stop(self):
        self._stopped.set()
        self.resume() # Ensure we don't hang on pause

    def wait_if_paused(self):
        self._paused.wait()

from app.project import save_project, set_project_config
from pathlib import Path
import shutil
import datetime

class AITaskRunnerWindow(ctk.CTkToplevel):
    def __init__(self, master: 'SubtitleStudioApp', selected_lines: List[Line], is_global: bool = False):
        super().__init__(master)
        self.master = master
        self.selected_lines = selected_lines
        self.is_global = is_global
        self.title("Uruchom Zadania SI")
        self.geometry("1000x700")
        
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

        self.skip_processed_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame_opts, text="Pomiń przetworzone (AI)", variable=self.skip_processed_var).pack(side="left", padx=10)

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
        
        # Control buttons for active task
        self.frame_progress_controls = ctk.CTkFrame(self.frame_progress, fg_color="transparent")
        self.frame_progress_controls.pack(pady=5)
        
        self.btn_pause = ctk.CTkButton(self.frame_progress_controls, text="Pauza", command=self._toggle_pause, width=100)
        self.btn_pause.pack(side="left", padx=5)
        
        self.btn_stop_task = ctk.CTkButton(self.frame_progress_controls, text="Anuluj", command=self._cancel_task, fg_color="red", width=100)
        self.btn_stop_task.pack(side="left", padx=5)
        
        # Select and add first item if available
        if self.list_available.size() > 0:
            self.list_available.selection_set(0)
            self._add_task()
        
        self.control = AIControl()

    def _toggle_pause(self):
        if self.control.is_paused:
            self.control.resume()
            self.btn_pause.configure(text="Pauza")
        else:
            self.control.pause()
            self.btn_pause.configure(text="Wznów")
            
    def _cancel_task(self):
        # Pause explicitly if running
        was_paused = self.control.is_paused
        
        if not was_paused:
            self.control.pause()
            
        if messagebox.askyesno("Anulowanie", "Czy na pewno chcesz przerwać zadanie?", parent=self):
            self.control.stop()
            self.lbl_progress.configure(text="Zatrzymywanie...")
            self.btn_pause.configure(state="disabled")
            self.btn_stop_task.configure(state="disabled")
        else:
            # Restore state if user cancelled the cancellation
            if not was_paused:
                self.control.resume()

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

    def _reset_to_start(self):
        """Resets the UI to initial state, hiding progress and showing options."""
        self.frame_progress.grid_remove()
        self.frame_actions.grid()
        
        # Hide result buttons if they exist
        if hasattr(self, 'frame_result_buttons'):
            self.frame_result_buttons.pack_forget()
            for widget in self.frame_result_buttons.winfo_children():
                widget.destroy()

    def _run_process(self):
        if not self.execution_queue:
            return

        # Jeśli globalny przebieg - zrób backup i nowy plik
        if self.is_global and self.master.loaded_path:
            try:
                current_p = Path(self.master.loaded_path)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{current_p.stem}_backup_{timestamp}{current_p.suffix}"
                backup_path = current_p.parent / backup_name
                
                # Copy current file to backup
                shutil.copy2(current_p, backup_path)
                print(f"Created backup at {backup_path}")
                
                # For processing we continue on current file, but first save any pending state
                # The user requirement: "create a new file ... and assign as current".
                # Usually "backup" implies the OLD state is saved aside, and we work on the main file.
                # OR we create a "v2" file and switch to it. 
                # "tworzyć nowy plik z danymi (taki backup) oraz przypisaywać jako aktualny plik"
                # This phrasing is slightly ambiguous. Usually a "backup" is the old copy. 
                # If I want to work on a fresh copy, I should copy current -> new_work_file, and switch app to new_work_file.
                
                # Let's assume:
                # 1. Save current state to `filename_timestamp.csv` (this becomes the "backup" / "snapshot").
                # 2. Assign this new file as the current loaded path.
                # 3. Process AI on this NEW file.
                # This way the original file remains untouched (as pre-AI state). 
                
                # Wait, "create new file (backup) and assign as current". 
                # If I assign backup as current, I am modification the backup.
                # That means the original file is safe.
                
                # Let's do this: 
                # 1. Copy `original.csv` -> `original_ai_TIMESTAMP.csv`
                # 2. Switch app to `original_ai_TIMESTAMP.csv`
                # 3. Run AI on the app (which now points to the new file).
                
                # Logic for filename cleaning (preventing explosion)
                # Keep base name and one timestamp tag
                stem = current_p.stem
                if "_AI_" in stem:
                    base_name = stem.split("_AI_")[0]
                else:
                    base_name = stem
                
                new_filename = f"{base_name}_AI_{timestamp}{current_p.suffix}"
                new_path = current_p.parent / new_filename
                shutil.copy2(current_p, new_path)
                
                # Switch app context
                self.master.loaded_path = new_path
                self.master.lbl_filename.configure(text=f"Plik: {new_filename}")
                
                # Update project config to remember this new file
                # Force update by clearing subtitle_path first if needed, 
                # but explicit calling save_project should be enough as _gather uses loaded_path
                self.master.project_config["subtitle_path"] = str(new_path)
                set_project_config(self.master, "subtitle_path", str(new_path))
                save_project(self.master)
                
                # Note: self.selected_lines still points to objects in memory. 
                # Since we just copied the file, the objects in memory match the new file content.
                # We can proceed modifying them.
                
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie udało się utworzyć kopii zapasowej:\n{e}")
                return

        # Reset control
        self.control = AIControl()
        self.btn_pause.configure(text="Pauza", state="normal")
        self.btn_stop_task.configure(state="normal")
        self.frame_progress_controls.pack(pady=5) # Ensure visible

        # Prepare parameters
        target = self.target_var.get()
        skip_processed = self.skip_processed_var.get()
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
                
                # Check for special completion signals or completion
                if message.startswith("Zakończono") or message.startswith("Anulowano"):
                   final_msg = message
                   self.lbl_progress.configure(text=final_msg)
                   self.frame_progress_controls.pack_forget() # Hide controls
                   
                   # Create a frame for result buttons to keep them organized and removable
                   if not hasattr(self, 'frame_result_buttons'):
                       self.frame_result_buttons = ctk.CTkFrame(self.frame_progress, fg_color="transparent")
                       self.frame_result_buttons.pack(pady=5)
                   else:
                       # Clear previous buttons if any
                       for widget in self.frame_result_buttons.winfo_children():
                           widget.destroy()
                       self.frame_result_buttons.pack(pady=5)
                   
                   btn_close = ctk.CTkButton(self.frame_result_buttons, text="Zamknij", fg_color="green", command=self.destroy)
                   btn_close.pack(side="left", padx=5)

                   btn_retry = ctk.CTkButton(self.frame_result_buttons, text="Wróć", fg_color="gray", command=self._reset_to_start)
                   btn_retry.pack(side="left", padx=5)
                   
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
            skip_processed=skip_processed,
            service=service,
            app_ref=self.master, 
            progress_callback=progress_callback,
            control=self.control
        )


def run_ai_pipeline(lines: List[Line], tasks: List[AITask], target_field: str, service: OllamaService, app_ref, skip_processed: bool = False, progress_callback=None, control: AIControl = None):
    """
    To jest funkcja uruchamiana w wątku Workera.
    """
    processed_count = 0
    total = len(lines)
    
    last_save_time = time.time()
    modified_lines_buffer = []

    # Notify start
    if progress_callback: progress_callback(0, total, "Startowanie...")
    
    for i, line in enumerate(lines):
        # Control checks
        if control:
            if control.is_stopped:
                if progress_callback: progress_callback(i, total, "Anulowano przez użytkownika")
                # Try to save pending changes before exit
                if modified_lines_buffer and app_ref and hasattr(app_ref, 'loaded_path') and app_ref.loaded_path:
                    try:
                        update_lines_in_csv(modified_lines_buffer, str(app_ref.loaded_path))
                    except: pass
                return processed_count
            control.wait_if_paused()
        
        # Check skip processed
        if skip_processed and getattr(line, 'ai_processed', False):
            continue

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
                
                # Check if empty - if so, stop processing this line
                if not temp_text or not temp_text.strip():
                    temp_text = ""
                    break
            
            # Update Object
            # Always mark as AI processed if it went through processing, even if text is same
            if target_field == "tts":
                line.set_tts_text(temp_text)
            else:
                line.set_text(temp_text)
            
            line.ai_processed = True
            modified_lines_buffer.append(line)
            
            # Periodic Save (30 sec)
            if time.time() - last_save_time >= 30:
                 if app_ref and hasattr(app_ref, 'loaded_path') and app_ref.loaded_path and modified_lines_buffer:
                    try:
                        update_lines_in_csv(modified_lines_buffer, str(app_ref.loaded_path))
                        # Clear buffer only if save successful
                        modified_lines_buffer = []
                        last_save_time = time.time()
                    except Exception as db_err:
                        print(f"Error saving batch: {db_err}")

            processed_count += 1
            
        except Exception as e:
            print(f"Error processing line {line.uid}: {e}")
            
    # Final save
    if modified_lines_buffer and app_ref and hasattr(app_ref, 'loaded_path') and app_ref.loaded_path:
        try:
            update_lines_in_csv(modified_lines_buffer, str(app_ref.loaded_path))
        except Exception as e:
            print(f"Error final save: {e}")

    # Final update
    if progress_callback: progress_callback(total, total, "Zakończono")
        
    return processed_count
# logic ends

