# app/main_window.py
# Lavender UI + full functionality (MDM, Synthetic Data, Tasks, Knowledge Files)
# Catalog: SLA column, editable & persisted + catalog toolbar

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
# Kernel
# ──────────────────────────────────────────────────────────────────────────────

class KernelManager:
    def __init__(self, app_name="Data Genius — Sidecar Application"):
        self.lock = threading.Lock()
        self.dir = os.path.join(os.path.expanduser("~"), ".sidecar")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "kernel.json")
        os.environ["SIDECAR_KERNEL_PATH"] = self.path

        self.data = {
            "kernel_version": "1.0",
            "creator": "Salah Mokhayesh",
            "app": {
                "name": app_name,
                "modules": [
                    "Knowledge Files","Load File","Load from URI/S3",
                    "MDM","Synthetic Data","Rule Assignment",
                    "Profile","Quality","Detect Anomalies",
                    "Catalog","Compliance","Tasks",
                    "Export CSV","Export TXT","Upload to S3"
                ]
            },
            "stats": {"launch_count": 0},
            "state": {"last_dataset": None, "kpis": {}, "catalog_meta": {}},
            "events": []
        }
        self._load_or_init()
        self.increment_launch()

    def _load_or_init(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing.setdefault("kernel_version", "1.0")
                existing.setdefault("creator", "Salah Mokhayesh")
                existing.setdefault("app", self.data["app"])
                existing.setdefault("stats", {"launch_count": 0})
                existing.setdefault("state", {"last_dataset": None, "kpis": {}, "catalog_meta": {}})
                existing.setdefault("events", [])
                self.data = existing
            else:
                self._save()
        except Exception:
            self._save()

    def _save(self):
        with self.lock:
            try:
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
        evt = {"ts": datetime.utcnow().isoformat() + "Z", "type": event_type, "payload": payload}
        with self.lock:
            self.data.setdefault("events", []).append(evt)
        self._save()

    def set_last_dataset(self, columns, rows_count):
        with self.lock:
            self.data["state"]["last_dataset"] = {
                "rows": int(rows_count),
                "cols": int(len(columns or [])),
                "columns": list(columns or []),
            }
        self._save()

    def set_kpis(self, kpi_dict):
        with self.lock:
            self.data["state"]["kpis"] = dict(kpi_dict or {})
        self._save()


# ──────────────────────────────────────────────────────────────────────────────
# Custom controls (buttons, badges, pill)
# ──────────────────────────────────────────────────────────────────────────────

class RoundedShadowButton(wx.Control):
    def __init__(self, parent, label, handler, colour=wx.Colour(115, 102, 192), radius=12):
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
        self._font = wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self._padx, self._pady = 16, 8

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self._font)
        tw, th = dc.GetTextExtent(self._label)
        return wx.Size(tw + self._padx * 2, th + self._pady * 2)

    def _set_hover(self, v):
        self._hover = v
        self.Refresh()

    def on_down(self, _):
        self._down = True
        self.CaptureMouse()
        self.Refresh()

    def _invoke(self, evt):
        try:
            sig = inspect.signature(self._handler)
            if len(sig.parameters) == 0:
                self._handler()
            else:
                self._handler(evt)
        except Exception as e:
            import traceback
            wx.MessageBox(f"{self._label} failed:\n\n{e}\n\n{traceback.format_exc()}",
                          "Action error", wx.OK | wx.ICON_ERROR)

    def on_up(self, evt):
        if self.HasCapture():
            self.ReleaseMouse()
        was_down = self._down
        self._down = False
        self.Refresh()
        if was_down and self.GetClientRect().Contains(evt.GetPosition()):
            self._invoke(evt)

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg = self.GetParent().GetBackgroundColour()
        dc.SetBrush(wx.Brush(bg)); dc.SetPen(wx.Pen(bg)); dc.DrawRectangle(0, 0, w, h)

        base = self._colour
        if self._hover:
            base = wx.Colour(min(255, base.Red()+10), min(255, base.Green()+10), min(255, base.Blue()+10))
        if self._down:
            base = wx.Colour(max(0, base.Red()-20), max(0, base.Green()-20), max(0, base.Blue()-20))

        # shadow
        dc.SetBrush(wx.Brush(wx.Colour(0,0,0,60))); dc.SetPen(wx.Pen(wx.Colour(0,0,0,0)))
        dc.DrawRoundedRectangle(2, 3, w-4, h-3, self._radius+1)

        # pill
        dc.SetBrush(wx.Brush(base)); dc.SetPen(wx.Pen(base))
        dc.DrawRoundedRectangle(0, 0, w-2, h-2, self._radius)

        dc.SetTextForeground(wx.Colour(245,245,245))
        dc.SetFont(self._font)
        tw, th = dc.GetTextExtent(self._label)
        dc.DrawText(self._label, (w-tw)//2, (h-th)//2)

class LittleBuddyPill(wx.Control):
    def __init__(self, parent, label="Little Genius", handler=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label; self._handler = handler
        self._hover = False; self._down = False
        self._h = 40; self.SetMinSize((150, self._h))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)
        self._font = wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)

    def _set_hover(self, v): self._hover = v; self.Refresh()
    def on_down(self, _): self._down = True; self.CaptureMouse(); self.Refresh()

    def on_up(self, evt):
        if self.HasCapture(): self.ReleaseMouse()
        was = self._down; self._down = False; self.Refresh()
        if was and self.GetClientRect().Contains(evt.GetPosition()) and callable(self._handler):
            self._handler(evt)

    def on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        base1 = wx.Colour(132, 86, 255); base2 = wx.Colour(108, 66, 238)
        if self._hover: base1, base2 = wx.Colour(150,104,255), wx.Colour(126,84,242)
        if self._down:  base1, base2 = wx.Colour(112,76,236),  wx.Colour(92,54,220)

        r = (h-6)//2
        gc.SetPen(wx.NullPen)
        gc.SetBrush(gc.CreateLinearGradientBrush(0,0,0,h, base1, base2))
        gc.DrawRoundedRectangle(0,0,w,h,r)

        gc.SetFont(self._font, wx.Colour(255,255,255))
        tw, th = gc.GetTextExtent(self._label)
        gc.DrawText(self._label, 14, (h-th)//2)

class KPIBadge(wx.Panel):
    def __init__(self, parent, title, init_value="—"):
        super().__init__(parent)
        self.SetMinSize((120, 88))
        self._title = title; self._value = init_value
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)

    def SetValue(self, v): self._value = v; self.Refresh()

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w,h = self.GetClientSize()
        c1 = wx.Colour(247, 243, 255); c2 = wx.Colour(233, 225, 255)
        dc.GradientFillLinear(wx.Rect(0,0,w,h), c1, c2, wx.SOUTH)
        dc.SetPen(wx.Pen(wx.Colour(200,190,245))); dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRoundedRectangle(1,1,w-2,h-2,8)

        dc.SetTextForeground(wx.Colour(94, 64, 150))
        dc.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        dc.DrawText(self._title.upper(), 12, 10)

        dc.SetTextForeground(wx.Colour(44, 31, 72))
        dc.SetFont(wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        dc.DrawText(str(self._value), 12, 34)


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────

class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Data Genius — Sidecar Application", size=(1320, 840))

        # icon (best effort)
        for p in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "sidecar-01.ico"),
        ):
            if os.path.exists(p):
                try:
                    self.SetIcon(wx.Icon(p, wx.BITMAP_TYPE_ICO)); break
                except Exception:
                    pass

        self.kernel = KernelManager()
        self.kernel.log("app_started", version=self.kernel.data["kernel_version"])

        self.headers = []
        self.raw_data = []
        self.knowledge_files = []
        self.quality_rules = {}
        self.current_process = ""

        self.metrics = {
            "rows": None, "cols": None, "null_pct": None, "uniqueness": None,
            "dq_score": None, "validity": None, "completeness": None, "anomalies": None,
        }

        self._build_ui()
        self._ensure_kernel_in_knowledge()
        self.CenterOnScreen()
        self.Show()

    # UI
    def _build_ui(self):
        BG = wx.Colour(249, 246, 255)         # light lavender
        HEADER = wx.Colour(53, 29, 102)       # deep lavender
        PANEL = wx.Colour(248, 245, 255)

        self.SetBackgroundColour(BG)
        main = wx.BoxSizer(wx.VERTICAL)

        # Header bar: title (left) + Little Buddy (right)
        header = wx.Panel(self); header.SetBackgroundColour(HEADER)
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        title = wx.StaticText(header, label="Data Genius — Sidecar Application")
        title.SetForegroundColour(wx.Colour(255, 255, 255))
        title.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        hbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        hbox.AddStretchSpacer(1)
        self.little_pill = LittleBuddyPill(header, handler=self.on_little_buddy)
        hbox.Add(self.little_pill, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        header.SetSizer(hbox)
        main.Add(header, 0, wx.EXPAND)

        # Build both panels (toolbar and KPI) so we can add in swapped order
        # Buttons (toolbar)
        toolbar_panel = wx.Panel(self); toolbar_panel.SetBackgroundColour(PANEL)
        tb = wx.WrapSizer(wx.HORIZONTAL)
        def add_btn(label, handler):
            b = RoundedShadowButton(toolbar_panel, label, handler)
            tb.Add(b, 0, wx.ALL, 6); return b

        add_btn("Upload", self.on_load_file)
        add_btn("Profile", lambda e: self.do_analysis_process("Profile"))
        add_btn("Quality", lambda e: self.do_analysis_process("Quality"))
        add_btn("Catalog", lambda e: self.do_analysis_process("Catalog"))
        add_btn("Compliance", lambda e: self.do_analysis_process("Compliance"))
        add_btn("Anomalies", lambda e: self.do_analysis_process("Detect Anomalies"))
        add_btn("Rule Assignment", self.on_rules)
        add_btn("Knowledge Files", self.on_load_knowledge)
        add_btn("MDM", self.on_mdm)                    # renamed from Optimizer
        add_btn("Synthetic Data", self.on_generate_synth)  # new button
        add_btn("To Do", self.on_run_tasks)
        # NEW: Export button next to "To Do"
        add_btn("Export", self.on_export_csv)

        toolbar_panel.SetSizer(tb)

        # KPI bar
        kpi_panel = wx.Panel(self); kpi_panel.SetBackgroundColour(BG)
        krow = wx.BoxSizer(wx.HORIZONTAL)
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
            krow.Add(c, 1, wx.ALL | wx.EXPAND, 6)
        kpi_panel.SetSizer(krow)

        # SWAPPED ORDER: KPIs first (top), toolbar second (below)
        main.Add(kpi_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        main.Add(toolbar_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Knowledge files strip
        info_panel = wx.Panel(self); info_panel.SetBackgroundColour(wx.Colour(243, 239, 255))
        hz = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(info_panel, label="Knowledge Files:")
        lab.SetForegroundColour(wx.Colour(44,31,72))
        self.knowledge_lbl = wx.StaticText(info_panel, label="(none)")
        self.knowledge_lbl.SetForegroundColour(wx.Colour(94,64,150))
        hz.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        hz.Add(self.knowledge_lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        hz.AddStretchSpacer()
        info_panel.SetSizer(hz)
        main.Add(info_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # ── Catalog toolbar (hidden unless Catalog is active)
        self.catalog_toolbar_panel = wx.Panel(self)
        self.catalog_toolbar_panel.SetBackgroundColour(wx.Colour(243, 239, 255))
        ct = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_catalog_save  = RoundedShadowButton(self.catalog_toolbar_panel, "Save Catalog Edits", self.on_catalog_save)
        self.btn_catalog_reset = RoundedShadowButton(self.catalog_toolbar_panel, "Reset Catalog Edits", self.on_catalog_reset, colour=wx.Colour(160, 120, 200))
        ct.Add(self.btn_catalog_save, 0, wx.ALL, 6)
        ct.Add(self.btn_catalog_reset, 0, wx.ALL, 6)
        ct.AddStretchSpacer(1)
        self.catalog_toolbar_panel.SetSizer(ct)
        self.catalog_toolbar_panel.Hide()
        main.Add(self.catalog_toolbar_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

        # Grid
        grid_panel = wx.Panel(self); grid_panel.SetBackgroundColour(BG)
        self.grid = wx.grid.Grid(grid_panel); self.grid.CreateGrid(0, 0)
        self.grid.SetDefaultCellTextColour(wx.Colour(35, 31, 51))
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(255,255,255))
        self.grid.SetLabelTextColour(wx.Colour(60,60,90))
        self.grid.SetLabelBackgroundColour(wx.Colour(235,231,250))
        self.grid.SetGridLineColour(wx.Colour(220,214,245))
        self.grid.EnableEditing(False)  # default; enable only for Catalog
        self.grid.SetRowLabelSize(36); self.grid.SetColLabelSize(28)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self.on_cell_changed)

        gp = wx.BoxSizer(wx.VERTICAL); gp.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)
        grid_panel.SetSizer(gp)
        main.Add(grid_panel, 1, wx.EXPAND | wx.ALL, 4)

        # Menubar
        mb = wx.MenuBar()
        m_file = wx.Menu(); m_file.append(wx.ID_EXIT, "&Quit\tCtrl+Q"); mb.Append(m_file, "&File")
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)

        m_settings = wx.Menu(); OPEN_SETTINGS_ID = wx.NewIdRef()
        m_settings.Append(OPEN_SETTINGS_ID, "&Preferences...\tCtrl+,"); mb.Append(m_settings, "&Settings")
        self.Bind(wx.EVT_MENU, self.open_settings, id=OPEN_SETTINGS_ID)
        self.SetMenuBar(mb)

        self.SetSizer(main)

    # Knowledge helpers
    def _get_prioritized_knowledge(self):
        paths = []
        if self.kernel and os.path.exists(self.kernel.path):
            paths.append(self.kernel.path)
        for p in self.knowledge_files:
            if p != self.kernel.path:
                paths.append(p)
        return paths

    def _update_knowledge_label_and_env(self):
        names = ", ".join(os.path.basename(p) for p in self._get_prioritized_knowledge()) or "(none)"
        self.knowledge_lbl.SetLabel(names)
        prio = self._get_prioritized_knowledge()
        os.environ["SIDECAR_KNOWLEDGE_FILES"] = os.pathsep.join(prio)
        os.environ["SIDECAR_KNOWLEDGE_FIRST"] = "1"
        os.environ["SIDECAR_KERNEL_FIRST"] = "1"

    def _ensure_kernel_in_knowledge(self):
        try:
            if self.kernel and os.path.exists(self.kernel.path):
                if self.kernel.path not in self.knowledge_files:
                    self.knowledge_files.append(self.kernel.path)
                self._update_knowledge_label_and_env()
                self.kernel.log("kernel_loaded_as_knowledge", path=self.kernel.path)
        except Exception:
            pass

    # KPI
    def _reset_kpis_for_new_dataset(self, hdr, data):
        self.metrics.update({
            "rows": len(data), "cols": len(hdr),
            "null_pct": None, "uniqueness": None, "dq_score": None,
            "validity": None, "completeness": None, "anomalies": None,
        })
        self._render_kpis()
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
        self.kernel.set_kpis(self.metrics)

    # Utils
    @staticmethod
    def _as_df(rows, cols):
        df = pd.DataFrame(rows, columns=cols)
        return df.map(lambda x: None if (x is None or (isinstance(x, str) and x.strip() == "")) else x)

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
                try: compiled[k] = re.compile(str(v))
                except Exception: compiled[k] = re.compile(".*")
        return compiled

    def _compute_quality_metrics(self, df: pd.DataFrame):
        total_cells = df.shape[0] * max(1, df.shape[1])
        nulls = int(df.isna().sum().sum())
        completeness = (1.0 - (nulls / total_cells)) * 100.0 if total_cells else 0.0
        rules = self._compile_rules()
        checked = 0; valid = 0
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
        if validity is not None: components.append(validity)
        dq_score = sum(components) / len(components) if components else 0.0
        return completeness, validity, dq_score

    @staticmethod
    def _coerce_hdr_data(obj):
        if isinstance(obj, tuple) and len(obj) == 2:
            hdr, data = obj
            if isinstance(hdr, pd.DataFrame):
                df = hdr; return list(df.columns), df.values.tolist()
            if isinstance(hdr, (list, tuple)):
                return list(hdr), list(data)
        if isinstance(obj, pd.DataFrame):
            df = obj; return list(df.columns), df.values.tolist()
        return ["message"], [["Quality complete."]]

    # File & knowledge & rules
    def on_load_knowledge(self, _evt=None):
        dlg = wx.FileDialog(self, "Load knowledge files", wildcard="Text|*.txt;*.csv;*.tsv|All|*.*",
                            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK: return
        files = dlg.GetPaths(); dlg.Destroy()

        new_list = []
        if self.kernel and os.path.exists(self.kernel.path):
            new_list.append(self.kernel.path)
        new_list.extend(files)
        seen = set()
        self.knowledge_files = [x for x in new_list if not (x in seen or seen.add(x))]
        self._update_knowledge_label_and_env()
        self.kernel.log("load_knowledge_files",
                        count=len(self._get_prioritized_knowledge()),
                        files=[os.path.basename(p) for p in self._get_prioritized_knowledge()])

    def _load_text_file(self, path): return open(path, "r", encoding="utf-8", errors="ignore").read()

    def on_load_file(self, _evt=None):
        dlg = wx.FileDialog(self, "Open data file", wildcard="Data|*.csv;*.tsv;*.txt|All|*.*",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK: return
        path = dlg.GetPath(); dlg.Destroy()
        try:
            text = self._load_text_file(path)
            hdr, data = detect_and_split_data(text)
        except Exception as e:
            wx.MessageBox(f"Could not read file: {e}", "Error", wx.OK | wx.ICON_ERROR); return
        self.headers, self.raw_data = hdr, data
        self._display(hdr, data); self._reset_kpis_for_new_dataset(hdr, data)
        self.kernel.log("load_file", path=path, rows=len(data), cols=len(hdr))

    def on_rules(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load data first so fields are available.", "Quality Rules",
                          wx.OK | wx.ICON_WARNING); return
        try:
            dlg = QualityRuleDialog(self, list(self.headers), dict(self.quality_rules))
            if dlg.ShowModal() == wx.ID_OK:
                self.quality_rules = getattr(dlg, "current_rules", self.quality_rules)
                self.kernel.log("rules_updated", rules=self.quality_rules)
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Could not open Quality Rule Assignment:\n{e}",
                          "Quality Rules", wx.OK | wx.ICON_ERROR)

    # Settings & Buddy
    def open_settings(self, _evt=None):
        try:
            dlg = SettingsWindow(self); self.kernel.log("open_settings")
            if hasattr(dlg, "ShowModal"):
                dlg.ShowModal(); dlg.Destroy()
            else: dlg.Show()
        except Exception as e:
            wx.MessageBox(f"Could not open Settings:\n{e}", "Settings", wx.OK | wx.ICON_ERROR)

    def on_little_buddy(self, _evt=None):
        try:
            dlg = DataBuddyDialog(self)
            prio = self._get_prioritized_knowledge()
            os.environ["SIDECAR_KNOWLEDGE_FILES"] = os.pathsep.join(prio)
            os.environ["SIDECAR_KNOWLEDGE_FIRST"] = "1"
            os.environ["SIDECAR_KERNEL_FIRST"] = "1"
            if hasattr(dlg, "set_kernel"): dlg.set_kernel(self.kernel)
            elif hasattr(dlg, "kernel"):   setattr(dlg, "kernel", self.kernel)
            elif hasattr(dlg, "kernel_path"): setattr(dlg, "kernel_path", self.kernel.path)
            if hasattr(dlg, "set_knowledge_files"): dlg.set_knowledge_files(list(prio))
            else:
                setattr(dlg, "knowledge_files", list(prio))
                setattr(dlg, "priority_sources", list(prio))
                setattr(dlg, "knowledge_first", True)
            self.kernel.log("little_buddy_opened",
                            kernel_path=self.kernel.path,
                            knowledge_files=[os.path.basename(p) for p in prio])
            dlg.ShowModal(); dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Little Buddy failed to open:\n{e}", "Little Genius", wx.OK | wx.ICON_ERROR)

    # Synthetic data
    @staticmethod
    def _most_common_format(strings, default_mask="DDD-DDD-DDDD"):
        def mask_one(s): return re.sub(r"\d", "D", s)
        masks = [mask_one(s) for s in strings if isinstance(s, str)]
        return Counter(masks).most_common(1)[0][0] if masks else default_mask

    @staticmethod
    def _sample_with_weights(values):
        if not values: return lambda *_: None
        counts = Counter(values); vals, weights = zip(*counts.items())
        total = float(sum(weights)); probs = [w/total for w in weights]
        def pick(_row=None):
            r = random.random(); acc = 0.0
            for v, p in zip(vals, probs):
                acc += p
                if r <= acc: return v
            return vals[-1]
        return pick

    def _build_generators(self, src_df: pd.DataFrame, fields):
        gens = {}
        # simple realistic name pools
        first_names = ["Olivia","Liam","Emma","Noah","Ava","Oliver","Sophia","Elijah","Isabella","James",
                       "Amelia","William","Mia","Benjamin","Charlotte","Lucas","Harper","Henry","Evelyn","Alexander"]
        last_names = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
                      "Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin"]
        for col in fields:
            lower = col.lower()
            series = src_df[col] if col in src_df.columns else pd.Series([], dtype=object)
            col_vals = [v for v in series.tolist() if (v is not None and str(v).strip() != "")]
            col_strs = [str(v) for v in col_vals]
            if "email" in lower:
                domains = [s.split("@",1)[1].lower() for s in col_strs if "@" in s]
                dom = self._sample_with_weights(domains or ["gmail.com","yahoo.com","outlook.com","example.com"])
                pick = self._sample_with_weights(col_vals) if col_vals else None
                gens[col] = (lambda _row, p=pick, d=dom: (p() if p and random.random()<0.7 else f"user{random.randint(1000,9999)}@{d()}"))
                continue
            if any(k in lower for k in ["phone","mobile","cell","telephone"]):
                mask = self._most_common_format([s for s in col_strs if re.search(r"\d", s)])
                gens[col] = lambda _row, m=mask: "".join(str(random.randint(0,9)) if ch=="D" else ch for ch in m); continue
            if "first" in lower and "name" in lower:
                gens[col] = lambda _row, pool=first_names: random.choice(pool); continue
            if "last" in lower and "name" in lower:
                gens[col] = lambda _row, pool=last_names: random.choice(pool); continue
            if "date" in lower or "dob" in lower:
                dmax=datetime.today(); dmin=dmax-timedelta(days=3650); delta=(dmax-dmin).days or 365
                gens[col]=lambda _row, a=dmin, d=delta: (a+timedelta(days=random.randint(0, max(1,d)))).strftime("%Y-%m-%d"); continue
            uniq = set(col_vals)
            if uniq and len(uniq) <= 50:
                gens[col] = self._sample_with_weights(col_vals); continue
            if col_vals:
                pick = self._sample_with_weights(col_vals); gens[col]=lambda _r, p=pick: p()
            else:
                letters="abcdefghijklmnopqrstuvwxyz"
                gens[col]=lambda _r: "".join(random.choice(letters) for _ in range(random.randint(5,10)))
        return gens

    def on_generate_synth(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load data first to choose fields.", "No data", wx.OK | wx.ICON_WARNING)
            return
        src_df = pd.DataFrame(self.raw_data, columns=self.headers)
        try:
            dlg = SyntheticDataDialog(self, sample_df=src_df)
        except TypeError:
            dlg = SyntheticDataDialog(self, src_df)
        if hasattr(dlg, "ShowModal"):
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy(); return
        try:
            df = dlg.get_dataframe()
            if df is None or df.empty:
                n_rows = 100
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
            if hasattr(dlg, "Destroy"): dlg.Destroy()
            return
        if hasattr(dlg, "Destroy"): dlg.Destroy()
        hdr = list(df.columns); data = df.values.tolist()
        self.headers = hdr; self.raw_data = data
        self._display(hdr, data); self._reset_kpis_for_new_dataset(hdr, data)
        self.kernel.log("synthetic_generated", rows=len(data), cols=len(hdr), fields=hdr)

    # MDM helpers and action
    @staticmethod
    def _find_col(cols, *cands):
        cl = {c.lower(): c for c in cols}
        for cand in cands:
            for c in cl:
                if cand in c:
                    return cl[c]
        return None

    @staticmethod
    def _norm_email(x): return str(x).strip().lower() if x is not None else None
    @staticmethod
    def _norm_phone(x):
        if x is None: return None
        digits = re.sub(r"\D+", "", str(x))
        if len(digits) >= 10: return digits[-10:]
        return digits or None
    @staticmethod
    def _norm_name(x):  return re.sub(r"[^a-z]", "", str(x).lower()) if x is not None else None
    @staticmethod
    def _norm_text(x):  return re.sub(r"\s+", " ", str(x).strip().lower()) if x is not None else None

    @staticmethod
    def _sim(a, b):
        if not a or not b: return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _block_key(self, row, cols):
        e = row.get(cols.get("email"))
        if e: return f"e:{self._norm_email(e)}"
        p = row.get(cols.get("phone"))
        if p: return f"p:{self._norm_phone(p)}"
        fi = (row.get(cols.get("first")) or "")[:1].lower()
        li = (row.get(cols.get("last")) or "")[:1].lower()
        zipc = str(row.get(cols.get("zip")) or "")[:3]
        city = str(row.get(cols.get("city")) or "")[:3].lower()
        return f"n:{fi}{li}|{zipc or city}"

    def _score_pair(self, a, b, cols, use_email, use_phone, use_name, use_addr):
        parts=[]; weights=[]
        if use_email and cols.get("email"):
            ea=self._norm_email(a.get(cols["email"])); eb=self._norm_email(b.get(cols["email"]))
            if ea and eb: parts.append(1.0 if ea==eb else self._sim(ea,eb)); weights.append(0.5)
        if use_phone and cols.get("phone"):
            pa=self._norm_phone(a.get(cols["phone"])); pb=self._norm_phone(b.get(cols["phone"]))
            if pa and pb: parts.append(1.0 if pa==pb else self._sim(pa,pb)); weights.append(0.5)
        if use_name and (cols.get("first") or cols.get("last")):
            fa=self._norm_name(a.get(cols.get("first"))); fb=self._norm_name(b.get(cols.get("first")))
            la=self._norm_name(a.get(cols.get("last")));  lb=self._norm_name(b.get(cols.get("last")))
            if fa and fb: parts.append(self._sim(fa,fb)); weights.append(0.25)
            if la and lb: parts.append(self._sim(la,lb)); weights.append(0.3)
        if use_addr and (cols.get("addr") or cols.get("city")):
            aa=self._norm_text(a.get(cols.get("addr"))); ab=self._norm_text(b.get(cols.get("addr")))
            ca=self._norm_text(a.get(cols.get("city"))); cb=self._norm_text(b.get(cols.get("city")))
            sa=self._norm_text(a.get(cols.get("state"))); sb=self._norm_text(b.get(cols.get("state")))
            za=self._norm_text(a.get(cols.get("zip")));   zb=self._norm_text(b.get(cols.get("zip")))
            chunk=[]
            if aa and ab: chunk.append(self._sim(aa,ab))
            if ca and cb: chunk.append(self._sim(ca,cb))
            if sa and sb: chunk.append(self._sim(sa,sb))
            if za and zb: chunk.append(1.0 if za==zb else self._sim(za,zb))
            if chunk: parts.append(sum(chunk)/len(chunk)); weights.append(0.25)
        if not parts: return 0.0
        wsum = sum(weights) or 1.0
        return sum(p*w for p,w in zip(parts,weights))/wsum

    def _run_mdm(self, dataframes, use_email=True, use_phone=True, use_name=True, use_addr=True, threshold=0.85):
        datasets=[]; union_cols=set()
        for df in dataframes:
            cols=list(df.columns)
            colmap={
                "email": self._find_col(cols,"email"),
                "phone": self._find_col(cols,"phone","mobile","cell","telephone"),
                "first": self._find_col(cols,"first name","firstname","given"),
                "last":  self._find_col(cols,"last name","lastname","surname","family"),
                "addr":  self._find_col(cols,"address","street"),
                "city":  self._find_col(cols,"city"),
                "state": self._find_col(cols,"state","province","region"),
                "zip":   self._find_col(cols,"zip","postal"),
            }
            union_cols.update(cols)
            datasets.append((df.reset_index(drop=True), colmap))

        records=[]; offset=0
        for df,colmap in datasets:
            for i in range(len(df)):
                records.append((offset+i, df.iloc[i].to_dict(), colmap))
            offset += len(df)

        parent={}
        def find(x):
            parent.setdefault(x,x)
            if parent[x]!=x: parent[x]=find(parent[x])
            return parent[x]
        def union(a,b):
            ra,rb = find(a),find(b)
            if ra!=rb: parent[rb]=ra

        blocks=defaultdict(list)
        for rec_id,row,cmap in records:
            key=self._block_key(row,cmap)
            blocks[(key, tuple(sorted(cmap.items())) )].append((rec_id,row,cmap))

        for _, members in blocks.items():
            n=len(members)
            if n<=1: continue
            for i in range(n):
                for j in range(i+1,n):
                    id_a,row_a,cmap_a = members[i]
                    id_b,row_b,cmap_b = members[j]
                    cols={k: cmap_a.get(k) or cmap_b.get(k) for k in ("email","phone","first","last","addr","city","state","zip")}
                    score=self._score_pair(row_a,row_b,cols,use_email,use_phone,use_name,use_addr)
                    if score>=threshold: union(id_a,id_b)

        clusters=defaultdict(list)
        for rec_id,row,cmap in records:
            clusters[find(rec_id)].append((row,cmap))

        def best_value(values):
            vals=[v for v in values if (v is not None and str(v).strip()!="")]
            if not vals: return ""
            parsed=[]
            for v in vals:
                s=str(v)
                for fmt in ("%Y-%m-%d","%m/%d/%Y","%d/%m/%Y","%Y/%m/%d"):
                    try:
                        parsed.append(datetime.strptime(s,fmt)); break
                    except: pass
            if parsed and len(parsed)>=len(vals)*0.6:
                return max(parsed).strftime("%Y-%m-%d")
            nums=pd.to_numeric(pd.Series(vals).astype(str).str.replace(",",""), errors="coerce").dropna()
            if len(nums)>=len(vals)*0.6:
                med=float(nums.median()); return str(int(med)) if med.is_integer() else f"{med:.2f}"
            counts=Counter([str(v).strip() for v in vals])
            top,freq=counts.most_common(1)[0]
            ties=[k for k,c in counts.items() if c==freq]
            return ties[0] if len(ties)==1 else max(ties, key=len)

        all_cols=list(sorted(union_cols, key=lambda x: x.lower()))
        golden=[]
        for cluster_rows in clusters.values():
            merged={col: best_value([r.get(col) for r,_ in cluster_rows]) for col in all_cols}
            golden.append(merged)
        return pd.DataFrame(golden, columns=all_cols)

    def on_mdm(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load a base dataset first (or generate synthetic data).",
                          "MDM", wx.OK | wx.ICON_WARNING); return

        dlg = MDMDialog(self)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        params = dlg.get_params(); dlg.Destroy()

        dataframes=[]
        if params["include_current"]():
            dataframes.append(pd.DataFrame(self.raw_data, columns=self.headers))
        try:
            for src in params["sources"]:
                if src["type"]=="file":
                    text = self._load_text_file(src["value"])
                    hdr,data = detect_and_split_data(text)
                else:
                    text = download_text_from_uri(src["value"])
                    hdr,data = detect_and_split_data(text)
                dataframes.append(pd.DataFrame(data, columns=hdr))
        except Exception as e:
            wx.MessageBox(f"Failed to load a source:\n{e}", "MDM", wx.OK | wx.ICON_ERROR); return

        if len(dataframes) < 2:
            wx.MessageBox("Please add at least one additional dataset.", "MDM",
                          wx.OK | wx.ICON_WARNING); return

        try:
            golden = self._run_mdm(
                dataframes,
                use_email=params["use_email"],
                use_phone=params["use_phone"],
                use_name=params["use_name"],
                use_addr=params["use_addr"],
                threshold=params["threshold"],
            )
        except Exception as e:
            import traceback
            wx.MessageBox(f"MDM failed:\n{e}\n\n{traceback.format_exc()}",
                          "MDM", wx.OK | wx.ICON_ERROR); return

        hdr = list(golden.columns); data = golden.astype(str).values.tolist()
        self.headers, self.raw_data = hdr, data
        self._display(hdr, data); self._reset_kpis_for_new_dataset(hdr, data)
        self.current_process = "MDM"
        self._show_catalog_toolbar(False)
        self.kernel.log("mdm_completed", golden_rows=len(data), golden_cols=len(hdr), params=params)

    # Catalog metadata persistence helpers
    def _load_catalog_meta(self):
        try:
            return dict(self.kernel.data.get("state", {}).get("catalog_meta", {}))
        except Exception:
            return {}

    def _save_catalog_meta(self, meta: dict):
        try:
            self.kernel.data.setdefault("state", {})["catalog_meta"] = dict(meta)
            self.kernel._save()
        except Exception:
            pass

    def _apply_catalog_meta_to_table(self, hdr, data):
        # Ensure SLA column exists (insert before 'Example' when possible)
        if "SLA" not in hdr:
            insert_at = hdr.index("Example") if "Example" in hdr else len(hdr)
            hdr = list(hdr[:insert_at]) + ["SLA"] + list(hdr[insert_at:])
            for r in range(len(data)):
                data[r] = list(data[r][:insert_at]) + ["" ] + list(data[r][insert_at:])

        col_idx = {name: i for i, name in enumerate(hdr)}
        meta = self._load_catalog_meta()

        if "Field" in col_idx:
            f_idx = col_idx["Field"]
            for r in range(len(data)):
                row = list(data[r])
                field_name = str(row[f_idx]).strip()
                if not field_name:
                    data[r] = row
                    continue
                saved = meta.get(field_name, {})
                for key in ("Friendly Name", "Description", "Data Type", "Nullable", "SLA"):
                    if key in col_idx and key in saved:
                        row[col_idx[key]] = saved[key]
                data[r] = row

        return hdr, data

    # Catalog toolbar show/hide
    def _show_catalog_toolbar(self, show: bool):
        if show:
            self.catalog_toolbar_panel.Show()
        else:
            self.catalog_toolbar_panel.Hide()
        self.Layout()

    # Save visible grid rows to catalog persistence (for editable columns)
    def _snapshot_grid_to_meta(self):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        try:
            f_idx = hdr.index("Field")
        except ValueError:
            return
        editable = {"Friendly Name", "Description", "Data Type", "Nullable", "SLA"}
        col_idx = {name: i for i, name in enumerate(hdr)}
        meta = self._load_catalog_meta()

        for r in range(self.grid.GetNumberRows()):
            field_name = self.grid.GetCellValue(r, f_idx).strip()
            if not field_name:
                continue
            meta.setdefault(field_name, {})
            for name in editable:
                if name in col_idx:
                    meta[field_name][name] = self.grid.GetCellValue(r, col_idx[name])

        self._save_catalog_meta(meta)

    def on_catalog_save(self, _evt=None):
        if self.current_process != "Catalog":
            return
        self._snapshot_grid_to_meta()
        wx.MessageBox("Catalog edits saved.", "Catalog", wx.OK | wx.ICON_INFORMATION)

    def on_catalog_reset(self, _evt=None):
        if self.current_process != "Catalog":
            return
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        try:
            f_idx = hdr.index("Field")
        except ValueError:
            return
        meta = self._load_catalog_meta()
        for r in range(self.grid.GetNumberRows()):
            field_name = self.grid.GetCellValue(r, f_idx).strip()
            if field_name in meta:
                del meta[field_name]
        self._save_catalog_meta(meta)
        self.do_analysis_process("Catalog")

    # Analyses
    def do_analysis_process(self, proc_name: str):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING); return

        self.current_process = proc_name
        df = self._as_df(self.raw_data, self.headers)

        if proc_name == "Profile":
            try:
                out = profile_analysis(df)
                hdr, data = self._coerce_hdr_data(out)
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
            self.grid.EnableEditing(False)
            self._show_catalog_toolbar(False)
            self.kernel.log("run_profile", null_pct=null_pct, uniqueness=uniq_pct)

        elif proc_name == "Quality":
            try:
                out = quality_analysis(df, self.quality_rules)
                hdr, data = self._coerce_hdr_data(out)
            except Exception:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows = []
                for c in df.columns:
                    comp = 100.0 - df[c].isna().mean()*100.0
                    uniq = df[c].nunique(dropna=True)
                    num = pd.to_numeric(df[c], errors="coerce")
                    validity = 100.0 if num.notna().mean() > 0.8 else None
                    qs = comp if validity is None else (comp + validity)/2.0
                    rows.append([c, len(df), f"{comp:.1f}", uniq,
                                 f"{validity:.1f}" if validity is not None else "—",
                                 f"{qs:.1f}", now])
                hdr = ["Field", "Total", "Completeness (%)", "Unique Values",
                       "Validity (%)", "Quality Score (%)", "Analysis Date"]
                data = rows
            completeness, validity, dq = self._compute_quality_metrics(df)
            self.metrics["completeness"] = completeness
            self.metrics["validity"] = validity
            self.metrics["dq_score"] = dq
            self._render_kpis()
            self.grid.EnableEditing(False)
            self._show_catalog_toolbar(False)
            self.kernel.log("run_quality", completeness=completeness, validity=validity, dq_score=dq)

        elif proc_name == "Detect Anomalies":
            try:
                work, count = self._detect_anomalies(df)
                hdr, data = list(work.columns), work.values.tolist()
            except Exception:
                hdr, data = list(df.columns), df.values.tolist(); count = 0
            self.metrics["anomalies"] = count
            self._render_kpis()
            self.grid.EnableEditing(False)
            self._show_catalog_toolbar(False)
            self.kernel.log("run_detect_anomalies", anomalies=count)

        elif proc_name == "Catalog":
            try:
                out = catalog_analysis(df)
                hdr, data = self._coerce_hdr_data(out)
            except Exception:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows = []
                for c in df.columns:
                    sample = next((str(v) for v in df[c].dropna().head(1).tolist()), "")
                    dtype = "Numeric" if pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.8 else "Text"
                    nullable = "Yes" if df[c].isna().mean() > 0 else "No"
                    friendly = c.replace("_", " ").title()
                    desc = f"{friendly} for each record."
                    rows.append([c, friendly, desc, dtype, nullable, sample, now])
                hdr = ["Field", "Friendly Name", "Description", "Data Type", "Nullable", "Example", "Analysis Date"]
                data = rows

            hdr, data = self._apply_catalog_meta_to_table(hdr, data)

            self.kernel.log("run_catalog", columns=len(hdr))
            self.grid.EnableEditing(True)
            self._show_catalog_toolbar(True)

        elif proc_name == "Compliance":
            try:
                out = compliance_analysis(df)
                hdr, data = self._coerce_hdr_data(out)
            except Exception:
                hdr = ["message"]; data = [["Compliance check complete."]]
            self.grid.EnableEditing(False)
            self._show_catalog_toolbar(False)
            self.kernel.log("run_compliance")

        else:
            hdr, data = ["message"], [[f"Unknown process: {proc_name}"]]
            self.grid.EnableEditing(False)
            self._show_catalog_toolbar(False)

        self._display(hdr, data)

    # Robust anomaly detector
    def _detect_anomalies(self, df: pd.DataFrame):
        work = df.copy()

        def parse_number(x):
            if x is None: return None
            s = str(x).strip()
            if s == "": return None
            neg = False
            if s.startswith("(") and s.endswith(")"):
                neg = True; s = s[1:-1]
            is_percent = s.endswith("%")
            s = s.replace("$","").replace(",","").replace("%","").strip()
            if re.fullmatch(r"[-+]?\d*\.?\d+", s):
                v = float(s); v = -v if neg else v
                if is_percent: v = v / 100.0
                return v
            return None

        numeric_cols=[]
        for c in work.columns:
            col_str = work[c].astype(str)
            dash_ratio = col_str.str.contains(r"[-()]+").mean()
            digit_median = col_str.str.findall(r"\d").map(len).median() if len(col_str) else 0
            phone_like = dash_ratio > 0.5 and digit_median >= 9
            vals = work[c].map(parse_number)
            ratio = vals.notna().mean()
            if ratio >= 0.60 and not phone_like:
                numeric_cols.append((c, vals.astype(float)))

        flags = pd.Series(False, index=work.index)
        reasons = [[] for _ in range(len(work))]
        pos_map = {idx: i for i, idx in enumerate(work.index)}

        for cname, x in numeric_cols:
            s = x.dropna()
            if s.size < 5: continue
            mu = s.mean(); sd = s.std(ddof=0)
            q1 = s.quantile(0.25); q3 = s.quantile(0.75); iqr = q3-q1
            lo = q1 - 1.5*iqr if iqr else None; hi = q3 + 1.5*iqr if iqr else None
            p01 = s.quantile(0.01) if len(s)>=50 else None
            p99 = s.quantile(0.99) if len(s)>=50 else None
            mostly_nonneg = (s.ge(0).mean() >= 0.95)
            mostly_nonzero = (s.ne(0).mean() >= 0.95)

            zhits = pd.Series(False, index=x.index)
            if sd and sd != 0:
                z = (x - mu).abs() / sd
                zhits = z > 3.0
            iqr_hits = pd.Series(False, index=x.index)
            if lo is not None and hi is not None:
                iqr_hits = (x < lo) | (x > hi)
            q_hits = pd.Series(False, index=x.index)
            if p01 is not None and p99 is not None:
                q_hits = (x < p01) | (x > p99)
            neg_hits = pd.Series(False, index=x.index)
            if mostly_nonneg: neg_hits = x < 0
            zero_hits = pd.Series(False, index=x.index)
            if mostly_nonzero: zero_hits = x == 0

            hits = (zhits.fillna(False) | iqr_hits.fillna(False) |
                    q_hits.fillna(False) | neg_hits.fillna(False) | zero_hits.fillna(False))
            flags = flags | hits.fillna(False)
            for idx, is_hit in hits.fillna(False).items():
                if is_hit:
                    bits=[]
                    if bool(zhits.get(idx, False)): bits.append("z>3")
                    if bool(iqr_hits.get(idx, False)): bits.append("IQR")
                    if bool(q_hits.get(idx, False)): bits.append("P1/P99")
                    if bool(neg_hits.get(idx, False)): bits.append("neg")
                    if bool(zero_hits.get(idx, False)): bits.append("zero")
                    reasons[pos_map[idx]].append(f"{cname} {'/'.join(bits)}")

        work["__anomaly__"] = ["; ".join(r) if r else "" for r in reasons]
        return work, int(flags.sum())

    # Tasks / export / upload
    def on_run_tasks(self, _evt=None):
        dlg = wx.FileDialog(self, "Open Tasks File",
                            wildcard="Tasks (*.json;*.txt)|*.json;*.txt|All|*.*",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        path = dlg.GetPath(); dlg.Destroy()

        try:
            tasks = self._load_tasks_from_file(path)
        except Exception as e:
            wx.MessageBox(f"Could not read tasks file:\n{e}", "Tasks", wx.OK | wx.ICON_ERROR); return
        self.kernel.log("tasks_started", path=path, steps=len(tasks))
        threading.Thread(target=self._run_tasks_worker, args=(tasks,), daemon=True).start()

    def _load_tasks_from_file(self, path: str):
        text = open(path, "r", encoding="utf-8", errors="ignore").read().strip()
        if not text: return []
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

        tasks=[]
        for line in text.splitlines():
            line=line.strip()
            if not line or line.startswith("#"): continue
            parts=line.split(maxsplit=1)
            action=parts[0]; arg=parts[1] if len(parts)==2 else None
            t={"action": action}
            if arg:
                if action.lower() in ("loadfile","exportcsv","exporttxt"):
                    t["path"]=arg
                elif action.lower() in ("loads3","loaduri"):
                    t["uri"]=arg
                else:
                    t["arg"]=arg
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
                    text = self._load_text_file(p)
                    self.headers, self.raw_data = detect_and_split_data(text)
                    wx.CallAfter(self._display, self.headers, self.raw_data)
                    wx.CallAfter(self._reset_kpis_for_new_dataset, self.headers, self.raw_data)

                elif act in ("loads3", "loaduri"):
                    uri = t.get("uri") or t.get("path")
                    if not uri: raise ValueError("LoadS3/LoadURI requires 'uri'")
                    text = download_text_from_uri(uri)
                    self.headers, self.raw_data = detect_and_split_data(text)
                    wx.CallAfter(self._display, self.headers, self.raw_data)
                    wx.CallAfter(self._reset_kpis_for_new_dataset, self.headers, self.raw_data)

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
                wx.CallAfter(wx.MessageBox, f"Tasks stopped at step {i}:\n{t}\n\n{e}",
                             "Tasks", wx.OK | wx.ICON_ERROR)
                self.kernel.log("tasks_failed", step=i, action=t.get("action"), error=str(e))
                return

        self.kernel.log("tasks_completed", steps=ran)
        wx.CallAfter(wx.MessageBox, f"Tasks completed. {ran} step(s) executed.",
                     "Tasks", wx.OK | wx.ICON_INFORMATION)

    def _export_to_path(self, path: str, sep: str):
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                    for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=sep)
            self.kernel.log("export_to_path", path=path, sep=sep, rows=len(data), cols=len(hdr))
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    # NEW: one-click CSV export from the toolbar
    def on_export_csv(self, _evt=None):
        if self.grid.GetNumberCols() == 0:
            wx.MessageBox("There is nothing to export yet.", "Export", wx.OK | wx.ICON_INFORMATION)
            return
        dlg = wx.FileDialog(
            self,
            "Export current results to CSV",
            wildcard="CSV files (*.csv)|*.csv|All files (*.*)|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        path = dlg.GetPath()
        dlg.Destroy()
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self._export_to_path(path, ",")

    def on_upload_s3(self, _evt=None):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
        try:
            msg = upload_to_s3(self.current_process or "Unknown", hdr, data)
            wx.MessageBox(msg, "Upload", wx.OK | wx.ICON_INFORMATION)
            self.kernel.log("upload_s3", rows=len(data), cols=len(hdr), process=self.current_process or "Unknown")
        except Exception as e:
            wx.MessageBox(f"Upload failed: {e}", "Upload", wx.OK | wx.ICON_ERROR)

    # Grid events/presentation
    def on_cell_changed(self, evt):
        # Persist Catalog edits
        if self.current_process == "Catalog":
            try:
                row = evt.GetRow()
                col = evt.GetCol()
                hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
                col_name = hdr[col]
                if col_name not in {"Friendly Name", "Description", "Data Type", "Nullable", "SLA"}:
                    evt.Skip(); return
                try:
                    f_idx = hdr.index("Field")
                except ValueError:
                    evt.Skip(); return
                field_name = self.grid.GetCellValue(row, f_idx).strip()
                new_val = self.grid.GetCellValue(row, col)
                if not field_name:
                    evt.Skip(); return
                meta = self._load_catalog_meta()
                meta.setdefault(field_name, {})
                meta[field_name][col_name] = new_val
                self._save_catalog_meta(meta)
            finally:
                evt.Skip()
        else:
            evt.Skip()

    def _display(self, hdr, data):
        # allow pd.DataFrame too
        if isinstance(hdr, pd.DataFrame):
            df = hdr; hdr = list(df.columns); data = df.values.tolist()
        if isinstance(hdr, tuple) and len(hdr) == 2:
            hdr, data = hdr

        self.grid.ClearGrid()
        if self.grid.GetNumberRows(): self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols(): self.grid.DeleteCols(0, self.grid.GetNumberCols())

        if not isinstance(hdr, (list, tuple)) or len(hdr) == 0:
            self._render_kpis()
            self._show_catalog_toolbar(False)
            return

        self.grid.AppendCols(len(hdr))
        for i, h in enumerate(hdr): self.grid.SetColLabelValue(i, str(h))
        self.grid.AppendRows(len(data))

        try: anom_idx = hdr.index("__anomaly__")
        except ValueError: anom_idx = -1

        for r, row in enumerate(data):
            row_has_anom = False
            if anom_idx >= 0 and anom_idx < len(row):
                row_has_anom = bool(str(row[anom_idx]).strip())
            for c, val in enumerate(row):
                self.grid.SetCellValue(r, c, "" if val is None else str(val))
                base = wx.Colour(255,255,255) if r%2==0 else wx.Colour(248,246,255)
                if row_has_anom: base = wx.Colour(255,235,238)
                self.grid.SetCellBackgroundColour(r, c, base)

        self.adjust_grid(); self._render_kpis()
        self.grid.EnableEditing(self.current_process == "Catalog")

    def adjust_grid(self):
        cols = self.grid.GetNumberCols()
        if cols == 0: return
        total_w = self.grid.GetClientSize().GetWidth()
        usable = max(0, total_w - self.grid.GetRowLabelSize())
        w = max(80, usable // cols)
        for c in range(cols): self.grid.SetColSize(c, w)

    def on_grid_resize(self, event):
        event.Skip(); wx.CallAfter(self.adjust_grid)


# ──────────────────────────────────────────────────────────────────────────────
# MDM dialog used above (kept here to keep file self-contained)
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
        btn_rm  = wx.Button(panel, label="Remove Selected")
        btns.Add(btn_add, 0, wx.RIGHT, 6)
        btns.Add(btn_uri, 0, wx.RIGHT, 6)
        btns.Add(btn_rm, 0)
        v.Add(btns, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        grid = wx.FlexGridSizer(2,2,6,6); grid.AddGrowableCol(1,1)
        grid.Add(wx.StaticText(panel, label="Match threshold (percent):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spn_thresh = wx.SpinCtrl(panel, min=50, max=100, initial=85)
        grid.Add(self.spn_thresh, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Fields to match on:"), 0, wx.ALIGN_CENTER_VERTICAL)
        h = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_email = wx.CheckBox(panel, label="Email")
        self.chk_phone = wx.CheckBox(panel, label="Phone")
        self.chk_name  = wx.CheckBox(panel, label="Name")
        self.chk_addr  = wx.CheckBox(panel, label="Address")
        for c in (self.chk_email, self.chk_phone, self.chk_name, self.chk_addr):
            c.SetValue(True); h.Add(c, 0, wx.RIGHT, 8)
        grid.Add(h, 0, wx.EXPAND)
        v.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        v.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 6)
        okc = wx.StdDialogButtonSizer(); ok = wx.Button(panel, wx.ID_OK); ca = wx.Button(panel, wx.ID_CANCEL)
        okc.AddButton(ok); okc.AddButton(ca); okc.Realize()
        v.Add(okc, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

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
        for i in reversed(self.lst.GetSelections()):
            self.lst.Delete(i)
            del self.sources[i]

    def get_params(self):
        return {
            "include_current": self.chk_include_current.GetValue,
            "threshold": self.spn_thresh.GetValue() / 100.0,
            "use_email": self.chk_email.GetValue(),
            "use_phone": self.chk_phone.GetValue(),
            "use_name": self.chk_name.GetValue(),
            "use_addr": self.chk_addr.GetValue(),
            "sources": list(self.sources),
        }


if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
