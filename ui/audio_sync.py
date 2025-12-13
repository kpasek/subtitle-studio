import customtkinter as ctk
import os
import threading
from pathlib import Path
from tkinter import messagebox
from typing import List, Tuple, Literal

# Typ operacji: ('delete', path) lub ('rename', src, dst)
Operation = Tuple[Literal['delete', 'rename'], Path, Path | None]


class AudioSyncWindow(ctk.CTkToplevel):
    def __init__(self, app, operations: List[Operation]):
        """
        :param operations: Lista krotek z zadaniami do wykonania na plikach.
                           Obliczona wcześniej w studio.py, aby zagwarantować spójność.
        """
        super().__init__(app)
        self.app = app
        self.operations = operations

        self.title("Synchronizacja plików audio")
        self.geometry("450x250")
        self.resizable(False, False)

        self.transient(app)
        self.wait_visibility()
        self.grab_set()

        self.protocol("WM_DELETE_WINDOW", self._disable_close)

        # UI
        self.lbl_info = ctk.CTkLabel(self, text="Synchronizacja...", font=("", 16, "bold"))
        self.lbl_info.pack(pady=(20, 10))

        self.lbl_detail = ctk.CTkLabel(self, text="Przygotowywanie...", text_color="gray")
        self.lbl_detail.pack(pady=5)

        self.progress_bar = ctk.CTkProgressBar(self, width=350)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=20)

        self.btn_close = ctk.CTkButton(self, text="Zamknij", state="disabled", command=self.destroy)
        self.btn_close.pack(pady=10)

        threading.Thread(target=self._run_sync, daemon=True).start()

    def _disable_close(self):
        pass

    def _update_ui(self, progress: float, text: str):
        self.app.queue.put(lambda: self.progress_bar.set(progress))
        self.app.queue.put(lambda: self.lbl_detail.configure(text=text))

    def _finish(self, deleted_count, renamed_count):
        self.app.queue.put(lambda: self.lbl_info.configure(text="Zakończono sukcesem!", text_color="green"))
        self.app.queue.put(lambda: self.lbl_detail.configure(
            text=f"Usunięto: {deleted_count} | Przeniesiono: {renamed_count}"
        ))
        self.app.queue.put(lambda: self.progress_bar.set(1.0))
        self.app.queue.put(lambda: self.btn_close.configure(state="normal", command=self.destroy))
        self.app.queue.put(lambda: self.protocol("WM_DELETE_WINDOW", self.destroy))

    def _run_sync(self):
        try:
            total_ops = len(self.operations)
            if total_ops == 0:
                self._finish(0, 0)
                return

            # Podział na typy zadań dla bezpiecznego wykonania
            to_delete = [op[1] for op in self.operations if op[0] == 'delete']
            # Dla rename: (src, dst)
            to_rename = [(op[1], op[2]) for op in self.operations if op[0] == 'rename']

            # Całkowita liczba kroków "fizycznych" (delete + rename_to_temp + rename_to_target)
            total_steps = len(to_delete) + (len(to_rename) * 2)

            # Konfiguracja paska postępu (aktualizacja co 5%)
            update_step = max(1, int(total_steps * 0.05))
            current_step = 0

            def tick(msg):
                nonlocal current_step
                current_step += 1
                if current_step % update_step == 0 or current_step == total_steps:
                    prog = current_step / total_steps
                    percent = int(prog * 100)
                    self._update_ui(prog, f"{msg} {percent}%")

            # 1. Usuwanie (bezpieczne, bo usuwamy pliki, które i tak wylatują)
            for path in to_delete:
                try:
                    if path.exists():
                        os.remove(path)
                except Exception as e:
                    print(f"Błąd delete {path}: {e}")
                tick("Usuwanie zbędnych plików...")

            # 2. Rename -> Temp (aby uniknąć kolizji gdy np. 3->2, a 2 jeszcze istnieje)
            temp_map = []  # (temp_path, target_path)

            for src, target in to_rename:
                if not src.exists():
                    # Jeśli plik źródłowy nie istnieje (np. błąd w logice nadrzędnej), pomijamy
                    # ale zaliczamy krok paska postępu
                    tick("Przenoszenie (etap 1)...")
                    continue

                temp_path = src.with_name(f"__TEMP_SYNC_{src.name}")
                try:
                    os.rename(src, temp_path)
                    temp_map.append((temp_path, target))
                except Exception as e:
                    print(f"Błąd rename->temp {src}: {e}")
                tick("Przenoszenie (etap 1)...")

            # 3. Temp -> Target
            for temp, target in temp_map:
                try:
                    if target.exists():
                        os.remove(target)  # Safety check, nie powinno wystąpić po delete
                    os.rename(temp, target)
                except Exception as e:
                    print(f"Błąd temp->target {target}: {e}")
                tick("Przenoszenie (etap 2)...")

            self._finish(len(to_delete), len(to_rename))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.app.queue.put(lambda: messagebox.showerror("Błąd", f"Wystąpił błąd synchronizacji:\n{e}"))
            self.app.queue.put(lambda: self.btn_close.configure(state="normal"))