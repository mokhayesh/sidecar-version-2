# app/main_window.py
import os
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

# Try anomalies under either name; provide a safe fallback if not present.
try:
    from app.analysis import anomalies_analysis as detect_anomalies_analysis
except Exception:
    try:
        from app.analysis import detect_anomalies as detect_anomalies_analysis
    except Exception:
        def detect_anomalies_analysis(df: pd.DataFrame):
            hdr = ["Issue", "Details"]
            data = [["No analyzer", "Define detect_anomalies() or anomalies_analysis() in app.analysis"]]
            return hdr, data


# ──────────────────────────────────────────────────────────────────────────────
# Cross-version font helper (uses wx.FontInfo; safe on Python 3.13 / wx 4.x)
# ──────────────────────────────────────────────────────────────────────────────
def mkfont(size: int, *, bold: bool = False, italic: bool = False,
           family: int = wx.FONTFAMILY_SWISS) -> wx.Font:
    info = wx.FontInfo(size).Family(family)
    if italic:
        info = info.Italic()
    if bold:
        info = info.Bold()
    return wx.Font(info)


# ──────────────────────────────────────────────────────────────────────────────
# Header banner (double-buffered, no flicker)
# ──────────────────────────────────────────────────────────────────────────────
class HeaderBanner(wx.Panel):
    def __init__(self, parent, height=160, bg=wx.Colour(28, 28, 28)):
        super().__init__(parent, size=(-1, height), style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)  # required for AutoBufferedPaintDC
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)  # prevent flicker

        self._bg = bg
        self._min_w = 320
        self.SetBackgroundColour(self._bg)
        self._img = self._load_banner_image()
        self.SetMinSize((self._min_w, height))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh())

    def _load_banner_image(self):
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "assets", "sidecar.gif"),
            os.path.join(here, "assets", "sidecar.jpg"),
            os.path.join(here, "assets", "sidecar.png"),
            os.path.join(here, "sidecar.gif"),
            os.path.join(here, "sidecar.jpg"),
            os.path.join(here, "sidecar.png"),
            os.path.join(os.getcwd(), "sidecar.gif"),
            os.path.join(os.getcwd(), "sidecar.jpg"),
            os.path.join(os.getcwd(), "sidecar.png"),
        ]
        for p in candidates:
            if os.path.exists(p):
                try:
                    return wx.Image(p, wx.BITMAP_TYPE_ANY)
                except Exception:
                    pass
        # Fallback: solid color image
        bmp = wx.Bitmap(self._min_w, 160)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(self._bg))
        dc.Clear()
        dc.SelectObject(wx.NullBitmap)
        return bmp.ConvertToImage()

    def _on_paint(self, _):
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
# Simple local synthetic data fallback
# ──────────────────────────────────────────────────────────────────────────────
import random as _r

_FIRST_NAMES = ["JAY", "ANA", "KIM", "LEE", "OMAR", "SARA", "NIA", "LIV", "RAJ"]
_LAST_NAMES  = ["SMITH", "NG", "GARCIA", "BROWN", "TAYLOR", "KHAN", "LI", "LEE"]
_STATES = ["AL","AK","AZ","CA","CO","CT","DC","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY",
           "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY",
           "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","WY"]

def _synth_value(kind: str, i: int) -> str:
    k = (kind or "").lower()
    if "email" in k:
        return f"user{i}@example.com"
    if "first" in k and "name" in k:
        return _r.choice(_FIRST_NAMES)
    if "last" in k and "name" in k:
        return _r.choice(_LAST_NAMES)
    if "phone" in k:
        return f"{_r.randint(200, 989)}-{_r.randint(100, 999)}-{_r.randint(1000, 9999)}"
    if "address" in k:
        return f"{_r.randint(100, 9999)} Main St, City, {_r.choice(_STATES)} {_r.randint(10000, 99999)}"
    if "amount" in k or "loan" in k or "balance" in k:
        return f"{_r.randint(100, 99999)}.{_r.randint(0, 99):02d}"
    return f"value_{i}"

def _synth_dataframe(n: int, columns: list[str]) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append([_synth_value(col, i) for col in columns])
    return pd.DataFrame(rows, columns=columns)


# ──────────────────────────────────────────────────────────────────────────────
# KPI Card (NEW)
# ──────────────────────────────────────────────────────────────────────────────
class MetricCard(wx.Panel):
    """Small pill-style card used in the KPI strip."""
    def __init__(self, parent, title: str, value="—", accent=wx.Colour(120, 99, 255)):
        super().__init__(parent)
        self.SetBackgroundColour(wx.Colour(46, 46, 56))

        v = wx.BoxSizer(wx.VERTICAL)

        t = wx.StaticText(self, label=title.upper())
        t.SetFont(mkfont(8, bold=True))
        t.SetForegroundColour(wx.Colour(190, 190, 198))

        self.val = wx.StaticText(self, label=str(value))
        self.val.SetFont(mkfont(14, bold=True))
        self.val.SetForegroundColour(wx.WHITE)

        bar = wx.Panel(self, size=(-1, 3))
        bar.SetBackgroundColour(accent)

        v.Add(t, 0, wx.ALL, 6)
        v.Add(self.val, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        v.Add(bar, 0, wx.EXPAND)

        self.SetSizer(v)

    def set(self, value):
        self.val.SetLabel(str(value))


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1200, 820))

        # Best-effort app icon
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

        self.raw_data: list[list[str]] = []
        self.headers: list[str] = []
        self.current_process: str = ""
        self.quality_rules: dict = {}
        self.knowledge_files: list[dict] = []

        self._build_ui()
        self.Centre()
        self.Show()

    def _build_ui(self):
        BG = wx.Colour(40, 40, 40)
        PANEL = wx.Colour(45, 45, 45)
        TXT = wx.Colour(235, 235, 235)
        ACCENT = wx.Colour(110, 82, 255)  # deep purple accent

        self.SetBackgroundColour(BG)
        main = wx.BoxSizer(wx.VERTICAL)

        # Header row: banner + centered title
        header_bg = wx.Colour(28, 28, 28)
        header_row = wx.BoxSizer(wx.HORIZONTAL)

        self.banner = HeaderBanner(self, height=160, bg=header_bg)
        header_row.Add(self.banner, 0, wx.EXPAND)

        title_panel = wx.Panel(self)
        title_panel.SetBackgroundColour(header_bg)
        title = wx.StaticText(title_panel, label="Data Buddy — Sidecar Application")
        title.SetFont(mkfont(18, bold=True))
        title.SetForegroundColour(wx.Colour(240, 240, 245))
        tps = wx.BoxSizer(wx.HORIZONTAL)
        tps.AddStretchSpacer()
        tps.Add(title, 0, wx.ALIGN_CENTER_VERTICAL)
        tps.AddStretchSpacer()
        title_panel.SetSizer(tps)

        header_row.Add(title_panel, 1, wx.EXPAND)
        main.Add(header_row, 0, wx.EXPAND)

        # ── KPI strip (NEW) ────────────────────────────────────────────────
        kpi_panel = wx.Panel(self)
        kpi_panel.SetBackgroundColour(wx.Colour(36, 36, 44))
        kpis = wx.BoxSizer(wx.HORIZONTAL)

        self.card_rows     = MetricCard(kpi_panel, "Rows",      "—", wx.Colour(120, 99, 255))
        self.card_cols     = MetricCard(kpi_panel, "Columns",   "—", wx.Colour(151, 133, 255))
        self.card_nulls    = MetricCard(kpi_panel, "Null %",    "—", wx.Colour(187, 168, 255))
        self.card_quality  = MetricCard(kpi_panel, "DQ Score",  "—", wx.Colour(255, 207, 92))
        self.card_anoms    = MetricCard(kpi_panel, "Anomalies", "—", wx.Colour(255, 113, 113))

        for c in (self.card_rows, self.card_cols, self.card_nulls, self.card_quality, self.card_anoms):
            kpis.Add(c, 0, wx.ALL, 6)

        kpi_panel.SetSizer(kpis)
        main.Add(kpi_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        # ───────────────────────────────────────────────────────────────────

        # Menu bar
        mb = wx.MenuBar()
        m_file, m_set = wx.Menu(), wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        mb.Append(m_file, "&File")
        mb.Append(m_set, "&Settings")
        self.SetMenuBar(mb)

        # Toolbar (wraps on resize)
        toolbar_panel = wx.Panel(self)
        toolbar_panel.SetBackgroundColour(PANEL)
        toolbar = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(label, handler):
            b = wx.Button(toolbar_panel, label=label, style=wx.BORDER_NONE)
            b.SetBackgroundColour(ACCENT)
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(mkfont(9))  # bold not strictly needed on dark buttons
            b.SetMinSize((150, 34))
            b.Bind(wx.EVT_BUTTON, handler)
            toolbar.Add(b, 0, wx.ALL, 4)
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
        add_btn("Little Buddy", self.on_buddy)
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
        lab.SetFont(mkfont(9, bold=True))
        hz.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)

        self.knowledge_line = wx.StaticText(info_panel, label="(none)")
        self.knowledge_line.SetForegroundColour(wx.Colour(210, 210, 210))
        self.knowledge_line.SetFont(mkfont(9))
        hz.Add(self.knowledge_line, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        info_panel.SetSizer(hz)
        main.Add(info_panel, 0, wx.EXPAND)

        # Grid
        grid_panel = wx.Panel(self)
        grid_panel.SetBackgroundColour(BG)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.grid = gridlib.Grid(grid_panel)
        self.grid.CreateGrid(0, 0)
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(55, 55, 55))
        self.grid.SetDefaultCellTextColour(wx.Colour(220, 220, 220))
        self.grid.SetLabelBackgroundColour(wx.Colour(80, 80, 80))
        self.grid.SetLabelTextColour(wx.Colour(240, 240, 240))
        self.grid.SetLabelFont(mkfont(9, bold=True))
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)

        vbox.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)
        grid_panel.SetSizer(vbox)
        main.Add(grid_panel, 1, wx.EXPAND)

        self.SetSizer(main)

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────
    def on_settings(self, _):
        SettingsWindow(self).Show()

    def on_load_file(self, _):
        dlg = wx.FileDialog(self, "Open CSV/TXT", wildcard="CSV/TXT|*.csv;*.txt",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        path = dlg.GetPath()
        dlg.Destroy()
        text = open(path, "r", encoding="utf-8").read()
        self.headers, self.raw_data = detect_and_split_data(text)
        self._display(self.headers, self.raw_data)

        # Update KPIs (basic)
        try:
            rows = len(self.raw_data)
            cols = len(self.headers)
            self.card_rows.set(rows)
            self.card_cols.set(cols)
        except Exception:
            pass

    def on_load_s3(self, _):
        uri = wx.GetTextFromUser("Enter HTTP(S) or S3 URI:", "Load from URI/S3")
        if not uri:
            return
        try:
            text = download_text_from_uri(uri)
            self.headers, self.raw_data = detect_and_split_data(text)
            self._display(self.headers, self.raw_data)

            # Update KPIs (basic)
            rows = len(self.raw_data)
            cols = len(self.headers)
            self.card_rows.set(rows)
            self.card_cols.set(cols)
        except Exception as e:
            wx.MessageBox(f"Failed to load data:\n{e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_load_knowledge(self, _):
        dlg = wx.FileDialog(self, "Add Knowledge Files",
                            wildcard="All supported|*.txt;*.csv;*.json;*.md;*.png;*.jpg;*.jpeg;*.gif|"
                                     "Text/CSV/JSON|*.txt;*.csv;*.json;*.md|"
                                     "Images|*.png;*.jpg;*.jpeg;*.gif|All|*.*",
                            style=wx.FD_OPEN | wx.FD_MULTIPLE)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        paths = dlg.GetPaths()
        dlg.Destroy()

        added = []
        for p in paths:
            try:
                ext = os.path.splitext(p)[1].lower()
                if ext in (".txt", ".csv", ".json", ".md"):
                    content = open(p, "r", encoding="utf-8", errors="ignore").read()
                    self.knowledge_files.append({"name": os.path.basename(p), "content": content})
                    added.append(os.path.basename(p))
                elif ext in (".png", ".jpg", ".jpeg", ".gif"):
                    self.knowledge_files.append({"name": os.path.basename(p), "path": p, "content": None})
                    added.append(os.path.basename(p))
                else:
                    try:
                        content = open(p, "r", encoding="utf-8", errors="ignore").read()
                    except Exception:
                        content = None
                    self.knowledge_files.append({"name": os.path.basename(p), "path": p, "content": content})
                    added.append(os.path.basename(p))
            except Exception:
                pass

        if added:
            self.knowledge_line.SetLabel("  • " + "  •  ".join(added))
            self.Layout()

    def on_rules(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

    def on_buddy(self, _):
        DataBuddyDialog(self, self.raw_data, self.headers, knowledge=self.knowledge_files).ShowModal()

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
            func = detect_anomalies_analysis
        else:
            func = profile_analysis

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

    def on_generate_synth(self, _):
        if not self.headers:
            wx.MessageBox("Load data first to choose fields.", "No data", wx.OK | wx.ICON_WARNING)
            return

        dlg = SyntheticDataDialog(self, self.headers)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        df = None
        if hasattr(dlg, "get_dataframe"):
            try:
                df = dlg.get_dataframe()
            except Exception:
                df = None

        if df is None:
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

        # Update KPIs after synthetic generation
        try:
            self.card_rows.set(len(data))
            self.card_cols.set(len(hdr))
        except Exception:
            pass

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
