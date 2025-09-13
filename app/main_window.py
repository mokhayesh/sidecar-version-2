# app/main_window.py
import os
import re
import json
import random
import threading
import inspect
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from difflib import SequenceMatcher

import wx
import wx.grid as gridlib
import pandas as pd

from app.settings import SettingsWindow
from app.dialogs import QualityRuleDialog, DataBuddyDialog, SyntheticDataDialog
from app.s3_utils import download_text_from_uri, upload_to_s3
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,
    compliance_analysis,
)


# ──────────────────────────────────────────────────────────────────────────────
# Kernel: persistent app “memory”
# ──────────────────────────────────────────────────────────────────────────────
class KernelManager:
    """
    Lightweight JSON kernel that:
      • stores metadata (version, creator, features)
      • logs interactions/events with timestamps
      • persists simple state (last dataset + KPIs)
    """

    def __init__(self, app_name="Data Buddy — Sidecar Application"):
        self.lock = threading.Lock()
        self.dir = os.path.join(os.path.expanduser("~"), ".sidecar")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "kernel.json")

        # advertise to any dialogs/child processes
        os.environ["SIDECAR_KERNEL_PATH"] = self.path

        # default structure
        self.data = {
            "kernel_version": "1.0",
            "creator": "Salah Mokhayesh",
            "app": {
                "name": app_name,
                "modules": [
                    "Knowledge Files", "Load File", "Load from URI/S3",
                    "MDM", "Synthetic Data", "Rule Assignment",
                    "Profile", "Quality", "Detect Anomalies",
                    "Catalog", "Compliance", "Tasks",
                    "Export CSV", "Export TXT", "Upload to S3"
                ]
            },
            "stats": {"launch_count": 0},
            "state": {
                "last_dataset": None,   # {"rows": int, "cols": int, "columns": [..]}
                "kpis": {}              # {"rows":..,"cols":..,"null_pct":.., ...}
            },
            "events": []               # appended over time (capped)
        }

        self._load_or_init()
        self.increment_launch()

    def _load_or_init(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                # merge a little bit, keep our metadata authoritative
                existing.setdefault("kernel_version", "1.0")
                existing.setdefault("creator", "Salah Mokhayesh")
                existing.setdefault("app", self.data["app"])
                existing.setdefault("stats", {"launch_count": 0})
                existing.setdefault("state", {"last_dataset": None, "kpis": {}})
                existing.setdefault("events", [])
                self.data = existing
            else:
                self._save()
        except Exception:
            # If anything goes wrong, start fresh
            self._save()

    def _save(self):
        with self.lock:
            try:
                # cap events to last 5000
                ev = self.data.get("events", [])
                if len(ev) > 5000:
                    self.data["events"] = ev[-5000:]
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def increment_launch(self):
        with self.lock:
            self.data["stats"]["launch_count"] = int(self.data["stats"].get("launch_count", 0)) + 1
        self._save()

    def log(self, event_type, **payload):
        evt = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "type": event_type,
            "payload": payload
        }
        with self.lock:
            self.data.setdefault("events", []).append(evt)
        self._save()

    def set_last_dataset(self, columns, rows_count):
        with self.lock:
            self.data["state"]["last_dataset"] = {
                "rows": int(rows_count),
                "cols": int(len(columns or [])),
                "columns": list(columns or [])
            }
        self._save()

    def set_kpis(self, kpi_dict):
        with self.lock:
            self.data["state"]["kpis"] = dict(kpi_dict or {})
        self._save()

    def summary(self):
        with self.lock:
            ev = self.data.get("events", [])
            return {
                "events_total": len(ev),
                "last_event": ev[-1] if ev else None,
                "kpis": self.data.get("state", {}).get("kpis", {}),
                "last_dataset": self.data.get("state", {}).get("last_dataset", None),
            }


# ──────────────────────────────────────────────────────────────────────────────
# Header banner (double-buffered, no flicker)
# ──────────────────────────────────────────────────────────────────────────────
class HeaderBanner(wx.Panel):
    def __init__(self, parent, height=60, bg=wx.Colour(28, 28, 28)):
        super().__init__(parent, size=(-1, height), style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self._bg = bg
        self._img = None
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base, "assets", "sidecar-architecture.png")
            if os.path.exists(p):
                self._img = wx.Image(p)
        except Exception:
            self._img = None
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh())

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self._bg))
        dc.Clear()
        if not self._img:
            return
        w, h = self.GetClientSize()
        iw, ih = self._img.GetWidth(), self._img.GetHeight()
        if ih <= 0:
            return
        target_h = h
        target_w = max(1, int(iw * target_h / ih))
        target_w = min(target_w, w)
        img = self._img.Scale(target_w, target_h, wx.IMAGE_QUALITY_HIGH)
        dc.DrawBitmap(wx.Bitmap(img), 0, 0)


# ──────────────────────────────────────────────────────────────────────────────
# Rounded button widget
# ──────────────────────────────────────────────────────────────────────────────
class RoundedShadowButton(wx.Control):
    def __init__(self, parent, label, handler, colour=wx.Colour(66, 133, 244), radius=12):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label
        self._handler = handler
        self._colour = colour
        self._radius = radius
        self._hover = False
        self._down = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)
        self._padx, self._pady = 16, 10
        self._font = wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self._text_colour = wx.Colour(240, 240, 240)
        self.SetMinSize((120, 32))

    def _set_hover(self, v):
        self._hover = v
        self.Refresh()

    def on_down(self, _):
        self._down = True
        self.CaptureMouse()
        self.Refresh()

    def _invoke_handler(self, evt):
        try:
            sig = inspect.signature(self._handler)
            if len(sig.parameters) == 0:
                self._handler()
            else:
                self._handler(evt)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            wx.MessageBox(
                f"Button '{self._label}' failed:\n\n{e}\n\n{tb}",
                "Button Error",
                wx.OK | wx.ICON_ERROR
            )

    def on_up(self, evt):
        if self.HasCapture():
            self.ReleaseMouse()
        was_down = self._down
        self._down = False
        self.Refresh()
        if was_down and self.GetClientRect().Contains(evt.GetPosition()):
            self._invoke_handler(evt)

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self._font)
        tw, th = dc.GetTextExtent(self._label)
        return wx.Size(tw + self._padx * 2, th + self._pady * 2)

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        w, h = self.GetClientSize()

        bg = self.GetParent().GetBackgroundColour()
        dc.SetBrush(wx.Brush(bg))
        dc.SetPen(wx.Pen(bg))
        dc.DrawRectangle(0, 0, w, h)

        base = self._colour
        if self._hover:
            base = wx.Colour(min(255, base.Red() + 10), min(255, base.Green() + 10), min(255, base.Blue() + 10))
        if self._down:
            base = wx.Colour(max(0, base.Red() - 20), max(0, base.Green() - 20), max(0, base.Blue() - 20))

        # shadow
        dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 60)))
        dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 0)))
        dc.DrawRoundedRectangle(2, 3, w - 4, h - 3, self._radius + 1)

        # body
        dc.SetBrush(wx.Brush(base))
        dc.SetPen(wx.Pen(base))
        dc.DrawRoundedRectangle(0, 0, w - 2, h - 2, self._radius)

        dc.SetTextForeground(self._text_colour)
        dc.SetFont(self._font)
        tw, th = dc.GetTextExtent(self._label)
        dc.DrawText(self._label, (w - tw) // 2, (h - th) // 2)


# ──────────────────────────────────────────────────────────────────────────────
# Special "Little Buddy" pill with icon (GraphicsContext)
# ──────────────────────────────────────────────────────────────────────────────
class LittleBuddyPill(wx.Control):
    """A distinctive glossy pill with a speech-bubble icon, rendered via wx.GraphicsContext."""
    def __init__(self, parent, label="Little Buddy", handler=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label
        self._handler = handler
        self._hover = False
        self._down = False
        self._h = 44
        self.SetMinSize((160, self._h))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)
        self._font = wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        self.SetToolTip("Open Little Buddy")

    def _set_hover(self, v):
        self._hover = v
        self.Refresh()

    def on_down(self, _):
        self._down = True
        self.CaptureMouse()
        self.Refresh()

    def on_up(self, evt):
        if self.HasCapture():
            self.ReleaseMouse()
        was_down = self._down
        self._down = False
        self.Refresh()
        if was_down and self.GetClientRect().Contains(evt.GetPosition()) and callable(self._handler):
            try:
                self._handler(evt)
            except Exception as e:
                wx.MessageBox(str(e), "Little Buddy", wx.OK | wx.ICON_ERROR)

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(bg))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)

        # Colors
        base1 = wx.Colour(122, 72, 255)
        base2 = wx.Colour(96, 52, 235)
        if self._hover:
            base1 = wx.Colour(142, 92, 255)
            base2 = wx.Colour(116, 72, 245)
        if self._down:
            base1 = wx.Colour(102, 62, 235)
            base2 = wx.Colour(86, 48, 220)

        # Geometry
        x, y = 0, 0
        r = (h - 6) // 2
        pill_w = w - 6
        pill_h = h - 6

        # Shadow
        gc.SetPen(wx.NullPen)
        gc.SetBrush(gc.CreateRadialGradientBrush(6, pill_h, 6, pill_h, max(pill_h, 20),
                                                 wx.Colour(0, 0, 0, 90), wx.Colour(0, 0, 0, 0)))
        gc.DrawRoundedRectangle(3, 4, pill_w, pill_h, r)

        # Base gradient
        path = gc.CreatePath()
        path.AddRoundedRectangle(x, y, pill_w, pill_h, r)
        gc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 0)))
        gc.SetBrush(gc.CreateLinearGradientBrush(x, y, x, y + pill_h, base1, base2))
        gc.FillPath(path)

        # Gloss highlight (top half)
        gloss = gc.CreateLinearGradientBrush(x, y, x, y + pill_h // 2,
                                             wx.Colour(255, 255, 255, 90),
                                             wx.Colour(255, 255, 255, 0))
        gc.SetBrush(gloss)
        gc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 0)))
        gc.DrawRoundedRectangle(x + 1, y + 1, pill_w - 2, pill_h // 2, max(2, r - 2))

        # Icon (speech bubble)
        icon_x = 12
        icon_y = 10
        ic_w = 22
        ic_h = 16
        white = wx.Colour(255, 255, 255)
        ic = gc.CreatePath()
        ic.AddRoundedRectangle(icon_x, icon_y, ic_w, ic_h, 6)
        tail = gc.CreatePath()
        tail.MoveToPoint(icon_x + 9, icon_y + ic_h)
        tail.AddLineToPoint(icon_x + 15, icon_y + ic_h)
        tail.AddLineToPoint(icon_x + 11, icon_y + ic_h + 6)
        tail.CloseSubpath()
        gc.SetBrush(wx.Brush(white))
        gc.SetPen(wx.Pen(white, 1))
        gc.FillPath(ic)
        gc.FillPath(tail)

        # Text
        gc.SetFont(self._font, white)
        tw, th = gc.GetTextExtent(self._label)
        gc.DrawText(self._label, icon_x + ic_w + 10, (h - th) // 2)


# ──────────────────────────────────────────────────────────────────────────────
# KPI badge (flex width so 8 KPIs fit one row)
# ──────────────────────────────────────────────────────────────────────────────
class KPIBadge(wx.Panel):
    def __init__(self, parent, title, init_value="—", colour=wx.Colour(32, 35, 41)):
        super().__init__(parent)
        self.SetMinSize((120, 92))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._title = title
        self._value = init_value
        self._colour = colour
        self._accent = wx.Colour(90, 180, 255)
        self._accent2 = wx.Colour(80, 210, 140)
        self._font_title = wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.NORMAL)
        self._font_value = wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh())

    def SetValue(self, v):
        self._value = v
        self.Refresh()

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg = wx.Colour(28, 28, 28)
        dc.SetBrush(wx.Brush(bg))
        dc.SetPen(wx.Pen(bg))
        dc.DrawRoundedRectangle(0, 0, w, h, 10)

        dc.SetBrush(wx.Brush(self._colour))
        dc.SetPen(wx.Pen(self._colour))
        dc.DrawRoundedRectangle(6, 6, w - 12, h - 12, 8)

        dc.SetTextForeground(wx.Colour(180, 180, 180))
        dc.SetFont(self._font_title)
        dc.DrawText(self._title.upper(), 18, 12)

        dc.SetPen(wx.Pen(self._accent, 3))
        dc.DrawLine(16, h - 22, w - 24, h - 22)
        dc.SetPen(wx.Pen(self._accent2, 3))
        dc.DrawLine(16, h - 16, w - 24, h - 16)

        dc.SetTextForeground(wx.Colour(240, 240, 240))
        dc.SetFont(self._font_value)
        dc.DrawText(str(self._value), 18, 34)


# ──────────────────────────────────────────────────────────────────────────────
# MDM Dialog
# ──────────────────────────────────────────────────────────────────────────────
class MDMDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Master Data Management (MDM)", size=(560, 420))
        panel = wx.Panel(self)
        v = wx.BoxSizer(wx.VERTICAL)

        self.chk_include_current = wx.CheckBox(panel, label="Include current dataset as a source")
        self.chk_include_current.SetValue(True)
        v.Add(self.chk_include_current, 0, wx.ALL, 8)

        v.Add(wx.StaticText(panel, label="Sources to merge (local files or URIs):"), 0, wx.LEFT | wx.TOP, 8)
        self.lst = wx.ListBox(panel, style=wx.LB_EXTENDED)
        v.Add(self.lst, 1, wx.EXPAND | wx.ALL, 8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        btn_add = wx.Button(panel, label="Add Local…")
        btn_uri = wx.Button(panel, label="Add URI/S3…")
        btn_rm = wx.Button(panel, label="Remove Selected")
        btns.Add(btn_add, 0, wx.RIGHT, 6)
        btns.Add(btn_uri, 0, wx.RIGHT, 6)
        btns.Add(btn_rm, 0)
        v.Add(btns, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        grid = wx.FlexGridSizer(2, 2, 6, 6)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(panel, label="Match threshold (percent):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spn_thresh = wx.SpinCtrl(panel, min=50, max=100, initial=85)
        grid.Add(self.spn_thresh, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Fields to match on:"), 0, wx.ALIGN_CENTER_VERTICAL)
        h = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_email = wx.CheckBox(panel, label="Email")
        self.chk_phone = wx.CheckBox(panel, label="Phone")
        self.chk_name = wx.CheckBox(panel, label="Name")
        self.chk_addr = wx.CheckBox(panel, label="Address")
        for c in (self.chk_email, self.chk_phone, self.chk_name, self.chk_addr):
            c.SetValue(True)
            h.Add(c, 0, wx.RIGHT, 8)
        grid.Add(h, 0, wx.EXPAND)

        v.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        v.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 6)

        ok_cancel = wx.StdDialogButtonSizer()
        ok = wx.Button(panel, wx.ID_OK)
        cancel = wx.Button(panel, wx.ID_CANCEL)
        ok_cancel.AddButton(ok)
        ok_cancel.AddButton(cancel)
        ok_cancel.Realize()
        v.Add(ok_cancel, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(v)

        self.sources = []

        btn_add.Bind(wx.EVT_BUTTON, self._on_add_file)
        btn_uri.Bind(wx.EVT_BUTTON, self._on_add_uri)
        btn_rm.Bind(wx.EVT_BUTTON, self._on_rm)

    def _on_add_file(self, _):
        dlg = wx.FileDialog(self, "Select data file", wildcard="Data|*.csv;*.tsv;*.txt|All|*.*",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dlg.ShowModal() != wx.ID_OK:
            return
        for p in dlg.GetPaths():
            self.sources.append({"type": "file", "value": p})
            self.lst.Append(f"[FILE] {p}")
        dlg.Destroy()

    def _on_add_uri(self, _):
        with wx.TextEntryDialog(self, "Enter HTTP/HTTPS/S3 URI:", "Add URI/S3") as d:
            if d.ShowModal() != wx.ID_OK:
                return
            uri = d.GetValue().strip()
        if uri:
            self.sources.append({"type": "uri", "value": uri})
            self.lst.Append(f"[URI]  {uri}")

    def _on_rm(self, _):
        sel = list(self.lst.GetSelections())
        sel.reverse()
        for i in sel:
            self.lst.Delete(i)
            del self.sources[i]

    def get_params(self):
        return {
            "include_current": self.chk_include_current.GetValue(),
            "threshold": self.spn_thresh.GetValue() / 100.0,
            "use_email": self.chk_email.GetValue(),
            "use_phone": self.chk_phone.GetValue(),
            "use_name": self.chk_name.GetValue(),
            "use_addr": self.chk_addr.GetValue(),
            "sources": list(self.sources)
        }


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1320, 840))

        # icon (best-effort)
        for p in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "sidecar-01.ico"),
        ):
            if os.path.exists(p):
                try:
                    self.SetIcon(wx.Icon(p, wx.BITMAP_TYPE_ICO))
                    break
                except Exception:
                    pass

        # ── Kernel (created on startup; logs begin immediately)
        self.kernel = KernelManager(app_name="Data Buddy — Sidecar Application")
        self.kernel.log("app_started", version=self.kernel.data["kernel_version"])

        self.headers = []
        self.raw_data = []
        self.knowledge_files = []
        self.quality_rules = {}
        self.current_process = ""

        # KPI state
        self.metrics = {
            "rows": None,
            "cols": None,
            "null_pct": None,
            "uniqueness": None,
            "dq_score": None,
            "validity": None,
            "completeness": None,
            "anomalies": None,
        }

        self._build_ui()
        self.CenterOnScreen()
        self.Show()

    # UI
    def _build_ui(self):
        BG = wx.Colour(21, 21, 21)
        PANEL = wx.Colour(32, 35, 41)
        TXT = wx.Colour(235, 235, 235)
        BLUE = wx.Colour(66, 133, 244)

        self.SetBackgroundColour(BG)
        main = wx.BoxSizer(wx.VERTICAL)

        # Header
        header_bg = wx.Colour(28, 28, 28)
        header_row = wx.BoxSizer(wx.HORIZONTAL)

        self.banner = HeaderBanner(self, height=60, bg=header_bg)
        header_row.Add(self.banner, 0, wx.EXPAND)

        title_panel = wx.Panel(self)
        title_panel.SetBackgroundColour(header_bg)
        title = wx.StaticText(title_panel, label="Data Buddy — Sidecar Application")
        title.SetForegroundColour(wx.Colour(230, 230, 230))
        title.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD))
        tp_sizer = wx.BoxSizer(wx.VERTICAL)
        tp_sizer.AddStretchSpacer()
        tp_sizer.Add(title, 0, wx.ALL, 4)
        tp_sizer.AddStretchSpacer()
        title_panel.SetSizer(tp_sizer)
        header_row.Add(title_panel, 1, wx.EXPAND)

        main.Add(header_row, 0, wx.EXPAND)

        # KPI strip
        kpi_panel = wx.Panel(self)
        kpi_panel.SetBackgroundColour(BG)
        kpi_v = wx.BoxSizer(wx.VERTICAL)

        kpi_row = wx.BoxSizer(wx.HORIZONTAL)

        self.card_rows     = KPIBadge(kpi_panel, "Rows")
        self.card_cols     = KPIBadge(kpi_panel, "Columns")
        self.card_nulls    = KPIBadge(kpi_panel, "Null %")
        self.card_unique   = KPIBadge(kpi_panel, "Uniqueness")
        self.card_quality  = KPIBadge(kpi_panel, "DQ Score")
        self.card_validity = KPIBadge(kpi_panel, "Validity")
        self.card_complete = KPIBadge(kpi_panel, "Completeness")
        self.card_anoms    = KPIBadge(kpi_panel, "Anomalies")

        for c in (self.card_rows, self.card_cols, self.card_nulls, self.card_unique,
                  self.card_quality, self.card_validity, self.card_complete, self.card_anoms):
            kpi_row.Add(c, 1, wx.ALL | wx.EXPAND, 6)

        kpi_v.Add(kpi_row, 0, wx.EXPAND)

        # Little Buddy centered
        self.little_pill = LittleBuddyPill(kpi_panel, handler=self.on_little_buddy)
        kpi_v.Add(self.little_pill, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 10)

        kpi_panel.SetSizer(kpi_v)
        main.Add(kpi_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Menus
        mb = wx.MenuBar()
        m_file = wx.Menu()
        m_file.Append(wx.ID_EXIT, "&Quit\tCtrl+Q")
        mb.Append(m_file, "&File")
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)

        m_settings = wx.Menu()
        OPEN_SETTINGS_ID = wx.NewIdRef()
        m_settings.Append(OPEN_SETTINGS_ID, "&Preferences...\tCtrl+,")
        mb.Append(m_settings, "&Settings")
        self.Bind(wx.EVT_MENU, self.open_settings, id=OPEN_SETTINGS_ID)
        self.SetMenuBar(mb)

        # Toolbar
        toolbar_panel = wx.Panel(self)
        toolbar_panel.SetBackgroundColour(PANEL)
        toolbar = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(label, handler):
            b = RoundedShadowButton(toolbar_panel, label, handler, colour=BLUE, radius=12)
            toolbar.Add(b, 0, wx.ALL, 6)
            return b

        add_btn("Knowledge Files", self.on_load_knowledge)
        add_btn("Load File", self.on_load_file)
        add_btn("Load from URI/S3", self.on_load_s3)
        add_btn("MDM", self.on_mdm)
        add_btn("Synthetic Data", self.on_generate_synth)
        add_btn("Rule Assignment", self.on_rules)
        add_btn("Profile", lambda e: self.do_analysis_process("Profile"))
        add_btn("Quality", lambda e: self.do_analysis_process("Quality"))
        add_btn("Detect Anomalies", lambda e: self.do_analysis_process("Detect Anomalies"))
        add_btn("Catalog", lambda e: self.do_analysis_process("Catalog"))
        add_btn("Compliance", lambda e: self.do_analysis_process("Compliance"))
        add_btn("Tasks", self.on_run_tasks)
        add_btn("Export CSV", self.on_export_csv)
        add_btn("Export TXT", self.on_export_txt)
        add_btn("Upload to S3", self.on_upload_s3)

        toolbar_panel.SetSizer(toolbar)
        main.Add(toolbar_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Knowledge line
        info_panel = wx.Panel(self)
        info_panel.SetBackgroundColour(wx.Colour(48, 48, 48))
        hz = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(info_panel, label="Knowledge Files:")
        lab.SetForegroundColour(TXT)
        lab.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.NORMAL))
        self.knowledge_lbl = wx.StaticText(info_panel, label="(none)")
        self.knowledge_lbl.SetForegroundColour(wx.Colour(200, 200, 200))
        hz.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        hz.Add(self.knowledge_lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        hz.AddStretchSpacer()
        info_panel.SetSizer(hz)
        main.Add(info_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Grid
        grid_panel = wx.Panel(self)
        grid_panel.SetBackgroundColour(BG)
        self.grid = gridlib.Grid(grid_panel)
        self.grid.CreateGrid(0, 0)
        self.grid.SetDefaultCellTextColour(wx.Colour(230, 230, 230))
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(35, 35, 35))
        self.grid.SetLabelTextColour(wx.Colour(210, 210, 210))
        self.grid.SetLabelBackgroundColour(wx.Colour(40, 40, 40))
        self.grid.SetGridLineColour(wx.Colour(55, 55, 55))
        self.grid.EnableEditing(False)
        self.grid.SetRowLabelSize(36)
        self.grid.SetColLabelSize(28)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)

        gp = wx.BoxSizer(wx.VERTICAL)
        gp.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)
        grid_panel.SetSizer(gp)
        main.Add(grid_panel, 1, wx.EXPAND | wx.ALL, 4)

        self.SetSizer(main)

    # ──────────────────────────────────────────────────────────────────────
    # KPI helpers
    # ──────────────────────────────────────────────────────────────────────
    def _reset_kpis_for_new_dataset(self, hdr, data):
        self.metrics.update({
            "rows": len(data),
            "cols": len(hdr),
            "null_pct": None,
            "uniqueness": None,
            "dq_score": None,
            "validity": None,
            "completeness": None,
            "anomalies": None,
        })
        self._render_kpis()
        # kernel state
        self.kernel.set_last_dataset(columns=hdr, rows_count=len(data))
        self.kernel.log("dataset_loaded", rows=len(data), cols=len(hdr))

    def _render_kpis(self):
        self.card_rows.SetValue(self.metrics["rows"] if self.metrics["rows"] is not None else "—")
        self.card_cols.SetValue(self.metrics["cols"] if self.metrics["cols"] is not None else "—")
        self.card_nulls.SetValue(f"{self.metrics['null_pct']:.1f}%" if self.metrics["null_pct"] is not None else "—")
        self.card_unique.SetValue(f"{self.metrics['uniqueness']:.1f}%" if self.metrics["uniqueness"] is not None else "—")
        self.card_quality.SetValue(f"{self.metrics['dq_score']:.1f}" if self.metrics["dq_score"] is not None else "—")
        self.card_validity.SetValue(f"{self.metrics['validity']:.1f}%" if self.metrics["validity"] is not None else "—")
        self.card_complete.SetValue(f"{self.metrics['completeness']:.1f}%" if self.metrics["completeness"] is not None else "—")
        self.card_anoms.SetValue(str(self.metrics["anomalies"]) if self.metrics["anomalies"] is not None else "—")
        # mirror in kernel
        self.kernel.set_kpis(self.metrics)

    @staticmethod
    def _as_df(rows, cols):
        df = pd.DataFrame(rows, columns=cols)
        return df.applymap(lambda x: None if (x is None or (isinstance(x, str) and x.strip() == "")) else x)

    def _compute_profile_metrics(self, df: pd.DataFrame):
        total_cells = df.shape[0] * max(1, df.shape[1])
        nulls = int(df.isna().sum().sum())
        null_pct = (nulls / total_cells) * 100.0 if total_cells else 0.0
        uniqs = []
        for c in df.columns:
            s = df[c].dropna()
            n = len(s)
            uniqs.append((s.nunique() / n * 100.0) if n else 0.0)
        uniq_pct = sum(uniqs) / len(uniqs) if uniqs else 0.0
        return null_pct, uniq_pct

    def _compile_rules(self):
        compiled = {}
        for k, v in (self.quality_rules or {}).items():
            if hasattr(v, "pattern"):
                compiled[k] = v
            else:
                try:
                    compiled[k] = re.compile(str(v))
                except Exception:
                    compiled[k] = re.compile(".*")
        return compiled

    def _compute_quality_metrics(self, df: pd.DataFrame):
        total_cells = df.shape[0] * max(1, df.shape[1])
        nulls = int(df.isna().sum().sum())
        completeness = (1.0 - (nulls / total_cells)) * 100.0 if total_cells else 0.0
        rules = self._compile_rules()
        checked = 0
        valid = 0
        for col, rx in rules.items():
            if col in df.columns:
                for val in df[col].astype(str):
                    checked += 1
                    if rx.fullmatch(val) or rx.search(val):
                        valid += 1
        validity = (valid / checked) * 100.0 if checked else None
        if self.metrics["uniqueness"] is None or self.metrics["null_pct"] is None:
            null_pct, uniq_pct = self._compute_profile_metrics(df)
            self.metrics["null_pct"] = null_pct
            self.metrics["uniqueness"] = uniq_pct
        components = [self.metrics["uniqueness"], completeness]
        if validity is not None:
            components.append(validity)
        dq_score = sum(components) / len(components) if components else 0.0
        return completeness, validity, dq_score

    def _detect_anomalies(self, df: pd.DataFrame):
        work = df.copy()

        def to_num(s):
            if s is None:
                return None
            if isinstance(s, (int, float)):
                return float(s)
            st = str(s).strip().replace(",", "")
            m = re.search(r"([-+]?\d*\.?\d+)", st)
            return float(m.group(1)) if m else None

        num_cols = []
        for c in work.columns:
            series = work[c].map(to_num)
            if series.notna().sum() >= 3:
                num_cols.append((c, series))

        flags = pd.Series(False, index=work.index)
        reasons = [[] for _ in range(len(work))]

        for cname, s in num_cols:
            x = s.astype(float)
            mu = x.mean()
            sd = x.std(ddof=0)
            if not sd or sd == 0:
                continue
            z = (x - mu).abs() / sd
            hits = z > 3.0
            flags = flags | hits.fillna(False)
            for i, hit in hits.fillna(False).items():
                if hit:
                    reasons[i].append(f"{cname} z>{3}")

        work["__anomaly__"] = [", ".join(r) if r else "" for r in reasons]
        count = int(flags.sum())
        return work, count

    # ──────────────────────────────────────────────────────────────────────
    # Settings & Little Buddy
    # ──────────────────────────────────────────────────────────────────────
    def open_settings(self, _evt=None):
        try:
            dlg = SettingsWindow(self)
            self.kernel.log("open_settings")
            if hasattr(dlg, "ShowModal"):
                dlg.ShowModal()
                if hasattr(dlg, "Destroy"):
                    dlg.Destroy()
            else:
                dlg.Show()
        except Exception as e:
            wx.MessageBox(f"Could not open Settings:\n{e}", "Settings", wx.OK | wx.ICON_ERROR)

    def on_little_buddy(self, _evt=None):
        try:
            dlg = DataBuddyDialog(self)
            # Pass kernel if dialog supports it; otherwise it can read env var
            if hasattr(dlg, "set_kernel"):
                dlg.set_kernel(self.kernel)
            elif hasattr(dlg, "kernel"):
                setattr(dlg, "kernel", self.kernel)
            elif hasattr(dlg, "kernel_path"):
                setattr(dlg, "kernel_path", self.kernel.path)
            self.kernel.log("little_buddy_opened", kernel_path=self.kernel.path)
            if hasattr(dlg, "ShowModal"):
                dlg.ShowModal()
                if hasattr(dlg, "Destroy"):
                    dlg.Destroy()
            else:
                dlg.Show()
        except Exception as e:
            wx.MessageBox(f"Little Buddy failed to open:\n{e}", "Little Buddy", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # File / S3 / Knowledge / Rules
    # ──────────────────────────────────────────────────────────────────────
    def on_load_knowledge(self, _evt=None):
        dlg = wx.FileDialog(self, "Load knowledge files", wildcard="Text|*.txt;*.csv;*.tsv|All|*.*",
                            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            return
        files = dlg.GetPaths()
        dlg.Destroy()
        self.knowledge_files = files
        self.knowledge_lbl.SetLabel(", ".join(os.path.basename(p) for p in files) if files else "(none)")
        self.kernel.log("load_knowledge_files", count=len(files), files=[os.path.basename(p) for p in files])

    def _load_text_file(self, path):
        return open(path, "r", encoding="utf-8", errors="ignore").read()

    def on_load_file(self, _evt=None):
        dlg = wx.FileDialog(self, "Open data file", wildcard="Data|*.csv;*.tsv;*.txt|All|*.*",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            text = self._load_text_file(path)
            hdr, data = detect_and_split_data(text)
        except Exception as e:
            wx.MessageBox(f"Could not read file: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        self.headers = hdr
        self.raw_data = data
        self._display(hdr, data)
        self._reset_kpis_for_new_dataset(hdr, data)
        self.kernel.log("load_file", path=path, rows=len(data), cols=len(hdr))

    def on_load_s3(self, _evt=None):
        with wx.TextEntryDialog(self, "Enter URI (S3 presigned or HTTP/HTTPS):", "Load from URI/S3") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            uri = dlg.GetValue().strip()
        try:
            text = download_text_from_uri(uri)
            hdr, data = detect_and_split_data(text)
        except Exception as e:
            wx.MessageBox(f"Download failed: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        self.headers = hdr
        self.raw_data = data
        self._display(hdr, data)
        self._reset_kpis_for_new_dataset(hdr, data)
        self.kernel.log("load_uri", uri=uri, rows=len(data), cols=len(hdr))

    def on_rules(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load data first so fields are available.", "Quality Rules", wx.OK | wx.ICON_WARNING)
            return
        if not isinstance(self.quality_rules, dict):
            try:
                self.quality_rules = dict(self.quality_rules)
            except Exception:
                self.quality_rules = {}
        fields = list(self.headers)
        current_rules = self.quality_rules
        dlg = None
        try:
            dlg = QualityRuleDialog(self, fields, current_rules)
            if hasattr(dlg, "ShowModal"):
                res = dlg.ShowModal()
                if res == wx.ID_OK:
                    self.quality_rules = getattr(dlg, "current_rules", current_rules)
                    self.kernel.log("rules_updated", rules=self.quality_rules)
                if hasattr(dlg, "Destroy"):
                    dlg.Destroy()
            else:
                dlg.Show()
        except Exception as e:
            if dlg and hasattr(dlg, "Destroy"):
                dlg.Destroy()
            wx.MessageBox(f"Could not open Quality Rule Assignment:\n{e}", "Quality Rules", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Synthetic data (generators)
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _most_common_format(strings, default_mask="DDD-DDD-DDDD"):
        def mask_one(s): return re.sub(r"\d", "D", s)
        masks = [mask_one(s) for s in strings if isinstance(s, str)]
        return Counter(masks).most_common(1)[0][0] if masks else default_mask

    @staticmethod
    def _sample_with_weights(values):
        if not values:
            return lambda *_: None
        counts = Counter(values)
        vals, weights = zip(*counts.items())
        total = float(sum(weights))
        probs = [w / total for w in weights]
        def pick(_row=None):
            r = random.random(); acc = 0.0
            for v, p in zip(vals, probs):
                acc += p
                if r <= acc: return v
            return vals[-1]
        return pick

    def _build_generators(self, src_df: pd.DataFrame, fields):
        gens = {}
        name_first = [ "James","Mary","Robert","Patricia","John","Jennifer","Michael","Linda","William","Elizabeth" ]
        name_last  = [ "Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez" ]
        first_col = next((c for c in src_df.columns if "first" in c.lower() and "name" in c.lower()), None)
        last_col  = next((c for c in src_df.columns if "last"  in c.lower() and "name" in c.lower()), None)

        for col in fields:
            lower = col.lower()
            series = src_df[col] if col in src_df.columns else pd.Series([], dtype=object)
            col_vals = [v for v in series.tolist() if (v is not None and str(v).strip() != "")]
            col_strs = [str(v) for v in col_vals]

            if "email" in lower:
                domains = [s.split("@", 1)[1].lower() for s in col_strs if "@" in s]
                dom = self._sample_with_weights(domains or ["gmail.com","yahoo.com","outlook.com","example.com"])
                if first_col or last_col:
                    first_vals = [str(x) for x in src_df[first_col].dropna()] if first_col else name_first
                    last_vals  = [str(x) for x in src_df[last_col].dropna()]  if last_col  else name_last
                    pick_f, pick_l = self._sample_with_weights(first_vals), self._sample_with_weights(last_vals)
                    def gen(row):
                        f = str(pick_f() or "user").lower(); l = str(pick_l() or "name").lower()
                        style = random.choice([0,1,2])
                        local = f"{f}.{l}" if style==0 else (f"{f}{l[:1]}" if style==1 else f"{f}{random.randint(1,99)}")
                        return f"{local}@{dom()}"
                    gens[col] = gen
                else:
                    pick = self._sample_with_weights(col_vals) if col_vals else None
                    gens[col] = (lambda _row, p=pick, d=dom: (p() if p and random.random()<0.7 else f"user{random.randint(1000,9999)}@{d()}"))
                continue

            if any(k in lower for k in ["phone","mobile","cell","telephone"]):
                mask = self._most_common_format([s for s in col_strs if re.search(r"\d", s)])
                def gen(_row):
                    return "".join(str(random.randint(0,9)) if ch=="D" else ch for ch in mask)
                gens[col] = gen; continue

            if "date" in lower or "dob" in lower:
                parsed=[]
                for s in col_strs:
                    for fmt in ("%Y-%m-%d","%m/%d/%Y","%d/%m/%Y","%Y/%m/%d"):
                        try: parsed.append(datetime.strptime(s, fmt)); break
                        except: pass
                if parsed: dmin,dmax=min(parsed),max(parsed)
                else:
                    dmax=datetime.today(); dmin=dmax-timedelta(days=3650)
                delta=(dmax-dmin).days or 365
                out_fmt="%Y-%m-%d"
                def gen(_row):
                    return (dmin+timedelta(days=random.randint(0, max(1,delta)))).strftime(out_fmt)
                gens[col]=gen; continue

            uniq = set(col_vals)
            if uniq and len(uniq) <= 50:
                gens[col] = self._sample_with_weights(col_vals); continue
            if col_vals:
                pick = self._sample_with_weights(col_vals)
                gens[col] = lambda _r, p=pick: p()
            else:
                def gen(_r):
                    letters="abcdefghijklmnopqrstuvwxyz"
                    return "".join(random.choice(letters) for _ in range(random.randint(5,10)))
                gens[col]=gen
        return gens

    def on_generate_synth(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load data first to choose fields.", "No data", wx.OK | wx.ICON_WARNING)
            return
        src_df = pd.DataFrame(self.raw_data, columns=self.headers)
        dlg = SyntheticDataDialog(self, fields=list(self.headers))
        if hasattr(dlg, "ShowModal"):
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
        try:
            if hasattr(dlg, "get_values"):
                n_rows, fields = dlg.get_values()
            else:
                n_rows = getattr(dlg, "n_rows", 0)
                fields = getattr(dlg, "fields", list(self.headers))
            if not fields:
                fields = list(self.headers)
            gens = self._build_generators(src_df, fields)
            out_rows = []
            for _ in range(int(n_rows)):
                row_map = {}
                for f in fields:
                    g = gens.get(f)
                    val = g(row_map) if callable(g) else None
                    row_map[f] = "" if val is None else val
                out_rows.append([row_map[f] for f in fields])
            df = pd.DataFrame(out_rows, columns=fields)
        except Exception as e:
            wx.MessageBox(f"Synthetic data error: {e}", "Error", wx.OK | wx.ICON_ERROR)
            if hasattr(dlg, "Destroy"):
                dlg.Destroy()
            return
        if hasattr(dlg, "Destroy"):
            dlg.Destroy()
        hdr = list(df.columns)
        data = df.values.tolist()
        self.headers = hdr
        self.raw_data = data
        self._display(hdr, data)
        self._reset_kpis_for_new_dataset(hdr, data)
        self.kernel.log("synthetic_generated", rows=len(data), cols=len(hdr), fields=hdr)

    # ──────────────────────────────────────────────────────────────────────
    # MDM — match & merge to golden records
    # ──────────────────────────────────────────────────────────────────────
    def on_mdm(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load a base dataset first (or generate synthetic data).", "MDM", wx.OK | wx.ICON_WARNING)
            return

        dlg = MDMDialog(self)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        params = dlg.get_params()
        dlg.Destroy()

        # Collect dataframes
        dataframes = []

        if params["include_current"]:
            dataframes.append(pd.DataFrame(self.raw_data, columns=self.headers))

        # Add extra sources
        try:
            for src in params["sources"]:
                if src["type"] == "file":
                    text = self._load_text_file(src["value"])
                    hdr, data = detect_and_split_data(text)
                    dataframes.append(pd.DataFrame(data, columns=hdr))
                else:
                    text = download_text_from_uri(src["value"])
                    hdr, data = detect_and_split_data(text)
                    dataframes.append(pd.DataFrame(data, columns=hdr))
        except Exception as e:
            wx.MessageBox(f"Failed to load a source:\n{e}", "MDM", wx.OK | wx.ICON_ERROR)
            return

        if len(dataframes) < 2:
            wx.MessageBox("Please add at least one additional dataset.", "MDM", wx.OK | wx.ICON_WARNING)
            return

        try:
            golden = self._run_mdm(
                dataframes,
                use_email=params["use_email"],
                use_phone=params["use_phone"],
                use_name=params["use_name"],
                use_addr=params["use_addr"],
                threshold=params["threshold"]
            )
        except Exception as e:
            import traceback
            wx.MessageBox(f"MDM failed:\n{e}\n\n{traceback.format_exc()}", "MDM", wx.OK | wx.ICON_ERROR)
            return

        hdr = list(golden.columns)
        data = golden.astype(str).values.tolist()
        self.headers = hdr
        self.raw_data = data
        self._display(hdr, data)
        self._reset_kpis_for_new_dataset(hdr, data)
        self.current_process = "MDM"
        self.kernel.log("mdm_completed", golden_rows=len(data), golden_cols=len(hdr), params=params)

    # Field name helpers
    @staticmethod
    def _find_col(cols, *candidates):
        cl = {c.lower(): c for c in cols}
        for cand in candidates:
            for c in cl:
                if cand in c:
                    return cl[c]
        return None

    @staticmethod
    def _norm_email(x):
        return str(x).strip().lower() if x is not None else None

    @staticmethod
    def _norm_phone(x):
        if x is None:
            return None
        digits = re.sub(r"\D+", "", str(x))
        if len(digits) >= 10:
            return digits[-10:]
        return digits or None

    @staticmethod
    def _norm_name(x):
        if x is None:
            return None
        return re.sub(r"[^a-z]", "", str(x).lower())

    @staticmethod
    def _norm_text(x):
        if x is None:
            return None
        return re.sub(r"\s+", " ", str(x).strip().lower())

    @staticmethod
    def _sim(a, b):
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _block_key(self, row, cols):
        e = row.get(cols.get("email"))
        if e:
            return f"e:{self._norm_email(e)}"
        p = row.get(cols.get("phone"))
        if p:
            return f"p:{self._norm_phone(p)}"
        fi = (row.get(cols.get("first")) or "")[:1].lower()
        li = (row.get(cols.get("last")) or "")[:1].lower()
        zipc = str(row.get(cols.get("zip")) or "")[:3]
        city = str(row.get(cols.get("city")) or "")[:3].lower()
        key = f"n:{fi}{li}|{zipc or city}"
        return key

    def _score_pair(self, a, b, cols, use_email, use_phone, use_name, use_addr):
        parts = []
        weights = []

        if use_email and cols.get("email"):
            ea = self._norm_email(a.get(cols["email"]))
            eb = self._norm_email(b.get(cols["email"]))
            if ea and eb:
                parts.append(1.0 if ea == eb else self._sim(ea, eb))
                weights.append(0.5)

        if use_phone and cols.get("phone"):
            pa = self._norm_phone(a.get(cols["phone"]))
            pb = self._norm_phone(b.get(cols["phone"]))
            if pa and pb:
                parts.append(1.0 if pa == pb else self._sim(pa, pb))
                weights.append(0.5)

        if use_name and (cols.get("first") or cols.get("last")):
            fa = self._norm_name(a.get(cols.get("first")))
            fb = self._norm_name(b.get(cols.get("first")))
            la = self._norm_name(a.get(cols.get("last")))
            lb = self._norm_name(b.get(cols.get("last")))
            if fa and fb:
                parts.append(self._sim(fa, fb))
                weights.append(0.25)
            if la and lb:
                parts.append(self._sim(la, lb))
                weights.append(0.3)

        if use_addr and (cols.get("addr") or cols.get("city")):
            aa = self._norm_text(a.get(cols.get("addr")))
            ab = self._norm_text(b.get(cols.get("addr")))
            ca = self._norm_text(a.get(cols.get("city")))
            cb = self._norm_text(b.get(cols.get("city")))
            sa = self._norm_text(a.get(cols.get("state")))
            sb = self._norm_text(b.get(cols.get("state")))
            za = self._norm_text(a.get(cols.get("zip")))
            zb = self._norm_text(b.get(cols.get("zip")))
            chunk = []
            if aa and ab:
                chunk.append(self._sim(aa, ab))
            if ca and cb:
                chunk.append(self._sim(ca, cb))
            if sa and sb:
                chunk.append(self._sim(sa, sb))
            if za and zb:
                chunk.append(1.0 if za == zb else self._sim(za, zb))
            if chunk:
                parts.append(sum(chunk) / len(chunk))
                weights.append(0.25)

        if not parts:
            return 0.0
        wsum = sum(weights) or 1.0
        score = sum(p * w for p, w in zip(parts, weights)) / wsum
        return score

    def _run_mdm(self, dataframes, use_email=True, use_phone=True, use_name=True, use_addr=True, threshold=0.85):
        """Return golden-record DataFrame from a list of DataFrames."""
        datasets = []
        union_cols = set()
        for df in dataframes:
            cols = list(df.columns)
            colmap = {
                "email": self._find_col(cols, "email"),
                "phone": self._find_col(cols, "phone", "mobile", "cell", "telephone"),
                "first": self._find_col(cols, "first name", "firstname", "given"),
                "last":  self._find_col(cols, "last name", "lastname", "surname", "family"),
                "addr":  self._find_col(cols, "address", "street"),
                "city":  self._find_col(cols, "city",),
                "state": self._find_col(cols, "state", "province", "region"),
                "zip":   self._find_col(cols, "zip", "postal"),
            }
            union_cols.update(cols)
            datasets.append((df.reset_index(drop=True), colmap))

        # Prepare records with blocking
        records = []
        offset = 0
        for df, colmap in datasets:
            for i in range(len(df)):
                row = df.iloc[i].to_dict()
                records.append((offset + i, row, colmap))
            offset += len(df)

        # Build blocks
        blocks = defaultdict(list)
        for rec_id, row, cmap in records:
            key = self._block_key(row, cmap)
            blocks[(key, tuple(sorted(cmap.items())) )].append((rec_id, row, cmap))

        # DSU for clustering
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Pairwise within blocks
        for _, members in blocks.items():
            n = len(members)
            if n <= 1:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    (id_a, row_a, cmap_a) = members[i]
                    (id_b, row_b, cmap_b) = members[j]
                    cols = {}
                    for k in ("email","phone","first","last","addr","city","state","zip"):
                        cols[k] = cmap_a.get(k) or cmap_b.get(k)
                    score = self._score_pair(row_a, row_b, cols, use_email, use_phone, use_name, use_addr)
                    if score >= threshold:
                        union(id_a, id_b)

        # Collect clusters
        clusters = defaultdict(list)
        for rec_id, row, cmap in records:
            clusters[find(rec_id)].append((row, cmap))

        def best_value(values):
            """Majority vote; numeric -> median; date -> most recent; tie -> longest string."""
            vals = [v for v in values if (v is not None and str(v).strip() != "")]
            if not vals:
                return ""
            # Date-like?
            parsed = []
            for v in vals:
                s = str(v)
                for fmt in ("%Y-%m-%d","%m/%d/%Y","%d/%m/%Y","%Y/%m/%d"):
                    try:
                        parsed.append(datetime.strptime(s, fmt))
                        break
                    except Exception:
                        continue
            if parsed and len(parsed) >= len(vals) * 0.6:
                return max(parsed).strftime("%Y-%m-%d")
            # Numeric?
            nums = pd.to_numeric(pd.Series(vals).astype(str).str.replace(",", ""), errors="coerce").dropna()
            if len(nums) >= len(vals) * 0.6:
                med = float(nums.median())
                return str(int(med)) if med.is_integer() else f"{med:.2f}"
            # Majority / longest
            counts = Counter([str(v).strip() for v in vals])
            top, freq = counts.most_common(1)[0]
            ties = [k for k, c in counts.items() if c == freq]
            if len(ties) == 1:
                return ties[0]
            return max(ties, key=len)

        all_cols = list(sorted(union_cols, key=lambda x: x.lower()))
        golden_rows = []
        for cluster_rows in clusters.values():
            merged = {}
            for col in all_cols:
                merged[col] = best_value([r.get(col) for r, _ in cluster_rows])
            golden_rows.append(merged)

        golden_df = pd.DataFrame(golden_rows, columns=all_cols)
        return golden_df

    # ──────────────────────────────────────────────────────────────────────
    # Analyses
    # ──────────────────────────────────────────────────────────────────────
    def do_analysis_process(self, proc_name: str):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        self.current_process = proc_name
        df = self._as_df(self.raw_data, self.headers)

        if proc_name == "Profile":
            try:
                hdr, data = profile_analysis(df)
            except Exception:
                desc = pd.DataFrame({
                    "Field": df.columns,
                    "Null %": [f"{df[c].isna().mean()*100:.1f}%" for c in df.columns],
                    "Unique": [df[c].nunique() for c in df.columns],
                })
                hdr, data = list(desc.columns), desc.values.tolist()
            null_pct, uniq_pct = self._compute_profile_metrics(df)
            self.metrics["null_pct"] = null_pct
            self.metrics["uniqueness"] = uniq_pct
            self._render_kpis()
            self.kernel.log("run_profile", null_pct=null_pct, uniqueness=uniq_pct)

        elif proc_name == "Quality":
            try:
                hdr, data = quality_analysis(df, self.quality_rules)
            except Exception:
                hdr, data = list(df.columns), df.values.tolist()
            completeness, validity, dq = self._compute_quality_metrics(df)
            self.metrics["completeness"] = completeness
            self.metrics["validity"] = validity
            self.metrics["dq_score"] = dq
            self._render_kpis()
            self.kernel.log("run_quality", completeness=completeness, validity=validity, dq_score=dq)

        elif proc_name == "Detect Anomalies":
            try:
                work, count = self._detect_anomalies(df)
                hdr, data = list(work.columns), work.values.tolist()
            except Exception:
                hdr, data = list(df.columns), df.values.tolist()
                count = 0
            self.metrics["anomalies"] = count
            self._render_kpis()
            self.kernel.log("run_detect_anomalies", anomalies=count)

        elif proc_name == "Catalog":
            try:
                hdr, data = catalog_analysis(df)
            except Exception:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows = []
                for c in df.columns:
                    ex = next((str(v) for v in df[c].dropna().head(1).tolist()), "")
                    dtype = "Number" if pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.8 else "Text"
                    rows.append([c, c.replace("_"," ").title(), f"Automatically generated description for {c}.", dtype,
                                 "No" if df[c].isna().mean() < 0.5 else "Yes", ex, now])
                hdr = ["Field","Friendly Name","Description","Data Type","Nullable","Example","Analysis Date"]
                data = rows
            self.kernel.log("run_catalog", columns=len(hdr))

        elif proc_name == "Compliance":
            try:
                hdr, data = compliance_analysis(df)
            except Exception:
                hdr, data = list(df.columns), df.values.tolist()
            self.kernel.log("run_compliance")

        else:
            hdr, data = ["Message"], [[f"Unknown process: {proc_name}"]]

        self._display(hdr, data)

    # ──────────────────────────────────────────────────────────────────────
    # Export / Upload / Tasks
    # ──────────────────────────────────────────────────────────────────────
    def on_export_csv(self, _evt=None):
        dlg = wx.FileDialog(self, "Save CSV", wildcard="CSV|*.csv",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=",")
            wx.MessageBox("CSV exported.", "Export", wx.OK | wx.ICON_INFORMATION)
            self.kernel.log("export_csv", path=path, rows=len(data), cols=len(hdr))
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_export_txt(self, _evt=None):
        dlg = wx.FileDialog(self, "Save TXT", wildcard="TXT|*.txt",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep="\t")
            wx.MessageBox("TXT exported.", "Export", wx.OK | wx.ICON_INFORMATION)
            self.kernel.log("export_txt", path=path, rows=len(data), cols=len(hdr))
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, _evt=None):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
        try:
            msg = upload_to_s3(self.current_process or "Unknown", hdr, data)
            wx.MessageBox(msg, "Upload", wx.OK | wx.ICON_INFORMATION)
            self.kernel.log("upload_s3", rows=len(data), cols=len(hdr), process=self.current_process or "Unknown")
        except Exception as e:
            wx.MessageBox(f"Upload failed: {e}", "Upload", wx.OK | wx.ICON_ERROR)

    def on_run_tasks(self, _evt=None):
        dlg = wx.FileDialog(
            self,
            "Open Tasks File",
            wildcard="Tasks (*.json;*.txt)|*.json;*.txt|All|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            tasks = self._load_tasks_from_file(path)
        except Exception as e:
            wx.MessageBox(f"Could not read tasks file:\n{e}", "Tasks", wx.OK | wx.ICON_ERROR)
            return
        self.kernel.log("tasks_started", path=path, steps=len(tasks))
        threading.Thread(target=self._run_tasks_worker, args=(tasks,), daemon=True).start()

    def _load_tasks_from_file(self, path: str):
        text = open(path, "r", encoding="utf-8", errors="ignore").read().strip()
        if not text:
            return []
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                obj = obj.get("tasks") or obj.get("steps") or obj.get("actions") or []
            if not isinstance(obj, list):
                raise ValueError("JSON must be a list of task objects")
            out = []
            for it in obj:
                if not isinstance(it, dict) or "action" not in it:
                    raise ValueError("Each JSON task must be an object with 'action'")
                t = {k: v for k, v in it.items()}
                t["action"] = str(t["action"]).strip()
                out.append(t)
            return out
        except Exception:
            pass

        tasks = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            action = parts[0]
            arg = parts[1] if len(parts) == 2 else None
            t = {"action": action}
            if arg:
                if action.lower() in ("loadfile", "exportcsv", "exporttxt"):
                    t["path"] = arg
                elif action.lower() in ("loads3", "loaduri"):
                    t["uri"] = arg
                else:
                    t["arg"] = arg
            tasks.append(t)
        return tasks

    def _run_tasks_worker(self, tasks):
        ran = 0
        for i, t in enumerate(tasks, 1):
            try:
                act = (t.get("action") or "").strip().lower()

                if act == "loadfile":
                    p = t.get("path") or t.get("file")
                    if not p:
                        raise ValueError("LoadFile requires 'path'")
                    text = self._load_text_file(p)
                    self.headers, self.raw_data = detect_and_split_data(text)
                    wx.CallAfter(self._display, self.headers, self.raw_data)
                    wx.CallAfter(self._reset_kpis_for_new_dataset, self.headers, self.raw_data)

                elif act in ("loads3", "loaduri"):
                    uri = t.get("uri") or t.get("path")
                    if not uri:
                        raise ValueError("LoadS3/LoadURI requires 'uri'")
                    text = download_text_from_uri(uri)
                    self.headers, self.raw_data = detect_and_split_data(text)
                    wx.CallAfter(self._display, self.headers, self.raw_data)
                    wx.CallAfter(self._reset_kpis_for_new_dataset, self.headers, self.raw_data)

                elif act in ("profile", "quality", "catalog", "compliance", "detectanomalies"):
                    name = {"detectanomalies": "Detect Anomalies"}.get(act, act.capitalize())
                    wx.CallAfter(self.do_analysis_process, name)

                elif act == "exportcsv":
                    p = t.get("path")
                    if not p:
                        raise ValueError("ExportCSV requires 'path'")
                    wx.CallAfter(self._export_to_path, p, ",")

                elif act == "exporttxt":
                    p = t.get("path")
                    if not p:
                        raise ValueError("ExportTXT requires 'path'")
                    wx.CallAfter(self._export_to_path, p, "\t")

                elif act == "uploads3":
                    wx.CallAfter(self.on_upload_s3, None)

                elif act == "sleep":
                    import time
                    time.sleep(float(t.get("seconds", 1)))

                else:
                    raise ValueError(f"Unknown action: {t.get('action')}")

                ran += 1

            except Exception as e:
                wx.CallAfter(wx.MessageBox, f"Tasks stopped at step {i}:\n{t}\n\n{e}", "Tasks", wx.OK | wx.ICON_ERROR)
                self.kernel.log("tasks_failed", step=i, action=t.get("action"), error=str(e))
                return

        self.kernel.log("tasks_completed", steps=ran)
        wx.CallAfter(wx.MessageBox, f"Tasks completed. {ran} step(s) executed.", "Tasks", wx.OK | wx.ICON_INFORMATION)

    def _export_to_path(self, path: str, sep: str):
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                    for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=sep)
            self.kernel.log("export_to_path", path=path, sep=sep, rows=len(data), cols=len(hdr))
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Grid helpers
    # ──────────────────────────────────────────────────────────────────────
    def _display(self, hdr, data):
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        if not hdr:
            self._render_kpis()
            return

        self.grid.AppendCols(len(hdr))
        for i, h in enumerate(hdr):
            self.grid.SetColLabelValue(i, str(h))

        self.grid.AppendRows(len(data))
        for r, row in enumerate(data):
            for c, val in enumerate(row):
                self.grid.SetCellValue(r, c, str(val))
                if r % 2 == 0:
                    self.grid.SetCellBackgroundColour(r, c, wx.Colour(45, 45, 45))
        self.adjust_grid()
        self._render_kpis()

    def adjust_grid(self):
        cols = self.grid.GetNumberCols()
        if cols == 0:
            return
        total_w = self.grid.GetClientSize().GetWidth()
        usable = max(0, total_w - self.grid.GetRowLabelSize())
        w = max(60, usable // cols)
        for c in range(cols):
            self.grid.SetColSize(c, w)

    def on_grid_resize(self, event):
        event.Skip()
        wx.CallAfter(self.adjust_grid)



if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
