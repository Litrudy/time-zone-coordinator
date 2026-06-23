"""Windows 桌面小挂件：时差协调器。

依赖 Python 3.9+。Windows 建议额外安装 tzdata，以便 zoneinfo 能找到 IANA 时区数据。
"""

import json
import os
import random
import subprocess
import sys
import tkinter as tk
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from tkinter import messagebox, ttk
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


APP_NAME = "时差协调器"
BASE_DPI = 96
WINDOW_WIDTH = 320
WINDOW_HEIGHT = 220
RESIZE_BORDER = 8
PET_OFF = "不显示"
PET_TICK_MS = 60
PET_WINDOW_KEY = "#01ff02"
PET_NAME = "英短"
PET_SLUG = "british-shorthair"
PETS = {PET_NAME: PET_SLUG}
PET_ACTIONS = ("walk", "sleep", "greet")
PET_ACTION_FRAME_COUNT = 4
PET_ACTION_FRAME_TICKS = {
    "walk": 3,
    "sleep": 8,
    "greet": 4,
}
PET_ACTION_TICK_RANGES = {
    "walk": (80, 150),
    "sleep": (44, 76),
    "greet": (24, 36),
}
PET_RANDOM_ACTIONS = ("walk", "walk", "walk", "sleep", "greet")


def logical_to_physical(value, scale):
    """把 96 DPI 下的逻辑尺寸换算为当前显示器的物理像素。"""
    return max(1, int(round(float(value) * float(scale))))


def physical_to_logical(value, scale):
    """把物理像素换算为 96 DPI 下的逻辑尺寸。"""
    if scale <= 0:
        scale = 1.0
    return float(value) / float(scale)


def calculate_resize_geometry(start_geometry, delta, edges, min_size):
    """根据拖动方向计算无边框窗口的新位置和尺寸。"""
    start_x, start_y, start_width, start_height = start_geometry
    delta_x, delta_y = delta
    min_width, min_height = min_size
    x, y = start_x, start_y
    width, height = start_width, start_height

    if "w" in edges:
        x = start_x + delta_x
        width = start_width - delta_x
        if width < min_width:
            width = min_width
            x = start_x + start_width - min_width
    elif "e" in edges:
        width = max(min_width, start_width + delta_x)

    if "n" in edges:
        y = start_y + delta_y
        height = start_height - delta_y
        if height < min_height:
            height = min_height
            y = start_y + start_height - min_height
    elif "s" in edges:
        height = max(min_height, start_height + delta_y)

    return int(x), int(y), int(width), int(height)


def clamp_geometry_to_work_area(geometry, work_area, min_size):
    """把窗口完整限制在目标显示器的可用工作区内。"""
    x, y, width, height = geometry
    left, top, right, bottom = work_area
    min_width, min_height = min_size
    available_width = max(1, right - left)
    available_height = max(1, bottom - top)
    width = min(max(width, min_width), available_width)
    height = min(max(height, min_height), available_height)
    x = min(max(x, left), right - width)
    y = min(max(y, top), bottom - height)
    return int(x), int(y), int(width), int(height)


def normalize_logical_size(value, default):
    """读取配置中的逻辑尺寸，并过滤布尔值、负数和无效类型。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(default, int(round(value)))


def pet_position_inside_border(window_geometry, sprite_size, distance, margin=10):
    """让宠物在主窗口内部沿下边缘往返移动。"""
    x, y, width, height = window_geometry
    sprite_width, sprite_height = sprite_size
    margin = max(0, int(margin))
    travel = max(1, width - sprite_width - margin * 2)
    phase = float(distance) % (travel * 2)

    if phase <= travel:
        pet_x = x + margin + phase
        direction = "right"
    else:
        pet_x = x + margin + (travel * 2 - phase)
        direction = "left"

    pet_y = y + max(margin, height - sprite_height - margin)

    return int(round(pet_x)), int(round(pet_y)), direction

# 三套主题装饰均使用 tkinter 可直接呈现的纯色。
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


def resource_path(relative_path):
    """返回源码运行或 PyInstaller 单文件运行时的资源路径。"""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_dir / relative_path


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
        "window_width": WINDOW_WIDTH,
        "window_height": WINDOW_HEIGHT,
        "pet": PET_OFF,
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
    if defaults.get("pet") not in PETS and defaults.get("pet") != PET_OFF:
        defaults["pet"] = PET_OFF
    defaults["window_width"] = normalize_logical_size(
        defaults.get("window_width"), WINDOW_WIDTH
    )
    defaults["window_height"] = normalize_logical_size(
        defaults.get("window_height"), WINDOW_HEIGHT
    )
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


def get_window_dpi(window_id):
    """读取窗口当前所在显示器的 DPI；旧版 Windows 回退到系统 DPI。"""
    if sys.platform != "win32":
        return BASE_DPI

    try:
        import ctypes

        user32 = ctypes.windll.user32
        get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
        if get_dpi_for_window is not None:
            get_dpi_for_window.argtypes = [ctypes.c_void_p]
            get_dpi_for_window.restype = ctypes.c_uint
            dpi = int(get_dpi_for_window(ctypes.c_void_p(window_id)))
            if dpi > 0:
                return dpi

        get_dpi_for_system = getattr(user32, "GetDpiForSystem", None)
        if get_dpi_for_system is not None:
            get_dpi_for_system.restype = ctypes.c_uint
            dpi = int(get_dpi_for_system())
            if dpi > 0:
                return dpi
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return BASE_DPI


def get_monitor_work_area(rectangle):
    """返回离指定窗口矩形最近的显示器工作区，失败时返回 None。"""
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        x, y, width, height = rectangle
        window_rect = wintypes.RECT(x, y, x + width, y + height)
        user32 = ctypes.windll.user32
        monitor_from_rect = user32.MonitorFromRect
        monitor_from_rect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
        monitor_from_rect.restype = ctypes.c_void_p
        monitor = monitor_from_rect(ctypes.byref(window_rect), 2)
        if not monitor:
            return None

        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        get_monitor_info = user32.GetMonitorInfoW
        get_monitor_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]
        get_monitor_info.restype = wintypes.BOOL
        if not get_monitor_info(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def set_native_window_geometry(window_id, geometry):
    """用绝对虚拟屏幕坐标设置窗口，支持位于主屏左侧/上方的显示器。"""
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        x, y, width, height = geometry
        user32 = ctypes.windll.user32
        get_parent = user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        native_window = get_parent(ctypes.c_void_p(window_id)) or window_id

        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        set_window_pos.restype = wintypes.BOOL
        flags = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE
        return bool(
            set_window_pos(
                ctypes.c_void_p(native_window),
                None,
                int(x),
                int(y),
                int(width),
                int(height),
                flags,
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class TimeCoordinator(tk.Tk):
    """时差协调器主窗口。"""

    def __init__(self):
        super().__init__()
        self.config_data = load_config()
        self._pointer_mode = None
        self._drag_origin = None
        self._resize_state = None
        self._save_job = None
        self._clock_job = None
        self._configure_job = None
        self._pet_job = None
        self._pet_window = None
        self._pet_label = None
        self._pet_images = {}
        self._pet_distance = 0.0
        self._pet_direction = "right"
        self._pet_action = "walk"
        self._pet_action_ticks = 0
        self._pet_frame_index = 0
        self._pet_frame_ticks = 0
        self._last_drawn_size = None
        self.frames = []
        self.selector_containers = []
        self.role_widgets = {"primary": [], "muted": [], "time": [], "diff": []}

        self.title(APP_NAME)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.update_idletasks()

        self._dpi = get_window_dpi(self.winfo_id())
        self._dpi_scale = self._dpi / BASE_DPI
        self._logical_width = float(self.config_data["window_width"])
        self._logical_height = float(self.config_data["window_height"])
        try:
            self.tk.call("tk", "scaling", self._dpi / 72.0)
        except tk.TclError:
            pass
        self.minsize(self._px(WINDOW_WIDTH), self._px(WINDOW_HEIGHT))

        self.local_city = tk.StringVar(value=self.config_data["local_city"])
        self.target_city = tk.StringVar(value=self.config_data["target_city"])
        self.theme_name = tk.StringVar(value=self.config_data["theme"])
        self.autostart = tk.BooleanVar(value=bool(self.config_data["autostart"]))
        self.pet_name = tk.StringVar(value=self.config_data["pet"])
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
        self.frames.append(self.content)

        self._build_ui()
        self._apply_layout_metrics()
        self.bind("<Configure>", self._on_root_configure, add="+")
        self._place_window()
        self.apply_theme()
        self._bind_window_interactions()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        # 非 Windows 不显示错误，只禁用无效的自启选项。
        if sys.platform != "win32":
            self.autostart.set(False)
            self.autostart_check.configure(state="disabled")

        self.after(0, self.update_clock)
        self.after(80, self._apply_pet_selection)

    def _px(self, logical_value):
        return logical_to_physical(logical_value, self._dpi_scale)

    def _register_role(self, widget, role):
        self.role_widgets[role].append(widget)
        return widget

    def _new_frame(self, parent):
        frame = tk.Frame(parent, bd=0, highlightthickness=0)
        self.frames.append(frame)
        return frame

    def _build_ui(self):
        top = self.top = self._new_frame(self.content)
        top.pack(fill="x", padx=8, pady=(4, 0))

        title_label = self.title_label = self._register_role(
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

        self.pet_button = tk.Menubutton(
            top,
            text="宠物",
            relief="flat",
            bd=0,
            width=4,
            cursor="hand2",
            indicatoron=False,
            font=("Microsoft YaHei UI", 8),
        )
        self.pet_button.pack(side="right", padx=(0, 2))
        self.pet_menu = tk.Menu(self.pet_button, tearoff=False)
        self.pet_button.configure(menu=self.pet_menu)
        self.pet_menu.add_radiobutton(
            label="关闭宠物",
            value=PET_OFF,
            variable=self.pet_name,
            command=self.on_pet_changed,
        )
        self.pet_menu.add_separator()
        self.pet_menu.add_command(label="案例宠物", state="disabled")
        self.pet_menu.add_radiobutton(
            label="  英短猫",
            value=PET_NAME,
            variable=self.pet_name,
            command=self.on_pet_changed,
        )

        selector_row = self.selector_row = self._new_frame(self.content)
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

        display = self.display = self._new_frame(self.content)
        display.pack(fill="both", expand=True, padx=8, pady=(0, 0))
        time_group = self.time_group = self._new_frame(display)
        time_group.pack(expand=True)
        target_time_label = self.target_time_label = self._register_role(
            tk.Label(
                time_group,
                textvariable=self.target_time_text,
                bd=0,
                font=("Consolas", 28, "bold"),
            ),
            "time",
        )
        target_time_label.pack()

        target_date_label = self.target_date_label = self._register_role(
            tk.Label(
                time_group,
                textvariable=self.target_date_text,
                bd=0,
                font=("Consolas", 9),
            ),
            "muted",
        )
        target_date_label.pack()

        self.divider_bottom = tk.Frame(self.content, height=1, bd=0)
        self.divider_bottom.pack(fill="x", padx=8, pady=(0, 1))

        bottom = self.bottom = self._new_frame(self.content)
        bottom.pack(fill="x", padx=8, pady=(0, 4))
        local_detail_label = self.local_detail_label = self._register_role(
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
        separator_label = self.separator_label = self._register_role(
            tk.Label(
                bottom,
                text=" · ",
                bd=0,
                font=("Microsoft YaHei UI", 8),
            ),
            "muted",
        )
        separator_label.pack(side="left")
        difference_label = self.difference_label = self._register_role(
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
            self.border_canvas,
            self.content,
            top,
            selector_row,
            display,
            time_group,
            bottom,
            title_label,
            target_time_label,
            target_date_label,
            local_detail_label,
            separator_label,
            difference_label,
        ]

    def _apply_layout_metrics(self):
        """把逻辑间距按当前显示器 DPI 应用到现有控件。"""
        outer_x = self._px(12)
        outer_y = self._px(9)
        inner = self._px(8)
        self.content.place(
            x=outer_x,
            y=outer_y,
            relwidth=1,
            relheight=1,
            width=-2 * outer_x,
            height=-2 * outer_y,
        )
        self.top.pack_configure(padx=inner, pady=(self._px(4), 0))
        self.theme_combo.pack_configure(padx=(self._px(8), 0))
        self.pet_button.pack_configure(padx=(0, self._px(2)))
        self.selector_row.pack_configure(padx=inner, pady=(self._px(3), 0))
        for container, column in self.selector_containers:
            padding = (0, self._px(4)) if column == 0 else (self._px(4), 0)
            container.grid_configure(padx=padding)
        self.divider_top.configure(height=self._px(1))
        self.divider_top.pack_configure(padx=inner, pady=(self._px(6), 0))
        self.display.pack_configure(padx=inner, pady=(0, 0))
        self.divider_bottom.configure(height=self._px(1))
        self.divider_bottom.pack_configure(padx=inner, pady=(0, self._px(1)))
        self.bottom.pack_configure(padx=inner, pady=(0, self._px(4)))
        self.minsize(self._px(WINDOW_WIDTH), self._px(WINDOW_HEIGHT))

    def _make_selector(self, parent, label_text, variable, column):
        container = self._new_frame(parent)
        self.selector_containers.append((container, column))
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
                borderwidth=self._px(1),
                padding=self._px(2),
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
        self.pet_button.configure(
            bg=theme["bg"],
            fg=theme["primary"],
            activebackground=theme["surface"],
            activeforeground=theme["accent"],
        )
        self.pet_menu.configure(
            bg=theme["control"],
            fg=theme["primary"],
            activebackground=theme["surface"],
            activeforeground=theme["accent"],
            disabledforeground=theme["muted"],
            selectcolor=theme["accent"],
            activeborderwidth=0,
            bd=self._px(1),
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
        self._last_drawn_size = (self.winfo_width(), self.winfo_height())

    def _draw_theme_border(self, name, theme):
        """绘制各主题的专属边框装饰。"""
        canvas = self.border_canvas
        canvas.delete("all")
        width = max(1, canvas.winfo_width() - 1)
        height = max(1, canvas.winfo_height() - 1)
        s = self._px
        thin = max(1, s(1))
        medium = max(1, s(2))

        if name == "春日":
            canvas.create_rectangle(
                s(2), s(2), width - s(2), height - s(2),
                outline=theme["border"], width=thin
            )
            canvas.create_rectangle(
                s(6), s(6), width - s(6), height - s(6),
                outline=theme["accent"], width=thin
            )
            self._draw_leaf_sprig(s(3), s(3), 1, 1, theme["accent"])
            self._draw_leaf_sprig(
                width - s(3), height - s(3), -1, -1, theme["accent"]
            )
            for distance in (73, 67, 61, 55):
                top_x = width - s(distance)
                bottom_x = s(distance - 2)
                canvas.create_oval(
                    top_x, s(4), top_x + s(2), s(6),
                    fill=theme["border"], outline=""
                )
                canvas.create_oval(
                    bottom_x,
                    height - s(6),
                    bottom_x + s(2),
                    height - s(4),
                    fill=theme["border"],
                    outline="",
                )
        elif name == "机械":
            points = [s(3), s(10), s(10), s(3), width - s(10), s(3),
                      width - s(3), s(10), width - s(3), height - s(10),
                      width - s(10), height - s(3), s(10), height - s(3),
                      s(3), height - s(10)]
            inner = [s(7), s(13), s(13), s(7), width - s(13), s(7),
                     width - s(7), s(13), width - s(7), height - s(13),
                     width - s(13), height - s(7), s(13), height - s(7),
                     s(7), height - s(13)]
            canvas.create_polygon(
                points, fill="", outline=theme["border"], width=medium
            )
            canvas.create_polygon(
                inner, fill="", outline="#2f383e", width=thin
            )
            for x, y in ((s(10), s(10)), (width - s(10), s(10)),
                         (s(10), height - s(10)),
                         (width - s(10), height - s(10))):
                canvas.create_oval(
                    x - s(3), y - s(3), x + s(3), y + s(3),
                    outline=theme["border"], width=thin
                )
                canvas.create_oval(
                    x - s(1), y - s(1), x + s(1), y + s(1),
                    fill=theme["accent2"], outline=""
                )
            ticks = (s(22), s(27), s(32),
                     width - s(32), width - s(27), width - s(22))
            for x in ticks:
                canvas.create_line(
                    x, s(4), x, s(8), fill=theme["accent2"], width=medium
                )
            canvas.create_line(
                s(3), s(78), s(8), s(78),
                fill=theme["accent"], width=max(1, s(3))
            )
            canvas.create_line(
                width - s(8), s(78), width - s(3), s(78),
                fill=theme["accent"], width=max(1, s(3))
            )
        else:
            magenta = theme["accent2"]
            cyan = theme["accent"]
            middle = width / 2
            # 不对称分段线与切角，让霓虹主题和春日主题拉开视觉距离。
            canvas.create_line(
                s(3), s(58), s(3), s(14), s(14), s(3), s(104), s(3),
                fill=magenta, width=medium
            )
            canvas.create_line(
                s(112), s(3), width - s(14), s(3), width - s(3), s(14),
                width - s(3), s(47), fill=cyan, width=medium
            )
            canvas.create_line(
                width - s(3), s(56), width - s(3), height - s(14),
                width - s(14), height - s(3), middle + s(30), height - s(3),
                fill=magenta, width=medium
            )
            canvas.create_line(
                middle + s(6), height - s(3), middle - s(6), height - s(3),
                middle - s(10), height - s(10), middle - s(14), height - s(1),
                middle - s(19), height - s(8), middle - s(23), height - s(3),
                s(52), height - s(3), fill=magenta, width=medium
            )
            canvas.create_line(
                s(48), height - s(3), s(14), height - s(3), s(3),
                height - s(14), s(3), s(70), fill=cyan, width=medium
            )
            canvas.create_oval(
                width - s(6), s(50), width, s(56),
                outline=magenta, width=medium
            )
            canvas.create_oval(
                s(46), height - s(6), s(52), height,
                outline=cyan, width=medium
            )

    def _draw_leaf_sprig(self, x, y, dx, dy, color):
        """绘制小型枝叶角花，避免引入外部图片。"""
        canvas = self.border_canvas
        canvas.create_line(
            x, y, x + self._px(7) * dx, y + self._px(6) * dy,
            fill=color, width=max(1, self._px(1)), smooth=True
        )
        leaves = ((1, 1, 4, 3), (3, 3, 6, 5), (5, 5, 8, 7))
        for x1, y1, x2, y2 in leaves:
            xa, xb = sorted((x + self._px(x1) * dx, x + self._px(x2) * dx))
            ya, yb = sorted((y + self._px(y1) * dy, y + self._px(y2) * dy))
            canvas.create_oval(
                xa, ya, xb, yb, outline=color, width=max(1, self._px(1))
            )

    def _place_window(self):
        """恢复保存的位置；首次运行默认放在屏幕右上角。"""
        width = self._px(self._logical_width)
        height = self._px(self._logical_height)
        min_size = (self._px(WINDOW_WIDTH), self._px(WINDOW_HEIGHT))
        saved_x = self.config_data.get("window_x")
        saved_y = self.config_data.get("window_y")

        has_saved_position = (
            isinstance(saved_x, int) and not isinstance(saved_x, bool)
            and isinstance(saved_y, int) and not isinstance(saved_y, bool)
        )
        if has_saved_position:
            x, y = saved_x, saved_y
        else:
            x, y = 0, 0

        work_area = self._get_work_area((x, y, width, height))
        if not has_saved_position:
            left, top, right, _bottom = work_area
            offset = self._px(16)
            x = right - width - offset
            y = top + offset

        x, y, width, height = clamp_geometry_to_work_area(
            (x, y, width, height), work_area, min_size
        )
        self._set_window_geometry((x, y, width, height))
        self.update_idletasks()
        self._logical_width = physical_to_logical(width, self._dpi_scale)
        self._logical_height = physical_to_logical(height, self._dpi_scale)

    def _get_work_area(self, rectangle):
        work_area = get_monitor_work_area(rectangle)
        if work_area is not None:
            return work_area
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    @staticmethod
    def _format_geometry(width, height, x, y):
        return f"{int(width)}x{int(height)}{int(x):+d}{int(y):+d}"

    def _set_window_geometry(self, geometry):
        x, y, width, height = geometry
        if set_native_window_geometry(self.winfo_id(), geometry):
            return
        self.geometry(self._format_geometry(width, height, x, y))

    def _on_root_configure(self, event):
        if event.widget is not self or self._configure_job is not None:
            return
        self._configure_job = self.after_idle(self._process_root_configure)

    def _process_root_configure(self):
        self._configure_job = None
        new_dpi = get_window_dpi(self.winfo_id())
        if new_dpi != self._dpi:
            self._apply_dpi_change(new_dpi)
            return

        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        if self._pointer_mode != "move":
            self._logical_width = max(
                WINDOW_WIDTH, physical_to_logical(width, self._dpi_scale)
            )
            self._logical_height = max(
                WINDOW_HEIGHT, physical_to_logical(height, self._dpi_scale)
            )
        size = (width, height)
        if size != self._last_drawn_size:
            name = self.theme_name.get()
            self._draw_theme_border(name, THEMES.get(name, THEMES["春日"]))
            self._last_drawn_size = size

    def _apply_dpi_change(self, new_dpi):
        """跨显示器时保持逻辑尺寸不变，只改变清晰的物理像素尺寸。"""
        self._dpi = max(BASE_DPI, int(new_dpi))
        self._dpi_scale = self._dpi / BASE_DPI
        try:
            self.tk.call("tk", "scaling", self._dpi / 72.0)
        except tk.TclError:
            pass

        self._apply_layout_metrics()
        width = self._px(self._logical_width)
        height = self._px(self._logical_height)
        x, y = self.winfo_x(), self.winfo_y()
        work_area = self._get_work_area((x, y, width, height))
        geometry = clamp_geometry_to_work_area(
            (x, y, width, height),
            work_area,
            (self._px(WINDOW_WIDTH), self._px(WINDOW_HEIGHT)),
        )
        self._set_window_geometry(geometry)
        self._last_drawn_size = None
        self.apply_theme()
        if self.pet_name.get() != PET_OFF:
            self._load_pet_images()
            if self._pet_label is not None:
                image = self._current_pet_image()
                if image is not None:
                    self._pet_label.configure(image=image)

    def _bind_window_interactions(self):
        for widget in self.drag_widgets:
            widget.bind("<ButtonPress-1>", self._on_pointer_press)
            widget.bind("<B1-Motion>", self._on_pointer_drag)
            widget.bind("<ButtonRelease-1>", self._on_pointer_release)
        self.border_canvas.bind("<Motion>", self._on_border_motion, add="+")
        self.border_canvas.bind("<Leave>", self._on_border_leave, add="+")

    def _resize_edges_at(self, x_root, y_root):
        x = x_root - self.winfo_rootx()
        y = y_root - self.winfo_rooty()
        grip = self._px(RESIZE_BORDER)
        width = self.winfo_width()
        height = self.winfo_height()
        vertical = "n" if y <= grip else "s" if y >= height - grip else ""
        horizontal = "w" if x <= grip else "e" if x >= width - grip else ""
        return vertical + horizontal

    def _set_resize_cursor(self, edges):
        cursor_map = {
            "n": "sb_v_double_arrow",
            "s": "sb_v_double_arrow",
            "e": "sb_h_double_arrow",
            "w": "sb_h_double_arrow",
            "nw": "size_nw_se",
            "se": "size_nw_se",
            "ne": "size_ne_sw",
            "sw": "size_ne_sw",
        }
        cursor = cursor_map.get(edges, "arrow")
        try:
            self.border_canvas.configure(cursor=cursor)
        except tk.TclError:
            self.border_canvas.configure(cursor="sizing" if edges else "arrow")

    def _on_border_motion(self, event):
        if self._pointer_mode is None:
            self._set_resize_cursor(self._resize_edges_at(event.x_root, event.y_root))

    def _on_border_leave(self, _event):
        if self._pointer_mode is None:
            self._set_resize_cursor("")

    def _on_pointer_press(self, event):
        edges = self._resize_edges_at(event.x_root, event.y_root)
        if edges:
            self._pointer_mode = "resize"
            self._resize_state = (
                event.x_root,
                event.y_root,
                (self.winfo_x(), self.winfo_y(),
                 self.winfo_width(), self.winfo_height()),
                edges,
            )
            self._set_resize_cursor(edges)
            return

        self._pointer_mode = "move"
        self._drag_origin = (
            event.x_root - self.winfo_x(),
            event.y_root - self.winfo_y(),
        )

    def _on_pointer_drag(self, event):
        if self._pointer_mode == "resize" and self._resize_state:
            start_x, start_y, start_geometry, edges = self._resize_state
            geometry = calculate_resize_geometry(
                start_geometry,
                (event.x_root - start_x, event.y_root - start_y),
                edges,
                (self._px(WINDOW_WIDTH), self._px(WINDOW_HEIGHT)),
            )
            self._set_window_geometry(geometry)
            return

        if self._pointer_mode == "move" and self._drag_origin:
            x = event.x_root - self._drag_origin[0]
            y = event.y_root - self._drag_origin[1]
            self._set_window_geometry(
                (x, y, self.winfo_width(), self.winfo_height())
            )

    def _on_pointer_release(self, event):
        self._pointer_mode = None
        self._drag_origin = None
        self._resize_state = None
        self._logical_width = max(
            WINDOW_WIDTH,
            physical_to_logical(self.winfo_width(), self._dpi_scale),
        )
        self._logical_height = max(
            WINDOW_HEIGHT,
            physical_to_logical(self.winfo_height(), self._dpi_scale),
        )
        self._set_resize_cursor(self._resize_edges_at(event.x_root, event.y_root))
        self.schedule_save()

    def on_city_changed(self, _event=None):
        self.refresh_clock_display()
        self.schedule_save()

    def on_theme_changed(self, _event=None):
        self.apply_theme()
        self.schedule_save()

    def on_pet_changed(self):
        self._apply_pet_selection()
        self.schedule_save()

    def _load_pet_images(self):
        pet_slug = PETS.get(self.pet_name.get())
        if not pet_slug:
            self._pet_images = {}
            return

        scale = Fraction(max(1.0, self._dpi_scale)).limit_denominator(4)
        images = {}
        for action in PET_ACTIONS:
            images[action] = {}
            for direction, direction_suffix in (("right", ""), ("left", "-left")):
                path = resource_path(
                    f"assets/pets/{pet_slug}-{action}-sheet{direction_suffix}.png"
                )
                sheet = tk.PhotoImage(file=str(path))
                frame_width = max(1, sheet.width() // PET_ACTION_FRAME_COUNT)
                frames = []
                for index in range(PET_ACTION_FRAME_COUNT):
                    frame = tk.PhotoImage(width=frame_width, height=sheet.height())
                    frame.tk.call(
                        frame,
                        "copy",
                        sheet,
                        "-from",
                        index * frame_width,
                        0,
                        (index + 1) * frame_width,
                        sheet.height(),
                        "-to",
                        0,
                        0,
                    )
                    if scale.numerator != scale.denominator:
                        frame = frame.zoom(scale.numerator, scale.numerator).subsample(
                            scale.denominator, scale.denominator
                        )
                    frames.append(frame)
                images[action][direction] = frames
        self._pet_images = images

    def _start_pet_action(self, action):
        self._pet_action = action
        self._pet_frame_index = 0
        self._pet_frame_ticks = 0
        low, high = PET_ACTION_TICK_RANGES[action]
        self._pet_action_ticks = random.randint(low, high)

    def _choose_next_pet_action(self):
        if self._pet_action != "walk":
            return "walk"
        return random.choice(PET_RANDOM_ACTIONS)

    def _current_pet_image(self):
        action_images = self._pet_images.get(self._pet_action)
        if not action_images:
            return None
        frames = action_images.get(self._pet_direction) or action_images.get("right")
        if not frames:
            return None
        self._pet_frame_index %= len(frames)
        return frames[self._pet_frame_index]

    def _apply_pet_selection(self):
        if self._pet_job is not None:
            self.after_cancel(self._pet_job)
            self._pet_job = None
        if self._pet_window is not None:
            self._pet_window.destroy()
            self._pet_window = None
            self._pet_label = None

        if self.pet_name.get() == PET_OFF:
            self._pet_images = {}
            return

        try:
            self._load_pet_images()
        except (OSError, tk.TclError):
            self.pet_name.set(PET_OFF)
            self._pet_images = {}
            return

        pet_window = tk.Toplevel(self)
        pet_window.overrideredirect(True)
        pet_window.configure(bg=PET_WINDOW_KEY)
        pet_window.attributes("-topmost", True)
        try:
            pet_window.attributes("-transparentcolor", PET_WINDOW_KEY)
            pet_window.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        self._pet_window = pet_window
        self._pet_label = tk.Label(
            pet_window,
            image=self._pet_images["walk"]["right"][0],
            bg=PET_WINDOW_KEY,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self._pet_label.pack()
        self._pet_label.bind("<Button-1>", self._show_pet_menu)
        self._pet_label.bind("<Button-3>", self._show_pet_menu)
        self._pet_distance = 0.0
        self._pet_direction = "right"
        self._start_pet_action("walk")
        self._animate_pet()

    def _show_pet_menu(self, event):
        try:
            self.pet_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.pet_menu.grab_release()

    def _animate_pet(self):
        self._pet_job = None
        if self._pet_window is None or not self._pet_images:
            return

        image = self._current_pet_image()
        if image is None:
            return
        sprite_size = (image.width(), image.height())
        window_geometry = (
            self.winfo_x(),
            self.winfo_y(),
            self.winfo_width(),
            self.winfo_height(),
        )
        pet_x, pet_y, direction = pet_position_inside_border(
            window_geometry,
            sprite_size,
            self._pet_distance,
            margin=self._px(10),
        )

        if direction != self._pet_direction:
            self._pet_direction = direction
            self._pet_frame_index = 0
            self._pet_frame_ticks = 0

        if self._pet_action == "walk":
            self._pet_distance += max(1, self._px(1.25))

        self._pet_frame_ticks += 1
        if self._pet_frame_ticks >= PET_ACTION_FRAME_TICKS[self._pet_action]:
            self._pet_frame_ticks = 0
            frames = self._pet_images[self._pet_action][self._pet_direction]
            self._pet_frame_index = (self._pet_frame_index + 1) % len(frames)

        self._pet_action_ticks -= 1
        if self._pet_action_ticks <= 0:
            self._start_pet_action(self._choose_next_pet_action())

        image = self._current_pet_image()
        self._pet_label.configure(image=image)
        self._pet_window.geometry(
            self._format_geometry(image.width(), image.height(), pet_x, pet_y)
        )
        self._pet_job = self.after(PET_TICK_MS, self._animate_pet)

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
        self._logical_width = max(
            WINDOW_WIDTH,
            physical_to_logical(self.winfo_width(), self._dpi_scale),
        )
        self._logical_height = max(
            WINDOW_HEIGHT,
            physical_to_logical(self.winfo_height(), self._dpi_scale),
        )
        data = {
            "local_city": self.local_city.get(),
            "target_city": self.target_city.get(),
            "theme": self.theme_name.get(),
            "autostart": bool(self.autostart.get()),
            "window_x": self.winfo_x(),
            "window_y": self.winfo_y(),
            "window_width": int(round(self._logical_width)),
            "window_height": int(round(self._logical_height)),
            "pet": self.pet_name.get(),
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
        if self._configure_job is not None:
            self.after_cancel(self._configure_job)
            self._configure_job = None
        if self._pet_job is not None:
            self.after_cancel(self._pet_job)
            self._pet_job = None
        if self._pet_window is not None:
            self._pet_window.destroy()
            self._pet_window = None
        self.save_config()
        self.destroy()


def enable_windows_dpi_awareness():
    """优先启用 Per-Monitor V2；旧版 Windows 逐级回退。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        set_context = ctypes.windll.user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        if set_context(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    try:
        import ctypes

        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:
            return
    except (AttributeError, OSError):
        pass

    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def main():
    enable_windows_dpi_awareness()
    app = TimeCoordinator()
    app.mainloop()


if __name__ == "__main__":
    main()
