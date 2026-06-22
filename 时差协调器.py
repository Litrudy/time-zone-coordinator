"""Windows 桌面小挂件：时差协调器。

依赖 Python 3.9+。Windows 建议额外安装 tzdata，以便 zoneinfo 能找到 IANA 时区数据。
"""

import json
import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


APP_NAME = "时差协调器"
WINDOW_WIDTH = 320
WINDOW_HEIGHT = 220

# 三套主题均只使用 tkinter 可直接呈现的纯色，确保打包时不需要外部素材。
THEMES = {
    "春日": {
        "bg": "#f7f5ec",
        "surface": "#eef3e5",
        "control": "#fbfaf4",
        "primary": "#174729",
        "muted": "#6e8a60",
        "accent": "#5f9847",
        "accent2": "#d2ac4f",
        "border": "#7e9a68",
        "danger": "#bf4b45",
    },
    "机械": {
        "bg": "#0b1014",
        "surface": "#151c21",
        "control": "#11171b",
        "primary": "#c5c8ca",
        "muted": "#80898e",
        "accent": "#26b5df",
        "accent2": "#f2a91f",
        "border": "#596269",
        "danger": "#e45b48",
    },
    "霓虹": {
        "bg": "#050316",
        "surface": "#0d0824",
        "control": "#09051e",
        "primary": "#f8f5ff",
        "muted": "#b7afca",
        "accent": "#00eee4",
        "accent2": "#ff2cb7",
        "border": "#ff2cb7",
        "danger": "#ff477e",
    },
}

# 中文名称到 IANA 时区 ID 的映射。一个时区可服务同一地区的多个港口/城市。
CITY_TIMEZONES = {
    "北京/上海": "Asia/Shanghai",
    "几内亚·卡纳克里": "Africa/Conakry",
    "刚果布·黑角": "Africa/Brazzaville",
    "塞拉利昂·弗里敦": "Africa/Freetown",
    "加纳·阿克拉": "Africa/Accra",
    "吉布提·吉布提市": "Africa/Djibouti",
    "塞内加尔·达喀尔": "Africa/Dakar",
    "科特迪瓦·阿比让": "Africa/Abidjan",
    "利比亚·的黎波里": "Africa/Tripoli",
    "尼日利亚·拉各斯": "Africa/Lagos",
    "鹿特丹": "Europe/Amsterdam",
    "汉堡": "Europe/Berlin",
    "安特卫普": "Europe/Brussels",
    "新加坡": "Asia/Singapore",
    "迪拜": "Asia/Dubai",
    "香港": "Asia/Hong_Kong",
    "釜山": "Asia/Seoul",
    "东京": "Asia/Tokyo",
    "伦敦": "Europe/London",
    "巴黎": "Europe/Paris",
    "纽约": "America/New_York",
    "洛杉矶": "America/Los_Angeles",
    "悉尼": "Australia/Sydney",
}


def get_config_path():
    """返回配置文件路径；没有 APPDATA 时使用用户主目录作为兜底。"""
    appdata = os.environ.get("APPDATA")
    base_dir = Path(appdata) if appdata else Path.home() / ".config"
    return base_dir / APP_NAME / "config.json"


def load_config():
    """读取配置；文件不存在或损坏时使用默认配置。"""
    defaults = {
        "local_city": "北京/上海",
        "target_city": "几内亚·卡纳克里",
        "theme": "春日",
        "autostart": False,
        "window_x": None,
        "window_y": None,
    }
    path = get_config_path()
    try:
        with path.open("r", encoding="utf-8") as file:
            saved = json.load(file)
        if isinstance(saved, dict):
            defaults.update(saved)
    except (OSError, ValueError, TypeError):
        pass

    # 防止手工修改配置后出现不存在的城市名。
    if defaults["local_city"] not in CITY_TIMEZONES:
        defaults["local_city"] = "北京/上海"
    if defaults["target_city"] not in CITY_TIMEZONES:
        defaults["target_city"] = "几内亚·卡纳克里"
    if defaults["theme"] not in THEMES:
        defaults["theme"] = "春日"
    return defaults


def build_autostart_command():
    """生成注册表 Run 项命令：打包后用 exe，源码运行时用 Python 加脚本。"""
    if getattr(sys, "frozen", False):
        parts = [os.path.abspath(sys.executable)]
    else:
        parts = [os.path.abspath(sys.executable), os.path.abspath(__file__)]
    # Windows 的命令行引用规则较复杂，交给标准库正确添加引号。
    return subprocess.list2cmdline(parts)


def set_windows_autostart(enabled):
    """设置或删除当前用户的开机自启项；非 Windows 平台直接返回。"""
    if sys.platform != "win32":
        return

    import winreg

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        run_key,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key, APP_NAME, 0, winreg.REG_SZ, build_autostart_command()
            )
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def format_offset_difference(hours):
    """把时差小时数格式化为 -8h、+5.5h、+5:45h 等紧凑形式。"""
    sign = "+" if hours >= 0 else "-"
    total_minutes = round(abs(hours) * 60)
    whole_hours, minutes = divmod(total_minutes, 60)
    if minutes == 0:
        value = str(whole_hours)
    elif minutes == 30:
        value = f"{whole_hours}.5"
    else:
        value = f"{whole_hours}:{minutes:02d}"
    return f"差{sign}{value}h"


class TimeCoordinator(tk.Tk):
    """时差协调器主窗口。"""

    def __init__(self):
        super().__init__()
        self.config_data = load_config()
        self._drag_origin = None
        self._save_job = None
        self._clock_job = None
        self.frames = []
        self.role_widgets = {"primary": [], "muted": [], "time": [], "diff": []}

        self.title(APP_NAME)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self.local_city = tk.StringVar(value=self.config_data["local_city"])
        self.target_city = tk.StringVar(value=self.config_data["target_city"])
        self.theme_name = tk.StringVar(value=self.config_data["theme"])
        self.autostart = tk.BooleanVar(value=bool(self.config_data["autostart"]))
        self.target_time_text = tk.StringVar(value="--:--:--")
        self.target_date_text = tk.StringVar(value="----/--/--")
        self.local_time_text = tk.StringVar(value="正在读取时区…")
        self.difference_text = tk.StringVar(value="")

        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.border_canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.border_canvas.pack(fill="both", expand=True)
        self.content = tk.Frame(self, bd=0, highlightthickness=0)
        self.content.place(x=12, y=9, width=WINDOW_WIDTH - 24, height=WINDOW_HEIGHT - 18)
        self.frames.append(self.content)

        self._build_ui()
        self.apply_theme()
        self._place_window()
        self._bind_dragging()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        # 非 Windows 不显示错误，只禁用无效的自启选项。
        if sys.platform != "win32":
            self.autostart.set(False)
            self.autostart_check.configure(state="disabled")

        self.after(0, self.update_clock)

    def _register_role(self, widget, role):
        self.role_widgets[role].append(widget)
        return widget

    def _new_frame(self, parent):
        frame = tk.Frame(parent, bd=0, highlightthickness=0)
        self.frames.append(frame)
        return frame

    def _build_ui(self):
        top = self._new_frame(self.content)
        top.pack(fill="x", padx=8, pady=(4, 0))

        title_label = self._register_role(
            tk.Label(
                top,
                text=APP_NAME,
                bd=0,
                font=("Microsoft YaHei UI", 9, "bold"),
            ),
            "primary",
        )
        title_label.pack(side="left")

        self.theme_combo = ttk.Combobox(
            top,
            textvariable=self.theme_name,
            values=list(THEMES),
            state="readonly",
            width=5,
            style="Theme.TCombobox",
            font=("Microsoft YaHei UI", 8, "bold"),
        )
        self.theme_combo.pack(side="left", padx=(8, 0))
        self.theme_combo.bind("<<ComboboxSelected>>", self.on_theme_changed)

        self.close_button = tk.Button(
            top,
            text="×",
            command=self.close_app,
            relief="flat",
            bd=0,
            width=2,
            cursor="hand2",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.close_button.pack(side="right")

        selector_row = self._new_frame(self.content)
        selector_row.pack(fill="x", padx=8, pady=(3, 0))
        local_box = self._make_selector(
            selector_row, "本地地区", self.local_city, 0
        )
        target_box = self._make_selector(
            selector_row, "目标地区", self.target_city, 1
        )
        local_box.bind("<<ComboboxSelected>>", self.on_city_changed)
        target_box.bind("<<ComboboxSelected>>", self.on_city_changed)

        self.divider_top = tk.Frame(self.content, height=1, bd=0)
        self.divider_top.pack(fill="x", padx=8, pady=(6, 0))

        display = self._new_frame(self.content)
        display.pack(fill="both", expand=True, padx=8, pady=(0, 0))
        target_time_label = self._register_role(
            tk.Label(
                display,
                textvariable=self.target_time_text,
                bd=0,
                font=("Consolas", 28, "bold"),
            ),
            "time",
        )
        target_time_label.pack()

        target_date_label = self._register_role(
            tk.Label(
                display,
                textvariable=self.target_date_text,
                bd=0,
                font=("Consolas", 9),
            ),
            "muted",
        )
        target_date_label.pack()

        self.divider_bottom = tk.Frame(self.content, height=1, bd=0)
        self.divider_bottom.pack(fill="x", padx=8, pady=(0, 1))

        bottom = self._new_frame(self.content)
        bottom.pack(fill="x", padx=8, pady=(0, 4))
        local_detail_label = self._register_role(
            tk.Label(
                bottom,
                textvariable=self.local_time_text,
                bd=0,
                anchor="w",
                font=("Microsoft YaHei UI", 8),
            ),
            "muted",
        )
        local_detail_label.pack(side="left")
        separator_label = self._register_role(
            tk.Label(
                bottom,
                text=" · ",
                bd=0,
                font=("Microsoft YaHei UI", 8),
            ),
            "muted",
        )
        separator_label.pack(side="left")
        difference_label = self._register_role(
            tk.Label(
                bottom,
                textvariable=self.difference_text,
                bd=0,
                font=("Microsoft YaHei UI", 8, "bold"),
            ),
            "diff",
        )
        difference_label.pack(side="left")

        self.autostart_check = tk.Checkbutton(
            bottom,
            text="自启",
            variable=self.autostart,
            command=self.on_autostart_changed,
            highlightthickness=0,
            bd=0,
            font=("Microsoft YaHei UI", 8),
        )
        self.autostart_check.pack(side="right")

        # 在背景、标题和时间区域拖动，避免与下拉框、按钮的点击冲突。
        self.drag_widgets = [
            self,
            self.border_canvas,
            self.content,
            top,
            selector_row,
            display,
            bottom,
            title_label,
            target_time_label,
            target_date_label,
            local_detail_label,
            separator_label,
            difference_label,
        ]

    def _make_selector(self, parent, label_text, variable, column):
        container = self._new_frame(parent)
        padding = (0, 4) if column == 0 else (4, 0)
        container.grid(row=0, column=column, sticky="ew", padx=padding)
        parent.grid_columnconfigure(column, weight=1)

        label = self._register_role(
            tk.Label(
                container,
                text=label_text,
                bd=0,
                anchor="w",
                font=("Microsoft YaHei UI", 7),
            ),
            "muted",
        )
        label.pack(fill="x")
        combo = ttk.Combobox(
            container,
            textvariable=variable,
            values=list(CITY_TIMEZONES),
            state="readonly",
            style="City.TCombobox",
            font=("Microsoft YaHei UI", 8),
            height=12,
        )
        combo.pack(fill="x")
        return combo

    def _configure_combobox_styles(self, theme):
        for style_name in ("City.TCombobox", "Theme.TCombobox"):
            self.style.configure(
                style_name,
                fieldbackground=theme["control"],
                background=theme["surface"],
                foreground=theme["primary"],
                arrowcolor=theme["accent"],
                bordercolor=theme["border"],
                lightcolor=theme["border"],
                darkcolor=theme["border"],
                insertcolor=theme["primary"],
                borderwidth=1,
                padding=2,
            )
            self.style.map(
                style_name,
                fieldbackground=[("readonly", theme["control"])],
                foreground=[("readonly", theme["primary"])],
                selectbackground=[("readonly", theme["control"])],
                selectforeground=[("readonly", theme["primary"])],
                bordercolor=[("focus", theme["accent"])],
            )

    def apply_theme(self):
        """把当前主题应用到所有控件，并重绘主题边框。"""
        name = self.theme_name.get()
        theme = THEMES.get(name, THEMES["春日"])
        self.configure(bg=theme["bg"])
        self.border_canvas.configure(bg=theme["bg"])
        for frame in self.frames:
            frame.configure(bg=theme["bg"])
        for role, widgets in self.role_widgets.items():
            if role == "time":
                color = theme["primary"] if name == "春日" else theme["accent"]
            elif role == "diff":
                color = theme["accent2"]
            else:
                color = theme[role]
            for widget in widgets:
                widget.configure(bg=theme["bg"], fg=color)

        self.divider_top.configure(bg=theme["border"])
        self.divider_bottom.configure(bg=theme["border"])
        self.close_button.configure(
            bg=theme["bg"],
            fg=theme["primary"],
            activebackground=theme["danger"],
            activeforeground="#ffffff",
        )
        self.autostart_check.configure(
            bg=theme["bg"],
            fg=theme["primary"],
            activebackground=theme["bg"],
            activeforeground=theme["accent"],
            selectcolor=theme["control"],
        )
        self._configure_combobox_styles(theme)
        self._draw_theme_border(name, theme)

    def _draw_theme_border(self, name, theme):
        """绘制各主题的专属边框装饰。"""
        canvas = self.border_canvas
        canvas.delete("all")
        width = WINDOW_WIDTH - 1
        height = WINDOW_HEIGHT - 1

        if name == "春日":
            canvas.create_rectangle(
                2, 2, width - 2, height - 2, outline=theme["border"], width=1
            )
            canvas.create_rectangle(
                6, 6, width - 6, height - 6, outline=theme["accent"], width=1
            )
            self._draw_leaf_sprig(3, 3, 1, 1, theme["accent"])
            self._draw_leaf_sprig(
                width - 3, height - 3, -1, -1, theme["accent"]
            )
            for x in (246, 252, 258, 264):
                canvas.create_oval(x, 4, x + 2, 6, fill=theme["border"], outline="")
                canvas.create_oval(
                    width - x - 2,
                    height - 6,
                    width - x,
                    height - 4,
                    fill=theme["border"],
                    outline="",
                )
        elif name == "机械":
            points = [3, 10, 10, 3, width - 10, 3, width - 3, 10,
                      width - 3, height - 10, width - 10, height - 3,
                      10, height - 3, 3, height - 10]
            inner = [7, 13, 13, 7, width - 13, 7, width - 7, 13,
                     width - 7, height - 13, width - 13, height - 7,
                     13, height - 7, 7, height - 13]
            canvas.create_polygon(points, fill="", outline=theme["border"], width=2)
            canvas.create_polygon(inner, fill="", outline="#2f383e", width=1)
            for x, y in ((10, 10), (width - 10, 10), (10, height - 10),
                         (width - 10, height - 10)):
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3,
                                   outline=theme["border"], width=1)
                canvas.create_oval(x - 1, y - 1, x + 1, y + 1,
                                   fill=theme["accent2"], outline="")
            for x in (22, 27, 32, width - 32, width - 27, width - 22):
                canvas.create_line(x, 4, x, 8, fill=theme["accent2"], width=2)
            canvas.create_line(3, 78, 8, 78, fill=theme["accent"], width=3)
            canvas.create_line(width - 8, 78, width - 3, 78,
                               fill=theme["accent"], width=3)
        else:
            magenta = theme["accent2"]
            cyan = theme["accent"]
            # 不对称分段线与切角，让霓虹主题和春日主题拉开视觉距离。
            canvas.create_line(3, 58, 3, 14, 14, 3, 104, 3,
                               fill=magenta, width=2)
            canvas.create_line(112, 3, width - 14, 3, width - 3, 14,
                               width - 3, 47, fill=cyan, width=2)
            canvas.create_line(width - 3, 56, width - 3, height - 14,
                               width - 14, height - 3, 190, height - 3,
                               fill=magenta, width=2)
            canvas.create_line(166, height - 3, 154, height - 3,
                               150, height - 10, 146, height - 1,
                               141, height - 8, 137, height - 3,
                               52, height - 3, fill=magenta, width=2)
            canvas.create_line(48, height - 3, 14, height - 3, 3,
                               height - 14, 3, 70, fill=cyan, width=2)
            canvas.create_oval(width - 6, 50, width, 56,
                               outline=magenta, width=2)
            canvas.create_oval(46, height - 6, 52, height,
                               outline=cyan, width=2)

    def _draw_leaf_sprig(self, x, y, dx, dy, color):
        """绘制小型枝叶角花，避免引入外部图片。"""
        canvas = self.border_canvas
        canvas.create_line(x, y, x + 7 * dx, y + 6 * dy,
                           fill=color, width=1, smooth=True)
        leaves = ((1, 1, 4, 3), (3, 3, 6, 5), (5, 5, 8, 7))
        for x1, y1, x2, y2 in leaves:
            xa, xb = sorted((x + x1 * dx, x + x2 * dx))
            ya, yb = sorted((y + y1 * dy, y + y2 * dy))
            canvas.create_oval(xa, ya, xb, yb, outline=color, width=1)

    def _place_window(self):
        """恢复保存的位置；首次运行默认放在屏幕右上角。"""
        self.update_idletasks()
        max_x = max(0, self.winfo_screenwidth() - WINDOW_WIDTH)
        max_y = max(0, self.winfo_screenheight() - WINDOW_HEIGHT)
        saved_x = self.config_data.get("window_x")
        saved_y = self.config_data.get("window_y")

        if isinstance(saved_x, int) and isinstance(saved_y, int):
            x = min(max(saved_x, 0), max_x)
            y = min(max(saved_y, 0), max_y)
        else:
            x = max(0, max_x - 16)
            y = 16
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def _bind_dragging(self):
        for widget in self.drag_widgets:
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)
            widget.bind("<ButtonRelease-1>", self.end_drag)

    def start_drag(self, event):
        self._drag_origin = (
            event.x_root - self.winfo_x(),
            event.y_root - self.winfo_y(),
        )

    def do_drag(self, event):
        if not self._drag_origin:
            return
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.geometry(f"+{x}+{y}")

    def end_drag(self, _event):
        self._drag_origin = None
        self.schedule_save()

    def on_city_changed(self, _event=None):
        self.refresh_clock_display()
        self.schedule_save()

    def on_theme_changed(self, _event=None):
        self.apply_theme()
        self.schedule_save()

    def refresh_clock_display(self):
        """刷新目标时间、本地时间和当下的真实 UTC 时差。"""
        try:
            now_utc = datetime.now(timezone.utc)
            local_zone = ZoneInfo(CITY_TIMEZONES[self.local_city.get()])
            target_zone = ZoneInfo(CITY_TIMEZONES[self.target_city.get()])
            local_now = now_utc.astimezone(local_zone)
            target_now = now_utc.astimezone(target_zone)

            local_offset = local_now.utcoffset().total_seconds()
            target_offset = target_now.utcoffset().total_seconds()
            difference_hours = (target_offset - local_offset) / 3600

            self.target_time_text.set(target_now.strftime("%H:%M:%S"))
            self.target_date_text.set(target_now.strftime("%Y-%m-%d"))
            self.local_time_text.set(f"本地 {local_now:%H:%M:%S}")
            self.difference_text.set(format_offset_difference(difference_hours))
        except ZoneInfoNotFoundError:
            self.local_time_text.set("缺少时区数据：请安装 tzdata")
            self.difference_text.set("")

    def update_clock(self):
        """每秒刷新，并把下一次刷新对齐到下一秒附近。"""
        self.refresh_clock_display()
        milliseconds = datetime.now().microsecond // 1000
        self._clock_job = self.after(
            max(100, 1000 - milliseconds), self.update_clock
        )

    def on_autostart_changed(self):
        enabled = self.autostart.get()
        try:
            set_windows_autostart(enabled)
        except OSError as exc:
            self.autostart.set(not enabled)
            messagebox.showerror(APP_NAME, f"修改开机自启失败：\n{exc}")
        self.schedule_save()

    def schedule_save(self):
        """短暂防抖，避免拖动窗口时频繁写配置文件。"""
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(250, self.save_config)

    def save_config(self):
        self._save_job = None
        data = {
            "local_city": self.local_city.get(),
            "target_city": self.target_city.get(),
            "theme": self.theme_name.get(),
            "autostart": bool(self.autostart.get()),
            "window_x": self.winfo_x(),
            "window_y": self.winfo_y(),
        }
        path = get_config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
        except OSError:
            # 挂件退出时不因配置写入失败而打断用户。
            pass

    def close_app(self):
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        if self._clock_job is not None:
            self.after_cancel(self._clock_job)
        self.save_config()
        self.destroy()


def enable_windows_dpi_awareness():
    """让高 DPI 屏幕上的 Tk 窗口与字体更清晰；失败时不影响启动。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main():
    enable_windows_dpi_awareness()
    app = TimeCoordinator()
    app.mainloop()


if __name__ == "__main__":
    main()
