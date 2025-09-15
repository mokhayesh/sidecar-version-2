# app/main_window.py
import os
import json
import threading
from datetime import datetime
from collections import defaultdict

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
# Kernel: persistent app “memory” (unchanged behavior)
# ──────────────────────────────────────────────────────────────────────────────
class KernelManager:
    """Lightweight JSON kernel for app metadata, event logs, and last dataset."""

    def __init__(self, app_name="Data Buddy — Sidecar Application"):
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
                    "Upload", "Profile", "Quality", "Catalog", "Anomalies",
                    "Optimizer", "To Do", "Knowledge Files", "Load File",
                    "Load from URI/S3", "MDM", "Synthetic Data",
                    "Rule Assignment", "Compliance", "Tasks",
                    "Export CSV", "Export TXT", "Upload to S3",
                ],
            },
            "stats": {"launch_count": 0},
            "state": {"last_dataset": None, "kpis": {}},
            "events": [],
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
                existing.setdefault("state", {"last_dataset": None, "kpis": {}})
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
        evt = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "type": event_type,
            "payload": payload,
        }
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
# Styled widgets (purple theme)
# ──────────────────────────────────────────────────────────────────────────────
PURPLE = wx.Colour(72, 50, 150)
PURPLE_DARK = wx.Colour(46, 34, 95)
PURPLE_LIGHT = wx.Colour(139, 123, 200)
INK = wx.Colour(235, 235, 245)
BG = wx.Colour(26, 26, 30)
CARD = wx.Colour(34, 34, 38)
ACCENT = wx.Colour(150, 125, 255)

def _rounded(panel, radius=18, bg=CARD, border=None):
    panel.SetBackgroundColour(bg)
    if border:
        panel.SetWindowStyle(panel.GetWindowStyle() | wx.BORDER_SIMPLE)
    return panel


class TabButton(wx.Control):
    """Pill-shaped 'tab' button used across the purple header row."""

    def __init__(self, parent, label, on_click=None, pad=(18, 10)):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.label = label
        self.on_click = on_click
        self.pad = pad
        self.hover = False
        self.down = False
        self.SetMinSize((-1, 38))
        self.SetBackgroundColour(PURPLE_DARK)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._ld)
        self.Bind(wx.EVT_LEFT_UP, self._lu)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))

    def _ld(self, _): self.down = True; self.Refresh()
    def _lu(self, _):
        was_down = self.down
        self.down = False
        self.Refresh()
        if was_down and callable(self.on_click):
            self.on_click(None)

    def _set_hover(self, v): self.hover = v; self.Refresh()

    def _paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        w, h = self.GetClientSize()
        r = h // 2
        bg = PURPLE if (self.down or self.hover) else PURPLE_DARK
        dc.SetPen(wx.Pen(bg))
        dc.SetBrush(wx.Brush(bg))
        path = wx.GraphicsContext.Create(dc)
        path = path.CreatePath()
        path.MoveToPoint(r, 0)
        path.AddRoundedRectangle(1, 1, w - 2, h - 2, r)
        g = wx.GraphicsContext.Create(dc)
        g.SetBrush(wx.Brush(bg))
        g.DrawRoundedRectangle(1, 1, w - 2, h - 2, r)
        dc.SetTextForeground(INK)
        font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.SEMIBOLD)
        dc.SetFont(font)
        tw, th = dc.GetTextExtent(self.label)
        dc.DrawText(self.label, (w - tw) // 2, (h - th) // 2)


class KPICard(wx.Panel):
    def __init__(self, parent, title, value="—"):
        super().__init__(parent)
        _rounded(self, radius=20, bg=CARD)
        v = wx.BoxSizer(wx.VERTICAL)
        t = wx.StaticText(self, label=title.upper())
        t.SetForegroundColour(PURPLE_LIGHT)
        t.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD))
        v.Add(t, 0, wx.TOP | wx.LEFT | wx.RIGHT, 10)

        self.lbl = wx.StaticText(self, label=str(value))
        self.lbl.SetForegroundColour(INK)
        self.lbl.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD))
        v.Add(self.lbl, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(v)

    def set(self, value): self.lbl.SetLabel(str(value))


class LittleBuddyPill(wx.Panel):
    """Floating button at the right side (like the screenshot)."""

    def __init__(self, parent, on_click):
        super().__init__(parent)
        _rounded(self, radius=18, bg=PURPLE)
        self.SetMinSize((150, 40))
        self.on_click = on_click
        self.Bind(wx.EVT_LEFT_UP, lambda e: on_click())
        hs = wx.BoxSizer(wx.HORIZONTAL)
        dot = wx.StaticText(self, label="💬")
        dot.SetForegroundColour(INK)
        title = wx.StaticText(self, label="Little Buddy")
        title.SetForegroundColour(INK)
        title.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD))
        hs.AddSpacer(10)
        hs.Add(dot, 0, wx.ALIGN_CENTER_VERTICAL)
        hs.AddSpacer(6)
        hs.Add(title, 0, wx.ALIGN_CENTER_VERTICAL)
        hs.AddSpacer(10)
        self.SetSizer(hs)


# ──────────────────────────────────────────────────────────────────────────────
# Main window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Data Buddy — Sidecar Application", size=(1320, 820))
        self.SetBackgroundColour(BG)
        self.kernel = KernelManager()
        self.df = pd.DataFrame()
        self.headers = []
        self.quality_rules = defaultdict(lambda: None)

        # Top “brand” row with title + Little Buddy pill aligned right
        top_panel = wx.Panel(self)
        top_panel.SetBackgroundColour(PURPLE_DARK)
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)

        title = wx.StaticText(top_panel, label="Data Buddy")
        title.SetForegroundColour(INK)
        title.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD))
        top_sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        top_sizer.AddStretchSpacer()
        self.buddy = LittleBuddyPill(top_panel, self.on_open_buddy)
        top_sizer.Add(self.buddy, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        top_panel.SetSizer(top_sizer)

        # Tab row (Upload / Profile / Quality / Catalog / Anomalies / Optimizer / To Do)
        tab_row = wx.Panel(self)
        tab_row.SetBackgroundColour(PURPLE_DARK)
        tr = wx.BoxSizer(wx.HORIZONTAL)
        tr.AddSpacer(8)

        def _tab(label, cb): tr.Add(TabButton(tab_row, label, cb), 0, wx.ALL, 6)

        _tab("Upload", self.on_upload_menu)      # opens a small menu: local file / URI-S3
        _tab("Profile", self.on_profile)
        _tab("Quality", self.on_quality)
        _tab("Catalog", self.on_catalog)
        _tab("Anomalies", self.on_detect_anomalies)
        _tab("Optimizer", lambda e: wx.MessageBox("Coming soon ✨"))
        _tab("To Do", self.on_tasks)

        tr.AddStretchSpacer()
        tab_row.SetSizer(tr)

        # KPI strip
        kpi_panel = wx.Panel(self)
        kpi_panel.SetBackgroundColour(BG)
        kbox = wx.BoxSizer(wx.HORIZONTAL)
        self.kpi_rows = KPICard(kpi_panel, "Rows", "—")
        self.kpi_cols = KPICard(kpi_panel, "Columns", "—")
        self.kpi_null = KPICard(kpi_panel, "Null %", "—")
        self.kpi_unique = KPICard(kpi_panel, "Uniqueness", "—")
        self.kpi_dq = KPICard(kpi_panel, "DQ Score", "—")
        self.kpi_valid = KPICard(kpi_panel, "Validity", "—")
        self.kpi_complete = KPICard(kpi_panel, "Completeness", "—")
        self.kpi_anom = KPICard(kpi_panel, "Anomalies", "—")
        for card in (self.kpi_rows, self.kpi_cols, self.kpi_null, self.kpi_unique,
                     self.kpi_dq, self.kpi_valid, self.kpi_complete, self.kpi_anom):
            kbox.Add(card, 1, wx.EXPAND | wx.ALL, 6)
        kpi_panel.SetSizer(kbox)

        # Knowledge files “chips” row
        chips_panel = wx.Panel(self)
        chips_panel.SetBackgroundColour(BG)
        chips = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(chips_panel, label="Knowledge Files:")
        lbl.SetForegroundColour(INK)
        chips.Add(lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        self.knowledge_lbl = wx.StaticText(chips_panel, label="(none)")
        self.knowledge_lbl.SetForegroundColour(PURPLE_LIGHT)
        chips.Add(self.knowledge_lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        chips.AddStretchSpacer()
        chips_panel.SetSizer(chips)

        # Secondary action row (as rounded chips, like bottom row in your app)
        act_row = wx.Panel(self)
        act_row.SetBackgroundColour(BG)
        a = wx.BoxSizer(wx.HORIZONTAL)
        for label, cb in [
            ("Knowledge Files", lambda e: self.on_set_knowledge()),
            ("Load File", self.on_load_file),
            ("Load from URI/S3", self.on_load_from_uri),
            ("MDM", lambda e: wx.MessageBox("MDM coming soon")),
            ("Synthetic Data", self.on_synth_data),
            ("Rule Assignment", self.on_rule_assignment),
            ("Compliance", self.on_compliance),
            ("Tasks", self.on_tasks),
            ("Export CSV", lambda e: self.on_export(sep=",")),
            ("Export TXT", lambda e: self.on_export(sep="\t")),
            ("Upload to S3", self.on_upload_to_s3),
        ]:
            a.Add(TabButton(act_row, label, cb), 0, wx.ALL, 4)
        a.AddStretchSpacer()
        act_row.SetSizer(a)

        # Data grid
        grid_panel = wx.Panel(self)
        grid_panel.SetBackgroundColour(BG)
        self.grid = gridlib.Grid(grid_panel)
        self.grid.CreateGrid(0, 0)
        self.grid.SetDefaultCellAlignment(wx.ALIGN_LEFT, wx.ALIGN_CENTER)
        self.grid.SetDefaultCellTextColour(INK)
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(38, 38, 42))
        self.grid.SetLabelTextColour(INK)
        self.grid.SetLabelBackgroundColour(PURPLE_DARK)
        self.grid.EnableEditing(False)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        gs = wx.BoxSizer(wx.VERTICAL)
        gs.Add(self.grid, 1, wx.EXPAND | wx.ALL, 6)
        grid_panel.SetSizer(gs)

        # Root sizer
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(top_panel, 0, wx.EXPAND)
        root.Add(tab_row, 0, wx.EXPAND)
        root.Add(kpi_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        root.Add(chips_panel, 0, wx.EXPAND)
        root.Add(act_row, 0, wx.EXPAND | wx.BOTTOM, 4)
        root.Add(grid_panel, 1, wx.EXPAND)
        self.SetSizer(root)

        self.Centre()
        self.Show(True)

        # render empty KPIs
        self._render_kpis()

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────
    def on_upload_menu(self, _evt=None):
        m = wx.Menu()
        m.Append(1, "Load local file…")
        m.Append(2, "Load from URI / S3…")
        self.Bind(wx.EVT_MENU, lambda e: self.on_load_file(), id=1)
        self.Bind(wx.EVT_MENU, lambda e: self.on_load_from_uri(), id=2)
        self.PopupMenu(m)
        m.Destroy()

    def on_set_knowledge(self):
        with wx.FileDialog(self, "Pick knowledge files", wildcard="*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                names = [os.path.basename(p) for p in dlg.GetPaths()]
                self.knowledge_lbl.SetLabel(", ".join(names))
                self.Layout()

    def on_load_file(self, _evt=None):
        with wx.FileDialog(self, "Open CSV", wildcard="CSV files (*.csv)|*.csv|All files|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            self.df = pd.read_csv(path)
            self.headers = list(self.df.columns)
            self._display(self.headers, self.df.values.tolist())
            self.kernel.set_last_dataset(self.headers, len(self.df))
            self.kernel.log("load_file", path=path, rows=len(self.df), cols=len(self.headers))
        except Exception as e:
            wx.MessageBox(f"Failed to load: {e}", "Load file", wx.OK | wx.ICON_ERROR)

    def on_load_from_uri(self, _evt=None):
        dlg = wx.TextEntryDialog(self, "Enter URI (s3://, https:// or file path):", "Load from URI/S3")
        if dlg.ShowModal() != wx.ID_OK:
            return
        uri = dlg.GetValue().strip()
        dlg.Destroy()
        try:
            content = download_text_from_uri(uri)
            # let detect_and_split decide separator & header
            df, _ = detect_and_split_data(content)
            self.df = df
            self.headers = list(df.columns)
            self._display(self.headers, df.values.tolist())
            self.kernel.set_last_dataset(self.headers, len(self.df))
            self.kernel.log("load_uri", uri=uri, rows=len(self.df), cols=len(self.headers))
        except Exception as e:
            wx.MessageBox(f"Failed to load from URI: {e}", "URI/S3", wx.OK | wx.ICON_ERROR)

    def on_profile(self, _evt=None):
        if self.df.empty:
            wx.MessageBox("Load data first.", "Profile", wx.OK | wx.ICON_WARNING)
            return
        res = profile_analysis(self.df)
        self._show_result("Profile", res)

    def on_quality(self, _evt=None):
        if self.df.empty:
            wx.MessageBox("Load data first.", "Quality", wx.OK | wx.ICON_WARNING)
            return
        res = quality_analysis(self.df)
        self._show_result("Quality", res)

    def on_catalog(self, _evt=None):
        if self.df.empty:
            wx.MessageBox("Load data first.", "Catalog", wx.OK | wx.ICON_WARNING)
            return
        res = catalog_analysis(self.df)
        self._show_result("Catalog", res)

    def on_compliance(self, _evt=None):
        if self.df.empty:
            wx.MessageBox("Load data first.", "Compliance", wx.OK | wx.ICON_WARNING)
            return
        res = compliance_analysis(self.df)
        self._show_result("Compliance", res)

    def on_detect_anomalies(self, _evt=None):
        if self.df.empty:
            wx.MessageBox("Load data first.", "Anomalies", wx.OK | wx.ICON_WARNING)
            return
        # reuse your detect+split helper so it stays consistent
        # If it returns a __anomaly__ column, we’ll auto-highlight in _display()
        res_df, _ = detect_and_split_data(self.df.to_csv(index=False))
        # If detect_and_split_data returns the same df on CSV string input,
        # fall back to simple z-score style detection per numeric column
        if "__anomaly__" not in res_df.columns:
            df = self.df.copy()
            anom = []
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            for _, row in df.iterrows():
                flag = False
                for c in num_cols:
                    s = df[c].astype(float)
                    if s.std(ddof=0) > 0:
                        z = abs((float(row[c]) - s.mean()) / (s.std(ddof=0)))
                        if z >= 3.0:
                            flag = True
                            break
                anom.append(flag)
            df["__anomaly__"] = anom
            res_df = df

        self.df = res_df
        self.headers = list(res_df.columns)
        self._display(self.headers, res_df.values.tolist())
        self.kernel.log("detect_anomalies", rows=len(self.df), cols=len(self.headers))

    def on_rule_assignment(self, _evt=None):
        if self.df.empty:
            wx.MessageBox("Load data first.", "Rule Assignment", wx.OK | wx.ICON_WARNING)
            return
        dlg = QualityRuleDialog(self, list(self.df.columns), self.quality_rules)
        dlg.ShowModal()
        dlg.Destroy()

    def on_synth_data(self, _evt=None):
        dlg = SyntheticDataDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def on_tasks(self, _evt=None):
        wx.MessageBox("Tasks pane coming soon.", "Tasks")

    def on_export(self, sep=","):
        if self.grid.GetNumberCols() == 0:
            wx.MessageBox("Nothing to export.", "Export", wx.OK | wx.ICON_WARNING)
            return
        wildcard = "CSV (*.csv)|*.csv" if sep == "," else "Text (*.txt)|*.txt"
        with wx.FileDialog(self, "Export", wildcard=wildcard,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            rows = []
            for r in range(self.grid.GetNumberRows()):
                rows.append([self.grid.GetCellValue(r, c) for c in range(len(hdr))])
            pd.DataFrame(rows, columns=hdr).to_csv(path, index=False, sep=sep)
            self.kernel.log("export", path=path, sep=sep, rows=len(rows), cols=len(hdr))
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_upload_to_s3(self, _evt=None):
        if self.grid.GetNumberCols() == 0:
            wx.MessageBox("Load data first.", "Upload to S3", wx.OK | wx.ICON_WARNING)
            return
        with wx.TextEntryDialog(self, "Enter S3 URI (s3://bucket/key.csv)", "Upload to S3") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            uri = dlg.GetValue().strip()
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            rows = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                    for r in range(self.grid.GetNumberRows())]
            csv_bytes = pd.DataFrame(rows, columns=hdr).to_csv(index=False).encode("utf-8")
            upload_to_s3(uri, csv_bytes)
            wx.MessageBox("Uploaded.", "S3")
        except Exception as e:
            wx.MessageBox(f"Upload failed: {e}", "S3", wx.OK | wx.ICON_ERROR)

    def on_open_buddy(self, _evt=None):
        knowledge = []
        kn_text = self.knowledge_lbl.GetLabel().strip()
        if kn_text and kn_text != "(none)":
            # These are just names; Buddy will also get kernel.json automatically
            knowledge = [kn_text]
        dlg = DataBuddyDialog(self,
                              data=self.df.values.tolist() if not self.df.empty else None,
                              headers=list(self.df.columns) if not self.df.empty else None,
                              knowledge=knowledge)
        dlg.ShowModal()
        dlg.Destroy()

    # ──────────────────────────────────────────────────────────────────────
    # Grid & KPI helpers
    # ──────────────────────────────────────────────────────────────────────
    def _render_kpis(self):
        if self.df.empty:
            cards = [
                (self.kpi_rows, "—"), (self.kpi_cols, "—"), (self.kpi_null, "—"),
                (self.kpi_unique, "—"), (self.kpi_dq, "—"), (self.kpi_valid, "—"),
                (self.kpi_complete, "—"), (self.kpi_anom, "—"),
            ]
        else:
            rows = len(self.df)
            cols = len(self.df.columns)
            null_pct = round(float(self.df.isna().sum().sum()) / (rows * max(cols, 1)) * 100, 1) if rows and cols else 0
            uniq = "—"
            try:
                uniq = f"{(self.df.drop_duplicates().shape[0] / rows * 100):.1f}%"
            except Exception:
                pass
            dq = "—"
            valid = "—"
            complete = f"{(1 - (self.df.isna().any(axis=1).mean()))*100:.1f}%" if rows else "—"
            anoms = "—"
            if "__anomaly__" in self.df.columns:
                try:
                    anoms = int(self.df["__anomaly__"].astype(bool).sum())
                except Exception:
                    anoms = "—"
            cards = [
                (self.kpi_rows, rows), (self.kpi_cols, cols), (self.kpi_null, f"{null_pct}%"),
                (self.kpi_unique, uniq), (self.kpi_dq, dq), (self.kpi_valid, valid),
                (self.kpi_complete, complete), (self.kpi_anom, anoms),
            ]
        for card, val in cards:
            card.set(val)
        self.Layout()

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

        # detect anomaly column to tint rows (same idea you had previously)
        try:
            anom_idx = hdr.index("__anomaly__")
        except ValueError:
            anom_idx = -1

        for r, row in enumerate(data):
            row_has_anom = bool(row[anom_idx]) if (anom_idx >= 0 and anom_idx < len(row)) else False
            for c, val in enumerate(row):
                self.grid.SetCellValue(r, c, str(val))
                base = wx.Colour(42, 42, 46) if r % 2 == 0 else wx.Colour(36, 36, 40)
                if row_has_anom:
                    base = wx.Colour(72, 32, 60)  # faint purple-red; readable in dark
                self.grid.SetCellBackgroundColour(r, c, base)

        self.adjust_grid()
        self._render_kpis()

    def adjust_grid(self):
        cols = self.grid.GetNumberCols()
        if cols == 0:
            return
        total_w = self.grid.GetClientSize().GetWidth()
        usable = max(0, total_w - self.grid.GetRowLabelSize())
        w = max(80, usable // cols)
        for c in range(cols):
            self.grid.SetColSize(c, w)

    def on_grid_resize(self, event):
        event.Skip()
        wx.CallAfter(self.adjust_grid)


if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
