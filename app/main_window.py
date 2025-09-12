# app/main_window.py
import os
import re
import json
import math
import random
import threading
import inspect
from datetime import datetime, timedelta
from collections import Counter

import wx
import wx.grid as gridlib
import pandas as pd

from app.settings import SettingsWindow, save_defaults, defaults
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
# Rounded button widget (safer handler invocation & useful error box)
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
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)
        self._padx, self._pady = 16, 10
        self._font = wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM)
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

        # label
        dc.SetTextForeground(self._text_colour)
        dc.SetFont(self._font)
        tw, th = dc.GetTextExtent(self._label)
        dc.DrawText(self._label, (w - tw) // 2, (h - th) // 2)


# ──────────────────────────────────────────────────────────────────────────────
# KPI badge
# ──────────────────────────────────────────────────────────────────────────────
class KPIBadge(wx.Panel):
    def __init__(self, parent, title, init_value="—", colour=wx.Colour(32, 35, 41)):
        super().__init__(parent, size=(260, 92))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._title = title
        self._value = init_value
        self._colour = colour
        self._accent = wx.Colour(90, 180, 255)
        self._accent2 = wx.Colour(80, 210, 140)
        self._font_title = wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM)
        self._font_value = wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        self.Bind(wx.EVT_PAINT, self.on_paint)

    def SetValue(self, v):
        self._value = v
        self.Refresh()

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()

        # background card
        bg = wx.Colour(28, 28, 28)
        dc.SetBrush(wx.Brush(bg))
        dc.SetPen(wx.Pen(bg))
        dc.DrawRoundedRectangle(0, 0, w, h, 10)

        # inner
        dc.SetBrush(wx.Brush(self._colour))
        dc.SetPen(wx.Pen(self._colour))
        dc.DrawRoundedRectangle(6, 6, w - 12, h - 12, 8)

        # title
        dc.SetTextForeground(wx.Colour(180, 180, 180))
        dc.SetFont(self._font_title)
        dc.DrawText(self._title.upper(), 18, 12)

        # decorative bars
        dc.SetPen(wx.Pen(self._accent, 3))
        dc.DrawLine(16, h - 22, w - 24, h - 22)
        dc.SetPen(wx.Pen(self._accent2, 3))
        dc.DrawLine(16, h - 16, w - 24, h - 16)

        # value
        dc.SetTextForeground(wx.Colour(240, 240, 240))
        dc.SetFont(self._font_value)
        dc.DrawText(str(self._value), 18, 34)


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1200, 820))

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

        self.headers = []
        self.raw_data = []
        self.knowledge_files = []
        # dict of quality rules (dialog expects mapping)
        self.quality_rules = {}
        self.current_process = ""

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

        # KPI row
        kpi_panel = wx.Panel(self)
        kpi_panel.SetBackgroundColour(BG)
        kpi_row = wx.WrapSizer()

        self.card_rows = KPIBadge(kpi_panel, "Rows")
        self.card_cols = KPIBadge(kpi_panel, "Columns")
        self.card_nulls = KPIBadge(kpi_panel, "Null %")
        self.card_quality = KPIBadge(kpi_panel, "DQ Score")
        self.card_complete = KPIBadge(kpi_panel, "Completeness")
        self.card_anoms = KPIBadge(kpi_panel, "Anomalies")

        for c in (self.card_rows, self.card_cols, self.card_nulls, self.card_quality, self.card_complete, self.card_anoms):
            kpi_row.Add(c, 0, wx.ALL, 6)

        kpi_panel.SetSizer(kpi_row)
        main.Add(kpi_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Menu bar with separate "File" and "Settings" menus
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

        add_btn("Load Knowledge Files", self.on_load_knowledge)
        add_btn("Load File", self.on_load_file)
        add_btn("Load from URI/S3", self.on_load_s3)
        add_btn("Generate Synthetic Data", self.on_generate_synth)
        add_btn("Quality Rule Assignment", self.on_rules)
        add_btn("Profile", lambda e: self.do_analysis_process("Profile"))
        add_btn("Quality", lambda e: self.do_analysis_process("Quality"))
        add_btn("Detect Anomalies", lambda e: self.do_analysis_process("Detect Anomalies"))
        add_btn("Catalog", lambda e: self.do_analysis_process("Catalog"))
        add_btn("Compliance", lambda e: self.do_analysis_process("Compliance"))
        # Tasks button (between Compliance and Export CSV)
        add_btn("Tasks", self.on_run_tasks)
        add_btn("Export CSV", self.on_export_csv)
        add_btn("Export TXT", self.on_export_txt)
        add_btn("Upload to S3", self.on_upload_s3)
        # Little Buddy button
        add_btn("Little Buddy", self.on_little_buddy)

        toolbar_panel.SetSizer(toolbar)
        main.Add(toolbar_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Knowledge line
        info_panel = wx.Panel(self)
        info_panel.SetBackgroundColour(wx.Colour(48, 48, 48))
        hz = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(info_panel, label="Knowledge Files:")
        lab.SetForegroundColour(TXT)
        lab.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.MEDIUM))
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
    # Menu handlers
    # ──────────────────────────────────────────────────────────────────────
    def open_settings(self, _evt=None):
        try:
            dlg = SettingsWindow(self)
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
        if files:
            self.knowledge_lbl.SetLabel(", ".join(os.path.basename(p) for p in files))
        else:
            self.knowledge_lbl.SetLabel("(none)")

    def on_load_file(self, _evt=None):
        dlg = wx.FileDialog(self, "Open data file", wildcard="Data|*.csv;*.tsv;*.txt|All|*.*",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            text = open(path, "r", encoding="utf-8", errors="ignore").read()
            hdr, data = detect_and_split_data(text)
        except Exception as e:
            wx.MessageBox(f"Could not read file: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        self.headers = hdr
        self.raw_data = data
        self._display(hdr, data)

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

    def on_rules(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load data first so fields are available.", "Quality Rules", wx.OK | wx.ICON_WARNING)
            return

        # Ensure dict for dialog
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
                if hasattr(dlg, "Destroy"):
                    dlg.Destroy()
            else:
                dlg.Show()
        except Exception as e:
            if dlg and hasattr(dlg, "Destroy"):
                dlg.Destroy()
            wx.MessageBox(f"Could not open Quality Rule Assignment:\n{e}", "Quality Rules", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Analyses
    # ──────────────────────────────────────────────────────────────────────
    def do_analysis_process(self, proc_name: str):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        self.current_process = proc_name
        df = pd.DataFrame(self.raw_data, columns=self.headers)

        if proc_name == "Profile":
            func = profile_analysis
        elif proc_name == "Quality":
            func = lambda d: quality_analysis(d, self.quality_rules)
        elif proc_name == "Catalog":
            func = catalog_analysis
        elif proc_name == "Compliance":
            func = compliance_analysis
        elif proc_name == "Detect Anomalies":
            def func(d):
                hdr = list(d.columns)
                if "__anomaly__" in hdr:
                    return hdr, d.values.tolist()
                d2 = d.copy()
                d2["__anomaly__"] = ""
                return list(d2.columns), d2.values.tolist()
        else:
            def func(d):
                return ["Message"], [[f"Unknown process: {proc_name}"]]

        try:
            hdr, data = func(df)
        except Exception as e:
            hdr, data = ["Error"], [[str(e)]]

        self._display(hdr, data)

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
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, _evt=None):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
        try:
            msg = upload_to_s3(self.current_process or "Unknown", hdr, data)
            wx.MessageBox(msg, "Upload", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Upload failed: {e}", "Upload", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Helpers for realistic synthetic data
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _clean_float(x):
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if not s:
            return None
        s = s.replace(",", "")
        m = re.search(r"([-+]?\d*\.?\d+)", s)
        if not m:
            return None
        try:
            return float(m.group(1))
        except Exception:
            return None

    @staticmethod
    def _most_common_format(strings, default_mask="DDD-DDD-DDDD"):
        """Return the most common phone-like mask from sample strings."""
        def mask_one(s):
            m = re.sub(r"\d", "D", s)
            # collapse 3+ Ds into D-blocks to keep shape
            return m
        masks = [mask_one(s) for s in strings if isinstance(s, str)]
        if not masks:
            return default_mask
        return Counter(masks).most_common(1)[0][0]

    @staticmethod
    def _sample_with_weights(values):
        if not values:
            return lambda *_: None
        counts = Counter(values)
        vals, weights = zip(*counts.items())
        total = float(sum(weights))
        probs = [w / total for w in weights]

        def pick(_row=None):
            r = random.random()
            acc = 0.0
            for v, p in zip(vals, probs):
                acc += p
                if r <= acc:
                    return v
            return vals[-1]
        return pick

    def _build_generators(self, src_df: pd.DataFrame, fields):
        """
        For each field, build a generator function row -> value that:
        - learns from the existing column (distribution, formats)
        - uses simple patterns from header names (email/phone/names/amounts/dates)
        """
        gens = {}
        low_name_lists = {
            "first": ["james","mary","robert","patricia","john","jennifer","michael","linda","william","elizabeth","david","barbara","richard","susan","joseph","jessica"],
            "last": ["smith","johnson","williams","brown","jones","garcia","miller","davis","rodriguez","martinez","hernandez","lopez","gonzalez","wilson","anderson","thomas"],
            "street": ["Main","Oak","Maple","Pine","Cedar","Elm","Washington","Lake","Hill","Sunset","Park","Ridge","Highland","Jackson","Adams"],
            "city": ["Springfield","Riverton","Franklin","Greenville","Clinton","Fairview","Madison","Georgetown","Arlington","Ashland","Milton"],
            "state": ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"]
        }

        fields_present = {f.lower(): f for f in src_df.columns}

        # Some reusable lookups
        first_col = next((fields_present[k] for k in fields_present if "first" in k and "name" in k), None)
        last_col  = next((fields_present[k] for k in fields_present if "last" in k and "name" in k), None)

        # Precompute per-column stats
        for col in fields:
            name = col
            lower = name.lower()
            series = src_df[name] if name in src_df.columns else pd.Series([], dtype=object)

            # Drop NA-like values for training
            col_vals = [v for v in series.tolist() if (v is not None and str(v).strip() != "")]
            col_strs = [str(v) for v in col_vals]

            # Email
            if "email" in lower:
                # learn domains from current column; else fallback
                domains = [s.split("@", 1)[1].lower()
                           for s in col_strs if "@" in s and len(s.split("@", 1)[1]) > 0]
                dom_pick = self._sample_with_weights(domains) if domains else self._sample_with_weights(
                    ["gmail.com", "yahoo.com", "outlook.com", "example.com"]
                )

                # if name cols exist, sample realistic emails from them; else sample observed emails
                if first_col or last_col:
                    first_values = [str(x) for x in src_df[first_col].dropna().tolist()] if first_col else []
                    last_values  = [str(x) for x in src_df[last_col].dropna().tolist()] if last_col else []
                    if not first_values:
                        first_values = [n.title() for n in low_name_lists["first"]]
                    if not last_values:
                        last_values = [n.title() for n in low_name_lists["last"]]
                    pick_first = self._sample_with_weights(first_values)
                    pick_last  = self._sample_with_weights(last_values)

                    def gen_email(row):
                        f = str(pick_first() or "user").lower().replace(" ", "")
                        l = str(pick_last() or "name").lower().replace(" ", "")
                        style = random.choice([0, 1, 2])
                        if style == 0:
                            local = f"{f}.{l}"
                        elif style == 1:
                            local = f"{f}{l[:1]}"
                        else:
                            local = f"{f}{random.randint(1, 99)}"
                        return f"{local}@{dom_pick()}"
                    gens[name] = gen_email
                else:
                    # Bootstrap from existing with slight mutation
                    pick_existing = self._sample_with_weights(col_vals) if col_vals else None
                    def gen_email(_row):
                        if pick_existing and random.random() < 0.7:
                            return pick_existing()
                        local = f"user{random.randint(1000,9999)}"
                        return f"{local}@{dom_pick()}"
                    gens[name] = gen_email
                continue

            # Phone
            if any(k in lower for k in ["phone", "mobile", "cell", "telephone"]):
                # learn most common mask
                mask = self._most_common_format([s for s in col_strs if re.search(r"\d", s)])
                def gen_phone(_row):
                    # replace every 'D' with digits while preserving separators
                    out = []
                    for ch in mask:
                        if ch == "D":
                            out.append(str(random.randint(0, 9)))
                        else:
                            out.append(ch)
                    return "".join(out)
                gens[name] = gen_phone
                continue

            # Date / datetime
            if "date" in lower or "dob" in lower or "dt" in lower:
                # parseable dates -> get min/max
                parsed = []
                for s in col_strs:
                    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d %Y", "%d-%b-%Y"):
                        try:
                            parsed.append(datetime.strptime(s, fmt))
                            break
                        except Exception:
                            continue
                if parsed:
                    dmin, dmax = min(parsed), max(parsed)
                else:
                    dmax = datetime.today()
                    dmin = dmax - timedelta(days=3650)  # 10 years
                delta = (dmax - dmin).days or 365

                # choose an output format based on most common sample
                fmts = Counter()
                for s in col_strs:
                    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
                        try:
                            datetime.strptime(s, fmt)
                            fmts[fmt] += 1
                        except Exception:
                            pass
                out_fmt = fmts.most_common(1)[0][0] if fmts else "%Y-%m-%d"

                def gen_date(_row):
                    rd = dmin + timedelta(days=random.randint(0, max(1, delta)))
                    return rd.strftime(out_fmt)
                gens[name] = gen_date
                continue

            # Amounts / currency / numeric
            looks_numeric = 0
            for v in col_vals[: min(100, len(col_vals))]:
                if self._clean_float(v) is not None:
                    looks_numeric += 1
            if looks_numeric >= max(5, int(0.6 * max(1, len(col_vals)))) or any(
                k in lower for k in ["amount", "balance", "score", "qty", "quantity", "count", "loan"]
            ):
                # learn prefix/suffix (e.g., $ and decimals)
                sample_str = next((s for s in col_strs if re.search(r"\d", s)), "")
                prefix = ""
                suffix = ""
                m_prefix = re.match(r"^\s*([^\d\-+]*)", sample_str)
                m_suffix = re.search(r"([^\d]*)\s*$", sample_str)
                if m_prefix:
                    prefix = m_prefix.group(1).strip()
                if m_suffix:
                    suffix = m_suffix.group(1).strip()
                # decimals
                decimals = 2 if re.search(r"\d+\.\d{2}", sample_str) else 0

                nums = [self._clean_float(v) for v in col_vals]
                nums = [x for x in nums if x is not None]
                if nums:
                    mu = float(pd.Series(nums).mean())
                    sd = float(pd.Series(nums).std(ddof=0) or 1.0)
                    mn = min(nums)
                    mx = max(nums)
                else:
                    mu, sd, mn, mx = 100.0, 30.0, 0.0, 1000.0

                def gen_num(_row):
                    # 70%: bootstrap from existing + tiny noise, 30%: truncated normal
                    if nums and random.random() < 0.7:
                        base = random.choice(nums)
                        noise = random.uniform(-0.05, 0.05) * (abs(base) + 1)
                        x = base + noise
                    else:
                        x = random.gauss(mu, sd)
                        x = min(max(x, mn), mx)
                    if decimals == 0:
                        x = int(round(x))
                    else:
                        x = round(x, decimals)
                    s = f"{x}"
                    if decimals and "." not in s:
                        s += "." + "0" * decimals
                    if prefix:
                        s = f"{prefix}{s}"
                    if suffix:
                        s = f"{s}{suffix}"
                    return s
                gens[name] = gen_num
                continue

            # Names (first/last/middle)
            if "first" in lower and "name" in lower:
                pool = [str(v).title() for v in col_vals if str(v).isalpha()] or [n.title() for n in low_name_lists["first"]]
                gens[name] = self._sample_with_weights(pool)
                continue
            if "last" in lower and "name" in lower:
                pool = [str(v).title() for v in col_vals if str(v).isalpha()] or [n.title() for n in low_name_lists["last"]]
                gens[name] = self._sample_with_weights(pool)
                continue
            if "middle" in lower and "name" in lower:
                # often initial
                initials = [str(v)[0].upper() for v in col_vals if isinstance(v, str) and v]
                if not initials:
                    initials = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                def gen_mid(_row):
                    return random.choice(initials)
                gens[name] = gen_mid
                continue

            # Address
            if "address" in lower:
                if col_vals:
                    # bootstrap with slight mutations: house number tweak
                    street_pool = [str(v) for v in col_vals]
                    pick = self._sample_with_weights(street_pool)
                    def gen_addr(_row):
                        s = pick()
                        m = re.match(r"\s*(\d+)(.*)", s)
                        if m and random.random() < 0.6:
                            base = int(m.group(1))
                            base = max(1, base + random.randint(-20, 20))
                            return f"{base}{m.group(2)}"
                        return s
                    gens[name] = gen_addr
                else:
                    def gen_addr(_row):
                        num = random.randint(10, 9999)
                        street = random.choice(low_name_lists["street"])
                        suf = random.choice(["St", "Ave", "Rd", "Blvd", "Ln", "Dr"])
                        return f"{num} {street} {suf}"
                    gens[name] = gen_addr
                continue

            # City/State/Zip quick heuristics
            if "city" in lower:
                pool = col_strs or low_name_lists["city"]
                gens[name] = self._sample_with_weights(pool)
                continue
            if "state" in lower and len(lower) <= 10:
                pool = col_strs or low_name_lists["state"]
                gens[name] = self._sample_with_weights(pool)
                continue
            if "zip" in lower or "postal" in lower:
                # keep 5-digit by default
                def gen_zip(_row):
                    return f"{random.randint(10000, 99999)}"
                gens[name] = gen_zip
                continue

            # Low-cardinality categorical -> weighted sampling
            unique_ratio = (len(set(col_vals)) / max(1, len(col_vals))) if col_vals else 0.0
            if col_vals and (len(set(col_vals)) <= 50 or unique_ratio <= 0.5):
                gens[name] = self._sample_with_weights(col_vals)
                continue

            # Fallback: bootstrap from existing or short random word
            if col_vals:
                pick = self._sample_with_weights(col_vals)
                gens[name] = lambda _row, p=pick: p()
            else:
                alphabet = "abcdefghijklmnopqrstuvwxyz"
                def gen_word(_row):
                    L = random.randint(5, 10)
                    return "".join(random.choice(alphabet) for _ in range(L))
                gens[name] = gen_word

        return gens

    # ──────────────────────────────────────────────────────────────────────
    # Synthetic data (realistic)
    # ──────────────────────────────────────────────────────────────────────
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

            # Build per-column generators conditioned on the uploaded data
            gens = self._build_generators(src_df, fields)

            # Generate row-by-row so fields can optionally depend on each other
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

    # ──────────────────────────────────────────────────────────────────────
    # Tasks runner
    # ──────────────────────────────────────────────────────────────────────
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

        threading.Thread(target=self._run_tasks_worker, args=(tasks,), daemon=True).start()

    def _load_tasks_from_file(self, path: str):
        text = open(path, "r", encoding="utf-8", errors="ignore").read().strip()
        if not text:
            return []

        # JSON first
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
                task = {k: v for k, v in it.items()}
                task["action"] = str(task["action"]).strip()
                out.append(task)
            return out
        except Exception:
            pass  # fall back to text

        # Plain-text lines: ACTION [arg]
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
                    if not p: raise ValueError("LoadFile requires 'path'")
                    text = open(p, "r", encoding="utf-8", errors="ignore").read()
                    self.headers, self.raw_data = detect_and_split_data(text)
                    wx.CallAfter(self._display, self.headers, self.raw_data)

                elif act in ("loads3", "loaduri"):
                    uri = t.get("uri") or t.get("path")
                    if not uri: raise ValueError("LoadS3/LoadURI requires 'uri'")
                    text = download_text_from_uri(uri)
                    self.headers, self.raw_data = detect_and_split_data(text)
                    wx.CallAfter(self._display, self.headers, self.raw_data)

                elif act in ("profile", "quality", "catalog", "compliance", "detectanomalies"):
                    name = {"detectanomalies": "Detect Anomalies"}.get(act, act.capitalize())
                    wx.CallAfter(self.do_analysis_process, name)

                elif act == "exportcsv":
                    p = t.get("path")
                    if not p: raise ValueError("ExportCSV requires 'path'")
                    wx.CallAfter(self._export_to_path, p, ",")

                elif act == "exporttxt":
                    p = t.get("path")
                    if not p: raise ValueError("ExportTXT requires 'path'")
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
                return

        wx.CallAfter(wx.MessageBox, f"Tasks completed. {ran} step(s) executed.", "Tasks", wx.OK | wx.ICON_INFORMATION)

    def _export_to_path(self, path: str, sep: str):
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                    for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=sep)
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Grid helpers + KPI updates
    # ──────────────────────────────────────────────────────────────────────
    def _display(self, hdr, data):
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        if not hdr:
            self.update_kpis([], [])
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

        self.update_kpis(hdr, data)

    def update_kpis(self, hdr, data):
        rows = len(data)
        cols = len(hdr)
        self.card_rows.SetValue(rows if rows else "0")
        self.card_cols.SetValue(cols if cols else "0")

        total_cells = rows * max(cols, 1)
        empty = 0
        if total_cells > 0:
            for r in data:
                for v in r:
                    if v is None or str(v).strip() == "":
                        empty += 1

        null_pct = (empty / total_cells * 100.0) if total_cells else 0.0
        self.card_nulls.SetValue(f"{null_pct:.1f}%")

        dq = max(0.0, 100.0 - null_pct)
        self.card_quality.SetValue(f"{dq:.1f}")

        completeness = 100.0 - null_pct
        self.card_complete.SetValue(f"{completeness:.1f}")

        anoms = 0
        if self.current_process.lower().startswith("detect"):
            anoms = rows
        else:
            lower_hdr = [str(h).lower() for h in hdr]
            if any(("anomaly" in h or "issue" in h or "error" in h) for h in lower_hdr):
                anoms = rows
        self.card_anoms.SetValue(str(anoms))

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
