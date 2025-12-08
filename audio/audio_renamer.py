import customtkinter as ctk
import os
from pathlib import Path
from tkinter import messagebox


class AudioRenameWindow(ctk.CTkToplevel):
    def __init__(self, app, audio_dir: Path):
        super().__init__(app)
        self.app = app
        self.audio_dir = audio_dir
        self.title("Dopasowanie dialogów do linii")
        self.geometry("600x300")

        # Ustawienie okna jako modalne
        self.transient(app)
        self.grab_set()

        # Konfiguracja grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)  # Strzałka
        self.grid_columnconfigure(2, weight=1)

        # --- LEWA STRONA: Napisy (Cel) ---
        target_frame = ctk.CTkFrame(self)
        target_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(target_frame, text="Docelowa linia tekstu", font=("", 14, "bold"),
                     text_color=("black", "white")).pack(pady=5)

        tf_inner = ctk.CTkFrame(target_frame, fg_color="transparent")
        tf_inner.pack(fill="x", padx=5, pady=5)

        # Width w konstruktorze
        self.ent_text_id = ctk.CTkEntry(tf_inner, placeholder_text="Nr linii", width=100)
        self.ent_text_id.pack(side="left", padx=5)
        self.ent_text_id.bind("<KeyRelease>", self.on_input_change)

        self.btn_play_text = ctk.CTkButton(tf_inner, text="▶ Odsłuchaj", width=80, fg_color="green", state="disabled",
                                           command=self._play_target_audio)
        self.btn_play_text.pack(side="right", padx=5)

        self.lbl_target_text = ctk.CTkLabel(target_frame, text="...", wraplength=250, text_color=("gray20", "gray80"))
        self.lbl_target_text.pack(pady=10, padx=5)

        # --- ŚRODEK: Strzałka ---
        arrow_lbl = ctk.CTkLabel(self, text="⬅ Zmień na", font=("", 20, "bold"), text_color=("black", "white"))
        arrow_lbl.grid(row=0, column=1, padx=5)

        # --- PRAWA STRONA: Plik Audio (Źródło) ---
        source_frame = ctk.CTkFrame(self)
        source_frame.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(source_frame, text="Rzeczywisty plik audio", font=("", 14, "bold"),
                     text_color=("black", "white")).pack(pady=5)

        sf_inner = ctk.CTkFrame(source_frame, fg_color="transparent")
        sf_inner.pack(fill="x", padx=5, pady=5)

        # Width w konstruktorze
        self.ent_audio_id = ctk.CTkEntry(sf_inner, placeholder_text="Nr pliku audio", width=100)
        self.ent_audio_id.pack(side="left", padx=5)
        self.ent_audio_id.bind("<KeyRelease>", self.on_input_change)

        self.btn_play_source = ctk.CTkButton(sf_inner, text="▶ Odsłuchaj", width=80, fg_color="green", state="disabled",
                                             command=self._play_source_audio)
        self.btn_play_source.pack(side="right", padx=5)

        self.lbl_source_status = ctk.CTkLabel(source_frame, text="...", text_color=("gray20", "gray80"))
        self.lbl_source_status.pack(pady=10)

        # --- DÓŁ: Akcja ---
        self.lbl_info = ctk.CTkLabel(self, text="Wpisz numery, aby zobaczyć podgląd.", text_color=("gray20", "gray80"))
        self.lbl_info.grid(row=1, column=0, columnspan=3, pady=(0, 5))

        self.btn_apply = ctk.CTkButton(self, text="PRZELICZ I ZMIEŃ NAZWY", height=40,
                                       fg_color="red", hover_color="darkred", state="disabled",
                                       command=self.apply_rename)
        self.btn_apply.grid(row=2, column=0, columnspan=3, padx=20, pady=10, sticky="ew")

        # Stan
        self.offset = 0

    def on_input_change(self, event=None):
        target_str = self.ent_text_id.get().strip()
        source_str = self.ent_audio_id.get().strip()

        if not target_str.isdigit() or not source_str.isdigit():
            self.btn_apply.configure(state="disabled")
            self.lbl_info.configure(text="Podaj poprawne numery.")
            self.btn_play_text.configure(state="disabled")
            self.btn_play_source.configure(state="disabled")
            return

        target_id = int(target_str)
        source_id = int(source_str)

        # 1. Pokaż tekst dla target
        if 0 < target_id <= len(self.app.processed_replace):
            text_content = self.app.processed_replace[target_id - 1]
            if len(text_content) > 50: text_content = text_content[:50] + "..."
            self.lbl_target_text.configure(text=f"\"{text_content}\"")

            # Sprawdź czy plik target już istnieje (żeby dać odsłuch)
            if self._check_file_exists(target_id):
                self.btn_play_text.configure(state="normal")
            else:
                self.btn_play_text.configure(state="disabled")
        else:
            self.lbl_target_text.configure(text="(Brak takiej linii)")
            self.btn_play_text.configure(state="disabled")

        # 2. Sprawdź plik źródłowy
        if self._check_file_exists(source_id):
            self.lbl_source_status.configure(text="Plik istnieje ✅", text_color="green")
            self.btn_play_source.configure(state="normal")
        else:
            self.lbl_source_status.configure(text="Brak pliku audio ❌", text_color="red")
            self.btn_play_source.configure(state="disabled")
            self.btn_apply.configure(state="disabled")
            return

        # 3. Oblicz offset
        # source + offset = target  =>  offset = target - source
        self.offset = target_id - source_id

        self.lbl_info.configure(
            text=f"Przesunięcie: {self.offset:+d}. Wszystkie pliki od numeru {source_id} zostaną przesunięte.")
        self.btn_apply.configure(state="normal")

    def _check_file_exists(self, ident):
        return (self.audio_dir / f"output1 ({ident}).wav").exists() or \
            (self.audio_dir / f"output1 ({ident}).mp3").exists()

    def _play_target_audio(self):
        ident = self.ent_text_id.get().strip()
        self._play_audio(ident)

    def _play_source_audio(self):
        ident = self.ent_audio_id.get().strip()
        self._play_audio(ident)

    def _play_audio(self, ident):
        wav = self.audio_dir / f"output1 ({ident}).wav"
        mp3 = self.audio_dir / f"output1 ({ident}).mp3"
        file_to_play = wav if wav.exists() else (mp3 if mp3.exists() else None)

        if file_to_play:
            # Używamy ffplay w tle
            import subprocess
            try:
                subprocess.Popen(["ffplay", "-nodisp", "-autoexit", str(file_to_play)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie można odtworzyć:\n{e}")

    def apply_rename(self):
        if not messagebox.askyesno("Potwierdź",
                                   f"Czy na pewno chcesz zmienić nazwy plików z przesunięciem {self.offset:+d}?\nTo operacja nieodwracalna."):
            return

        # Logika zmiany nazw (podobna do AudioSync, ale prostsza - czyste przesunięcie w górę lub w dół)
        # Przy przesunięciu trzeba uważać na kolejność!

        start_id = int(self.ent_audio_id.get())
        files = []

        # Znajdź wszystkie pliki >= start_id
        # Niestety glob nie sortuje numerycznie idealnie, trzeba sparsować
        for f in self.audio_dir.glob("output1 (*).*"):
            try:
                # nazwa formatu: output1 (123).wav
                stem = f.stem  # output1 (123)
                num_part = stem.split('(')[1].split(')')[0]
                num = int(num_part)
                if num >= start_id:
                    files.append((num, f))
            except:
                pass

        if not files:
            messagebox.showinfo("Info", "Brak plików do zmiany.")
            return

        # Sortowanie:
        # Jeśli offset > 0 (np. 1 -> 2), musimy zmieniać od KOŃCA (największe numery najpierw), żeby nie nadpisać.
        # Jeśli offset < 0 (np. 2 -> 1), musimy zmieniać od POCZĄTKU.

        reverse_order = (self.offset > 0)
        files.sort(key=lambda x: x[0], reverse=reverse_order)

        count = 0
        for num, path in files:
            new_num = num + self.offset
            new_name = path.with_name(f"output1 ({new_num}){path.suffix}")

            try:
                if new_name.exists():
                    # Conflict!
                    print(f"Konflikt: {new_name} już istnieje. Pomijam {path}.")
                    continue
                os.rename(path, new_name)
                count += 1
            except Exception as e:
                print(f"Błąd zmiany {path}: {e}")

        # To samo dla folderu ready
        ready_dir = self.audio_dir / "ready"
        if ready_dir.exists():
            ready_files = []
            for f in ready_dir.glob("output1 (*).ogg"):
                try:
                    num = int(f.stem.split('(')[1].split(')')[0])
                    if num >= start_id:
                        ready_files.append((num, f))
                except:
                    pass

            ready_files.sort(key=lambda x: x[0], reverse=reverse_order)
            for num, path in ready_files:
                new_num = num + self.offset
                new_name = path.with_name(f"output1 ({new_num}){path.suffix}")
                try:
                    if not new_name.exists():
                        os.rename(path, new_name)
                except:
                    pass

        messagebox.showinfo("Sukces", f"Zmieniono nazwy {count} plików.")
        self.destroy()