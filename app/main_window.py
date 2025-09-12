# app/main_window.py
import os
import json
import threading
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

    def on_up(self, evt):
        if self.HasCapture():
            self.ReleaseMouse()
        was_down = self._down
        self._down = False
        self.Refresh()
        if was_down and self.GetClientRect().Contains(evt.GetPosition()):
            try:
                self._handler(evt)
            except Exception:
                wx.LogError("Button handler failed.")

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
        self.quality_rules = []
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
        # FIX: use wx.FONTSTYLE_NORMAL / wx.FONTWEIGHT_BOLD
        title.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
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
        lab.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM))
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
    def open_settings(self, _evt):
        """Open the Settings dialog (wired to the 'Settings' top menu)."""
        try:
            SettingsWindow(self).ShowModal()
        except Exception as e:
            wx.MessageBox(f"Could not open Settings: {e}", "Settings", wx.OK | wx.ICON_ERROR)

    def on_little_buddy(self, _evt):
        """Open the Little Buddy chat/dialog."""
        try:
            dlg = DataBuddyDialog(self)
            dlg.ShowModal()
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Little Buddy failed to open:\n{e}", "Little Buddy", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # File / S3 / Knowledge / Rules
    # ──────────────────────────────────────────────────────────────────────
    def on_load_knowledge(self, _):
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

    def on_load_file(self, _):
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

    def on_load_s3(self, _):
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

    def on_rules(self, _):
        dlg = QualityRuleDialog(self, rules=self.quality_rules)
        if dlg.ShowModal() == wx.ID_OK:
            self.quality_rules = dlg.get_rules()
        dlg.Destroy()

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

    def on_export_csv(self, _):
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

    def on_export_txt(self, _):
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

    def on_upload_s3(self, _):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
        try:
            msg = upload_to_s3(self.current_process or "Unknown", hdr, data)
            wx.MessageBox(msg, "Upload", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Upload failed: {e}", "Upload", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Synthetic data
    # ──────────────────────────────────────────────────────────────────────
    def on_generate_synth(self, _):
        if not self.headers:
            wx.MessageBox("Load data first to choose fields.", "No data", wx.OK | wx.ICON_WARNING)
            return

        def _synth_dataframe(n, fields):
            import random
            import string
            rows = []
            for _ in range(int(n)):
                row = []
                for _f in fields:
                    val = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
                    row.append(val)
                rows.append(row)
            return pd.DataFrame(rows, columns=fields)

        dlg = SyntheticDataDialog(self, columns=list(self.headers))
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        try:
            n, fields = dlg.get_values()
            if not fields:
                fields = list(self.headers)
            df = _synth_dataframe(n, fields)
        except Exception as e:
            wx.MessageBox(f"Synthetic data error: {e}", "Error", wx.OK | wx.ICON_ERROR)
            dlg.Destroy()
            return

        dlg.Destroy()
        hdr = list(df.columns)
        data = df.values.tolist()
        self.headers = hdr
        self.raw_data = data
        self._display(hdr, data)

    # ──────────────────────────────────────────────────────────────────────
    # Tasks runner
    # ──────────────────────────────────────────────────────────────────────
    def on_run_tasks(self, _evt):
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
