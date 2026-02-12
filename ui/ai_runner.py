import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import List, TYPE_CHECKING
import threading
import datetime
import shutil
from pathlib import Path

from app.builtin_tasks import BUILTIN_TASKS, AITask
from app.entity import Line
from app.ai_core import OllamaService
from app.io import update_lines_in_csv
from app.project import save_project, set_project_config

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

class AIRunnerState:
    """Holds the state of the active AI task process."""
    def __init__(self, master):
        self.master = master
        self.is_running = False
        self.is_finished = False
        self.current_progress = 0
        self.total_items = 0
        self.status_message = ""
        self.control = AIControl()
        self.execution_queue: List[AITask] = []
        self.selected_lines = []
        self.task_thread = None
        self.listeners = [] # List of windows to update
        self.result_message = None
        self.target_field = None
        self.skip_processed = False
        self.is_global_run = False

    def reset(self):
        self.is_running = False
        self.is_finished = False
        self.current_progress = 0
        self.status_message = ""
        self.result_message = None
        self.control = AIControl()

    def update_progress(self, current, total, message):
        self.current_progress = current
        self.total_items = total
        self.status_message = message
        
        self.notify_listeners()

    def set_finished(self, final_msg):
        self.is_running = False
        self.is_finished = True
        self.result_message = final_msg
        self.status_message = final_msg
        
        self.notify_listeners()
        
    def add_listener(self, window):
        if window not in self.listeners:
            self.listeners.append(window)
            
    def remove_listener(self, window):
        if window in self.listeners:
            self.listeners.remove(window)
            
    def notify_listeners(self):
        to_remove = []
        for win in list(self.listeners):
            # We call a thread-safe update method on the window or schedule it
            try:
                # Do NOT call winfo_exists() here as it is not thread safe if this runs in worker
                # Just schedule. If window is dead, after() might raise TclError or just work if C part handles it.
                # However, Python wrapper checks.
                # Safest is try-except around after()
                win.after(0, lambda w=win: w.update_from_state(self))
            except Exception:
                to_remove.append(win)
        
        for dead in to_remove:
            if dead in self.listeners:
                self.listeners.remove(dead)

    def start_pipeline(self, lines, tasks, target, skip_processed, service):
        self.selected_lines = lines
        self.execution_queue = tasks
        self.target_field = target
        self.skip_processed = skip_processed
        self.is_running = True
        self.is_finished = False
        self.total_items = len(lines)
        
        # Define worker callback
        def progress_callback(current, total, message):
             # This runs in worker thread
             # We update State immediately
             self.master.after(0, lambda: self._handle_callback(current, total, message))
             
        self.master.worker.add_task(
            func=run_ai_pipeline,
            lines=self.selected_lines,
            tasks=self.execution_queue,
            target_field=target,
            skip_processed=skip_processed,
            service=service,
            app_ref=self.master, 
            progress_callback=progress_callback,
            control=self.control
        )
        
    def _handle_callback(self, current, total, message):
        self.update_progress(current, total, message)
        if message.startswith("Zakończono") or message.startswith("Anulowano"):
             self.set_finished(message)
             # Trigger refresh in main window
             if hasattr(self.master, 'subtitle_panel') and hasattr(self.master.subtitle_panel, 'set_preview'):
                 self.master.subtitle_panel.set_preview(self.master.lines)


class AITaskRunnerWindow(ctk.CTkToplevel):
    def __init__(self, master, selected_lines: List[Line], is_global: bool = False):
        super().__init__(master)
        self.master = master
        self._was_attached = False
        
        # Check logic:
        # If there is an ACTIVE state in self.master.ai_state, we must attach to it
        # IF the intention is to run selected lines, but a GLOBAL task is running -> Conflict?
        # User usually wants to see the running task.
        
        if self.master.ai_state and self.master.ai_state.is_running:
             # Task is active -> Attach
             self.state_ref = self.master.ai_state
             self.selected_lines = self.state_ref.selected_lines
             self.is_global = self.state_ref.is_global_run
             self._was_attached = True
        else:
             # New State (discard old if exists)
             self.selected_lines = selected_lines
             self.is_global = is_global
             self.state_ref = AIRunnerState(master)
             self.state_ref.is_global_run = is_global
             self.master.ai_state = self.state_ref
             # Explicitly store selected lines in state for recovery
             self.state_ref.selected_lines = selected_lines
             self._was_attached = False

        self.title("Uruchom Zadania SI")
        self.geometry("1000x700")

        self.state_ref.add_listener(self)
        
        # Load tasks initial
        self.all_tasks = []
        self._load_tasks()
        self.execution_queue: List[AITask] = []  # Local queue builder
        
        # Initialize execution queue with first available task if present and not restoring
        if self.all_tasks and not self._was_attached:
            self.execution_queue.append(self.all_tasks[0])

        self._setup_ui()
        
        # Ensure the queue list in UI reflects the initial queue state
        if not self._was_attached and self.execution_queue:
            self._update_queue_list()
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        if self._was_attached:
             self._restore_view()

    def _on_close(self):
        self.state_ref.remove_listener(self)
        # We DO NOT clear master.ai_state here, to allow background run
        # State is cleared only when user explicitly "Resets" or "Starts New" ??
        # Or maybe check if finished?
        self.destroy()

    def update_from_state(self, state: AIRunnerState):
        """Called by state when progress updates."""
        if not self.winfo_exists(): return
        
        # Update progress bar
        ratio = state.current_progress / state.total_items if state.total_items > 0 else 0
        self.progress_bar.set(ratio)
        msg_text = f"{state.status_message} ({state.current_progress}/{state.total_items})"
        self.lbl_progress.configure(text=msg_text)
        
        if state.is_finished:
            self.lbl_progress.configure(text=state.status_message)
            self._show_finish_screen()
        elif state.is_running:
             # Ensure progress view is shown if not already
             pass

    def _restore_view(self):
        """Switches to progress view immediately."""
        self.execution_queue = self.state_ref.execution_queue
        # Update UI execution list
        self._update_queue_list()
        
        self.frame_actions.grid_remove()
        self.frame_progress.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")
        
        # Set controls
        self.frame_progress_controls.pack(pady=5)
        if self.state_ref.control.is_paused:
             self.btn_pause.configure(text="Wznów")
        else:
             self.btn_pause.configure(text="Pauza")
        
        # Force one update
        self.update_from_state(self.state_ref)

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
        frame_left = ctk.CTkFrame(self)
        frame_left.grid(row=1, column=0, rowspan=2, padx=10, pady=5, sticky="nsew")
        
        ctk.CTkLabel(frame_left, text="Dostępne zadania").pack(pady=5)
        self.list_available = tk.Listbox(frame_left, bg="#2b2b2b", fg="white", selectbackground="#1f538d", borderwidth=0, highlightthickness=0)
        self.list_available.pack(fill="both", expand=True, padx=5, pady=5)
        
        for t in self.all_tasks:
            self.list_available.insert("end", t.name)
            
        self.list_available.bind("<Double-Button-1>", lambda e: self._add_task())

        # Middle: Buttons
        frame_mid = ctk.CTkFrame(self, fg_color="transparent")
        frame_mid.grid(row=1, column=1, rowspan=2, padx=5, sticky="ns")
        
        ctk.CTkButton(frame_mid, text="Dodaj >", width=50, command=self._add_task).pack(pady=10)
        ctk.CTkButton(frame_mid, text="< Usuń", width=50, command=self._remove_task).pack(pady=10)
        ctk.CTkButton(frame_mid, text="^ Góra", width=50, command=self._move_up).pack(pady=10)
        ctk.CTkButton(frame_mid, text="v Dół", width=50, command=self._move_down).pack(pady=10)

        # Right: Execution Queue
        frame_right = ctk.CTkFrame(self)
        frame_right.grid(row=1, column=2, rowspan=2, padx=10, pady=5, sticky="nsew")
        
        ctk.CTkLabel(frame_right, text="Kolejka wykonania").pack(pady=5)
        self.list_queue = tk.Listbox(frame_right, bg="#2b2b2b", fg="white", selectbackground="#1f538d", borderwidth=0, highlightthickness=0)
        self.list_queue.pack(fill="both", expand=True, padx=5, pady=5)
        self.list_queue.bind("<Double-Button-1>", lambda e: self._remove_task())

        # Bottom: Options & Run
        self.frame_actions = ctk.CTkFrame(self)
        self.frame_actions.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")

        ctk.CTkLabel(self.frame_actions, text="Zapisz wynik do:").pack(side="left", padx=10)
        self.target_var = ctk.StringVar(value="tts")
        combo_target = ctk.CTkOptionMenu(self.frame_actions, variable=self.target_var, values=["Text", "TTS Text", "Original Text (Overwrite)"])
        combo_target.pack(side="left", padx=5)

        self.skip_processed_var = ctk.BooleanVar(value=True)
        chk_skip = ctk.CTkCheckBox(self.frame_actions, text="Pomiń już przetworzone przez SI", variable=self.skip_processed_var)
        chk_skip.pack(side="left", padx=15)

        action_container = ctk.CTkFrame(self.frame_actions, fg_color="transparent")
        action_container.pack(side="right", padx=10)

        if self.is_global:
             ctk.CTkLabel(action_container, text="Tryb globalny: aplikacja utworzy nową wersję pliku.").pack(side="top", pady=2)

        self.btn_run = ctk.CTkButton(action_container, text="URUCHOM", fg_color="green", width=120, command=self._run_process)
        self.btn_run.pack(side="bottom", pady=5)

        # Progress Frame (Hidden initially)
        self.frame_progress = ctk.CTkFrame(self)
        # Don't grid yet
        
        self.lbl_progress = ctk.CTkLabel(self.frame_progress, text="Oczekiwanie...", font=("", 14))
        self.lbl_progress.pack(pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(self.frame_progress, width=600)
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)
        
        # Stop/Pause buttons
        self.frame_progress_controls = ctk.CTkFrame(self.frame_progress, fg_color="transparent")
        
        self.btn_pause = ctk.CTkButton(self.frame_progress_controls, text="Pauza", width=100, command=self._toggle_pause)
        self.btn_pause.pack(side="left", padx=10)
        
        self.btn_stop_task = ctk.CTkButton(self.frame_progress_controls, text="Zatrzymaj", width=100, fg_color="red", command=self._stop_task)
        self.btn_stop_task.pack(side="left", padx=10)
        
        # By default don't pack controls, only when running? 
        # Actually logic packs them.

    # --- Queue Management ---
    def _add_task(self):
        sel = self.list_available.curselection()
        if not sel: return
        idx = sel[0]
        if idx < len(self.all_tasks):
            task = self.all_tasks[idx]
            self.execution_queue.append(task)
            self._update_queue_list()

    def _remove_task(self):
        sel = self.list_queue.curselection()
        if not sel: return
        idx = sel[0]
        del self.execution_queue[idx]
        self._update_queue_list()

    def _move_up(self):
        sel = self.list_queue.curselection()
        if not sel: return
        idx = sel[0]
        if idx > 0:
            self.execution_queue[idx], self.execution_queue[idx-1] = self.execution_queue[idx-1], self.execution_queue[idx]
            self._update_queue_list()
            self.list_queue.selection_set(idx-1)

    def _move_down(self):
        sel = self.list_queue.curselection()
        if not sel: return
        idx = sel[0]
        if idx < len(self.execution_queue) - 1:
            self.execution_queue[idx], self.execution_queue[idx+1] = self.execution_queue[idx+1], self.execution_queue[idx]
            self._update_queue_list()
            self.list_queue.selection_set(idx+1)

    def _update_queue_list(self):
        self.list_queue.delete(0, "end")
        for i, t in enumerate(self.execution_queue):
            self.list_queue.insert("end", f"{i+1}. {t.name}")

    # --- Execution ---
    def _toggle_pause(self):
        if self.state_ref.control.is_paused:
            self.state_ref.control.resume()
            self.btn_pause.configure(text="Pauza")
        else:
            self.state_ref.control.pause()
            self.btn_pause.configure(text="Wznów")

    def _stop_task(self):
        if not self.winfo_exists(): return
        
        # Pause execution so the background worker effectively stops at the next checkpoint
        # while user decides
        was_paused = self.state_ref.control.is_paused
        if not was_paused:
            self.state_ref.control.pause()
            
        if messagebox.askyesno("Potwierdzenie", "Czy na pewno chcesz przerwać przetwarzanie?", parent=self):
            try:
                if self.winfo_exists() and hasattr(self, 'btn_stop_task'):
                    self.btn_stop_task.configure(state="disabled")
            except Exception:
                pass
            self.state_ref.control.stop()
        else:
            # User cancelled stop -> Resume (unless it was already paused?)
            # User requirement: "Jeżeli nie potwierdzi to wznawia" (If not confirmed, it resumes)
            # So we force resume even if it was paused before? 
            # Usually strict adherence means force resume.
            self.state_ref.control.resume()
            # Update button text just in case
            if self.winfo_exists() and hasattr(self, 'btn_pause'):
                self.btn_pause.configure(text="Pauza")

    def _reset_to_start(self):
        """Resets the view (not the data) to allow new run configuration."""
        if hasattr(self, 'frame_result_buttons'):
            self.frame_result_buttons.destroy()
            del self.frame_result_buttons
            
        self.frame_progress.grid_remove()
        self.frame_actions.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")
        
        # Determine if we should clear global state?
        if self.state_ref.is_finished:
             self.master.ai_state = None
        
        # Create new state for configuring new run
        self.state_ref = AIRunnerState(self.master)
        self.state_ref.is_global_run = self.is_global
        self.state_ref.add_listener(self)
        self.master.ai_state = self.state_ref
        
        # Clean queues
        self.execution_queue = []
        self._update_queue_list()

    def _show_finish_screen(self):
       """Updates UI when finished."""
       self.frame_progress_controls.pack_forget() # Hide controls
       
       if not hasattr(self, 'frame_result_buttons') or not self.frame_result_buttons.winfo_exists():
           self.frame_result_buttons = ctk.CTkFrame(self.frame_progress, fg_color="transparent")
           self.frame_result_buttons.pack(pady=5)
       
       # Clear just in case
       for w in self.frame_result_buttons.winfo_children(): w.destroy()
       
       btn_close = ctk.CTkButton(self.frame_result_buttons, text="Zamknij", fg_color="green", command=self.destroy)
       btn_close.pack(side="left", padx=5)

       btn_retry = ctk.CTkButton(self.frame_result_buttons, text="Wróć / Nowe zadanie", fg_color="gray", command=self._reset_to_start)
       btn_retry.pack(side="left", padx=5)

    def _run_process(self):
        if not self.execution_queue:
            # messagebox.showwarning("Brak zadań", "Dodaj zadania do kolejki.")
            return

        # Backup Logic for Global Processing
        if self.is_global and self.master.loaded_path:
            try:
                current_p = Path(self.master.loaded_path)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Filename logic
                stem = current_p.stem
                if "_AI_" in stem:
                    base_name = stem.split("_AI_")[0]
                else:
                    base_name = stem
                
                new_filename = f"{base_name}_AI_{timestamp}{current_p.suffix}"
                new_path = current_p.parent / new_filename
                
                # Copy current -> new
                shutil.copy2(current_p, new_path)
                
                # Switch app context
                self.master.loaded_path = new_path
                if self.master.lbl_filename:
                    self.master.lbl_filename.configure(text=f"Plik: {new_filename}")
                self.master.project_config["subtitle_path"] = str(new_path)
                set_project_config(self.master, "subtitle_path", str(new_path))
                save_project(self.master)
                
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie udało się utworzyć kopii zapasowej:\n{e}")
                return

        # Prepare Service
        ollama_url = self.master.global_config.get('ollama_url', 'http://localhost:11434')
        ollama_model = self.master.global_config.get('ollama_model', 'gemma2:2b')
        service = OllamaService(ollama_url, ollama_model)
        
        if not service.check_connection():
            messagebox.showerror("Błąd", f"Nie można połączyć z Ollama pod adresem {ollama_url}.\nUpewnij się, że serwer działa.")
            return

        # UI Setup
        self.btn_pause.configure(text="Pauza", state="normal")
        self.btn_stop_task.configure(state="normal")
        self.frame_progress_controls.pack(pady=5)
        
        self.frame_actions.grid_remove() # Hide buttons
        self.frame_progress.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")
        
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        
        # Start State Pipeline
        tasks = list(self.execution_queue)
        target = self.target_var.get()
        # Mapping target value to field names
        target_map = {
            "tts": "TTS Text",
            "text": "Text",
            "Original Text (Overwrite)": "Original Text (Overwrite)"
        }
        # In UI I used "tts" / "text" values in radio button, but code expects "Text"/"TTS Text"
        # Wait, I initialized radio button with "values" list in CTkOptionMenu previously, but now I used request RadioButtons.
        # Let's fix that.
        
        # Correction: I used CTkRadioButton with variable self.target_var.
        # Values used in radiobuttons: "tts", "text". 
        # But pipeline expects "Text" or "TTS Text".
        
        target_key = self.target_var.get()
        if target_key == "tts":
            target = "TTS Text"
        elif target_key == "text":
            target = "Text"
        else:
            # Handle option menu if used
            target = target_key
            
        skip_processed = self.skip_processed_var.get()
        
        self.state_ref.start_pipeline(self.selected_lines, tasks, target, skip_processed, service)


# --- Pipeline Logic (runs in worker thread) ---

def run_ai_pipeline(lines: List[Line], tasks: List[AITask], target_field: str, skip_processed: bool, 
                    service: OllamaService, app_ref, progress_callback, control: AIControl):
    
    total = len(lines)
    processed_count = 0
    lines_since_save = 0
    
    for i, line in enumerate(lines):
        # 1. check control
        if control.is_stopped: break

        # Wait if paused. If stopped while paused, stop() calls resume() to unblock this.
        control.wait_if_paused()
        
        # Check stopped again
        if control.is_stopped: break
            
        progress_callback(processed_count, total, f"Przetwarzanie wiersza {i+1}...")

        # 2. Skip logic
        if skip_processed and getattr(line, 'ai_processed', False):
             processed_count += 1
             continue

        # 3. Context gathering
        current_text = line.text or line.original_text or ""
        prev_line_text = lines[i-1].text or lines[i-1].original_text or "" if i > 0 else ""
        next_line_text = lines[i+1].text or lines[i+1].original_text or "" if i < len(lines)-1 else ""
        
        context = {
            "previous_line": prev_line_text,
            "next_line": next_line_text,
            "speaker": getattr(line, 'speaker', '') or "",
            "original": line.original_text or ""
        }
        
        # Execute chain
        result_text = current_text
        
        try:
            for task in tasks:
                # Check for pause/stop between individual tasks
                if control.is_stopped: break
                control.wait_if_paused()
                
                # Use raw system prompt from task definition - do NOT inject text yet
                sys_prompt = getattr(task, 'system_prompt', '') or ''
                
                # Check for optional model attribute in task, fallback to None (service uses default)
                task_model = getattr(task, 'model', None)
                
                print(f"SI  IN: {result_text}")
                
                # Use standard 'process_text' which includes the security wrapper
                response = service.process_text(
                    text=result_text,
                    system_prompt=sys_prompt,
                    model=task_model
                )
                
                print(f"SI OUT: {response}")
                
                if response:
                    result_text = response.strip()
                
                if control.is_stopped: break
                
        except Exception as e:
            print(f"Error AI on line {i}: {e}")
            
        # 4. Save result
        if not control.is_stopped:
            if target_field == "Text":
                line.text = result_text
            elif target_field == "TTS Text":
                line.tts_text = result_text
            elif target_field == "Original Text (Overwrite)":
                line.original_text = result_text
            
            line.ai_processed = True
            
            processed_count += 1
            lines_since_save += 1
            progress_callback(processed_count, total, f"Ukończono wiersz {i+1}")

            # Batch save every 5 lines
            if lines_since_save >= 5:
                try:
                    if app_ref.loaded_path:
                        update_lines_in_csv(lines, str(app_ref.loaded_path))
                        lines_since_save = 0
                except: pass
            
    # End
    # Always try to save pending changes, even if stopped
    try:
        if app_ref.loaded_path:
            update_lines_in_csv(lines, str(app_ref.loaded_path))
    except: pass

    if control.is_stopped:
        progress_callback(processed_count, total, "Anulowano przez użytkownika.")
    else:
        progress_callback(processed_count, total, "Zakończono pomyślnie.")
