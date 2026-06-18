# -*- coding: utf-8 -*-
"""
Neo Vocaster RackStrip FIXED6

Slim vertical control strip for a side monitor.
- Original Vocaster Hub runs in the background as backend.
- This app controls the original Hub through Windows UI Automation.
- No binary patching. No firmware modification.

Install:
    py -m pip install pywinauto comtypes pywin32 six

Run:
    py neo_vocaster_rackstrip.py
"""

import ctypes
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import Tk, Canvas, filedialog

from pywinauto import Desktop


APP_NAME = "Neo Vocaster RackStrip"
TITLE_KEYWORD = "Vocaster Hub"

CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "NeoVocasterHub"
CONFIG_PATH = CONFIG_DIR / "rackstrip_config.json"

COMMON_HUB_PATHS = [
    r"C:\Program Files\Focusrite\Vocaster Hub\Vocaster Hub.exe",
    r"C:\Program Files\Focusrite\Vocaster Hub\VocasterHub.exe",
    r"C:\Program Files (x86)\Focusrite\Vocaster Hub\Vocaster Hub.exe",
]

SLIDER_MAP = {
    "host_mic": 0,
    "guest_mic": 1,
    "host_mix": 2,
    "guest_mix": 3,
    "aux": 4,
    "bluetooth": 5,
    "loopback1": 6,
    "loopback2": 7,
    "showmix": 8,
}

RANGES = {
    "host_mic": (0.0, 70.0),
    "guest_mic": (0.0, 70.0),
    "aux": (-70.0, 0.0),
    "bluetooth": (0.0, 30.0),
}


# ---------- small math/helpers ----------

def clamp(x, lo, hi):
    if lo <= hi:
        return max(lo, min(hi, x))
    return max(hi, min(lo, x))


def pct_from_range(value, lo, hi):
    if hi == lo:
        return 0.0
    return clamp((value - lo) / (hi - lo), 0.0, 1.0)


def value_from_pct(pct, lo, hi):
    pct = clamp(pct, 0.0, 1.0)
    return lo + pct * (hi - lo)


def native_to_display_pct(value, lo, hi, gamma=1.0):
    """Map native hardware value to UI display percent.

    gamma < 1 visually lifts the upper/meaningful range.
    This changes only how the fader is shown/dragged in this UI.
    The backend hardware value remains unchanged.
    """
    p = pct_from_range(value, lo, hi)
    gamma = max(0.01, float(gamma))
    return clamp(p ** gamma, 0.0, 1.0)


def display_pct_to_native(display_pct, lo, hi, gamma=1.0):
    """Inverse of native_to_display_pct()."""
    display_pct = clamp(display_pct, 0.0, 1.0)
    gamma = max(0.01, float(gamma))
    native_pct = display_pct ** (1.0 / gamma)
    return value_from_pct(native_pct, lo, hi)


def gamma_map(source_value, source_min, source_max, target_min, target_max, gamma=1.0):
    p = pct_from_range(source_value, source_min, source_max)
    gamma = max(0.01, float(gamma))
    p = p ** gamma
    return value_from_pct(p, target_min, target_max)


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "hub_path": "",
        "hide_original": True,
        "always_on_top": True,
        "geometry": "390x1040+0+0",
        "host_to_aux": True,
        "guest_to_bt": False,
        "aux_gamma": 0.25,
        "bt_gamma": 1.0,
        "mix_visual_gamma": 0.5,
        "threshold": 0.10,
        "poll": 0.045,
    }


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def resource_path(relative_path):
    """Return resource path for both normal Python run and PyInstaller onefile.

    --icon changes the EXE file icon.
    Tkinter window/taskbar icon needs iconbitmap(), so icon.ico must also be
    bundled with --add-data "icon.ico;.".
    """
    try:
        base_path = Path(sys._MEIPASS)
    except Exception:
        base_path = Path(__file__).resolve().parent
    return base_path / relative_path


def virtual_screen_bounds():
    """Return virtual desktop bounds: left, top, width, height.

    Works when a secondary monitor is placed left of the main display.
    Falls back to primary screen if Windows metrics are unavailable.
    """
    try:
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))    # SM_XVIRTUALSCREEN
        top = int(user32.GetSystemMetrics(77))     # SM_YVIRTUALSCREEN
        width = int(user32.GetSystemMetrics(78))   # SM_CXVIRTUALSCREEN
        height = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
        if width > 0 and height > 0:
            return left, top, width, height
    except Exception:
        pass
    return 0, 0, 1920, 1080


# ---------- backend: original Vocaster Hub via UIA ----------

class HubBackend:
    def __init__(self):
        self.win = None
        self.sliders = []
        self.process = None
        self.lock = threading.RLock()

    def launch(self, path=""):
        candidates = []
        path = str(path).strip('" ').strip()
        if path:
            candidates.append(path)
        candidates.extend(COMMON_HUB_PATHS)

        for candidate in candidates:
            if Path(candidate).exists():
                flags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    flags = subprocess.CREATE_NO_WINDOW
                try:
                    self.process = subprocess.Popen([candidate], creationflags=flags)
                    time.sleep(1.2)
                    return True, f"Launched: {candidate}"
                except Exception as e:
                    return False, f"Launch failed: {e!r}"

        return False, "Hub EXE not found. Launch original Vocaster Hub manually or choose path."

    def connect(self):
        with self.lock:
            desktop = Desktop(backend="uia")
            candidates = []

            for w in desktop.windows():
                try:
                    title = w.window_text()
                    if TITLE_KEYWORD.lower() not in title.lower():
                        continue
                    rect = w.rectangle()
                    area = max(0, rect.width()) * max(0, rect.height())
                    candidates.append((area, w))
                except Exception:
                    pass

            if not candidates:
                raise RuntimeError("Vocaster Hub window not found.")

            candidates.sort(key=lambda item: item[0], reverse=True)
            self.win = candidates[0][1]
            self.refresh()
            return True

    def refresh(self):
        with self.lock:
            if self.win is None:
                self.connect()

            sliders = []
            for c in self.win.descendants(control_type="Slider"):
                try:
                    info = c.element_info
                    rv = c.iface_range_value
                    sliders.append({
                        "wrapper": c,
                        "name": info.name,
                        "value": float(rv.CurrentValue),
                        "min": float(rv.CurrentMinimum),
                        "max": float(rv.CurrentMaximum),
                    })
                except Exception:
                    pass

            self.sliders = sliders
            return sliders

    def hide_original(self):
        with self.lock:
            if self.win is None:
                return
            try:
                # Keep the UI alive and fully laid out, just move it outside the visible desktop.
                self.win.move_window(x=-2400, y=200, width=1350, height=1020, repaint=False)
            except Exception:
                try:
                    self.win.minimize()
                except Exception:
                    pass

    def show_original(self):
        with self.lock:
            if self.win is None:
                return
            try:
                self.win.restore()
                self.win.move_window(x=120, y=120, width=1350, height=1020, repaint=True)
            except Exception:
                pass

    def _slider(self, idx):
        with self.lock:
            if not self.sliders or idx >= len(self.sliders):
                self.refresh()

            if idx >= len(self.sliders):
                raise RuntimeError(f"Slider index {idx} missing. Found {len(self.sliders)} sliders.")

            return self.sliders[idx]["wrapper"]

    def native_range(self, idx):
        slider = self._slider(idx)
        rv = slider.iface_range_value
        return float(rv.CurrentMinimum), float(rv.CurrentMaximum)

    def get(self, idx):
        slider = self._slider(idx)
        return float(slider.iface_range_value.CurrentValue)

    def set(self, idx, value):
        slider = self._slider(idx)
        rv = slider.iface_range_value
        lo = float(rv.CurrentMinimum)
        hi = float(rv.CurrentMaximum)
        rv.SetValue(clamp(float(value), lo, hi))


# ---------- custom canvas controls ----------

class VToggle:
    def __init__(self, app, x, y, label, getter, setter, accent="#62C03A"):
        self.app = app
        self.c = app.canvas
        self.x = x
        self.y = y
        self.label = label
        self.getter = getter
        self.setter = setter
        self.accent = accent
        self.draw()

    def draw(self):
        c = self.c
        x, y = self.x, self.y

        self.label_item = c.create_text(
            x, y,
            text=self.label,
            fill="#B7B7BA",
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        )

        # Premium compact switch: not bubbly, not toy-like.
        self.track = c.create_round_rect(
            x + 178, y - 12, x + 242, y + 12,
            radius=6,
            fill="#171719",
            outline="#3A3A3C",
            width=1,
            tags=("clickable",),
        )
        self.inner = c.create_rectangle(
            x + 183, y - 7, x + 237, y + 7,
            fill="#202023",
            outline="",
            tags=("clickable",),
        )
        self.led = c.create_oval(
            x + 188, y - 4, x + 196, y + 4,
            fill="#505052",
            outline="",
            tags=("clickable",),
        )
        self.state_text = c.create_text(
            x + 225, y,
            text="OFF",
            fill="#77777A",
            font=("Segoe UI", 7, "bold"),
            tags=("clickable",),
        )

        for item in (self.track, self.inner, self.led, self.state_text):
            c.tag_bind(item, "<Button-1>", self.toggle)

        self.redraw()

    def toggle(self, event=None):
        self.setter(not self.getter())
        self.redraw()
        self.app.save_runtime_config()

    def redraw(self):
        on = bool(self.getter())
        if on:
            self.c.itemconfig(self.track, fill="#1F2A1F", outline=self.accent)
            self.c.itemconfig(self.inner, fill="#162016")
            self.c.coords(self.led, self.x + 226, self.y - 4, self.x + 234, self.y + 4)
            self.c.itemconfig(self.led, fill=self.accent)
            self.c.itemconfig(self.state_text, text="ON", fill="#E6F6E0")
            self.c.coords(self.state_text, self.x + 195, self.y)
        else:
            self.c.itemconfig(self.track, fill="#171719", outline="#3A3A3C")
            self.c.itemconfig(self.inner, fill="#202023")
            self.c.coords(self.led, self.x + 188, self.y - 4, self.x + 196, self.y + 4)
            self.c.itemconfig(self.led, fill="#505052")
            self.c.itemconfig(self.state_text, text="OFF", fill="#77777A")
            self.c.coords(self.state_text, self.x + 225, self.y)

class RotaryKnob:
    def __init__(self, app, x, y, r, label, key, slider_index, value_range, accent="#E5C043"):
        self.app = app
        self.c = app.canvas
        self.x = x
        self.y = y
        self.r = r
        self.label = label
        self.key = key
        self.slider_index = slider_index
        self.value_range = value_range
        self.accent = accent
        self.value = 0.0
        self.drag_start_y = None
        self.drag_start_value = None
        self.draw()

    def draw(self):
        c = self.c
        x, y, r = self.x, self.y, self.r

        # Tkinter has no high-quality antialiasing, so keep the knob mostly flat.
        c.create_oval(x - r + 2, y - r + 4, x + r + 2, y + r + 4, fill="#151515", outline="")
        c.create_oval(x - r, y - r, x + r, y + r, fill="#2C2C2E", outline="#111111", width=2)
        c.create_oval(x - r + 8, y - r + 8, x + r - 8, y + r - 8, fill="#1E1E1E", outline="#3A3A3C", width=1)

        c.create_arc(
            x - r + 14, y - r + 14, x + r - 14, y + r - 14,
            start=-40,
            extent=260,
            style="arc",
            outline="#303030",
            width=4,
        )

        self.pointer = c.create_oval(
            x - 5, y - r + 10, x + 5, y - r + 20,
            fill=self.accent,
            outline="#111111",
            width=1,
        )

        self.value_text = c.create_text(
            x, y + r + 20,
            text="0%",
            fill="#E0E0E0",
            font=("Segoe UI", 9, "bold"),
        )
        c.create_text(
            x, y + r + 40,
            text=self.label.upper(),
            fill="#8A8A8C",
            font=("Segoe UI", 9, "bold"),
            justify="center",
        )

        # Hit target. No wheel binding here: wheel is routed globally by RackApp.
        hit = c.create_oval(x - r, y - r, x + r, y + r, fill="", outline="", tags=("knobhit",))
        c.tag_bind(hit, "<Button-1>", self.on_down)
        c.tag_bind(hit, "<B1-Motion>", self.on_drag)

    def set_visual_from_value(self, value):
        self.value = value
        lo, hi = self.value_range
        pct = pct_from_range(value, lo, hi)

        angle = math.radians(225 - pct * 270)
        rr = self.r - 15
        px = self.x + math.cos(angle) * rr
        py = self.y - math.sin(angle) * rr

        self.c.coords(self.pointer, px - 5, py - 5, px + 5, py + 5)
        self.c.itemconfig(self.value_text, text=f"{pct * 100:.0f}%")

    def on_down(self, event):
        self.drag_start_y = event.y
        self.drag_start_value = self.value

    def on_drag(self, event):
        if self.drag_start_y is None:
            return

        dy = self.drag_start_y - event.y
        lo, hi = self.value_range
        span = hi - lo
        new_value = self.drag_start_value + (dy / 140.0) * span
        new_value = clamp(new_value, lo, hi)

        try:
            self.app.backend.set(self.slider_index, new_value)
        except Exception as e:
            self.app.set_status(f"SET ERR {e!r}", False)


class VFader:
    def __init__(self, app, x, y, h, label, key, slider_index, value_range, accent="#62C03A", display_gamma=1.0):
        self.app = app
        self.c = app.canvas
        self.x = x
        self.y = y
        self.h = h
        self.label = label
        self.key = key
        self.slider_index = slider_index
        self.value_range = value_range
        self.accent = accent
        self.display_gamma = display_gamma
        self.value = 0.0
        self.dragging = False
        self.draw()

    def draw(self):
        c = self.c
        x, y, h = self.x, self.y, self.h

        c.create_rectangle(x - 4, y, x + 4, y + h, fill="#0D0D0D", outline="#1F1F1F", width=1)

        for i in range(0, 11):
            yy = y + i * h / 10
            major = (i % 2 == 0)
            length = 22 if major else 12
            color = "#505052" if major else "#333336"
            width = 2 if major else 1
            c.create_line(x - 30, yy, x - 30 + length, yy, fill=color, width=width)
            c.create_line(x + 30, yy, x + 30 - length, yy, fill=color, width=width)

        self.fill = c.create_rectangle(x - 2, y + h, x + 2, y + h, fill=self.accent, outline="")

        # Clean console fader cap. No diagonal grooves/stripes.
        self.shadow = c.create_rectangle(x - 25, y + h - 13, x + 25, y + h + 17, fill="#111111", outline="")
        self.handle = c.create_rectangle(x - 24, y + h - 16, x + 24, y + h + 16,
                                         fill="#2D2D30", outline="#4B4B4E", width=1)
        self.highlight = c.create_line(x - 20, y + h - 11, x + 20, y + h - 11,
                                       fill="#555558", width=1)
        self.pointer = c.create_rectangle(x - 24, y + h - 2, x + 24, y + h + 2,
                                          fill="#D8D8D8", outline="")

        self.value_text = c.create_text(
            x, y + h + 45,
            text="0%",
            fill="#E0E0E0",
            font=("Segoe UI", 9, "bold"),
        )
        c.create_text(
            x, y + h + 65,
            text=self.label.upper(),
            fill="#8A8A8C",
            font=("Segoe UI", 9, "bold"),
            justify="center",
        )

        for item in (self.handle, self.pointer, self.shadow, self.highlight):
            c.tag_bind(item, "<Button-1>", self.on_down)
            c.tag_bind(item, "<B1-Motion>", self.on_drag)
            c.tag_bind(item, "<ButtonRelease-1>", self.on_up)

    def get_range(self):
        if self.value_range is not None:
            return self.value_range

        try:
            return self.app.backend.native_range(self.slider_index)
        except Exception:
            return 0.0, 100.0

    def set_visual_from_value(self, value):
        self.value = value
        lo, hi = self.get_range()
        native_pct = pct_from_range(value, lo, hi)
        display_pct = native_to_display_pct(value, lo, hi, self.display_gamma)

        x, y, h = self.x, self.y, self.h
        yy = y + h - display_pct * h

        self.c.coords(self.shadow, x - 25, yy - 13, x + 25, yy + 17)
        self.c.coords(self.handle, x - 24, yy - 16, x + 24, yy + 16)
        self.c.coords(self.highlight, x - 20, yy - 11, x + 20, yy - 11)
        self.c.coords(self.pointer, x - 24, yy - 2, x + 24, yy + 2)
        self.c.coords(self.fill, x - 2, yy, x + 2, y + h)
        self.c.itemconfig(self.value_text, text=f"{native_pct * 100:.0f}%")

    def value_from_y(self, yy):
        lo, hi = self.get_range()
        display_pct = 1.0 - (yy - self.y) / self.h
        display_pct = clamp(display_pct, 0.0, 1.0)
        return display_pct_to_native(display_pct, lo, hi, self.display_gamma)

    def on_down(self, event):
        self.dragging = True
        self.on_drag(event)

    def on_drag(self, event):
        try:
            value = self.value_from_y(event.y)
            self.app.backend.set(self.slider_index, value)
        except Exception as e:
            self.app.set_status(f"SET ERR {e!r}", False)

    def on_up(self, event):
        self.dragging = False

# ---------- main app ----------

class RackApp(Tk):
    def __init__(self):
        super().__init__()

        self.cfg = load_config()
        self.backend = HubBackend()
        self.running = True
        self.connected = False

        self.host_to_aux = bool(self.cfg.get("host_to_aux", True))
        self.guest_to_bt = bool(self.cfg.get("guest_to_bt", False))
        self.hide_original = bool(self.cfg.get("hide_original", True))
        self.always_on_top = bool(self.cfg.get("always_on_top", True))
        self.aux_gamma = float(self.cfg.get("aux_gamma", 0.25))
        self.bt_gamma = float(self.cfg.get("bt_gamma", 1.0))
        self.mix_visual_gamma = float(self.cfg.get("mix_visual_gamma", 0.5))
        self.threshold = float(self.cfg.get("threshold", 0.10))
        self.poll = float(self.cfg.get("poll", 0.045))
        self.hub_path = str(self.cfg.get("hub_path", ""))

        self.last_host = None
        self.last_guest = None

        self.title(APP_NAME)
        try:
            self.iconbitmap(str(resource_path("icon.ico")))
        except Exception:
            pass
        self.geometry(self.cfg.get("geometry", "390x1040+0+0"))
        self.minsize(340, 760)
        self.attributes("-topmost", self.always_on_top)
        self.configure(bg="#1E1E1E")

        self.canvas = Canvas(self, width=390, height=1040, bg="#1E1E1E", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.controls = []
        self.make_rounded_rect_support()
        self.draw_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.worker = threading.Thread(target=self.loop, daemon=True)
        self.worker.start()

    def make_rounded_rect_support(self):
        def round_rect(canvas, x1, y1, x2, y2, radius=25, **kwargs):
            points = [
                x1 + radius, y1,
                x2 - radius, y1,
                x2, y1,
                x2, y1 + radius,
                x2, y2 - radius,
                x2, y2,
                x2 - radius, y2,
                x1 + radius, y2,
                x1, y2,
                x1, y2 - radius,
                x1, y1 + radius,
                x1, y1,
            ]
            return canvas.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

        Canvas.create_round_rect = round_rect

    def draw_box(self, x1, y1, x2, y2, title):
        c = self.canvas
        c.create_round_rect(x1, y1, x2, y2, radius=12, fill="#252526", outline="#151515", width=2)
        c.create_line(x1 + 20, y1 + 45, x2 - 20, y1 + 45, fill="#3A3A3C", width=1)
        c.create_text(
            (x1 + x2) / 2,
            y1 + 25,
            text=title,
            fill="#9A9A9C",
            font=("Segoe UI", 11, "bold"),
        )

    def draw_button(self, x1, y1, x2, y2, label, command, fill="#2C2C2E", text_color="#E0E0E0"):
        c = self.canvas
        rect = c.create_round_rect(x1, y1, x2, y2, radius=6, fill=fill, outline="#3A3A3C", width=1)
        text = c.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text=label,
            fill=text_color,
            font=("Segoe UI", 9, "bold"),
        )

        for item in (rect, text):
            c.tag_bind(item, "<Button-1>", lambda event, cmd=command: cmd())

    def draw_ui(self):
        c = self.canvas
        c.delete("all")
        self.controls.clear()

        c.create_text(
            28, 28,
            text="FIDELITY",
            anchor="nw",
            fill="#E0E0E0",
            font=("Segoe UI", 22, "bold", "italic"),
        )
        c.create_text(
            30, 62,
            text="VOCASTER RACKSTRIP",
            anchor="nw",
            fill="#8A8A8C",
            font=("Segoe UI", 10, "bold"),
        )

        self.led = c.create_oval(325, 38, 341, 54, fill="#333333", outline="#111111", width=2)
        self.status_text = c.create_text(
            333, 72,
            text="READY",
            fill="#8A8A8C",
            anchor="e",
            font=("Segoe UI", 8, "bold"),
        )

        # Two clean centered button rows. Equal width and equal margins.
        button_left = 42
        button_w = 135
        gap = 36
        button_h = 34
        row1_y = 112
        row2_y = 158
        self.draw_button(button_left, row1_y, button_left + button_w, row1_y + button_h, "CONNECT", self.connect_now)
        self.draw_button(button_left + button_w + gap, row1_y, button_left + button_w * 2 + gap, row1_y + button_h, "LAUNCH", self.launch_hub)
        self.draw_button(button_left, row2_y, button_left + button_w, row2_y + button_h, "DOCK LEFT", self.dock_left)
        self.draw_button(button_left + button_w + gap, row2_y, button_left + button_w * 2 + gap, row2_y + button_h, "HUB PATH", self.choose_path)

        self.draw_box(24, 218, 366, 365, "SMART REMAP")
        self.host_toggle = VToggle(
            self,
            52, 292,
            "HOST → AUX",
            lambda: self.host_to_aux,
            self.set_host_to_aux,
            accent="#62C03A",
        )
        self.bt_toggle = VToggle(
            self,
            52, 329,
            "GUEST → BT",
            lambda: self.guest_to_bt,
            self.set_guest_to_bt,
            accent="#14A8A0",
        )

        self.draw_box(24, 388, 366, 635, "MIC CONTROL")
        self.host_knob = RotaryKnob(
            self, 116, 498, 50,
            "Host", "host_mic",
            SLIDER_MAP["host_mic"],
            RANGES["host_mic"],
            "#E5C043",
        )
        self.guest_knob = RotaryKnob(
            self, 274, 498, 50,
            "Guest", "guest_mic",
            SLIDER_MAP["guest_mic"],
            RANGES["guest_mic"],
            "#14A8A0",
        )
        self.controls += [self.host_knob, self.guest_knob]

        self.draw_box(24, 658, 366, 1010, "SHOW MIX")
        self.aux_fader = VFader(
            self, 112, 735, 190,
            "AUX", "aux",
            SLIDER_MAP["aux"],
            RANGES["aux"],
            "#62C03A",
            display_gamma=self.mix_visual_gamma,
        )
        self.bt_fader = VFader(
            self, 276, 735, 190,
            "BT", "bluetooth",
            SLIDER_MAP["bluetooth"],
            RANGES["bluetooth"],
            "#14A8A0",
            display_gamma=self.mix_visual_gamma,
        )
        self.controls += [self.aux_fader, self.bt_fader]

        # Wheel events are bound to the canvas, then routed by cursor position.
        # This avoids illegal Canvas item <MouseWheel> tag bindings on some Tk builds.
        self.canvas.bind("<MouseWheel>", self.on_canvas_wheel)
        self.canvas.bind("<Button-4>", self.on_canvas_wheel)
        self.canvas.bind("<Button-5>", self.on_canvas_wheel)

    def set_status(self, text, good=None):
        color = "#62C03A" if good is True else "#E04F5E" if good is False else "#E5C043"
        try:
            self.canvas.itemconfig(self.status_text, text=text[:22])
            self.canvas.itemconfig(self.led, fill=color)
        except Exception:
            pass

    def set_host_to_aux(self, value):
        self.host_to_aux = bool(value)

    def set_guest_to_bt(self, value):
        self.guest_to_bt = bool(value)

    def draw_toggle_states(self):
        self.host_toggle.redraw()
        self.bt_toggle.redraw()

    def choose_path(self):
        path = filedialog.askopenfilename(
            title="Select Vocaster Hub.exe",
            filetypes=[("EXE files", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.hub_path = path
            self.save_runtime_config()
            self.set_status("PATH SAVED", True)

    def launch_hub(self):
        ok, message = self.backend.launch(self.hub_path)
        self.set_status("HUB LAUNCHED" if ok else "HUB NOT FOUND", ok)
        self.after(1200, self.connect_now)

    def connect_now(self):
        try:
            self.backend.connect()
            if self.hide_original:
                self.backend.hide_original()
            self.connected = True
            self.set_status("CONNECTED", True)
        except Exception:
            self.connected = False
            self.set_status("WAITING", False)

    def dock_left(self):
        """Dock to the left edge of the virtual desktop.

        If a secondary monitor is placed left of the main monitor, Windows virtual screen
        left coordinate is negative. This correctly docks to that monitor.
        """
        try:
            left, top, width, height = virtual_screen_bounds()
            panel_width = 390
            panel_height = 1040
            x = left
            y = top + max(0, (height - panel_height) // 2)

            self.geometry(f"{panel_width}x{panel_height}+{x}+{y}")
            self.attributes("-topmost", True)
            self.always_on_top = True
            self.lift()
            self.focus_force()
            self.save_runtime_config()
            self.set_status("DOCKED LEFT", True)
        except Exception as e:
            self.set_status(f"DOCK ERR {e!r}", False)

    def on_canvas_wheel(self, event):
        """Route mouse wheel to the nearest visible control."""
        try:
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)

            if hasattr(event, "delta") and event.delta:
                delta_sign = 1 if event.delta > 0 else -1
            else:
                delta_sign = 1 if getattr(event, "num", None) == 4 else -1

            for knob in (self.host_knob, self.guest_knob):
                dx = x - knob.x
                dy = y - knob.y
                if dx * dx + dy * dy <= (knob.r + 18) ** 2:
                    lo, hi = knob.value_range
                    step = (hi - lo) / 80.0
                    self.backend.set(knob.slider_index, clamp(knob.value + delta_sign * step, lo, hi))
                    return "break"

            for fader in (self.aux_fader, self.bt_fader):
                if fader.x - 58 <= x <= fader.x + 58 and fader.y - 12 <= y <= fader.y + fader.h + 38:
                    lo, hi = fader.get_range()
                    step = (hi - lo) / 80.0
                    self.backend.set(fader.slider_index, clamp(fader.value + delta_sign * step, lo, hi))
                    return "break"

        except Exception as e:
            self.set_status(f"WHEEL ERR {e!r}", False)
            return "break"

    def save_runtime_config(self):
        self.cfg.update({
            "hub_path": self.hub_path,
            "hide_original": self.hide_original,
            "always_on_top": self.always_on_top,
            "geometry": self.geometry(),
            "host_to_aux": self.host_to_aux,
            "guest_to_bt": self.guest_to_bt,
            "aux_gamma": self.aux_gamma,
            "bt_gamma": self.bt_gamma,
            "mix_visual_gamma": self.mix_visual_gamma,
            "threshold": self.threshold,
            "poll": self.poll,
        })
        save_config(self.cfg)

    def update_visuals(self, values):
        if "host_mic" in values:
            self.host_knob.set_visual_from_value(values["host_mic"])
        if "guest_mic" in values:
            self.guest_knob.set_visual_from_value(values["guest_mic"])
        if "aux" in values:
            self.aux_fader.set_visual_from_value(values["aux"])
        if "bluetooth" in values:
            self.bt_fader.set_visual_from_value(values["bluetooth"])

        self.draw_toggle_states()

    def loop(self):
        while self.running:
            try:
                if self.backend.win is None:
                    try:
                        self.backend.connect()
                        if self.hide_original:
                            self.backend.hide_original()
                        self.connected = True
                        self.after(0, lambda: self.set_status("CONNECTED", True))
                    except Exception:
                        self.connected = False
                        self.after(0, lambda: self.set_status("WAITING", False))
                        time.sleep(1.0)
                        continue

                self.backend.refresh()
                if len(self.backend.sliders) < 6:
                    raise RuntimeError(f"Not enough sliders: {len(self.backend.sliders)}")

                values = {
                    "host_mic": self.backend.get(SLIDER_MAP["host_mic"]),
                    "guest_mic": self.backend.get(SLIDER_MAP["guest_mic"]),
                    "aux": self.backend.get(SLIDER_MAP["aux"]),
                    "bluetooth": self.backend.get(SLIDER_MAP["bluetooth"]),
                }

                if self.last_host is None:
                    self.last_host = values["host_mic"]
                if self.last_guest is None:
                    self.last_guest = values["guest_mic"]

                if self.host_to_aux and abs(values["host_mic"] - self.last_host) >= self.threshold:
                    mapped = gamma_map(
                        values["host_mic"],
                        RANGES["host_mic"][0], RANGES["host_mic"][1],
                        RANGES["aux"][0], RANGES["aux"][1],
                        gamma=self.aux_gamma,
                    )
                    self.backend.set(SLIDER_MAP["aux"], mapped)
                    values["aux"] = self.backend.get(SLIDER_MAP["aux"])
                    self.last_host = values["host_mic"]
                elif not self.host_to_aux:
                    self.last_host = values["host_mic"]

                if self.guest_to_bt and abs(values["guest_mic"] - self.last_guest) >= self.threshold:
                    mapped = gamma_map(
                        values["guest_mic"],
                        RANGES["guest_mic"][0], RANGES["guest_mic"][1],
                        RANGES["bluetooth"][0], RANGES["bluetooth"][1],
                        gamma=self.bt_gamma,
                    )
                    self.backend.set(SLIDER_MAP["bluetooth"], mapped)
                    values["bluetooth"] = self.backend.get(SLIDER_MAP["bluetooth"])
                    self.last_guest = values["guest_mic"]
                elif not self.guest_to_bt:
                    self.last_guest = values["guest_mic"]

                self.after(0, lambda v=values: self.update_visuals(v))
                time.sleep(max(0.015, self.poll))

            except Exception:
                self.backend.win = None
                self.connected = False
                self.after(0, lambda: self.set_status("RECONNECT", False))
                time.sleep(1.0)

    def on_close(self):
        self.running = False
        self.save_runtime_config()
        self.destroy()


def main():
    app = RackApp()
    app.mainloop()


if __name__ == "__main__":
    main()
