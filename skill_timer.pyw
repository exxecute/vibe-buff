"""
Оверлей-таймер для скиллов в игре (Windows).

- Окно поверх всех окон (работает с играми в режиме "оконный без рамки" / borderless).
- Глобально следит за нажатием назначенной кнопки (клавиатура или боковые кнопки мыши),
  даже когда фокус в игре. Нажатие (пере)запускает таймер.
- Когда время почти вышло — подсвечивает, когда вышло — мигает и пищит, пока не нажмёшь кнопку.

Управление:
  ЛКМ + тянуть      — переместить оверлей
  ПКМ               — меню (добавить/настроить/удалить таймер, закрепить, выход)
  Ctrl+Alt+L        — закрепить/открепить (в закреплённом режиме клики проходят сквозь оверлей)

Без внешних зависимостей: только стандартный Python 3.
"""

import ctypes
import io
import json
import math
import os
import threading
import wave
from array import array
import time
import tkinter as tk
import winsound
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetParent.restype = wintypes.HWND
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_timer_config.json")

DEFAULT_CONFIG = {
    "x": 40,
    "y": 40,
    "alpha": 0.85,
    "font_size": 16,
    "locked": False,
    "sound": True,
    "volume": 0.5,
    "sound_file": "",  # свой .wav вместо встроенного колокольчика (необязательно)
    "beep_every": 4,
    "timers": [
        {"name": "Скилл", "key": 0x52, "seconds": 60, "warn": 10},  # R, 60 сек
    ],
}

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10

VK_CONTROL, VK_MENU, VK_L = 0x11, 0x12, 0x4C

VK_NAMES = {
    0x01: "ЛКМ", 0x02: "ПКМ", 0x04: "СКМ", 0x05: "Mouse4", 0x06: "Mouse5",
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt",
    0x14: "CapsLock", 0x1B: "Esc", 0x20: "Space",
    0x21: "PgUp", 0x22: "PgDn", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl", 0xA4: "LAlt", 0xA5: "RAlt",
    0xC0: "`",
}
VK_NAMES.update({0x70 + i: f"F{i + 1}" for i in range(24)})
VK_NAMES.update({0x60 + i: f"Num{i}" for i in range(10)})
VK_NAMES.update({0x30 + i: str(i) for i in range(10)})
VK_NAMES.update({0x41 + i: chr(0x41 + i) for i in range(26)})

# Обобщённые модификаторы дублируют L/R-варианты — при назначении кнопки их пропускаем
BIND_SKIP = {0x01, 0x02, 0x10, 0x11, 0x12}


def key_name(vk):
    return VK_NAMES.get(vk, f"VK {vk:#04x}")


def is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def fmt_time(sec):
    sec = max(0, int(sec + 0.999))
    return f"{sec // 60}:{sec % 60:02d}"


def make_chime(volume=0.5, rate=44100):
    """Мягкий колокольчик «динь-дон» (E6 → C6) в виде WAV-байтов."""
    duration = 1.6
    notes = [(1318.5, 0.0), (1046.5, 0.22)]
    partials = [(1.0, 1.0), (2.0, 0.25), (3.01, 0.08)]  # (множитель частоты, громкость)
    peak = 32767 * max(0.0, min(1.0, volume)) * 0.45
    samples = array("h")
    for n in range(int(duration * rate)):
        t = n / rate
        v = 0.0
        for freq, start in notes:
            dt = t - start
            if dt < 0:
                continue
            env = math.exp(-dt * 3.2) * min(1.0, dt / 0.006)
            for mul, amp in partials:
                v += amp * env * math.sin(2 * math.pi * freq * mul * dt) / (1 + mul * dt * 2)
        samples.append(int(max(-1.0, min(1.0, v / 1.4)) * peak))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class Timer:
    def __init__(self, data):
        self.data = data
        self.deadline = None  # None — ещё не запускался
        self.last_beep = 0.0

    def remaining(self):
        if self.deadline is None:
            return None
        return self.deadline - time.monotonic()

    def restart(self):
        self.deadline = time.monotonic() + float(self.data["seconds"])
        self.last_beep = 0.0


class Overlay:
    BG = "#14161c"
    COL_IDLE = "#8a8f9c"
    COL_OK = "#7CFC9A"
    COL_WARN = "#FFB347"
    COL_ALERT = "#FF4D4D"

    def __init__(self):
        self.cfg = load_config()
        self.timers = [Timer(t) for t in self.cfg["timers"]]
        self.prev_down = {}
        self.binding_cb = None  # колбэк, когда ждём нажатия для назначения кнопки
        self.blink = False
        self.chime = make_chime(self.cfg["volume"])

        self.root = tk.Tk()
        self.root.title("Skill Timer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.cfg["alpha"])
        self.root.configure(bg=self.BG)
        self.root.geometry(f"+{self.cfg['x']}+{self.cfg['y']}")

        self.frame = tk.Frame(self.root, bg=self.BG, padx=10, pady=6)
        self.frame.pack()
        self.rows = []
        self.build_rows()

        self.menu = tk.Menu(self.root, tearoff=0)
        self.root.bind_all("<ButtonPress-1>", self.drag_start)
        self.root.bind_all("<B1-Motion>", self.drag_move)
        self.root.bind_all("<ButtonRelease-1>", self.drag_end)
        self.root.bind_all("<Button-3>", self.show_menu)

        self.root.update_idletasks()
        self.hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self.apply_lock()

        self.poll_keys()
        self.tick()
        self.keep_on_top()

    # ---------- UI ----------
    def build_rows(self):
        for w in self.frame.winfo_children():
            w.destroy()
        self.rows = []
        font = ("Segoe UI", self.cfg["font_size"], "bold")
        small = ("Segoe UI", max(8, self.cfg["font_size"] - 6))
        if not self.timers:
            tk.Label(self.frame, text="ПКМ → добавить таймер", fg=self.COL_IDLE,
                     bg=self.BG, font=small).grid(row=0, column=0)
        for i, t in enumerate(self.timers):
            name = tk.Label(self.frame, text=t.data["name"], fg="#e6e6e6", bg=self.BG, font=font, anchor="w")
            key = tk.Label(self.frame, text=f"[{key_name(t.data['key'])}]", fg=self.COL_IDLE, bg=self.BG, font=small)
            val = tk.Label(self.frame, text="", bg=self.BG, font=font, width=8, anchor="e")
            name.grid(row=i, column=0, sticky="w")
            key.grid(row=i, column=1, padx=(6, 6))
            val.grid(row=i, column=2, sticky="e")
            self.rows.append(val)

    def tick(self):
        self.blink = not self.blink
        now = time.monotonic()
        for t, lbl in zip(self.timers, self.rows):
            rem = t.remaining()
            if rem is None:
                lbl.config(text="—", fg=self.COL_IDLE)
            elif rem > float(t.data.get("warn", 0)):
                lbl.config(text=fmt_time(rem), fg=self.COL_OK)
            elif rem > 0:
                lbl.config(text=fmt_time(rem), fg=self.COL_WARN)
            else:
                lbl.config(text="ОБНОВИ!", fg=self.COL_ALERT if self.blink else "#ffffff")
                if self.cfg["sound"] and now - t.last_beep >= float(self.cfg["beep_every"]):
                    t.last_beep = now
                    threading.Thread(target=self.beep, daemon=True).start()
        self.root.after(250, self.tick)

    def beep(self):
        path = self.cfg.get("sound_file")
        if path and os.path.isfile(path):
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        else:
            winsound.PlaySound(self.chime, winsound.SND_MEMORY)

    # ---------- Глобальные кнопки ----------
    def poll_keys(self):
        if self.binding_cb:
            for vk in range(1, 255):
                if vk in BIND_SKIP:
                    continue
                down = is_down(vk)
                if down and not self.prev_down.get(vk):
                    cb, self.binding_cb = self.binding_cb, None
                    cb(vk)
                    break
                self.prev_down[vk] = down
        else:
            watch = {t.data["key"] for t in self.timers} | {VK_L}
            for vk in watch:
                down = is_down(vk)
                if down and not self.prev_down.get(vk):
                    self.on_key(vk)
                self.prev_down[vk] = down
        self.root.after(15, self.poll_keys)

    def on_key(self, vk):
        if vk == VK_L and is_down(VK_CONTROL) and is_down(VK_MENU):
            self.toggle_lock()
            return
        for t in self.timers:
            if t.data["key"] == vk:
                t.restart()

    # ---------- Поверх всех / сквозные клики ----------
    def keep_on_top(self):
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.root.after(2000, self.keep_on_top)

    def apply_lock(self):
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if self.cfg["locked"]:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        self.root.attributes("-alpha", self.cfg["alpha"])  # переустановить прозрачность после смены стиля

    def toggle_lock(self):
        self.cfg["locked"] = not self.cfg["locked"]
        self.apply_lock()
        save_config(self.cfg)

    # ---------- Перетаскивание ----------
    def drag_start(self, e):
        if e.widget.winfo_toplevel() is not self.root:
            return
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def drag_move(self, e):
        if getattr(self, "_drag", None):
            dx, dy = self._drag
            self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def drag_end(self, e):
        if getattr(self, "_drag", None):
            self._drag = None
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
            save_config(self.cfg)

    # ---------- Меню ----------
    def show_menu(self, e):
        if e.widget.winfo_toplevel() is not self.root:
            return
        m = self.menu
        m.delete(0, "end")
        m.add_command(label="➕ Добавить таймер", command=lambda: self.edit_timer(None))
        for i, t in enumerate(self.timers):
            sub = tk.Menu(m, tearoff=0)
            sub.add_command(label="Настроить…", command=lambda i=i: self.edit_timer(i))
            sub.add_command(label="Сбросить", command=lambda t=t: setattr(t, "deadline", None))
            sub.add_command(label="Удалить", command=lambda i=i: self.remove_timer(i))
            m.add_cascade(label=f"{t.data['name']} [{key_name(t.data['key'])}]", menu=sub)
        m.add_separator()
        m.add_command(label="Общие настройки…", command=self.edit_general)
        m.add_command(label="🔒 Закрепить (Ctrl+Alt+L)", command=self.toggle_lock)
        m.add_separator()
        m.add_command(label="Выход", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    def dialog(self, title):
        d = tk.Toplevel(self.root)
        d.title(title)
        d.attributes("-topmost", True)
        d.resizable(False, False)
        d.geometry(f"+{self.root.winfo_x()}+{self.root.winfo_y() + self.root.winfo_height() + 10}")
        return d

    def edit_timer(self, idx):
        data = dict(self.timers[idx].data) if idx is not None else {"name": "Скилл", "key": 0x52, "seconds": 60, "warn": 10}
        d = self.dialog("Таймер")
        vars_ = {
            "name": tk.StringVar(value=data["name"]),
            "seconds": tk.StringVar(value=str(data["seconds"])),
            "warn": tk.StringVar(value=str(data.get("warn", 10))),
        }
        key = {"vk": data["key"]}
        rows = [("Название", "name"), ("Длительность (сек)", "seconds"), ("Предупредить за (сек)", "warn")]
        for r, (label, k) in enumerate(rows):
            tk.Label(d, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            tk.Entry(d, textvariable=vars_[k], width=18).grid(row=r, column=1, padx=8, pady=4)

        tk.Label(d, text="Кнопка").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        key_btn = tk.Button(d, text=key_name(key["vk"]), width=16)
        key_btn.grid(row=3, column=1, padx=8, pady=4)

        def got_key(vk):
            key["vk"] = vk
            key_btn.config(text=key_name(vk))

        def start_bind():
            key_btn.config(text="нажми кнопку…")
            # маленькая задержка, чтобы не поймать сам клик по кнопке
            self.root.after(200, lambda: setattr(self, "binding_cb", got_key))

        key_btn.config(command=start_bind)

        def save():
            try:
                seconds = float(vars_["seconds"].get().replace(",", "."))
                warn = float(vars_["warn"].get().replace(",", "."))
            except ValueError:
                return
            new = {"name": vars_["name"].get().strip() or "Скилл", "key": key["vk"],
                   "seconds": seconds, "warn": warn}
            if idx is None:
                self.timers.append(Timer(new))
            else:
                self.timers[idx].data = new
            self.sync_timers()
            d.destroy()

        tk.Button(d, text="Сохранить", command=save).grid(row=4, column=0, columnspan=2, pady=8)
        d.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "binding_cb", None), d.destroy()))

    def edit_general(self):
        d = self.dialog("Общие настройки")
        alpha = tk.DoubleVar(value=self.cfg["alpha"])
        size = tk.IntVar(value=self.cfg["font_size"])
        sound = tk.BooleanVar(value=self.cfg["sound"])
        every = tk.StringVar(value=str(self.cfg["beep_every"]))
        tk.Label(d, text="Прозрачность").grid(row=0, column=0, sticky="w", padx=8)
        tk.Scale(d, from_=0.3, to=1.0, resolution=0.05, orient="horizontal", variable=alpha,
                 command=lambda v: self.root.attributes("-alpha", float(v))).grid(row=0, column=1, padx=8)
        tk.Label(d, text="Размер шрифта").grid(row=1, column=0, sticky="w", padx=8)
        tk.Spinbox(d, from_=8, to=48, textvariable=size, width=6).grid(row=1, column=1, sticky="w", padx=8)
        volume = tk.DoubleVar(value=self.cfg["volume"])
        tk.Checkbutton(d, text="Звук", variable=sound).grid(row=2, column=0, sticky="w", padx=8)
        tk.Label(d, text="Звенеть каждые (сек)").grid(row=3, column=0, sticky="w", padx=8)
        tk.Entry(d, textvariable=every, width=6).grid(row=3, column=1, sticky="w", padx=8)
        tk.Label(d, text="Громкость").grid(row=4, column=0, sticky="w", padx=8)
        tk.Scale(d, from_=0.05, to=1.0, resolution=0.05, orient="horizontal",
                 variable=volume).grid(row=4, column=1, padx=8)

        def preview():
            self.chime = make_chime(float(volume.get()))
            threading.Thread(target=self.beep, daemon=True).start()

        tk.Button(d, text="▶ Проверить звук", command=preview).grid(row=5, column=0, columnspan=2, pady=(4, 0))

        def save():
            self.cfg["alpha"] = float(alpha.get())
            self.cfg["font_size"] = int(size.get())
            self.cfg["sound"] = bool(sound.get())
            self.cfg["volume"] = float(volume.get())
            self.chime = make_chime(self.cfg["volume"])
            try:
                self.cfg["beep_every"] = max(0.5, float(every.get().replace(",", ".")))
            except ValueError:
                pass
            self.root.attributes("-alpha", self.cfg["alpha"])
            self.build_rows()
            save_config(self.cfg)
            d.destroy()

        tk.Button(d, text="Сохранить", command=save).grid(row=6, column=0, columnspan=2, pady=8)

    def remove_timer(self, idx):
        del self.timers[idx]
        self.sync_timers()

    def sync_timers(self):
        self.cfg["timers"] = [t.data for t in self.timers]
        save_config(self.cfg)
        self.build_rows()

    def quit(self):
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_config(self.cfg)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    Overlay().run()
