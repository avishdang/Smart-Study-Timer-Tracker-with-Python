"""
study_timer_with_target.py

Features:
- Single-study timer (Start / Pause / Stop)
- Save session to CSV instantly on Stop (custom CSV path supported)
- Manual daily target input each run (not persisted)
- Progress bar showing today's progress toward the target
- Popup when daily target achieved
- Analytics (Per Subject last 7 days, Daily last 14 days)
- Voice commands supported

Dependencies:
    customtkinter, matplotlib, pandas, speechrecognition, pyttsx3, pyaudio
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

# ---------- Defaults ----------
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

# ---------- Voice Recognizer ----------
_recognizer = sr.Recognizer()
def listen_once(timeout=6, phrase_time_limit=6):
    try:
        with sr.Microphone() as source:
            _recognizer.adjust_for_ambient_noise(source, duration=0.6)
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        try:
            text = _recognizer.recognize_google(audio)
            return text
        except (sr.UnknownValueError, sr.RequestError):
            return None
    except Exception as e:
        print("Microphone error:", e)
        return None

# ---------- Utilities ----------
def ensure_csv_exists(path):
    if not os.path.exists(path):
        df = pd.DataFrame(columns=["timestamp","date","subject","duration_seconds"])
        # ensure parent dir exists
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
    mins = sec // 60
    secs = sec % 60
    return f"{mins:02d}:{secs:02d}"

# ---------- Voice move parsing (small) ----------
word_to_num = {"one":1,"1":1,"two":2,"2":2,"three":3,"3":3,"four":4,"4":4,"five":5,"5":5}
def parse_voice_start(text):
    """
    Try to extract subject and optional minutes from a voice command.
    Returns (subject_or_None, minutes_or_None)
    """
    if not text:
        return None, None
    txt = text.lower()
    # look for 'for <subject>' or 'for math'
    m = re.search(r"for\s+([a-zA-Z ]+?)(?:\s|$)", txt)
    subj = None
    minutes = None
    if m:
        subj = m.group(1).strip().title()
        subj = re.sub(r"\d+", "", subj).strip()
    # look for number (minutes)
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
        self.geometry("980x660")
        self.resizable(False, False)

        # state
        self.subjects = DEFAULT_SUBJECTS.copy()
        self.current_subject = tk.StringVar(value=self.subjects[0])
        self.csv_path = os.path.join(os.getcwd(), DEFAULT_CSV_NAME)  # default path in cwd
        self.daily_target_minutes = tk.IntVar(value=60)  # manual each run
        self.today_minutes = 0

        # timer state
        self.timer_running = False
        self.start_time = None
        self.accumulated_seconds = 0
        self._timer_job = None

        # voice
        self.voice_listening = False

        # analytics figures
        self.fig_subj = None
        self.fig_daily = None

        # build UI
        ensure_csv_exists(self.csv_path)
        self._build_ui()
        self._refresh_timer_display()
        self._refresh_recent_sessions()
        self._refresh_all_charts()

    # ---- UI ----
    def _build_ui(self):
        root_frame = ctk.CTkFrame(self)
        root_frame.pack(fill="both", expand=True, padx=16, pady=16)

        # Top bar: title and CSV path selection
        top = ctk.CTkFrame(root_frame, corner_radius=12)
        top.pack(fill="x", pady=(0,12))

        title = ctk.CTkLabel(top, text="📘 Study Timer — Daily Target", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(side="left", padx=12, pady=10)

        path_btn = ctk.CTkButton(top, text="Set CSV Path", width=140, command=self._choose_csv_path)
        path_btn.pack(side="right", padx=8)
        path_lbl = ctk.CTkLabel(top, text="(Default: current folder)", text_color="#94A3B8")
        path_lbl.pack(side="right", padx=(0,6))

        # Main layout: left controls, center timer, right analytics
        main = ctk.CTkFrame(root_frame)
        main.pack(fill="both", expand=True)

        left = ctk.CTkFrame(main, width=300)
        left.pack(side="left", fill="y", padx=(0,12))

        center = ctk.CTkFrame(main)
        center.pack(side="left", fill="both", expand=True)

        right = ctk.CTkFrame(main, width=380)
        right.pack(side="right", fill="both", padx=(12,0))

        # --- Left: subject, target, controls, recent ---
        ctk.CTkLabel(left, text="Subject", font=ctk.CTkFont(size=14)).pack(pady=(12,4))
        self.subject_menu = ctk.CTkOptionMenu(left, values=self.subjects, variable=self.current_subject, width=220)
        self.subject_menu.pack(pady=(0,12))

        add_sub = ctk.CTkButton(left, text="➕ Add Subject", width=220, command=self._add_subject)
        add_sub.pack(pady=(0,12))

        ctk.CTkLabel(left, text="Daily Target (minutes)", font=ctk.CTkFont(size=14)).pack(pady=(8,4))
        target_entry = ctk.CTkEntry(left, textvariable=self.daily_target_minutes, width=120)
        target_entry.pack(pady=(0,6))

        # progress bar & label
        self.progress_label = ctk.CTkLabel(left, text="Today's progress: 0 / 60 min")
        self.progress_label.pack(pady=(8,4))
        self.progress = ctk.CTkProgressBar(left, width=220)
        self.progress.set(0.0)
        self.progress.pack(pady=(0,12))

        # timer controls
        ctk.CTkLabel(left, text="Controls", font=ctk.CTkFont(size=14)).pack(pady=(6,6))
        self.start_btn = ctk.CTkButton(left, text="▶ Start", width=100, command=self._start_timer)
        self.start_btn.pack(pady=(6,4))
        self.pause_btn = ctk.CTkButton(left, text="⏸ Pause", width=100, command=self._pause_timer)
        self.pause_btn.pack(pady=(6,4))
        self.stop_btn = ctk.CTkButton(left, text="⏹ Stop Study (Save)", width=150, fg_color="#ef4444", hover_color="#e11d48", command=self._stop_and_save)
        self.stop_btn.pack(pady=(12,8))

        # voice
        self.voice_btn = ctk.CTkButton(left, text="🎤 Voice Command", width=160, command=self._toggle_voice)
        self.voice_btn.pack(pady=(6,4))
        ctk.CTkLabel(left, text="Say: 'Start study for Math 45', 'Pause', 'Stop'", text_color="#94A3B8").pack(pady=(4,12))

        # recent sessions list
        ctk.CTkLabel(left, text="Recent Sessions", font=ctk.CTkFont(size=14)).pack(pady=(6,4))
        self.recent_list = tk.Listbox(left, height=8, width=36)
        self.recent_list.pack(pady=(2,8))

        # --- Center: big timer display & quick buttons ---
        self.mode_label = ctk.CTkLabel(center, text="Study", font=ctk.CTkFont(size=18))
        self.mode_label.pack(pady=(28,6))
        self.time_label = ctk.CTkLabel(center, text="00:00", font=ctk.CTkFont(size=72, weight="bold"))
        self.time_label.pack(pady=(8,12))

        quick_frame = ctk.CTkFrame(center)
        quick_frame.pack(pady=(6,12))
        ctk.CTkButton(quick_frame, text="Reset Timer", width=140, command=self._reset_timer).pack(side="left", padx=8)
        ctk.CTkButton(quick_frame, text="Refresh Analytics", width=160, command=self._refresh_all_charts).pack(side="left", padx=8)

        # small note
        ctk.CTkLabel(center, text="When you Stop Study the session is saved to CSV immediately.", text_color="#94A3B8").pack(pady=(8,14))

        # --- Right: analytics (tabs) ---
        tabs = ctk.CTkTabview(right, width=360)
        tabs.pack(fill="both", expand=True, pady=(12,12))
        tabs.add("Overview")
        tabs.add("Per Subject")
        tabs.add("Daily")

        # Overview tab
        ov = tabs.tab("Overview")
        self.ov_label = ctk.CTkLabel(ov, text="No data yet", font=ctk.CTkFont(size=14))
        self.ov_label.pack(pady=18)

        # Per Subject chart
        ps = tabs.tab("Per Subject")
        self.fig_subj = Figure(figsize=(4.2,3), dpi=100)
        self.ax_subj = self.fig_subj.add_subplot(111)
        self.canvas_subj = FigureCanvasTkAgg(self.fig_subj, master=ps)
        self.canvas_subj.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        # Daily chart
        dw = tabs.tab("Daily")
        self.fig_daily = Figure(figsize=(4.2,3), dpi=100)
        self.ax_daily = self.fig_daily.add_subplot(111)
        self.canvas_daily = FigureCanvasTkAgg(self.fig_daily, master=dw)
        self.canvas_daily.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    # ---- CSV Path selection ----
    def _choose_csv_path(self):
        # ask for folder or file location
        file = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], initialfile=DEFAULT_CSV_NAME)
        if file:
            # create parent dir and ensure file exists
            os.makedirs(os.path.dirname(file) or ".", exist_ok=True)
            self.csv_path = file
            ensure_csv_exists(self.csv_path)
            speak("CSV path set.")
            messagebox.showinfo("CSV Path", f"CSV path set to:\n{self.csv_path}")

    # ---- Subjects ----
    def _add_subject(self):
        ans = simpledialog.askstring("Add Subject", "Enter subject name:", parent=self)
        if ans and ans.strip():
            s = ans.strip().title()
            if s not in self.subjects:
                self.subjects.append(s)
                self.subject_menu.configure(values=self.subjects)
                self.current_subject.set(s)
                speak(f"Added subject {s}")
            else:
                messagebox.showinfo("Info", "Subject already exists.")

    # ---- Timer functions ----
    def _start_timer(self):
        if self.timer_running:
            return
        self.timer_running = True
        self.start_time = time.time()
        self._tick()
        speak(f"Started study for {self.current_subject.get()}")

    def _pause_timer(self):
        if not self.timer_running:
            return
        elapsed = time.time() - self.start_time if self.start_time else 0
        self.accumulated_seconds += elapsed
        self.start_time = None
        self.timer_running = False
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        speak("Paused.")
        self._refresh_timer_display()

    def _reset_timer(self):
        was_running = self.timer_running
        self.timer_running = False
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        self.start_time = None
        self.accumulated_seconds = 0
        self._refresh_timer_display()
        if was_running:
            speak("Timer reset.")

    def _stop_and_save(self):
        # compute total seconds
        elapsed = 0
        if self.timer_running and self.start_time:
            elapsed = time.time() - self.start_time
        total_seconds = self.accumulated_seconds + elapsed
        if total_seconds <= 0:
            messagebox.showinfo("No Study Time", "No study time recorded to save.")
            return
        subj = self.current_subject.get()
        append_session_csv(self.csv_path, subj, int(total_seconds))
        # reset timer
        self.timer_running = False
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        self.start_time = None
        self.accumulated_seconds = 0
        self._refresh_timer_display()
        speak(f"Saved session: {subj} — {int(total_seconds//60)} minutes")
        messagebox.showinfo("Saved", f"Saved {subj} — {int(total_seconds//60)} min to:\n{self.csv_path}")
        # refresh recent & analytics & progress
        self._refresh_recent_sessions()
        self._refresh_all_charts()
        # check daily target and popup
        self._check_daily_target_and_notify()

    def _tick(self):
        if not self.timer_running:
            return
        self._refresh_timer_display()
        self._timer_job = self.after(1000, self._tick)

    def _refresh_timer_display(self):
        current = self.accumulated_seconds
        if self.timer_running and self.start_time:
            current += (time.time() - self.start_time)
        self.time_label.configure(text=seconds_to_mmss(current))

    # ---- Recent sessions & analytics ----
    def _refresh_recent_sessions(self):
        ensure_csv_exists(self.csv_path)
        try:
            df = pd.read_csv(self.csv_path)
            last = df.tail(8).iloc[::-1] if not df.empty else pd.DataFrame()
            self.recent_list.delete(0, tk.END)
            for _, row in last.iterrows():
                t = row.get("timestamp", "")
                subj = row.get("subject", "")
                dur = int(row.get("duration_seconds", 0))
                try:
                    ts = datetime.datetime.fromisoformat(t).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    ts = str(t)
                self.recent_list.insert(tk.END, f"{ts} | {subj} | {dur//60}m")
        except Exception as e:
            print("Recent refresh error:", e)

    def _draw_subject_chart(self):
        ensure_csv_exists(self.csv_path)
        df = pd.read_csv(self.csv_path)
        self.ax_subj = self.fig_subj.subplots()[0] if hasattr(self, "ax_subj") is False else self.ax_subj
        self.ax_subj.clear()
        if df.empty:
            self.ax_subj.text(0.5, 0.5, "No data", ha='center', va='center')
            self.canvas_subj.draw()
            return
        df['date'] = pd.to_datetime(df['date'])
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=7)
        df_recent = df[df['date'] >= cutoff]
        grouped = df_recent.groupby('subject')['duration_seconds'].sum().sort_values(ascending=False)
        if grouped.empty:
            self.ax_subj.text(0.5, 0.5, "No recent data (7 days)", ha='center', va='center')
        else:
            labels = grouped.index.tolist()
            values = (grouped.values / 60)
            bars = self.ax_subj.bar(labels, values)
            self.ax_subj.set_ylabel("Minutes (7 days)")
            self.ax_subj.set_title("Study time per subject (7 days)")
            self.ax_subj.set_xticklabels(labels, rotation=30, ha='right')
        self.canvas_subj.draw()

    def _draw_daily_chart(self):
        ensure_csv_exists(self.csv_path)
        df = pd.read_csv(self.csv_path)
        self.ax_daily = self.fig_daily.subplots()[0] if hasattr(self, "ax_daily") is False else self.ax_daily
        self.ax_daily.clear()
        if df.empty:
            self.ax_daily.text(0.5, 0.5, "No data", ha='center', va='center')
            self.canvas_daily.draw()
            return
        df['date'] = pd.to_datetime(df['date'])
        end = pd.Timestamp.today()
        start = end - pd.Timedelta(days=13)
        rng = pd.date_range(start=start, end=end)
        grouped = df.groupby('date')['duration_seconds'].sum()
        vals = []
        for d in rng.date:
            vals.append(grouped.get(pd.Timestamp(d), 0)/60)
        dates = [d.strftime("%b %d") for d in rng]
        self.ax_daily.plot(dates, vals, marker='o')
        self.ax_daily.set_title("Daily study minutes (last 14 days)")
        self.ax_daily.set_ylabel("Minutes")
        self.ax_daily.set_xticks(range(len(dates)))
        self.ax_daily.set_xticklabels(dates, rotation=40, ha='right')
        self.canvas_daily.draw()

    def _refresh_overview(self):
        ensure_csv_exists(self.csv_path)
        df = pd.read_csv(self.csv_path)
        if df.empty:
            self.ov_label.configure(text="No logged sessions yet.")
            self.today_minutes = 0
        else:
            df['date'] = pd.to_datetime(df['date'])
            today = pd.Timestamp.today().date()
            total_today = df[df['date'].dt.date == today]['duration_seconds'].sum() // 60
            week_start = today - datetime.timedelta(days=today.weekday())
            total_week = df[df['date'].dt.date >= week_start]['duration_seconds'].sum() // 60
            self.ov_label.configure(text=f"Today: {int(total_today)} min  •  This week: {int(total_week)} min")
            self.today_minutes = int(total_today)
        # update progress bar
        target = max(1, int(self.daily_target_minutes.get() or 60))
        fraction = min(1.0, self.today_minutes / target) if target > 0 else 0.0
        self.progress.set(fraction)
        self.progress_label.configure(text=f"Today's progress: {self.today_minutes} / {target} min")

    def _refresh_all_charts(self):
        self._draw_subject_chart()
        self._draw_daily_chart()
        self._refresh_overview()
        self._refresh_recent_sessions()

    # ---- Daily target check on save ----
    def _check_daily_target_and_notify(self):
        # recompute today total from CSV
        ensure_csv_exists(self.csv_path)
        try:
            df = pd.read_csv(self.csv_path)
            if df.empty:
                total_today = 0
            else:
                df['date'] = pd.to_datetime(df['date'])
                today = pd.Timestamp.today().date()
                total_today = df[df['date'].dt.date == today]['duration_seconds'].sum() // 60
        except Exception as e:
            print("Target check error:", e)
            total_today = self.today_minutes
        target = max(1, int(self.daily_target_minutes.get() or 60))
        # update progress and overview
        self.today_minutes = int(total_today)
        self._refresh_overview()
        if total_today >= target:
            # show popup congratulating user
            messagebox.showinfo("Target achieved 🎉", f"Congrats — you reached your daily target of {target} minutes!\nYou studied {int(total_today)} minutes today.")
            speak(f"Congratulations. You have achieved your daily goal of {target} minutes. You can take a break.")

    # ---- Voice handling ----
    def _toggle_voice(self):
        if self.voice_listening:
            self.voice_listening = False
            self.voice_btn.configure(text="🎤 Voice Command")
            speak("Stopped listening.")
        else:
            self.voice_listening = True
            self.voice_btn.configure(text="🎧 Listening...")
            t = threading.Thread(target=self._voice_worker, daemon=True)
            t.start()

    def _voice_worker(self):
        speak("Listening for command.")
        text = listen_once()
        self.voice_listening = False
        self.voice_btn.configure(text="🎤 Voice Command")
        if not text:
            speak("I didn't hear anything. Try again.")
            return
        txt = text.lower()
        # pause or stop
        if re.search(r"\b(pause|stop|end)\b", txt):
            if "pause" in txt:
                self._pause_timer()
                return
            else:
                self._stop_and_save()
                return
        # start commands
        if re.search(r"\b(start|begin)\b", txt):
            subj, minutes = parse_voice_start(txt)
            if subj:
                if subj not in self.subjects:
                    self.subjects.append(subj)
                    self.subject_menu.configure(values=self.subjects)
                self.current_subject.set(subj)
            # ignore minutes for enforced duration — we just start and user stops when done
            self._start_timer()
            return
        # fallback
        self._start_timer()

# ---------- Run ----------
if __name__ == "__main__":
    app = StudyTimerTargetApp()
    app.mainloop()
