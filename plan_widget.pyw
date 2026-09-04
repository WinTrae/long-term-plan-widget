import json
import math
import os
import queue
import re
import shutil
import threading
import tkinter as tk
import ctypes
import traceback
from ctypes import wintypes
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox

try:
    import numpy as np
    import sounddevice as sd
except Exception:
    np = None
    sd = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "plan_data.json"
DATA_BACKUP_PATH = BASE_DIR / "plan_data.json.bak"
SETTINGS_PATH = BASE_DIR / "settings.json"
ERROR_LOG_PATH = BASE_DIR / "plan_widget_error.log"
VOICE_MODEL_DIR = BASE_DIR / "models"
SKIN_ASSET_DIR = BASE_DIR / "assets"
INSTANCE_MUTEX_NAME = r"Local\LongTermPlanWidget"
INSTANCE_EVENT_NAME = r"Local\LongTermPlanWidget_Show"
WINDOW_MASK = "#ff00ff"
DOCK_THRESHOLD = 36
HANDLE_LENGTH = 224
HANDLE_THICKNESS = 11
HANDLE_REVEAL_DELAY_MS = 160
AUTO_HIDE_DELAY_MS = 550
DEFAULT_COLORS = {
    "bg": WINDOW_MASK,
    "panel": "#f7fafc",
    "panel_alt": "#edf4f7",
    "line": "#cfd9e2",
    "text": "#102033",
    "muted": "#334e68",
    "todo": "#1f6f8b",
    "done": "#337357",
    "done_marker": "#4a866c",
    "warn": "#a15c25",
    "handle": "#aebfc8",
    "handle_hover": "#bdcdd4",
    "handle_border": "#f3f8fa",
    "handle_icon": "#486f81",
}
THEMES = {
    "default": {
        "label": "默认经典",
        "colors": DEFAULT_COLORS,
        "banner": "",
        "banner_height": 0,
    },
    "sunny": {
        "label": "晴野暖橙",
        "colors": {
            "bg": WINDOW_MASK,
            "panel": "#fff9ed",
            "panel_alt": "#f3f4df",
            "line": "#d8d3aa",
            "text": "#3d2b24",
            "muted": "#655f4b",
            "todo": "#c36f4c",
            "done": "#7b8550",
            "done_marker": "#98a367",
            "warn": "#b45f3e",
            "handle": "#d7ab8d",
            "handle_hover": "#e1b99e",
            "handle_border": "#fff4e8",
            "handle_icon": "#855946",
        },
        "banner": "sunny-field.png",
        "banner_height": 58,
        "banner_aspect": 7.39,
        "banner_crop_bottom": 0.541,
    },
    "cloud": {
        "label": "云境浅蓝",
        "colors": {
            "bg": WINDOW_MASK,
            "panel": "#f4fbfc",
            "panel_alt": "#e7f3f5",
            "line": "#c5dce0",
            "text": "#22343b",
            "muted": "#526c75",
            "todo": "#568ba0",
            "done": "#75835d",
            "done_marker": "#91a078",
            "warn": "#b46f49",
            "handle": "#9fbac4",
            "handle_hover": "#b0c8d0",
            "handle_border": "#f4fbfc",
            "handle_icon": "#426d7e",
        },
        "banner": "cloud-glass.png",
        "banner_height": 58,
        "banner_aspect": 7.36,
        "banner_crop_bottom": 0.543,
    },
}
COLORS = DEFAULT_COLORS.copy()


def write_error_log(message):
    try:
        if ERROR_LOG_PATH.exists() and ERROR_LOG_PATH.stat().st_size > 1_000_000:
            ERROR_LOG_PATH.replace(ERROR_LOG_PATH.with_suffix(".log.old"))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with ERROR_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {message.rstrip()}\n")
    except Exception:
        pass


def acquire_instance_guard():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    mutex = kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    already_running = ctypes.get_last_error() == 183
    event = kernel32.CreateEventW(None, True, False, INSTANCE_EVENT_NAME)

    if not mutex:
        write_error_log("无法创建单实例互斥锁，程序将继续启动")
        return None, event, True
    if already_running:
        if event:
            kernel32.SetEvent(event)
            kernel32.CloseHandle(event)
        kernel32.CloseHandle(mutex)
        return None, None, False
    return mutex, event, True


def release_instance_guard(mutex, event):
    try:
        kernel32 = ctypes.windll.kernel32
        if event:
            kernel32.CloseHandle(event)
        if mutex:
            kernel32.CloseHandle(mutex)
    except Exception:
        pass


def load_settings():
    default = {
        "geometry": "",
        "topmost": True,
        "alpha": 0.9,
        "autoHide": True,
        "dockEdge": "",
        "skin": "default",
    }
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as file:
            settings = json.load(file)
        if not isinstance(settings, dict):
            return default
        merged = {**default, **settings}
        if not isinstance(merged.get("geometry"), str):
            merged["geometry"] = ""
        if merged.get("dockEdge") not in ("", "left", "right", "top"):
            merged["dockEdge"] = ""
        if merged.get("skin") not in THEMES:
            merged["skin"] = "default"
        try:
            merged["alpha"] = min(1.0, max(0.62, float(merged["alpha"])))
        except (TypeError, ValueError):
            merged["alpha"] = default["alpha"]
        merged["topmost"] = bool(merged.get("topmost"))
        merged["autoHide"] = bool(merged.get("autoHide"))
        return merged
    except Exception:
        return default


def save_settings(root, topmost, alpha, auto_hide, dock_edge, geometry, skin):
    settings = {
        "geometry": geometry,
        "topmost": bool(topmost.get()),
        "alpha": float(alpha.get()),
        "autoHide": bool(auto_hide.get()),
        "dockEdge": dock_edge,
        "skin": skin,
    }
    try:
        temp_path = SETTINGS_PATH.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, SETTINGS_PATH)
    except Exception as error:
        write_error_log(f"保存窗口设置失败：{error}")


def validate_plan_data(data):
    if not isinstance(data, dict):
        raise ValueError("计划数据的最外层必须是对象")
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("计划数据中的 tasks 必须是列表")
    seen_ids = set()
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"第 {index} 条计划不是有效对象")
        task_id = task.get("id")
        if not task_id:
            raise ValueError(f"第 {index} 条计划缺少 id")
        if task_id in seen_ids:
            raise ValueError(f"计划 id 重复：{task_id}")
        seen_ids.add(task_id)
        if not task.get("title"):
            raise ValueError(f"计划缺少标题：{task_id}")
        if task.get("status") not in ("todo", "done"):
            raise ValueError(f"计划状态不合法：{task_id}")
    return {"updatedAt": data.get("updatedAt", ""), "tasks": tasks}


def load_plan():
    if not DATA_PATH.exists():
        empty_plan = {"updatedAt": date.today().isoformat(), "tasks": []}
        try:
            save_plan(empty_plan)
        except Exception as error:
            write_error_log(f"创建初始计划数据失败：{error}")
            return {**empty_plan, "error": str(error)}
        return empty_plan

    try:
        with DATA_PATH.open("r", encoding="utf-8-sig") as file:
            return validate_plan_data(json.load(file))
    except Exception as primary_error:
        try:
            with DATA_BACKUP_PATH.open("r", encoding="utf-8-sig") as file:
                recovered = validate_plan_data(json.load(file))
            write_error_log(
                f"主计划数据读取失败，已临时使用自动备份：{primary_error}"
            )
            return recovered
        except Exception as backup_error:
            write_error_log(
                "主计划数据与自动备份均无法读取："
                f"主文件={primary_error}；备份={backup_error}"
            )
            return {"updatedAt": "", "tasks": [], "error": str(primary_error)}


def save_plan(plan):
    plan["updatedAt"] = date.today().isoformat()
    temp_path = DATA_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(plan, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    if DATA_PATH.exists():
        try:
            shutil.copy2(DATA_PATH, DATA_BACKUP_PATH)
        except Exception as error:
            write_error_log(f"备份计划数据失败：{error}")
    os.replace(temp_path, DATA_PATH)


def due_date_from_text(text):
    today = date.today()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "今天" in text:
        return today.isoformat()

    match = re.search(
        r"(?:(\d{4})\s*[年./-]\s*)?"
        r"(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?",
        text,
    )
    if not match:
        return ""
    try:
        year = int(match.group(1) or today.year)
        due = date(year, int(match.group(2)), int(match.group(3)))
        if not match.group(1) and due < today:
            due = date(year + 1, due.month, due.day)
        return due.isoformat()
    except ValueError:
        return ""


def clean_spoken_text(text):
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = cleaned.replace(",", "，").replace(";", "；")
    leading_fillers = re.compile(
        r"^(?:(?:嗯+|呃+|额+|哎呀|那个|就是|然后|对了|比如说|怎么说呢)[，、。！？；\s]*)+"
    )
    cleaned = leading_fillers.sub("", cleaned)
    cleaned = re.sub(
        r"[，、]\s*(?:嗯+|呃+|额+|那个|就是|然后)(?=[，、。！？；\s]|$)",
        "，",
        cleaned,
    )
    cleaned = re.sub(r"([，、。！？；])\1+", r"\1", cleaned)
    return cleaned.strip(" ，、。；")


def organize_task_text(text):
    cleaned = clean_spoken_text(text) or text.strip()
    task_cue = re.search(
        r"(?:帮我|给我)?(?:记录一下|记一下|记个|添加(?:一个)?计划|新建(?:一个)?计划)"
        r"[，、：:\s]*(.+)$",
        cleaned,
    )
    task_body = task_cue.group(1).strip() if task_cue else cleaned
    task_body = re.sub(r"(?:的)?计划[。！!？?]*$", "", task_body).strip(" ，、。；")

    candidate = task_body
    candidate = re.sub(
        r"^(?:我|我们|我这边)?(?:现在|最近|近期|这两天)?[，、\s]*",
        "",
        candidate,
    )
    candidate = re.sub(
        r"^(?:今天|明天|后天)(?:的时候)?(?:早上|上午|中午|下午|晚上)?[，、\s]*",
        "",
        candidate,
    )
    candidate = re.sub(
        r"^(?:我|我们)?(?:想要?|要|得|需要|计划|准备|打算|记得)[，、\s]*",
        "",
        candidate,
    )
    candidate = re.sub(r"^去(?:一趟)?", "", candidate)
    candidate = candidate.strip(" ，、。；") or task_body

    certificate_codes = []
    if "考证" in task_body or "证书" in task_body:
        for code in re.findall(r"(?<![A-Za-z])[A-Za-z]{2,8}(?![A-Za-z])", task_body):
            normalized = code.upper()
            if normalized not in certificate_codes:
                certificate_codes.append(normalized)

    if certificate_codes:
        title = f"确认并准备 {' / '.join(certificate_codes)} 证书考试"
    else:
        clauses = [
            part.strip()
            for part in re.split(r"[，、。！？；]|然后|但是|所以|另外|回头|具体", candidate)
            if part.strip()
        ]
        selected = []
        for clause in clauses:
            proposed = "，".join([*selected, clause])
            if selected and len(proposed) > 16:
                break
            selected.append(clause)
            if len(proposed) >= 8:
                break
        title = "，".join(selected) or candidate
        if len(title) > 16:
            title = title[:15].rstrip(" ，、。；") + "…"

    action_words = (
        "联系|沟通|发送|提交|准备|购买|买|修|办理|报名|学习|复习|考试|考证|"
        "预约|完成|整理|确认|搭建|查看|查询|领取|拿|取|交|写|修改|更新|参加|去"
    )
    is_task = bool(task_cue or due_date_from_text(task_body) or re.search(action_words, task_body))
    has_detail = len(task_body) > len(title) + 2 or task_body != title
    note = task_body if has_detail else ""
    return title, note, cleaned, is_task


def fmt_date(value):
    if not value:
        return ""
    return str(value).replace("-", ".")


def due_state(value):
    if not value:
        return ""
    try:
        due = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return ""
    today = date.today()
    days = (due - today).days
    if days < 0:
        return "已过期"
    if days == 0:
        return "今天"
    if days == 1:
        return "明天"
    if days <= 3:
        return f"{days}天内"
    return ""


class PlanWindow:
    def __init__(self, instance_event=None):
        self.root = tk.Tk()
        self.root.title("长期计划表")
        self.root.report_callback_exception = self.report_callback_exception
        self.instance_event = instance_event
        self.settings = load_settings()
        self.skin_name = self.settings.get("skin", "default")
        COLORS.clear()
        COLORS.update(THEMES[self.skin_name]["colors"])
        self.skin = tk.StringVar(value=self.skin_name)
        self.topmost = tk.BooleanVar(value=bool(self.settings["topmost"]))
        self.alpha = tk.DoubleVar(value=float(self.settings["alpha"]))
        self.auto_hide = tk.BooleanVar(value=bool(self.settings["autoHide"]))
        self.dock_edge = self.settings.get("dockEdge", "")
        self.dock_work_area = None
        self.visible_geometry = self.settings.get("geometry", "")
        self.visible_bounds = None
        self.is_hidden = False
        self.auto_hide_after_id = None
        self.handle_reveal_after_id = None
        self.last_mtime = None
        self.plan = {"updatedAt": "", "tasks": []}
        self.drag_start = None
        self.resize_start = None
        self.no_drag_widgets = set()
        self.task_action_widgets = set()
        self.edit_dialog = None
        self.audio_stream = None
        self.audio_chunks = []
        self.is_recording = False
        self.is_transcribing = False
        self.whisper_model = None
        self.voice_results = queue.Queue()
        self.skin_banner_photo = None
        self.skin_banner_after_id = None

        self.setup_window()
        self.build_ui()
        self.sync_plan(force=True)
        self.root.after(100, self.poll_voice_results)
        self.root.after(120, self.poll_dock_pointer)
        if self.instance_event:
            self.root.after(200, self.poll_instance_signal)
        self.root.after(900, self.initialize_auto_hide)

    def report_callback_exception(self, exception_type, exception, exception_traceback):
        details = "".join(
            traceback.format_exception(exception_type, exception, exception_traceback)
        )
        write_error_log(f"界面回调异常：\n{details}")

    def poll_instance_signal(self):
        if not self.instance_event:
            return
        try:
            kernel32 = ctypes.windll.kernel32
            if kernel32.WaitForSingleObject(self.instance_event, 0) == 0:
                kernel32.ResetEvent(self.instance_event)
                self.cancel_auto_hide()
                self.reveal_window()
                self.root.lift()
                self.root.focus_force()
        except Exception as error:
            write_error_log(f"检查重复启动信号失败：{error}")
        try:
            self.root.after(200, self.poll_instance_signal)
        except tk.TclError:
            pass

    def setup_window(self):
        self.root.overrideredirect(True)
        self.root.configure(bg=COLORS["bg"])
        self.root.attributes(
            "-topmost",
            self.topmost.get() or (self.auto_hide.get() and bool(self.dock_edge)),
        )
        self.root.attributes("-alpha", self.alpha.get())
        try:
            self.root.attributes("-transparentcolor", WINDOW_MASK)
        except tk.TclError:
            pass
        self.place_window()

    def place_window(self):
        geometry = self.settings.get("geometry")
        if geometry:
            match = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", geometry)
            if match:
                width, height, x, y = map(int, match.groups())
                self.root.geometry(f"{width}x{height}")
                self.root.update_idletasks()
                self.set_window_bounds(width, height, x, y)
                return

        width = 380
        height = 500
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(20, screen_width - width - 42)
        y = max(20, min(120, screen_height - height - 42))
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def build_ui(self):
        self.title_font = tkfont.Font(family="Microsoft YaHei UI", size=16, weight="bold")
        self.heading_font = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        self.body_font = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self.task_title_font = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        self.small_font = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self.header_action_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.voice_action_font = tkfont.Font(family="Segoe MDL2 Assets", size=12)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="切换置顶", command=self.toggle_topmost)
        self.menu.add_checkbutton(
            label="贴边自动隐藏",
            variable=self.auto_hide,
            command=self.toggle_auto_hide,
        )
        self.menu.add_command(label="透明一点", command=lambda: self.change_alpha(-0.06))
        self.menu.add_command(label="清楚一点", command=lambda: self.change_alpha(0.06))
        skin_menu = tk.Menu(self.menu, tearoff=0)
        for skin_key, theme in THEMES.items():
            skin_menu.add_radiobutton(
                label=theme["label"],
                variable=self.skin,
                value=skin_key,
                command=lambda name=skin_key: self.switch_skin(name),
            )
        self.menu.add_cascade(label="皮肤", menu=skin_menu)
        self.menu.add_command(label="重置位置", command=self.reset_position)
        self.menu.add_separator()
        self.menu.add_command(label="关闭", command=self.close)

        self.background = tk.Canvas(
            self.root,
            bg=WINDOW_MASK,
            highlightthickness=0,
            bd=0,
        )
        self.background.pack(fill="both", expand=True)
        self.background.bind("<Configure>", self.draw_rounded_background)

        self.shell = tk.Frame(
            self.root,
            bg=COLORS["panel"],
            highlightthickness=0,
        )
        self.shell.place(x=8, y=8, relwidth=1.0, relheight=1.0, width=-16, height=-16)

        header = tk.Frame(self.shell, bg=COLORS["panel"])
        header.pack(fill="x", padx=13, pady=(11, 6))

        tk.Label(
            header,
            text="长期计划表",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=self.title_font,
            anchor="w",
        ).pack(side="left")

        self.close_button = tk.Label(
            header,
            text="×",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.header_action_font,
            cursor="hand2",
            width=2,
            padx=0,
        )
        self.close_button.pack(side="right")
        self.close_button.bind("<Button-1>", lambda event: self.close())

        self.add_button = tk.Label(
            header,
            text="+",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.header_action_font,
            cursor="hand2",
            width=2,
            padx=0,
        )
        self.add_button.pack(side="right", padx=(0, 5))
        self.add_button.bind("<Button-1>", self.toggle_add_bar)
        self.no_drag_widgets.add(self.add_button)

        self.voice_button = tk.Label(
            header,
            text="\ue720",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.voice_action_font,
            cursor="hand2",
            width=2,
            padx=0,
        )
        self.voice_button.pack(side="right", padx=(0, 3))
        self.voice_button.bind("<ButtonPress-1>", self.start_voice_recording)
        self.voice_button.bind("<ButtonRelease-1>", self.stop_voice_recording)
        self.no_drag_widgets.add(self.voice_button)

        info = tk.Frame(self.shell, bg=COLORS["panel"])
        info.pack(fill="x", padx=13)

        self.updated_label = tk.Label(
            info,
            text="最后更新：-",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.small_font,
            anchor="w",
        )
        self.updated_label.pack(side="left")

        self.count_label = tk.Label(
            info,
            text="0 项",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.small_font,
            anchor="e",
        )
        self.count_label.pack(side="right")

        self.skin_banner = None
        self.skin_banner_box = None
        theme = THEMES[self.skin_name]
        banner_name = theme.get("banner")
        if banner_name and ImageTk is not None:
            banner_path = SKIN_ASSET_DIR / banner_name
            if banner_path.exists():
                banner_height = int(theme.get("banner_height", 58))
                banner_box = tk.Frame(
                    self.shell,
                    bg=COLORS["panel"],
                    height=banner_height,
                )
                self.skin_banner_box = banner_box
                banner_box.pack(fill="x", padx=13, pady=(8, 0))
                banner_box.pack_propagate(False)
                self.skin_banner = tk.Label(
                    banner_box,
                    bg=COLORS["panel"],
                    bd=0,
                    highlightthickness=0,
                )
                self.skin_banner.pack(fill="both", expand=True)
                self.skin_banner.bind("<Configure>", self.schedule_skin_banner)

        self.add_bar = tk.Frame(
            self.shell,
            bg=COLORS["panel_alt"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        self.add_entry = tk.Entry(
            self.add_bar,
            bg="#ffffff",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            font=self.body_font,
        )
        self.add_entry.pack(side="left", fill="x", expand=True, padx=(9, 5), pady=8)
        self.add_entry.bind("<Return>", self.add_offline_task)
        self.add_entry.bind("<Escape>", lambda event: self.hide_add_bar())
        self.add_confirm = tk.Label(
            self.add_bar,
            text="✓",
            bg=COLORS["panel_alt"],
            fg=COLORS["todo"],
            font=tkfont.Font(family="Segoe UI Symbol", size=13, weight="bold"),
            cursor="hand2",
            padx=8,
        )
        self.add_confirm.pack(side="right", fill="y")
        self.add_confirm.bind("<Button-1>", self.add_offline_task)
        self.no_drag_widgets.update({self.add_entry, self.add_confirm})

        self.canvas = tk.Canvas(
            self.shell,
            bg=COLORS["panel"],
            highlightthickness=0,
            bd=0,
        )
        self.content = tk.Frame(self.canvas, bg=COLORS["panel"])

        self.content.bind(
            "<Configure>",
            lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self.resize_content)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)
        self.bind_widget_events(self.root)
        self.root.bind("<ButtonRelease-1>", self.stop_pointer_action, add="+")
        self.root.bind("<Enter>", self.on_window_enter, add="+")
        self.root.bind("<Leave>", self.on_window_leave, add="+")

        self.canvas.pack(fill="both", expand=True, padx=13, pady=(10, 13))

        self.resize_grip = tk.Label(
            self.root,
            text="◢",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=tkfont.Font(family="Segoe UI", size=11),
            cursor="size_nw_se",
            anchor="se",
            padx=3,
            pady=2,
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-8, y=-8, width=26, height=26)
        self.resize_grip.bind("<ButtonPress-1>", self.start_resize)
        self.resize_grip.bind("<B1-Motion>", self.resize_window)
        self.resize_grip.bind("<ButtonRelease-1>", self.stop_pointer_action)
        self.resize_grip.bind("<Enter>", self.highlight_resize_grip)
        self.resize_grip.bind("<Leave>", self.restore_resize_grip)

        self.hide_handle = tk.Canvas(
            self.root,
            bg=WINDOW_MASK,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.hide_handle.bind("<Enter>", self.on_hidden_handle_enter)
        self.hide_handle.bind("<Leave>", self.on_hidden_handle_leave)
        self.hide_handle.bind("<Button-1>", self.activate_hidden_handle)

    def schedule_skin_banner(self, event=None):
        if self.skin_banner is None:
            return
        if self.skin_banner_after_id is not None:
            try:
                self.root.after_cancel(self.skin_banner_after_id)
            except tk.TclError:
                pass
        self.skin_banner_after_id = self.root.after(80, self.render_skin_banner)

    def render_skin_banner(self):
        self.skin_banner_after_id = None
        if self.skin_banner is None or Image is None or ImageTk is None:
            return
        theme = THEMES[self.skin_name]
        banner_path = SKIN_ASSET_DIR / theme.get("banner", "")
        width = max(1, self.skin_banner.winfo_width())
        aspect = max(1.0, float(theme.get("banner_aspect", 7.0)))
        height = max(42, int(round(width / aspect)))
        if self.skin_banner_box is not None:
            self.skin_banner_box.configure(height=height)
        try:
            with Image.open(banner_path) as source:
                source = source.convert("RGB")
                crop_bottom = min(
                    1.0,
                    max(0.1, float(theme.get("banner_crop_bottom", 1.0))),
                )
                crop_height = max(1, int(round(source.height * crop_bottom)))
                source = source.crop((0, 0, source.width, crop_height))
                banner = source.resize(
                    (width, height),
                    resample=Image.Resampling.LANCZOS,
                )
            self.skin_banner_photo = ImageTk.PhotoImage(banner)
            self.skin_banner.configure(image=self.skin_banner_photo)
        except Exception as error:
            write_error_log(f"加载皮肤横幅失败：{error}")

    def switch_skin(self, skin_name):
        if skin_name not in THEMES:
            self.skin.set(self.skin_name)
            return
        if skin_name == self.skin_name:
            return
        if self.edit_dialog is not None or self.is_recording or self.is_transcribing:
            self.skin.set(self.skin_name)
            self.root.bell()
            return

        self.cancel_auto_hide()
        self.reveal_window()
        if self.skin_banner_after_id is not None:
            try:
                self.root.after_cancel(self.skin_banner_after_id)
            except tk.TclError:
                pass
            self.skin_banner_after_id = None

        self.skin_name = skin_name
        self.skin.set(skin_name)
        COLORS.clear()
        COLORS.update(THEMES[skin_name]["colors"])
        self.root.configure(bg=COLORS["bg"])

        try:
            self.menu.destroy()
        except (AttributeError, tk.TclError):
            pass
        self.root.unbind_all("<MouseWheel>")
        for sequence in (
            "<ButtonPress-1>",
            "<B1-Motion>",
            "<Button-3>",
            "<ButtonRelease-1>",
            "<Enter>",
            "<Leave>",
        ):
            self.root.unbind(sequence)
        for child in self.root.winfo_children():
            child.destroy()

        self.no_drag_widgets.clear()
        self.task_action_widgets.clear()
        self.skin_banner_photo = None
        self.build_ui()
        self.render()
        self.root.update_idletasks()
        self.draw_rounded_background()
        self.save_window_settings()
        self.schedule_auto_hide()

    def toggle_add_bar(self, event=None):
        if self.add_bar.winfo_manager():
            self.hide_add_bar()
        else:
            self.show_add_bar()
        return "break"

    def show_add_bar(self):
        self.cancel_auto_hide()
        self.reveal_window()
        if not self.add_bar.winfo_manager():
            self.add_bar.pack(fill="x", padx=13, pady=(8, 0), before=self.canvas)
        self.add_entry.focus_set()

    def start_voice_recording(self, event=None):
        if self.is_transcribing or self.is_recording:
            self.root.bell()
            return "break"
        if sd is None or np is None:
            messagebox.showerror("无法录音", "本地录音组件没有安装。", parent=self.root)
            return "break"

        self.audio_chunks = []
        self.is_recording = True
        try:
            self.audio_stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                callback=self.capture_audio,
            )
            self.audio_stream.start()
        except Exception as error:
            self.is_recording = False
            self.audio_stream = None
            messagebox.showerror("无法录音", str(error), parent=self.root)
            return "break"

        self.voice_button.config(bg=COLORS["panel_alt"], fg="#b42318")
        return "break"

    def capture_audio(self, indata, frames, time_info, status):
        if self.is_recording:
            self.audio_chunks.append(indata.copy())

    def stop_voice_recording(self, event=None):
        if not self.is_recording:
            return "break"

        self.is_recording = False
        stream = self.audio_stream
        self.audio_stream = None
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass

        if not self.audio_chunks:
            self.restore_voice_button()
            self.root.bell()
            return "break"

        try:
            audio = np.concatenate(self.audio_chunks, axis=0).reshape(-1)
        except Exception as error:
            self.audio_chunks = []
            self.restore_voice_button()
            write_error_log(f"合并录音数据失败：{error}")
            messagebox.showerror("无法处理录音", str(error), parent=self.root)
            return "break"
        self.audio_chunks = []
        if audio.size < 4800:
            self.restore_voice_button()
            self.root.bell()
            return "break"

        self.is_transcribing = True
        self.voice_button.config(
            text="…",
            bg=COLORS["panel_alt"],
            fg=COLORS["todo"],
            font=self.header_action_font,
        )
        threading.Thread(
            target=self.transcribe_voice,
            args=(audio,),
            daemon=True,
        ).start()
        return "break"

    def transcribe_voice(self, audio):
        try:
            from faster_whisper import WhisperModel

            if self.whisper_model is None:
                offline_only = os.environ.get(
                    "PLAN_WIDGET_OFFLINE_ONLY", ""
                ).strip().lower() in {"1", "true", "yes", "on"}
                self.whisper_model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="int8",
                    download_root=str(VOICE_MODEL_DIR),
                    local_files_only=offline_only,
                    cpu_threads=max(2, (os.cpu_count() or 4) // 2),
                )

            segments, _ = self.whisper_model.transcribe(
                audio,
                language="zh",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
                condition_on_previous_text=False,
                initial_prompt="这是一条中文个人计划，可能包含日期、人名、证书名称和任务。",
            )
            transcript = "".join(segment.text.strip() for segment in segments).strip()
            self.voice_results.put(("success", transcript))
        except Exception as error:
            self.voice_results.put(("error", str(error)))

    def poll_voice_results(self):
        try:
            while True:
                result_type, payload = self.voice_results.get_nowait()
                self.is_transcribing = False
                self.restore_voice_button()
                if result_type == "error":
                    messagebox.showerror("语音识别失败", payload, parent=self.root)
                elif payload:
                    self.create_task_from_text(payload, input_method="voice")
                else:
                    self.root.bell()
        except queue.Empty:
            pass
        try:
            self.root.after(100, self.poll_voice_results)
        except tk.TclError:
            pass

    def restore_voice_button(self):
        self.voice_button.config(
            text="\ue720",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.voice_action_font,
        )

    def hide_add_bar(self):
        self.add_bar.pack_forget()
        self.add_entry.delete(0, "end")
        self.root.focus_set()
        self.schedule_auto_hide()

    def add_offline_task(self, event=None):
        source_text = self.add_entry.get().strip()
        if not source_text:
            self.root.bell()
            return "break"

        if self.create_task_from_text(source_text, input_method="manual"):
            self.hide_add_bar()
        return "break"

    def create_task_from_text(self, source_text, input_method):
        title, note, cleaned_text, is_task = organize_task_text(source_text)
        if input_method == "voice" and not is_task:
            return False

        plan = load_plan()
        if plan.get("error"):
            messagebox.showerror("无法添加计划", plan["error"], parent=self.root)
            return False

        task = {
            "id": datetime.now().strftime("%Y-%m-%d-%H%M%S-%f"),
            "title": title,
            "note": note,
            "status": "todo",
            "createdAt": date.today().isoformat(),
            "inputMethod": input_method,
        }
        if source_text != title or cleaned_text != source_text:
            task["sourceText"] = source_text
        due_at = due_date_from_text(source_text)
        if due_at:
            task["dueAt"] = due_at

        plan.setdefault("tasks", []).append(task)
        try:
            save_plan(plan)
        except Exception as error:
            messagebox.showerror("无法添加计划", str(error), parent=self.root)
            return False

        self.refresh_from_disk()
        return True

    def toggle_task_status(self, task_id):
        plan = load_plan()
        if plan.get("error"):
            messagebox.showerror("无法更新计划", plan["error"], parent=self.root)
            return

        for task in plan.get("tasks", []):
            if task.get("id") != task_id:
                continue
            if task.get("status") == "done":
                task["status"] = "todo"
                task.pop("completedAt", None)
            else:
                task["status"] = "done"
                task["completedAt"] = date.today().isoformat()
            break
        else:
            messagebox.showerror("无法更新计划", "没有找到这条计划。", parent=self.root)
            return

        try:
            save_plan(plan)
        except Exception as error:
            messagebox.showerror("无法更新计划", str(error), parent=self.root)
            return
        self.refresh_from_disk()

    def show_edit_dialog(self, task_id):
        if self.edit_dialog is not None:
            try:
                self.edit_dialog.lift()
                self.edit_dialog.focus_force()
                return
            except tk.TclError:
                self.edit_dialog = None

        plan = load_plan()
        if plan.get("error"):
            messagebox.showerror("无法编辑计划", plan["error"], parent=self.root)
            return

        task = next(
            (item for item in plan.get("tasks", []) if item.get("id") == task_id),
            None,
        )
        if task is None:
            messagebox.showerror("无法编辑计划", "没有找到这条计划。", parent=self.root)
            return

        self.cancel_auto_hide()
        self.reveal_window()

        dialog = tk.Toplevel(self.root)
        self.edit_dialog = dialog
        dialog.title("编辑计划")
        dialog.configure(bg=COLORS["panel"])
        dialog.resizable(True, True)
        dialog.minsize(360, 300)
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)

        window_x, window_y, window_width, window_height = self.current_window_bounds()
        dialog_width = min(460, max(360, window_width))
        dialog_height = 350
        dialog_x = window_x + max(0, (window_width - dialog_width) // 2)
        dialog_y = window_y + max(20, min(80, (window_height - dialog_height) // 3))
        dialog.geometry(f"{dialog_width}x{dialog_height}+{dialog_x}+{dialog_y}")

        body = tk.Frame(dialog, bg=COLORS["panel"], padx=18, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="标题",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=self.body_font,
            anchor="w",
        ).pack(fill="x")
        title_entry = tk.Entry(
            body,
            bg="#ffffff",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="solid",
            bd=1,
            font=self.body_font,
        )
        title_entry.pack(fill="x", pady=(5, 12), ipady=5)
        title_entry.insert(0, task.get("title", ""))

        tk.Label(
            body,
            text="详细内容",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=self.body_font,
            anchor="w",
        ).pack(fill="x")
        note_text = tk.Text(
            body,
            height=6,
            wrap="word",
            bg="#ffffff",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="solid",
            bd=1,
            font=self.small_font,
            undo=True,
        )
        note_text.pack(fill="both", expand=True, pady=(5, 12))
        note_text.insert("1.0", task.get("note", ""))

        date_row = tk.Frame(body, bg=COLORS["panel"])
        date_row.pack(fill="x")
        tk.Label(
            date_row,
            text="目标日期",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=self.body_font,
            anchor="w",
        ).pack(side="left")
        due_entry = tk.Entry(
            date_row,
            width=16,
            bg="#ffffff",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="solid",
            bd=1,
            font=self.small_font,
        )
        due_entry.pack(side="left", padx=(10, 0), ipady=4)
        due_entry.insert(0, task.get("dueAt", ""))

        button_row = tk.Frame(body, bg=COLORS["panel"])
        button_row.pack(fill="x", pady=(14, 0))

        def close_dialog():
            if self.edit_dialog is not dialog:
                return
            self.edit_dialog = None
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            self.schedule_auto_hide()

        def save_changes(event=None):
            new_title = title_entry.get().strip()
            if not new_title:
                messagebox.showwarning("标题不能为空", "请填写计划标题。", parent=dialog)
                title_entry.focus_set()
                return "break"

            new_note = note_text.get("1.0", "end-1c").strip()
            due_text = due_entry.get().strip()
            due_at = due_date_from_text(due_text) if due_text else ""
            if due_text and not due_at:
                messagebox.showwarning(
                    "目标日期无法识别",
                    "请使用 2026-08-15、明天或下周一这样的日期。",
                    parent=dialog,
                )
                due_entry.focus_set()
                due_entry.selection_range(0, "end")
                return "break"

            fresh_plan = load_plan()
            if fresh_plan.get("error"):
                messagebox.showerror("无法保存计划", fresh_plan["error"], parent=dialog)
                return "break"

            for fresh_task in fresh_plan.get("tasks", []):
                if fresh_task.get("id") != task_id:
                    continue
                fresh_task["title"] = new_title
                fresh_task["note"] = new_note
                fresh_task["updatedAt"] = date.today().isoformat()
                if due_at:
                    fresh_task["dueAt"] = due_at
                else:
                    fresh_task.pop("dueAt", None)
                break
            else:
                messagebox.showerror("无法保存计划", "没有找到这条计划。", parent=dialog)
                return "break"

            try:
                save_plan(fresh_plan)
            except Exception as error:
                messagebox.showerror("无法保存计划", str(error), parent=dialog)
                return "break"

            close_dialog()
            self.refresh_from_disk()
            return "break"

        cancel_button = tk.Button(
            button_row,
            text="取消",
            command=close_dialog,
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            activebackground=COLORS["line"],
            relief="flat",
            padx=15,
            pady=5,
        )
        cancel_button.pack(side="right")
        save_button = tk.Button(
            button_row,
            text="保存",
            command=save_changes,
            bg=COLORS["todo"],
            fg="#ffffff",
            activebackground=COLORS["muted"],
            activeforeground="#ffffff",
            relief="flat",
            padx=15,
            pady=5,
        )
        save_button.pack(side="right", padx=(0, 8))

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.bind("<Control-Return>", save_changes)
        dialog.bind("<Escape>", lambda event: close_dialog())
        dialog.grab_set()
        title_entry.focus_set()
        title_entry.selection_range(0, "end")

    def refresh_from_disk(self):
        self.plan = load_plan()
        try:
            self.last_mtime = os.path.getmtime(DATA_PATH)
        except OSError:
            self.last_mtime = None
        self.render()

    def resize_content(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def resize_task_text(self, event, labels, title_label=None):
        for label in labels:
            inset = 78 if label is title_label else 22
            try:
                if label.winfo_exists():
                    label.config(wraplength=max(120, event.width - inset))
            except tk.TclError:
                pass

    def draw_rounded_background(self, event=None):
        width = max(1, event.width if event is not None else self.background.winfo_width())
        height = max(1, event.height if event is not None else self.background.winfo_height())
        radius = 14
        points = [
            radius, 0,
            width - radius, 0,
            width, 0,
            width, radius,
            width, height - radius,
            width, height,
            width - radius, height,
            radius, height,
            0, height,
            0, height - radius,
            0, radius,
            0, 0,
        ]
        self.background.delete("rounded_panel")
        self.background.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            fill=COLORS["panel"],
            outline=COLORS["panel"],
            tags="rounded_panel",
        )

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def bind_widget_events(self, widget):
        is_action_widget = (
            widget in self.no_drag_widgets
            or widget in self.task_action_widgets
            or isinstance(widget, tk.Entry)
        )
        if not is_action_widget:
            widget.bind("<ButtonPress-1>", self.start_drag, add="+")
            widget.bind("<B1-Motion>", self.drag_window, add="+")
            widget.bind("<Button-3>", self.show_menu, add="+")
        for child in widget.winfo_children():
            self.bind_widget_events(child)

    def start_drag(self, event):
        if (
            event.widget in (self.close_button, getattr(self, "resize_grip", None))
            or event.widget in self.no_drag_widgets
            or event.widget in self.task_action_widgets
            or isinstance(event.widget, tk.Entry)
        ):
            self.drag_start = None
            return
        self.resize_start = None
        self.cancel_auto_hide()
        self.reveal_window()
        window_x, window_y, _, _ = self.current_window_bounds()
        self.drag_start = (event.x_root, event.y_root, window_x, window_y)

    def drag_window(self, event):
        if not self.drag_start:
            return
        start_x, start_y, window_x, window_y = self.drag_start
        next_x = window_x + event.x_root - start_x
        next_y = window_y + event.y_root - start_y
        self.dock_edge = ""
        self.dock_work_area = None
        self.apply_window_level()
        _, _, width, height = self.current_window_bounds()
        self.set_window_bounds(width, height, next_x, next_y)

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def start_resize(self, event):
        self.cancel_auto_hide()
        self.reveal_window()
        self.drag_start = None
        self.resize_start = (
            event.x_root,
            event.y_root,
            self.root.winfo_width(),
            self.root.winfo_height(),
        )

    def resize_window(self, event):
        if not self.resize_start:
            return
        start_x, start_y, start_width, start_height = self.resize_start
        width = max(360, start_width + event.x_root - start_x)
        height = max(420, start_height + event.y_root - start_y)
        window_x, window_y, _, _ = self.current_window_bounds()
        self.set_window_bounds(width, height, window_x, window_y)

    def stop_pointer_action(self, event=None):
        was_dragging = self.drag_start is not None
        changed = was_dragging or self.resize_start is not None
        pointer = None
        if was_dragging and event is not None:
            pointer = (event.x_root, event.y_root)
        self.drag_start = None
        self.resize_start = None
        if changed:
            self.snap_to_edge(
                force_existing=not was_dragging and bool(self.dock_edge),
                pointer=pointer,
            )
            self.remember_visible_geometry()
            self.save_window_settings()
            self.schedule_auto_hide()

    def get_work_area(self, pointer=None):
        try:
            class MonitorInfo(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            window_x, window_y, window_width, window_height = self.current_window_bounds()
            window_rect = wintypes.RECT(
                window_x,
                window_y,
                window_x + window_width,
                window_y + window_height,
            )
            user32 = ctypes.windll.user32
            if pointer is not None:
                user32.MonitorFromPoint.argtypes = [
                    wintypes.POINT,
                    wintypes.DWORD,
                ]
                user32.MonitorFromPoint.restype = wintypes.HANDLE
                monitor = user32.MonitorFromPoint(
                    wintypes.POINT(pointer[0], pointer[1]), 2
                )
            else:
                user32.MonitorFromRect.argtypes = [
                    ctypes.POINTER(wintypes.RECT),
                    wintypes.DWORD,
                ]
                user32.MonitorFromRect.restype = wintypes.HANDLE
                monitor = user32.MonitorFromRect(ctypes.byref(window_rect), 2)
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                return work.left, work.top, work.right, work.bottom
        except Exception:
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    @staticmethod
    def geometry_string(width, height, x, y):
        return f"{width}x{height}{x:+d}{y:+d}"

    def top_window_handle(self):
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        widget_handle = self.root.winfo_id()
        return user32.GetParent(widget_handle) or widget_handle

    def set_window_bounds(self, width, height, x, y):
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(
            self.top_window_handle(),
            None,
            int(x),
            int(y),
            int(width),
            int(height),
            0x0004 | 0x0010,
        )

    def hidden_handle_geometry(self, width, height):
        if self.dock_edge in ("left", "right"):
            handle_height = min(HANDLE_LENGTH, max(48, height - 40))
            handle_y = max(0, (height - handle_height) // 2)
            handle_x = 0 if self.dock_edge == "left" else width - HANDLE_THICKNESS
            return handle_x, handle_y, HANDLE_THICKNESS, handle_height

        handle_width = min(HANDLE_LENGTH, max(48, width - 40))
        handle_x = max(0, (width - handle_width) // 2)
        return handle_x, 0, handle_width, HANDLE_THICKNESS

    def draw_hidden_handle(self, width, height, hovered=False):
        self.hide_handle.delete("all")
        is_top = self.dock_edge == "top"
        major = width if is_top else height
        minor = height if is_top else width
        outer_color = COLORS["handle_hover"] if hovered else COLORS["handle"]

        def orient(points):
            oriented = []
            for index in range(0, len(points), 2):
                along = points[index]
                inward = points[index + 1]
                if is_top:
                    oriented.extend((along, inward))
                elif self.dock_edge == "left":
                    oriented.extend((inward, along))
                else:
                    oriented.extend((minor - 1 - inward, along))
            return oriented

        def flatten(points):
            values = []
            for x, y in points:
                values.extend((x, y))
            return values

        left = 5
        right = major - 5
        top = 0
        bottom = minor - 3
        cut = bottom - top
        vertices = [
            (left, top),
            (right, top),
            (right - cut, bottom),
            (left + cut, bottom),
        ]

        def rounded_corner(previous, corner, following, radius=7, steps=10):
            def point_toward(target):
                delta_x = target[0] - corner[0]
                delta_y = target[1] - corner[1]
                length = math.hypot(delta_x, delta_y) or 1
                distance = min(radius, length / 2)
                return (
                    corner[0] + delta_x / length * distance,
                    corner[1] + delta_y / length * distance,
                )

            start = point_toward(previous)
            end = point_toward(following)
            curve = []
            for step in range(steps + 1):
                progress = step / steps
                inverse = 1 - progress
                curve.append(
                    (
                        inverse * inverse * start[0]
                        + 2 * inverse * progress * corner[0]
                        + progress * progress * end[0],
                        inverse * inverse * start[1]
                        + 2 * inverse * progress * corner[1]
                        + progress * progress * end[1],
                    )
                )
            return curve

        corner_arcs = []
        for index, corner in enumerate(vertices):
            corner_arcs.append(
                rounded_corner(
                    vertices[index - 1],
                    corner,
                    vertices[(index + 1) % len(vertices)],
                )
            )

        body = []
        for arc in corner_arcs:
            body.extend(arc)
        self.hide_handle.create_polygon(
            orient(flatten(body)),
            fill=outer_color,
            outline="",
        )

        for arc in corner_arcs:
            self.hide_handle.create_line(
                *orient(flatten(arc)),
                fill=COLORS["handle_border"],
                width=1,
                capstyle="round",
                smooth=True,
                splinesteps=24,
            )
        for index, arc in enumerate(corner_arcs):
            if self.dock_edge == "right" and index == 0:
                continue
            next_arc = corner_arcs[(index + 1) % len(corner_arcs)]
            self.hide_handle.create_line(
                *orient(flatten([arc[-1], next_arc[0]])),
                fill=COLORS["handle_border"],
                width=1,
                capstyle="round",
            )

        center = major // 2
        arrow_center = minor // 2 - 1 + (1 if hovered else 0)
        self.hide_handle.create_line(
            *orient([center - 6, arrow_center - 2, center, arrow_center + 2]),
            fill=COLORS["handle_icon"],
            width=2,
            capstyle="round",
        )
        self.hide_handle.create_line(
            *orient([center, arrow_center + 2, center + 6, arrow_center - 2]),
            fill=COLORS["handle_icon"],
            width=2,
            capstyle="round",
        )

    def show_hidden_handle(self):
        _, _, width, height = self.current_window_bounds()
        handle_x, handle_y, handle_width, handle_height = self.hidden_handle_geometry(
            width, height
        )
        self.hide_handle.place(
            x=handle_x,
            y=handle_y,
            width=handle_width,
            height=handle_height,
        )
        self.draw_hidden_handle(handle_width, handle_height)
        self.hide_handle.tk.call("raise", self.hide_handle._w)
        self.root.update_idletasks()
        return (
            handle_x,
            handle_y,
            handle_x + handle_width,
            handle_y + handle_height,
        )

    def set_hidden_clip(self):
        clip = self.show_hidden_handle()

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        gdi32.CreateRectRgn.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        gdi32.CreateRectRgn.restype = wintypes.HRGN
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int
        region = gdi32.CreateRectRgn(*clip)
        if region:
            if user32.SetWindowRgn(self.top_window_handle(), region, True):
                return True
            gdi32.DeleteObject(region)
        return False

    def clear_hidden_clip(self):
        self.cancel_hidden_handle_reveal(redraw=False)
        self.hide_handle.place_forget()
        user32 = ctypes.windll.user32
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int
        user32.SetWindowRgn(self.top_window_handle(), None, True)

    def current_window_bounds(self):
        self.root.update_idletasks()
        try:
            rect = wintypes.RECT()
            user32 = ctypes.windll.user32
            if user32.GetWindowRect(self.top_window_handle(), ctypes.byref(rect)):
                return (
                    rect.left,
                    rect.top,
                    rect.right - rect.left,
                    rect.bottom - rect.top,
                )
        except Exception:
            pass
        return (
            self.root.winfo_x(),
            self.root.winfo_y(),
            self.root.winfo_width(),
            self.root.winfo_height(),
        )

    def initialize_auto_hide(self):
        if not self.auto_hide.get():
            return
        self.root.update_idletasks()
        self.snap_to_edge(force_existing=bool(self.dock_edge))
        self.remember_visible_geometry()
        self.save_window_settings()
        self.schedule_auto_hide()

    def snap_to_edge(self, force_existing=False, pointer=None):
        if not self.auto_hide.get() or self.is_hidden:
            return False

        x, y, width, height = self.current_window_bounds()
        left, top, right, bottom = self.get_work_area(pointer)
        if pointer is not None:
            pointer_x, pointer_y = pointer
            distances = {
                "left": abs(pointer_x - left),
                "right": abs(pointer_x - right),
                "top": abs(pointer_y - top),
            }
        else:
            distances = {
                "left": abs(x - left),
                "right": abs((x + width) - right),
                "top": abs(y - top),
            }

        edge = self.dock_edge if force_existing and self.dock_edge else min(
            distances, key=distances.get
        )
        if not (force_existing and self.dock_edge) and distances[edge] > DOCK_THRESHOLD:
            self.dock_edge = ""
            return False

        if edge == "left":
            x = left
            y = min(max(y, top), max(top, bottom - height))
        elif edge == "right":
            x = right - width
            y = min(max(y, top), max(top, bottom - height))
        else:
            y = top
            x = min(max(x, left), max(left, right - width))

        self.dock_edge = edge
        self.dock_work_area = (left, top, right, bottom)
        self.apply_window_level()
        self.set_window_bounds(width, height, x, y)
        return True

    def remember_visible_geometry(self):
        if self.is_hidden:
            return
        x, y, width, height = self.current_window_bounds()
        self.visible_bounds = (x, y, width, height)
        self.visible_geometry = self.geometry_string(width, height, x, y)

    def pointer_inside_window(self):
        try:
            pointer_x = self.root.winfo_pointerx()
            pointer_y = self.root.winfo_pointery()
            x, y, width, height = self.current_window_bounds()
            return (
                x <= pointer_x < x + width
                and y <= pointer_y < y + height
            )
        except tk.TclError:
            return False

    def on_window_enter(self, event=None):
        self.cancel_auto_hide()
        if self.is_hidden:
            self.reveal_window()

    def on_window_leave(self, event=None):
        self.schedule_auto_hide()

    def on_hidden_handle_enter(self, event=None):
        self.cancel_auto_hide()
        self.schedule_hidden_handle_reveal()
        return "break"

    def on_hidden_handle_leave(self, event=None):
        self.cancel_hidden_handle_reveal()
        return "break"

    def activate_hidden_handle(self, event=None):
        self.cancel_auto_hide()
        self.cancel_hidden_handle_reveal(redraw=False)
        self.reveal_window()
        return "break"

    def schedule_hidden_handle_reveal(self):
        if not self.is_hidden or self.handle_reveal_after_id is not None:
            return
        if self.hide_handle.winfo_manager():
            self.draw_hidden_handle(
                self.hide_handle.winfo_width(),
                self.hide_handle.winfo_height(),
                hovered=True,
            )
        self.handle_reveal_after_id = self.root.after(
            HANDLE_REVEAL_DELAY_MS,
            self.finish_hidden_handle_hover,
        )

    def cancel_hidden_handle_reveal(self, redraw=True):
        had_pending_reveal = self.handle_reveal_after_id is not None
        if self.handle_reveal_after_id is not None:
            try:
                self.root.after_cancel(self.handle_reveal_after_id)
            except tk.TclError:
                pass
            self.handle_reveal_after_id = None
        if (
            redraw
            and had_pending_reveal
            and self.is_hidden
            and self.hide_handle.winfo_manager()
        ):
            self.draw_hidden_handle(
                self.hide_handle.winfo_width(),
                self.hide_handle.winfo_height(),
                hovered=False,
            )

    def finish_hidden_handle_hover(self):
        self.handle_reveal_after_id = None
        if self.is_hidden and self.pointer_in_edge_zone():
            self.reveal_window()
        elif self.is_hidden and self.hide_handle.winfo_manager():
            self.draw_hidden_handle(
                self.hide_handle.winfo_width(),
                self.hide_handle.winfo_height(),
                hovered=False,
            )

    def poll_dock_pointer(self):
        try:
            if self.auto_hide.get() and self.dock_edge:
                if self.is_hidden:
                    if self.pointer_in_edge_zone():
                        self.cancel_auto_hide()
                        self.schedule_hidden_handle_reveal()
                    else:
                        self.cancel_hidden_handle_reveal()
                elif (
                    not self.pointer_inside_window()
                    and self.auto_hide_after_id is None
                ):
                    self.schedule_auto_hide()
        except tk.TclError:
            return
        except Exception as error:
            write_error_log(f"贴边指针轮询异常：{error}")
        try:
            self.root.after(100, self.poll_dock_pointer)
        except tk.TclError:
            pass

    def pointer_in_edge_zone(self):
        if not self.visible_bounds:
            return False
        try:
            pointer_x = self.root.winfo_pointerx()
            pointer_y = self.root.winfo_pointery()
            window_x, window_y, window_width, window_height = self.visible_bounds
            handle_x, handle_y, handle_width, handle_height = self.hidden_handle_geometry(
                window_width, window_height
            )
            return (
                window_x + handle_x <= pointer_x < window_x + handle_x + handle_width
                and window_y + handle_y <= pointer_y < window_y + handle_y + handle_height
            )
        except tk.TclError:
            return False

    def schedule_auto_hide(self):
        self.cancel_auto_hide()
        if not self.auto_hide.get() or not self.dock_edge or self.is_hidden:
            return
        self.auto_hide_after_id = self.root.after(
            AUTO_HIDE_DELAY_MS, self.hide_if_pointer_away
        )

    def cancel_auto_hide(self):
        if self.auto_hide_after_id is None:
            return
        try:
            self.root.after_cancel(self.auto_hide_after_id)
        except tk.TclError:
            pass
        self.auto_hide_after_id = None

    def hide_if_pointer_away(self):
        self.auto_hide_after_id = None
        if (
            self.pointer_inside_window()
            or self.drag_start
            or self.resize_start
            or self.is_recording
            or self.is_transcribing
            or self.add_bar.winfo_manager()
            or self.edit_dialog is not None
        ):
            return
        self.hide_window()

    def hide_window(self):
        if self.is_hidden or not self.auto_hide.get() or not self.dock_edge:
            return
        self.cancel_hidden_handle_reveal(redraw=False)
        self.remember_visible_geometry()
        self.is_hidden = True
        self.apply_window_level()
        try:
            if not self.set_hidden_clip():
                raise RuntimeError("Windows 窗口裁剪调用失败")
        except Exception as error:
            self.is_hidden = False
            self.hide_handle.place_forget()
            self.apply_window_level()
            write_error_log(f"自动隐藏失败，已恢复窗口：{error}")

    def reveal_window(self):
        if not self.is_hidden:
            return
        self.cancel_hidden_handle_reveal(redraw=False)
        self.is_hidden = False
        self.clear_hidden_clip()
        self.apply_window_level()
        if self.visible_geometry:
            match = re.fullmatch(
                r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self.visible_geometry
            )
            if match:
                width, height, x, y = map(int, match.groups())
                self.set_window_bounds(width, height, x, y)
            self.root.update_idletasks()
        self.root.lift()

    def toggle_auto_hide(self):
        self.cancel_auto_hide()
        if self.auto_hide.get():
            self.snap_to_edge(force_existing=bool(self.dock_edge))
            if not self.dock_edge:
                left, top, right, _ = self.get_work_area()
                center_x = self.root.winfo_x() + self.root.winfo_width() // 2
                self.dock_edge = "left" if center_x < (left + right) // 2 else "right"
                self.snap_to_edge(force_existing=True)
            self.remember_visible_geometry()
            self.schedule_auto_hide()
        else:
            self.reveal_window()
            self.dock_edge = ""
            self.dock_work_area = None
            self.remember_visible_geometry()
        self.apply_window_level()
        self.save_window_settings()

    def save_window_settings(self):
        geometry = self.visible_geometry or self.root.geometry()
        save_settings(
            self.root,
            self.topmost,
            self.alpha,
            self.auto_hide,
            self.dock_edge,
            geometry,
            self.skin_name,
        )

    def highlight_resize_grip(self, event=None):
        self.resize_grip.config(bg=COLORS["panel_alt"], fg=COLORS["todo"])

    def restore_resize_grip(self, event=None):
        self.resize_grip.config(bg=COLORS["panel"], fg=COLORS["muted"])

    def toggle_topmost(self):
        self.topmost.set(not self.topmost.get())
        self.apply_window_level()
        self.save_window_settings()

    def apply_window_level(self):
        docked_auto_hide = self.auto_hide.get() and bool(self.dock_edge)
        self.root.attributes("-topmost", self.topmost.get() or docked_auto_hide)
        if docked_auto_hide:
            self.root.lift()

    def change_alpha(self, delta):
        value = min(1.0, max(0.62, self.alpha.get() + delta))
        self.alpha.set(value)
        self.root.attributes("-alpha", value)
        self.save_window_settings()

    def reset_position(self):
        self.cancel_auto_hide()
        self.reveal_window()
        self.dock_edge = ""
        self.dock_work_area = None
        self.settings["geometry"] = ""
        self.place_window()
        self.remember_visible_geometry()
        self.save_window_settings()
        self.root.after(100, self.initialize_auto_hide)

    def sync_plan(self, force=False):
        try:
            try:
                mtime = os.path.getmtime(DATA_PATH)
            except OSError:
                mtime = None

            if force or mtime != self.last_mtime:
                self.last_mtime = mtime
                self.plan = load_plan()
                self.render()
        except tk.TclError:
            return
        except Exception as error:
            write_error_log(f"同步计划数据失败：{error}")
        try:
            self.root.after(1000, self.sync_plan)
        except tk.TclError:
            pass

    def render(self):
        self.task_action_widgets.clear()
        for child in self.content.winfo_children():
            child.destroy()

        tasks = self.plan.get("tasks", [])
        todo = [task for task in tasks if task.get("status") != "done"]
        done = [task for task in tasks if task.get("status") == "done"]

        self.updated_label.config(text=f"最后更新：{fmt_date(self.plan.get('updatedAt')) or '-'}")
        self.count_label.config(text=f"{len(todo)} 个计划中 / {len(done)} 个已完成")

        if self.plan.get("error"):
            self.error_card(self.plan["error"])
            return

        self.section("计划中", todo, COLORS["todo"])
        self.section("已完成", done, COLORS["done_marker"])

    def section(self, title, tasks, color):
        row = tk.Frame(self.content, bg=COLORS["panel"])
        row.pack(fill="x", pady=(0, 8))

        tk.Label(
            row,
            text=title,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=self.heading_font,
            anchor="w",
        ).pack(side="left")

        tk.Label(
            row,
            text=f"{len(tasks)} 项",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.small_font,
            anchor="e",
        ).pack(side="right")
        self.bind_widget_events(row)

        if not tasks:
            self.empty_card("暂无任务")
            return

        for task in tasks:
            self.task_card(task, color)

    def task_card(self, task, color):
        outer = tk.Frame(self.content, bg=color)
        outer.pack(fill="x", pady=(0, 10))

        card = tk.Frame(outer, bg=COLORS["panel_alt"], padx=10, pady=9)
        card.pack(fill="x", padx=(5, 0))
        wrapping_labels = []

        title_row = tk.Frame(card, bg=COLORS["panel_alt"])
        title_row.pack(fill="x")

        title = tk.Label(
            title_row,
            text=task.get("title") or "未命名任务",
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            font=self.task_title_font,
            anchor="w",
            justify="left",
            wraplength=300,
        )
        wrapping_labels.append(title)

        is_done = task.get("status") == "done"
        action_bar = tk.Frame(
            title_row,
            bg=COLORS["panel_alt"],
            width=52,
            height=24,
        )
        action_bar.pack(side="right", padx=(8, 0), anchor="n")
        action_bar.pack_propagate(False)

        edit_button = tk.Label(
            action_bar,
            text="\ue70f",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=self.voice_action_font,
            cursor="hand2",
            anchor="center",
            padx=0,
            pady=0,
        )
        edit_button.place(x=0, y=0, width=24, height=24)
        edit_button.bind(
            "<Button-1>",
            lambda event, task_id=task.get("id"): (
                self.show_edit_dialog(task_id),
                "break",
            )[1],
        )

        completion_button = tk.Label(
            action_bar,
            text="\ue73a" if is_done else "\ue739",
            bg=COLORS["panel_alt"],
            fg=COLORS["done"] if is_done else COLORS["todo"],
            font=self.voice_action_font,
            cursor="hand2",
            anchor="center",
            padx=0,
            pady=0,
        )
        completion_button.place(x=28, y=0, width=24, height=24)
        completion_button.bind(
            "<Button-1>",
            lambda event, task_id=task.get("id"): (
                self.toggle_task_status(task_id),
                "break",
            )[1],
        )
        title.pack(side="left", fill="x", expand=True)

        self.task_action_widgets.add(action_bar)
        self.task_action_widgets.add(edit_button)
        self.task_action_widgets.add(completion_button)

        note = task.get("note")
        if note:
            note_label = tk.Label(
                card,
                text=note,
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                font=self.small_font,
                anchor="w",
                justify="left",
                wraplength=300,
            )
            note_label.pack(fill="x", pady=(6, 0))
            wrapping_labels.append(note_label)

        if task.get("status") == "done":
            tk.Label(
                card,
                text=f"完成：{fmt_date(task.get('completedAt') or task.get('updatedAt') or task.get('createdAt'))}",
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                font=self.small_font,
                anchor="w",
            ).pack(fill="x", pady=(8, 0))
        else:
            meta_row = tk.Frame(card, bg=COLORS["panel_alt"])
            meta_row.pack(fill="x", pady=(8, 0))
            tk.Label(
                meta_row,
                text=f"创建：{fmt_date(task.get('createdAt'))}",
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                font=self.small_font,
                anchor="w",
            ).pack(side="left")

            if task.get("dueAt"):
                state = due_state(task.get("dueAt"))
                suffix = f" · {state}" if state else ""
                tk.Label(
                    meta_row,
                    text=f"目标：{fmt_date(task.get('dueAt'))}{suffix}",
                    bg=COLORS["panel_alt"],
                    fg=COLORS["warn"],
                    font=self.small_font,
                    anchor="w",
                ).pack(side="left", padx=(16, 0))

        card.bind(
            "<Configure>",
            lambda event, labels=tuple(wrapping_labels), title_label=title: self.resize_task_text(
                event, labels, title_label
            ),
        )
        self.bind_widget_events(outer)

    def empty_card(self, text):
        card = tk.Frame(self.content, bg=COLORS["panel_alt"], highlightbackground=COLORS["line"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 14))
        tk.Label(
            card,
            text=text,
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=self.small_font,
            pady=18,
        ).pack(fill="x")
        self.bind_widget_events(card)

    def error_card(self, text):
        card = tk.Frame(self.content, bg=COLORS["panel_alt"], highlightbackground=COLORS["warn"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))
        tk.Label(
            card,
            text=f"计划数据读取失败：{text}",
            bg=COLORS["panel_alt"],
            fg=COLORS["warn"],
            font=self.small_font,
            justify="left",
            wraplength=300,
            padx=10,
            pady=12,
        ).pack(fill="x")
        self.bind_widget_events(card)

    def close(self):
        self.cancel_auto_hide()
        self.cancel_hidden_handle_reveal(redraw=False)
        self.is_recording = False
        try:
            if self.audio_stream is not None:
                self.audio_stream.stop()
                self.audio_stream.close()
        except Exception:
            pass
        self.save_window_settings()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    instance_mutex = None
    instance_event = None
    try:
        instance_mutex, instance_event, should_run = acquire_instance_guard()
        if should_run:
            PlanWindow(instance_event=instance_event).run()
    except Exception:
        write_error_log(f"程序启动失败：\n{traceback.format_exc()}")
    finally:
        release_instance_guard(instance_mutex, instance_event)
