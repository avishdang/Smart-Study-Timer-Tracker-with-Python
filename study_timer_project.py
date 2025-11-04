# study_timer_with_target_expanded_logs.py

"""
Enhanced: Larger 'Recent Sessions' log section.
Everything else (GUI, CSV handling, analytics, etc.) remains unchanged.
"""

import os
import re
import time
import datetime
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
import customtkinter as ctk
import pandas as pd
import speech_recognition as sr
import pyttsx3
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------- CONFIG ----------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

DEFAULT_SUBJECTS = ["Math", "Physics", "Chemistry", "English", "Programming", "Other"]
DEFAULT_CSV_NAME = "study_log.csv"

# ---------- TTS ----------
_tts = pyttsx3.init()
_tts.setProperty("rate", 150)
def speak(text):
    try:
        _tts.say(text)
        _tts.runAndWait()
    except Exception:
        pass

# ---------- Voice Recognition ----------
_recognizer = sr.Recognizer()
def listen_once(timeout=6, phrase_time_limit=6):
    try:
        with sr.Microphone() as source:
            _recognizer.adjust_for_ambient_noise(source, duration=0.6)
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        try:
            return _recognizer.recognize_google(audio)
        except (sr.UnknownValueError, sr.RequestError):
            return None
    except Exception as e:
        print("Microphone error:", e)
        return None

# ---------- Utilities ----------
def ensure_csv_exists(path):
    if not os.path.exists(path):
        df = pd.DataFrame(columns=["timestamp","date","subject","duration_seconds"])
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        df.to_csv(path, index=False)

def append_session_csv(path, subject, duration_seconds):
    ensure_csv_exists(path)
    ts = datetime.datetime.now().isoformat()
    date_str = datetime.date.today().isoformat()
    row = {"timestamp": ts, "date": date_str, "subject": subject, "duration_seconds": int(duration_seconds)}
    pd.DataFrame([row]).to_csv(path, mode='a', header=False, index=False)

def seconds_to_mmss(sec):
    sec = int(sec)
    return f"{sec//60:02d}:{sec%60:02d}"

# ---------- Voice Parsing ----------
def parse_voice_start(text):
    if not text:
        return None, None
    txt = text.lower()
    subj = None
    minutes = None
    m = re.search(r"for\s+([a-zA-Z ]+?)(?:\s|$)", txt)
    if m:
        subj = m.group(1).strip().title()
        subj = re.sub(r"\d+", "", subj).strip()
    m2 = re.search(r"(\d{1,3})\s*(minutes|minute|mins|min|m)?", txt)
    if m2:
        try:
            minutes = int(m2.group(1))
        except:
            minutes = None
    return subj, minutes

# ---------- Main App ----------
class StudyTimerTargetApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Study Timer — Daily Target & CSV")
        self.geometry("980x680")
        self.resizable(False, False)

        self.subjects = DEFAULT_SUBJECTS.copy()
        self.current_subject = tk.StringVar(value=self.subjects[0])
        self.csv_path = os.path.join(os.getcwd(), DEFAULT_CSV_NAME)
        self.daily_target_minutes = tk.IntVar(value=60)
        self.today_minutes = 0
        self.timer_running = False
        self.start_time = None
        self.accumulated_seconds = 0
        self._timer_job = None
        self.voice_listening = False

        ensure_csv_exists(self.csv_path)
        self._build_ui()
        self._refresh_all_charts()

    def _build_ui(self):
        root = ctk.CTkFrame(self)
        root.pack(fill="both", expand=True, padx=16, pady=16)

        top = ctk.CTkFrame(root, corner_radius=12)
        top.pack(fill="x", pady=(0,12))
        ctk.CTkLabel(top, text="📘 Study Timer — Daily Target", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left", padx=12, pady=10)
        ctk.CTkButton(top, text="Set CSV Path", width=140, command=self._choose_csv_path).pack(side="right", padx=8)
        ctk.CTkLabel(top, text="(Default: current folder)", text_color="#94A3B8").pack(side="right", padx=(0,6))

        main = ctk.CTkFrame(root)
        main.pack(fill="both", expand=True)

        # LEFT PANEL
        left = ctk.CTkFrame(main, width=300)
        left.pack(side="left", fill="y", padx=(0,12))

        ctk.CTkLabel(left, text="Subject", font=ctk.CTkFont(size=14)).pack(pady=(12,4))
        self.subject_menu = ctk.CTkOptionMenu(left, values=self.subjects, variable=self.current_subject, width=220)
        self.subject_menu.pack(pady=(0,12))
        ctk.CTkButton(left, text="➕ Add Subject", width=220, command=self._add_subject).pack(pady=(0,12))

        ctk.CTkLabel(left, text="Daily Target (minutes)", font=ctk.CTkFont(size=14)).pack(pady=(8,4))
        ctk.CTkEntry(left, textvariable=self.daily_target_minutes, width=120).pack(pady=(0,6))

        self.progress_label = ctk.CTkLabel(left, text="Today's progress: 0 / 60 min")
        self.progress_label.pack(pady=(8,4))
        self.progress = ctk.CTkProgressBar(left, width=220)
        self.progress.set(0.0)
        self.progress.pack(pady=(0,12))

        ctk.CTkLabel(left, text="Controls", font=ctk.CTkFont(size=14)).pack(pady=(6,6))
        ctk.CTkButton(left, text="▶ Start", width=100, command=self._start_timer).pack(pady=(6,4))
        ctk.CTkButton(left, text="⏸ Pause", width=100, command=self._pause_timer).pack(pady=(6,4))
        ctk.CTkButton(left, text="⏹ Stop Study (Save)", width=150, fg_color="#ef4444", hover_color="#e11d48", command=self._stop_and_save).pack(pady=(12,8))
        ctk.CTkButton(left, text="🎤 Voice Command", width=160, command=self._toggle_voice).pack(pady=(6,4))
        ctk.CTkLabel(left, text="Say: 'Start study for Math 45', 'Pause', 'Stop'", text_color="#94A3B8").pack(pady=(4,8))

        # --- EXPANDED Recent Sessions ---
        ctk.CTkLabel(left, text="Recent Sessions", font=ctk.CTkFont(size=14)).pack(pady=(6,4))
        self.recent_list = tk.Listbox(left, height=18, width=38, bg="#1f2937", fg="white", relief="flat", font=("Consolas", 10))
        self.recent_list.pack(pady=(2,8), padx=8, fill="both", expand=True)

        # CENTER PANEL
        center = ctk.CTkFrame(main)
        center.pack(side="left", fill="both", expand=True)
        self.time_label = ctk.CTkLabel(center, text="00:00", font=ctk.CTkFont(size=72, weight="bold"))
        self.time_label.pack(pady=(30,20))
        ctk.CTkButton(center, text="Reset Timer", width=140, command=self._reset_timer).pack(pady=8)
        ctk.CTkButton(center, text="Refresh Analytics", width=160, command=self._refresh_all_charts).pack(pady=8)
        ctk.CTkLabel(center, text="When you Stop Study, session is saved to CSV.", text_color="#94A3B8").pack(pady=12)

        # RIGHT PANEL - Charts
        right = ctk.CTkFrame(main, width=380)
        right.pack(side="right", fill="both", padx=(12,0))
        tabs = ctk.CTkTabview(right, width=360)
        tabs.pack(fill="both", expand=True, pady=(12,12))
        tabs.add("Overview"); tabs.add("Per Subject"); tabs.add("Daily")
        self.ov_label = ctk.CTkLabel(tabs.tab("Overview"), text="No data yet", font=ctk.CTkFont(size=14))
        self.ov_label.pack(pady=18)

        self.fig_subj = Figure(figsize=(4.2,3), dpi=100)
        self.ax_subj = self.fig_subj.add_subplot(111)
        self.canvas_subj = FigureCanvasTkAgg(self.fig_subj, master=tabs.tab("Per Subject"))
        self.canvas_subj.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        self.fig_daily = Figure(figsize=(4.2,3), dpi=100)
        self.ax_daily = self.fig_daily.add_subplot(111)
        self.canvas_daily = FigureCanvasTkAgg(self.fig_daily, master=tabs.tab("Daily"))
        self.canvas_daily.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    # CSV Path
    def _choose_csv_path(self):
        file = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], initialfile=DEFAULT_CSV_NAME)
        if file:
            os.makedirs(os.path.dirname(file) or ".", exist_ok=True)
            self.csv_path = file
            ensure_csv_exists(self.csv_path)
            speak("CSV path set.")
            messagebox.showinfo("CSV Path", f"CSV path set to:\n{self.csv_path}")

    def _add_subject(self):
        ans = simpledialog.askstring("Add Subject", "Enter subject name:", parent=self)
        if ans:
            s = ans.strip().title()
            if s not in self.subjects:
                self.subjects.append(s)
                self.subject_menu.configure(values=self.subjects)
                self.current_subject.set(s)

    # Timer functions
    def _start_timer(self):
        if self.timer_running: return
        self.timer_running = True
        self.start_time = time.time()
        self._tick()

    def _pause_timer(self):
        if not self.timer_running: return
        elapsed = time.time() - self.start_time
        self.accumulated_seconds += elapsed
        self.timer_running = False
        if self._timer_job: self.after_cancel(self._timer_job)
        self._refresh_timer_display()

    def _reset_timer(self):
        if self._timer_job: self.after_cancel(self._timer_job)
        self.timer_running = False
        self.accumulated_seconds = 0
        self._refresh_timer_display()

    def _stop_and_save(self):
        elapsed = 0
        if self.timer_running: elapsed = time.time() - self.start_time
        total_seconds = self.accumulated_seconds + elapsed
        if total_seconds <= 0:
            messagebox.showinfo("No Study Time", "No study time recorded.")
            return
        subj = self.current_subject.get()
        append_session_csv(self.csv_path, subj, int(total_seconds))
        self.timer_running = False
        self.accumulated_seconds = 0
        self._refresh_timer_display()
        messagebox.showinfo("Saved", f"{subj} — {int(total_seconds//60)} min saved.")
        self._refresh_all_charts()

    def _tick(self):
        if not self.timer_running: return
        self._refresh_timer_display()
        self._timer_job = self.after(1000, self._tick)

    def _refresh_timer_display(self):
        current = self.accumulated_seconds
        if self.timer_running: current += time.time() - self.start_time
        self.time_label.configure(text=seconds_to_mmss(current))

    # Refresh charts & logs
    def _refresh_all_charts(self):
        self._refresh_recent_sessions()
        self._refresh_overview()
        self._draw_subject_chart()
        self._draw_daily_chart()

    def _refresh_recent_sessions(self):
        ensure_csv_exists(self.csv_path)
        try:
            df = pd.read_csv(self.csv_path)
            last = df.tail(18).iloc[::-1] if not df.empty else pd.DataFrame()
            self.recent_list.delete(0, tk.END)
            for _, r in last.iterrows():
                t = r.get("timestamp", "")
                subj = r.get("subject", "")
                dur = int(r.get("duration_seconds", 0))
                ts = str(t)[:16]
                self.recent_list.insert(tk.END, f"{ts} | {subj} | {dur//60}m")
        except Exception as e:
            print("Recent refresh error:", e)

    def _draw_subject_chart(self):
        ensure_csv_exists(self.csv_path)
        df = pd.read_csv(self.csv_path)
        self.ax_subj.clear()
        if df.empty:
            self.ax_subj.text(0.5, 0.5, "No data", ha='center', va='center')
        else:
            df['date'] = pd.to_datetime(df['date'])
            cutoff = pd.Timestamp.today() - pd.Timedelta(days=7)
            grouped = df[df['date'] >= cutoff].groupby('subject')['duration_seconds'].sum()
            if not grouped.empty:
                self.ax_subj.bar(grouped.index, grouped.values/60)
                self.ax_subj.set_ylabel("Minutes (7 days)")
                self.ax_subj.set_title("Study Time per Subject")
        self.canvas_subj.draw()

    def _draw_daily_chart(self):
        ensure_csv_exists(self.csv_path)
        df = pd.read_csv(self.csv_path)
        self.ax_daily.clear()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            grouped = df.groupby('date')['duration_seconds'].sum()
            dates = grouped.index.strftime("%b %d")
            vals = grouped.values / 60
            self.ax_daily.plot(dates, vals, marker='o')
            self.ax_daily.set_ylabel("Minutes")
            self.ax_daily.set_title("Daily Study (last 14 days)")
        else:
            self.ax_daily.text(0.5,0.5,"No data",ha='center',va='center')
        self.canvas_daily.draw()

    def _refresh_overview(self):
        ensure_csv_exists(self.csv_path)
        df = pd.read_csv(self.csv_path)
        if df.empty:
            self.ov_label.configure(text="No logged sessions.")
            return
        df['date'] = pd.to_datetime(df['date'])
        today = pd.Timestamp.today().date()
        total_today = df[df['date'].dt.date==today]['duration_seconds'].sum()//60
        self.ov_label.configure(text=f"Today's total: {int(total_today)} min")

    def _toggle_voice(self):
        if self.voice_listening:
            self.voice_listening = False
            self.voice_btn.configure(text="🎤 Voice Command")
        else:
            self.voice_listening = True
            threading.Thread(target=self._voice_worker, daemon=True).start()

    def _voice_worker(self):
        speak("Listening for command.")
        text = listen_once()
        self.voice_listening = False
        if not text:
            speak("Try again.")
            return
        txt = text.lower()
        if "pause" in txt: self._pause_timer(); return
        if "stop" in txt: self._stop_and_save(); return
        subj, _ = parse_voice_start(txt)
        if subj:
            if subj not in self.subjects:
                self.subjects.append(subj)
                self.subject_menu.configure(values=self.subjects)
            self.current_subject.set(subj)
        self._start_timer()

if __name__ == "__main__":
    app = StudyTimerTargetApp()
    app.mainloop()
