# app/main_window.py
import os
import re
import json
from datetime import datetime
import threading

import wx
import wx.grid as gridlib
try:
    import wx.adv as wxadv
except Exception:
    wxadv = None

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
# Theme (lavender)
# ──────────────────────────────────────────────────────────────────────────────
PURPLE        = wx.Colour(67, 38, 120)
PAGE_BG       = wx.Colour(245, 241, 251)
CARD_BG       = wx.Colour(255, 255, 255)
CARD_EDGE     = wx.Colour(225, 221, 240)
TEXT_BODY     = wx.Colour(35, 35, 55)
TEXT_MUTED    = wx.Colour(92, 92, 120)
GAUGE_BLUE    = wx.Colour(110, 130, 255)

def _font(size=9, bold=False):
    return wx.Font(
        size,
        wx.FONTFAMILY_SWISS,
        wx.FONTSTYLE_NORMAL,
        wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL,
    )

# ──────────────────────────────────────────────────────────────────────────────
# Lightweight kernel state
# ──────────────────────────────────────────────────────────────────────────────
class KernelManager:
    def __init__(self, app_name="Data Buddy — Sidecar Application"):
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
                    "Knowledge Files", "Load File", "Load from URI/S3",
                    "MDM", "Synthetic Data", "Rule Assignment",
                    "Profile", "Quality", "Detect Anomalies",
                    "Catalog", "Compliance", "Tasks",
                    "Export CSV", "Export TXT", "Upload to S3"
                ]
            },
            "stats": {"launch_count": 0},
            "state": {"last_dataset": None, "kpis": {}},
            "events": [],
        }
        self._load_or_init()
        self._save()

    def _load_or_init(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    cur = json.load(f)
                for k, v in self.data.items():
                    cur.setdefault(k, v)
                self.data = cur
            except Exception:
                pass

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def set_last_dataset(self, columns, rows_count):
        self.data["state"]["last_dataset"] = {
            "rows": int(rows_count),
            "cols": int(len(columns or [])),
            "columns": list(columns or []),
        }
        self._save()

    def set_kpis(self, kpi_dict):
        self.data["state"]["kpis"] = dict(kpi_dict or {})
        self._save()

# ──────────────────────────────────────────────────────────────────────────────
# UI atoms: capsules / pill / KPI card
# ──────────────────────────────────────────────────────────────────────────────
class CapsuleButton(wx.Control):
    def __init__(self, parent, label, handler=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label
        self._handler = handler
        self._hover = False
        self._down = False
        self._padx, self._pady = 18, 10
        self.SetMinSize((96, 36))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)

    def _set_hover(self, v): self._hover = v; self.Refresh()
    def on_down(self, _):   self._down = True; self.CaptureMouse(); self.Refresh()

    def on_up(self, evt):
        if self.HasCapture(): self.ReleaseMouse()
        was_down = self._down
        self._down = False
        self.Refresh()
        if was_down and self.GetClientRect().Contains(evt.GetPosition()) and callable(self._handler):
            try:
                self._handler(evt)
            except TypeError:
                self._handler()

    def DoGetBestSize(self):
        dc = wx.ClientDC(self); dc.SetFont(_font(9, True))
        tw, th = dc.GetTextExtent(self._label)
        return wx.Size(tw + self._padx * 2, th + self._pady * 2)

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg = self.GetParent().GetBackgroundColour()
        dc.SetBrush(wx.Brush(bg)); dc.SetPen(wx.Pen(bg)); dc.DrawRectangle(0, 0, w, h)

        body = CARD_BG
        if self._hover: body = wx.Colour(250, 248, 255)
        if self._down:  body = wx.Colour(238, 233, 248)
        dc.SetBrush(wx.Brush(body))
        dc.SetPen(wx.Pen(CARD_EDGE))
        dc.DrawRoundedRectangle(0, 0, w, h, 14)

        dc.SetFont(_font(9, True)); dc.SetTextForeground(PURPLE)
        tw, th = dc.GetTextExtent(self._label)
        dc.DrawText(self._label, (w - tw)//2, (h - th)//2)

class LittleBuddyPill(wx.Control):
    def __init__(self, parent, label="Little Buddy", handler=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label
        self._handler = handler
        self._hover = False
        self._down = False
        self.SetMinSize((130, 36))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)

    def _set_hover(self, v): self._hover = v; self.Refresh()
    def on_down(self, _): self._down = True; self.CaptureMouse(); self.Refresh()

    def on_up(self, evt):
        if self.HasCapture(): self.ReleaseMouse()
        was = self._down; self._down = False; self.Refresh()
        if was and self.GetClientRect().Contains(evt.GetPosition()) and callable(self._handler):
            self._handler(evt)

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(bg)); dc.Clear()
        gc = wx.GraphicsContext.Create(dc)

        c1 = wx.Colour(132, 99, 233); c2 = wx.Colour(106, 68, 210)
        if self._hover: c1, c2 = wx.Colour(150,118,240), wx.Colour(123,81,220)
        if self._down:  c1, c2 = wx.Colour(110,78,210),  wx.Colour(92,58,190)

        r = (h-4)//2
        path = gc.CreatePath(); path.AddRoundedRectangle(0, 0, w, h, r)
        gc.SetBrush(gc.CreateLinearGradientBrush(0, 0, 0, h, c1, c2))
        gc.SetPen(wx.Pen(wx.Colour(0,0,0,0))); gc.FillPath(path)

        gc.SetFont(_font(9, True), wx.Colour(255,255,255))
        tw, th = gc.GetTextExtent(self._label)
        gc.DrawText(self._label, (w - tw)//2, (h - th)//2)

class StatCard(wx.Panel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.SetBackgroundColour(CARD_BG)
        self.SetWindowStyle(wx.BORDER_SIMPLE)

        s = wx.BoxSizer(wx.VERTICAL)
        self.lbl_title = wx.StaticText(self, label=title.upper())
        self.lbl_title.SetFont(_font(8, True))
        self.lbl_title.SetForegroundColour(TEXT_MUTED)

        self.lbl_value = wx.StaticText(self, label="—")
        self.lbl_value.SetFont(_font(12, True))
        self.lbl_value.SetForegroundColour(TEXT_BODY)

        self.gauge = wx.Gauge(self, range=100, size=(-1, 4), style=wx.GA_SMOOTH)
        self.gauge.SetForegroundColour(GAUGE_BLUE)

        s.Add(self.lbl_title, 0, wx.ALL, 8)
        s.Add(self.lbl_value, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        s.Add(self.gauge, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        self.SetSizer(s)

    def set_value(self, text, percent=None):
        self.lbl_value.SetLabel(text)
        if percent is None or percent < 0:
            self.gauge.Hide()
        else:
            self.gauge.SetValue(int(max(0, min(100, percent))))
            self.gauge.Show()
        self.Layout()

# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Data Buddy — Sidecar Application", size=(1320, 850))

        for p in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "sidecar-01.ico"),
        ):
            if os.path.exists(p):
                try: self.SetIcon(wx.Icon(p, wx.BITMAP_TYPE_ICO)); break
                except Exception: pass

        self.kernel = KernelManager()
        self.headers = []
        self.raw_data = []
        self.knowledge_files = []
        self.quality_rules = {}
        self.metrics = {
            "rows": None, "cols": None, "null_pct": None, "uniqueness": None,
            "dq_score": None, "validity": None, "completeness": None, "anomalies": None
        }

        self._build_ui()
        self._ensure_kernel_in_knowledge()

        self.CenterOnScreen()
        self.Show()

    # UI layout
    def _build_ui(self):
        self.SetBackgroundColour(PAGE_BG)
        outer = wx.BoxSizer(wx.VERTICAL)

        header = wx.Panel(self, size=(-1, 64))
        header.SetBackgroundColour(PURPLE)
        hz = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(header, label="Data Buddy")
        title.SetForegroundColour(wx.Colour(255, 255, 255))
        title.SetFont(_font(14, True))
        hz.Add(title, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 16)
        hz.AddStretchSpacer()
        hz.Add(LittleBuddyPill(header, handler=self.on_little_buddy),
               0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 16)
        header.SetSizer(hz)
        outer.Add(header, 0, wx.EXPAND)

        nav_panel = wx.Panel(self); nav_panel.SetBackgroundColour(PAGE_BG)
        nav = wx.WrapSizer(wx.HORIZONTAL); nav.AddSpacer(12)

        def add_capsule(label, handler):
            b = CapsuleButton(nav_panel, label, handler)
            nav.Add(b, 0, wx.ALL, 8); return b

        add_capsule("Upload", self._on_upload_menu)
        add_capsule("Profile", lambda _=None: self.do_analysis_process("Profile"))
        add_capsule("Quality", lambda _=None: self.do_analysis_process("Quality"))
        add_capsule("Catalog", lambda _=None: self.do_analysis_process("Catalog"))
        add_capsule("Compliance", lambda _=None: self.do_analysis_process("Compliance"))
        add_capsule("Anomalies", lambda _=None: self.do_analysis_process("Detect Anomalies"))
        add_capsule("Rule Assignment", self.on_rules)
        add_capsule("Knowledge Files", self.on_load_knowledge)
        add_capsule("Optimizer", self.on_mdm)
        add_capsule("To Do", self.on_run_tasks)
        nav_panel.SetSizer(nav)
        outer.Add(nav_panel, 0, wx.EXPAND)

        # KPI strip
        kpi_wrap = wx.Panel(self); kpi_wrap.SetBackgroundColour(PAGE_BG)
        kgrid = wx.GridSizer(rows=1, cols=8, hgap=8, vgap=8)
        titles = ["Rows","Columns","Null %","Uniqueness","DQ Score","Validity","Completeness","Anomalies"]
        self.kpi_cards = {}
        for t in titles:
            c = StatCard(kpi_wrap, t); c.SetMinSize((150, 76))
            self.kpi_cards[t] = c; kgrid.Add(c, 0, wx.EXPAND)
        kpi_wrap.SetSizer(wx.BoxSizer(wx.VERTICAL))
        kpi_wrap.GetSizer().Add(kgrid, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 12)
        outer.Add(kpi_wrap, 0, wx.EXPAND)
        self._refresh_kpis()

        # Knowledge files chips
        info = wx.Panel(self); info.SetBackgroundColour(PAGE_BG)
        hz2 = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(info, label="Knowledge Files:")
        lab.SetFont(_font(10, True)); lab.SetForegroundColour(TEXT_BODY)
        hz2.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        self.chips_panel = wx.Panel(info); self.chips_panel.SetBackgroundColour(PAGE_BG)
        self._chips_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.chips_panel.SetSizer(self._chips_sizer)
        hz2.Add(self.chips_panel, 1, wx.ALL | wx.EXPAND, 4)

        if wxadv:
            link = wxadv.HyperlinkCtrl(info, id=wx.ID_ANY, label="(add)", url="")
            link.Bind(wxadv.EVT_HYPERLINK, lambda e: self.on_load_knowledge())
        else:
            link = wx.StaticText(info, label="(add)")
            link.SetForegroundColour(wx.Colour(60, 80, 200))
            f = link.GetFont(); f.SetUnderlined(True); link.SetFont(f)
            link.Bind(wx.EVT_LEFT_UP, lambda e: self.on_load_knowledge())
        hz2.Add(link, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        info.SetSizer(hz2)
        outer.Add(info, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Data grid
        grid_panel = wx.Panel(self); grid_panel.SetBackgroundColour(PAGE_BG)
        self.grid = gridlib.Grid(grid_panel); self.grid.CreateGrid(0, 0); self.grid.EnableEditing(False)
        self._apply_light_grid_theme()
        gp = wx.BoxSizer(wx.VERTICAL); gp.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)
        grid_panel.SetSizer(gp)
        outer.Add(grid_panel, 1, wx.EXPAND)

        self.SetSizer(outer)

        # Menus
        mb = wx.MenuBar()
        m_file = wx.Menu(); m_file.Append(wx.ID_EXIT, "&Quit\tCtrl+Q"); mb.Append(m_file, "&File")
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)

        m_settings = wx.Menu(); OPEN_SETTINGS_ID = wx.NewIdRef()
        m_settings.Append(OPEN_SETTINGS_ID, "&Preferences...\tCtrl+,")
        mb.Append(m_settings, "&Settings")
        self.Bind(wx.EVT_MENU, self.open_settings, id=OPEN_SETTINGS_ID)

        m_export = wx.Menu()
        EXPORT_CSV = wx.NewIdRef(); EXPORT_TXT = wx.NewIdRef()
        m_export.Append(EXPORT_CSV, "Export CSV…")
        m_export.Append(EXPORT_TXT, "Export TXT…")
        mb.Append(m_export, "&Export")
        self.Bind(wx.EVT_MENU, lambda e: self._export("csv"), id=EXPORT_CSV)
        self.Bind(wx.EVT_MENU, lambda e: self._export("txt"), id=EXPORT_TXT)

        self.SetMenuBar(mb)

    def _apply_light_grid_theme(self):
        self.grid.SetDefaultCellTextColour(wx.Colour(20, 20, 20))
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(255, 255, 255))
        self.grid.SetLabelTextColour(wx.Colour(60, 60, 60))
        self.grid.SetLabelBackgroundColour(wx.Colour(235, 235, 240))
        self.grid.SetGridLineColour(wx.Colour(210, 210, 220))
        self.grid.SetRowLabelSize(36); self.grid.SetColLabelSize(28)

    # Knowledge chips/env
    def _get_prioritized_knowledge(self):
        paths = []
        if self.kernel and os.path.exists(self.kernel.path):
            paths.append(self.kernel.path)
        for p in self.knowledge_files:
            if p != self.kernel.path:
                paths.append(p)
        return paths

    def _refresh_knowledge_chips(self):
        for c in list(self.chips_panel.GetChildren()): c.Destroy()
        self._chips_sizer.Clear()

        def add_chip(text):
            pnl = wx.Panel(self.chips_panel); pnl.SetBackgroundColour(PAGE_BG)
            s = wx.BoxSizer(wx.HORIZONTAL)
            box = wx.Panel(pnl); box.SetBackgroundColour(CARD_BG); box.SetForegroundColour(TEXT_BODY)
            boxs = wx.BoxSizer(wx.HORIZONTAL)
            lbl = wx.StaticText(box, label=text); lbl.SetFont(_font(9)); lbl.SetForegroundColour(TEXT_BODY)
            boxs.Add(lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
            box.SetSizer(boxs); box.SetMinSize((120, -1)); box.SetWindowStyle(wx.BORDER_SIMPLE)
            s.Add(box, 0, wx.RIGHT, 8); pnl.SetSizer(s)
            self._chips_sizer.Add(pnl, 0, wx.TOP | wx.RIGHT, 4)

        for p in self._get_prioritized_knowledge():
            add_chip(os.path.basename(p))

        self.chips_panel.Layout(); self.chips_panel.GetParent().Layout()
        prio = self._get_prioritized_knowledge()
        os.environ["SIDECAR_KNOWLEDGE_FILES"] = os.pathsep.join(prio)
        os.environ["SIDECAR_KNOWLEDGE_FIRST"] = "1"
        os.environ["SIDECAR_KERNEL_FIRST"] = "1"

    def _ensure_kernel_in_knowledge(self):
        try:
            if self.kernel and os.path.exists(self.kernel.path):
                if self.kernel.path not in self.knowledge_files:
                    self.knowledge_files.append(self.kernel.path)
                self._refresh_knowledge_chips()
        except Exception:
            pass

    # KPI helpers
    def _refresh_kpis(self):
        m = self.metrics

        def pct(v):
            return None if v is None else max(0, min(100, round(float(v), 1)))

        def fmt(v, suffix=""):
            if v is None: return "—"
            if isinstance(v, int) or (isinstance(v, float) and v.is_integer()):
                return f"{int(v)}{suffix}"
            return f"{v:.1f}{suffix}"

        self.kpi_cards["Rows"].set_value(fmt(m["rows"]))
        self.kpi_cards["Columns"].set_value(fmt(m["cols"]))
        self.kpi_cards["Null %"].set_value(fmt(m["null_pct"], "%"), pct(m["null_pct"]))
        self.kpi_cards["Uniqueness"].set_value(fmt(m["uniqueness"], "%"), pct(m["uniqueness"]))
        self.kpi_cards["DQ Score"].set_value(fmt(m["dq_score"], "%"), pct(m["dq_score"]))
        self.kpi_cards["Validity"].set_value(fmt(m["validity"], "%"), pct(m["validity"]))
        self.kpi_cards["Completeness"].set_value(fmt(m["completeness"], "%"), pct(m["completeness"]))
        self.kpi_cards["Anomalies"].set_value(fmt(m["anomalies"]))

    def _reset_kpis_for_new_dataset(self, hdr, data):
        self.metrics.update({
            "rows": len(data), "cols": len(hdr),
            "null_pct": None, "uniqueness": None,
            "dq_score": None, "validity": None, "completeness": None, "anomalies": None
        })
        self.kernel.set_last_dataset(columns=hdr, rows_count=len(data))
        self.kernel.set_kpis(self.metrics)
        self._refresh_kpis()

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

    # Detailed per-column quality table (classic layout)
    def _quality_table(self, df: pd.DataFrame) -> pd.DataFrame:
        rules = self._compile_rules()
        total_rows = len(df)
        rows = []

        agg_comp, agg_uniq, agg_val, agg_q = [], [], [], []

        for c in df.columns:
            series = df[c]
            nn = int(series.notna().sum())
            completeness = (nn / total_rows * 100.0) if total_rows else 0.0

            s_nonnull = series.dropna().astype(str)
            uniq = (s_nonnull.nunique() / nn * 100.0) if nn else 0.0

            validity = None
            if nn:
                if c in rules:
                    rx = rules[c]
                    matches = s_nonnull.map(lambda v: bool(rx.fullmatch(v) or rx.search(v))).sum()
                    validity = (matches / nn) * 100.0
                else:
                    validity = 100.0  # no rule -> assume valid

            comps = [uniq, completeness]
            if validity is not None: comps.append(validity)
            qscore = sum(comps) / len(comps) if comps else 0.0

            # accumulate aggs
            agg_comp.append(completeness)
            agg_uniq.append(uniq)
            if validity is not None: agg_val.append(validity)
            agg_q.append(qscore)

            rows.append({
                "Field": c,
                "Total": nn,
                "Completeness (%)": round(completeness, 2),
                "Uniqueness (%)": round(uniq, 2),
                "Validity (%)": "—" if validity is None else round(validity, 2),
                "Quality Score (%)": round(qscore, 2),
                "Analysis Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        # update KPIs with column averages
        self.metrics["completeness"] = sum(agg_comp) / len(agg_comp) if agg_comp else None
        self.metrics["uniqueness"]   = sum(agg_uniq) / len(agg_uniq) if agg_uniq else None
        self.metrics["validity"]     = (sum(agg_val) / len(agg_val)) if agg_val else None
        self.metrics["dq_score"]     = sum(agg_q) / len(agg_q) if agg_q else None
        self._refresh_kpis()

        return pd.DataFrame(rows)

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
            self.metrics["null_pct"] = null_pct; self.metrics["uniqueness"] = uniq_pct

        components = [self.metrics["uniqueness"], completeness]
        if validity is not None: components.append(validity)
        dq_score = sum(components) / len(components) if components else 0.0
        return completeness, validity, dq_score

    def _detect_anomalies(self, df: pd.DataFrame):
        work = df.copy()

        def to_num(s):
            if s is None: return None
            if isinstance(s, (int, float)): return float(s)
            st = str(s).strip().replace(",", "")
            m = re.search(r"([-+]?\d*\.?\d+)", st)
            return float(m.group(1)) if m else None

        num_cols = []
        for c in work.columns:
            series = work[c].map(to_num)
            if series.notna().sum() >= 3:
                num_cols.append((c, series))

        reasons = [[] for _ in range(len(work))]
        flags = pd.Series(False, index=work.index)
        for cname, s in num_cols:
            x = s.astype(float); mu = x.mean(); sd = x.std(ddof=0)
            if not sd: continue
            z = (x - mu).abs() / sd
            hits = z > 3.0
            flags = flags | hits.fillna(False)
            for i, hit in hits.fillna(False).items():
                if hit: reasons[i].append(f"{cname} z>{3}")

        work["__anomaly__"] = [", ".join(r) if r else "" for r in reasons]
        count = int(flags.sum())
        return work, count

    # Upload / knowledge / rules / export
    def _on_upload_menu(self, _evt=None):
        menu = wx.Menu()
        itm1 = menu.Append(-1, "Load File…")
        itm2 = menu.Append(-1, "Load from URI/S3…")
        menu.AppendSeparator()
        itm3 = menu.Append(-1, "Synthetic Data…")
        itm4 = menu.Append(-1, "Rule Assignment…")
        itm5 = menu.Append(-1, "Upload to S3")
        itm6 = menu.Append(-1, "Export CSV…")
        itm7 = menu.Append(-1, "Export TXT…")
        self.Bind(wx.EVT_MENU, self.on_load_file, itm1)
        self.Bind(wx.EVT_MENU, self.on_load_s3, itm2)
        self.Bind(wx.EVT_MENU, self.on_generate_synth, itm3)
        self.Bind(wx.EVT_MENU, self.on_rules, itm4)
        self.Bind(wx.EVT_MENU, self.on_upload_s3, itm5)
        self.Bind(wx.EVT_MENU, lambda e: self._export("csv"), itm6)
        self.Bind(wx.EVT_MENU, lambda e: self._export("txt"), itm7)
        self.PopupMenu(menu); menu.Destroy()

    def on_load_knowledge(self, _evt=None):
        dlg = wx.FileDialog(self, "Load knowledge files",
                            wildcard="Text & Data|*.txt;*.md;*.csv;*.tsv;*.json|All|*.*",
                            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            return
        files = dlg.GetPaths(); dlg.Destroy()
        new_list = []
        if self.kernel and os.path.exists(self.kernel.path): new_list.append(self.kernel.path)
        new_list.extend(files)
        seen = set(); self.knowledge_files = [x for x in new_list if not (x in seen or seen.add(x))]
        self._refresh_knowledge_chips()

    def _load_text_file(self, path):
        return open(path, "r", encoding="utf-8", errors="ignore").read()

    def on_load_file(self, _evt=None):
        dlg = wx.FileDialog(self, "Open data file",
                            wildcard="Data|*.csv;*.tsv;*.txt|All|*.*",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            return
        path = dlg.GetPath(); dlg.Destroy()
        try:
            text = self._load_text_file(path)
            hdr, data = detect_and_split_data(text)
        except Exception as e:
            wx.MessageBox(f"Could not read file: {e}", "Error", wx.OK | wx.ICON_ERROR); return
        self.headers = hdr; self.raw_data = data
        self._display(hdr, data)
        self._reset_kpis_for_new_dataset(hdr, data)

    def on_load_s3(self, _evt=None):
        with wx.TextEntryDialog(self, "Enter URI (S3 presigned or HTTP/HTTPS):", "Load from URI/S3") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            uri = dlg.GetValue().strip()
        try:
            text = download_text_from_uri(uri)
            hdr, data = detect_and_split_data(text)
        except Exception as e:
            wx.MessageBox(f"Download failed: {e}", "Error", wx.OK | wx.ICON_ERROR); return
        self.headers = hdr; self.raw_data = data
        self._display(hdr, data)
        self._reset_kpis_for_new_dataset(hdr, data)

    def on_rules(self, _evt=None):
        if not self.headers:
            wx.MessageBox("Load data first so fields are available.", "Quality Rules", wx.OK | wx.ICON_WARNING)
            return
        fields = list(self.headers); current_rules = self.quality_rules
        try:
            dlg = QualityRuleDialog(self, fields, current_rules)
            if dlg.ShowModal() == wx.ID_OK:
                self.quality_rules = getattr(dlg, "current_rules", current_rules)
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Could not open Quality Rule Assignment:\n{e}", "Quality Rules", wx.OK | wx.ICON_ERROR)

    def on_generate_synth(self, _evt=None):
        try:
            sample = pd.DataFrame(self.raw_data, columns=self.headers) if self.headers else pd.DataFrame()
            dlg = SyntheticDataDialog(self, sample)
            if dlg.ShowModal() == wx.ID_OK:
                df = dlg.get_dataframe()
                self.headers = list(df.columns)
                self.raw_data = df.values.tolist()
                self._display(self.headers, self.raw_data)
                self._reset_kpis_for_new_dataset(self.headers, self.raw_data)
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Synthetic Data failed:\n{e}", "Synthetic Data", wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, _evt=None):
        if not self.headers:
            wx.MessageBox("No data loaded.", "Upload", wx.OK | wx.ICON_WARNING); return
        try:
            df = pd.DataFrame(self.raw_data, columns=self.headers)
            with wx.FileDialog(self, "Export to CSV (saved then uploaded)", wildcard="CSV|*.csv",
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
                if dlg.ShowModal() != wx.ID_OK: return
                local = dlg.GetPath()
            df.to_csv(local, index=False)
            uri = upload_to_s3(local)
            wx.MessageBox(f"Uploaded:\n{uri}", "Upload", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Upload failed:\n{e}", "Upload", wx.OK | wx.ICON_ERROR)

    def _export(self, typ: str):
        if not self.headers:
            wx.MessageBox("No data loaded.", "Export", wx.OK | wx.ICON_WARNING); return
        try:
            df = pd.DataFrame(self.raw_data, columns=self.headers)
            wildcard = "CSV|*.csv" if typ == "csv" else "Text|*.txt"
            with wx.FileDialog(self, f"Export to {typ.upper()}",
                               wildcard=wildcard,
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
                if dlg.ShowModal() != wx.ID_OK: return
                path = dlg.GetPath()
            if typ == "csv": df.to_csv(path, index=False)
            else:            df.to_csv(path, index=False, sep="\t")
            wx.MessageBox(f"Saved:\n{path}", "Export", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Export failed:\n{e}", "Export", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────────
    # Analysis -> normalize any shape into a DataFrame and show in main grid
    # ──────────────────────────────────────────────────────────────────────────
    def _result_to_df(self, result):
        """Robustly coerce analyzer outputs into a DataFrame."""
        try:
            if isinstance(result, pd.DataFrame):
                return result

            # Older analyzers sometimes return (headers, rows)
            if isinstance(result, tuple) and len(result) == 2:
                hdr, rows = result
                try:
                    return pd.DataFrame(rows, columns=list(hdr))
                except Exception:
                    pass  # fallthrough if malformed

            if isinstance(result, list):
                if len(result) and isinstance(result[0], dict):
                    return pd.DataFrame(result)
                if len(result) and isinstance(result[0], (list, tuple)):
                    maxlen = max(len(r) for r in result)
                    cols = [f"col{i+1}" for i in range(maxlen)]
                    data = [list(r) + [""]*(maxlen-len(r)) for r in result]
                    return pd.DataFrame(data, columns=cols)
                return pd.DataFrame({"result": [str(x) for x in result]})

            if isinstance(result, dict):
                return pd.DataFrame([result])

            if isinstance(result, str):
                lines = [ln for ln in result.splitlines() if ln.strip()]
                return pd.DataFrame({"result": lines or [result]})
        except Exception:
            pass
        return None  # signal to use a fallback

    def _display_df(self, df: pd.DataFrame, default_text="Done."):
        if df is None or df.empty:
            df = pd.DataFrame({"message": [default_text]})
        headers = list(df.columns)
        rows = df.astype(object).where(pd.notna(df), None).values.tolist()
        self.headers = headers
        self.raw_data = rows
        self._display(headers, rows)

    def do_analysis_process(self, which):
        if not self.headers:
            wx.MessageBox("Load data first.", which, wx.OK | wx.ICON_WARNING); return

        df = pd.DataFrame(self.raw_data, columns=self.headers)

        try:
            if which == "Profile":
                # KPIs first
                null_pct, uniq_pct = self._compute_profile_metrics(df)
                self.metrics["null_pct"] = null_pct
                self.metrics["uniqueness"] = uniq_pct
                self._refresh_kpis()

                res = profile_analysis(df)
                self._display_df(self._result_to_df(res) or
                                 pd.DataFrame(
                                     [
                                         {"metric": "Rows",        "value": len(df)},
                                         {"metric": "Columns",     "value": len(df.columns)},
                                         {"metric": "Null %",      "value": round(null_pct, 2)},
                                         {"metric": "Uniqueness",  "value": round(uniq_pct, 2)},
                                     ]
                                 ),
                                 "Profile complete.")

            elif which == "Quality":
                # Prefer analyzer; if it doesn't return a DataFrame, build our classic table
                ext = quality_analysis(df, self._compile_rules())
                table = self._result_to_df(ext)
                if table is None or table.empty:
                    table = self._quality_table(df)  # also updates KPIs
                else:
                    # keep KPIs in sync even when external table is used
                    try:
                        if "Completeness (%)" in table:
                            self.metrics["completeness"] = pd.to_numeric(
                                table["Completeness (%)"], errors="coerce"
                            ).dropna().mean()
                        if "Uniqueness (%)" in table:
                            self.metrics["uniqueness"] = pd.to_numeric(
                                table["Uniqueness (%)"], errors="coerce"
                            ).dropna().mean()
                        if "Validity (%)" in table:
                            vals = pd.to_numeric(table["Validity (%)"], errors="coerce").dropna()
                            self.metrics["validity"] = float(vals.mean()) if len(vals) else None
                        if "Quality Score (%)" in table:
                            self.metrics["dq_score"] = pd.to_numeric(
                                table["Quality Score (%)"], errors="coerce"
                            ).dropna().mean()
                        # If the table lacked the above, compute quick aggregates
                        if self.metrics["dq_score"] is None:
                            c, v, q = self._compute_quality_metrics(df)
                            self.metrics["completeness"] = c
                            self.metrics["validity"] = v
                            self.metrics["dq_score"] = q
                        self._refresh_kpis()
                    except Exception:
                        # Fallback to computing KPIs from data
                        c, v, q = self._compute_quality_metrics(df)
                        self.metrics["completeness"] = c
                        self.metrics["validity"] = v
                        self.metrics["dq_score"] = q
                        self._refresh_kpis()
                self._display_df(table, "Quality complete.")

            elif which == "Catalog":
                res = catalog_analysis(df)
                table = self._result_to_df(res)
                if table is None or table.empty:
                    # simple data dictionary fallback
                    rows = []
                    for c in df.columns:
                        s = df[c]
                        rows.append({
                            "column": c,
                            "dtype": str(s.dtype),
                            "non_null": int(s.notna().sum()),
                            "unique": int(s.nunique()),
                            "min": s.min() if pd.api.types.is_numeric_dtype(s) else "",
                            "max": s.max() if pd.api.types.is_numeric_dtype(s) else "",
                        })
                    table = pd.DataFrame(rows)
                self._display_df(table, "Catalog complete.")

            elif which == "Compliance":
                res = compliance_analysis(df)
                table = self._result_to_df(res) or pd.DataFrame(
                    [{"status": "ok", "description": "Compliance check completed."}]
                )
                self._display_df(table, "Compliance complete.")

            elif which == "Detect Anomalies":
                flagged, count = self._detect_anomalies(df)
                self.metrics["anomalies"] = count
                self._refresh_kpis()
                self._display_df(flagged)

            else:
                wx.MessageBox(f"Unknown process: {which}", "Analysis", wx.OK | wx.ICON_WARNING)
        except Exception as e:
            wx.MessageBox(f"{which} failed:\n{e}", which, wx.OK | wx.ICON_ERROR)

    # Placeholders
    def on_mdm(self, _evt=None):
        wx.MessageBox("Optimizer/MDM placeholder.", "MDM", wx.OK | wx.ICON_INFORMATION)

    def on_run_tasks(self, _evt=None):
        wx.MessageBox("To Do / Tasks placeholder.", "Tasks", wx.OK | wx.ICON_INFORMATION)

    # Settings & Little Buddy
    def open_settings(self, _evt=None):
        try:
            dlg = SettingsWindow(self)
            if hasattr(dlg, "ShowModal"):
                dlg.ShowModal()
                dlg.Destroy()
            else:
                dlg.Show()
        except Exception as e:
            wx.MessageBox(f"Settings failed to open:\n{e}", "Settings", wx.OK | wx.ICON_ERROR)

    def on_little_buddy(self, _evt=None):
        try:
            dlg = DataBuddyDialog(self, data=self.raw_data, headers=self.headers,
                                  knowledge=self._get_prioritized_knowledge())
            prio = self._get_prioritized_knowledge()
            os.environ["SIDECAR_KNOWLEDGE_FILES"] = os.pathsep.join(prio)
            os.environ["SIDECAR_KNOWLEDGE_FIRST"] = "1"
            os.environ["SIDECAR_KERNEL_FIRST"] = "1"
            if hasattr(dlg, "set_kernel"): dlg.set_kernel(self.kernel)
            if hasattr(dlg, "set_knowledge_files"): dlg.set_knowledge_files(list(prio))
            dlg.ShowModal()
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Little Buddy failed to open:\n{e}", "Little Buddy", wx.OK | wx.ICON_ERROR)

    # Grid display
    def _display(self, headers, rows):
        self.grid.BeginBatch()
        try:
            cur_cols = self.grid.GetNumberCols()
            if cur_cols < len(headers):
                self.grid.AppendCols(len(headers) - cur_cols)
            elif cur_cols > len(headers):
                self.grid.DeleteCols(0, cur_cols - len(headers))
            for i, h in enumerate(headers):
                self.grid.SetColLabelValue(i, str(h))

            cur_rows = self.grid.GetNumberRows()
            if cur_rows < len(rows):
                self.grid.AppendRows(len(rows) - cur_rows)
            elif cur_rows > len(rows):
                self.grid.DeleteRows(0, cur_rows - len(rows))

            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    self.grid.SetCellValue(r, c, "" if val is None else str(val))
        finally:
            self.grid.EndBatch()
            self.grid.AutoSizeColumns(False)
            self.grid.ForceRefresh()
