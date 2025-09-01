import os
import csv
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

# Try to import an anomalies function; provide a friendly fallback if missing.
try:
    from app.analysis import anomalies_analysis as detect_anomalies_analysis
except Exception:
    try:
        from app.analysis import detect_anomalies as detect_anomalies_analysis
    except Exception:
        def detect_anomalies_analysis(df: pd.DataFrame):
            hdr = ["Issue", "Details"]
            data = [["No analyzer", "Install/define detect_anomalies() in app.analysis"]]
            return hdr, data


# ──────────────────────────────────────────────────────────────────────────────
# Header banner (fixed init order)
# ──────────────────────────────────────────────────────────────────────────────
class HeaderBanner(wx.Panel):
    def __init__(self, parent, height=160, bg=wx.Colour(28, 28, 28)):
        super().__init__(parent, size=(-1, height), style=wx.BORDER_NONE)
        self._bg = bg
        self._min_w = 320  # <-- set BEFORE _load_banner_image()
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
        # Fallback placeholder
        h = self.GetSize().y if self.GetSize().y else 160
        bmp = wx.Bitmap(self._min_w, h)
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
# Simple local synthetic data fallback (used if dialog returns only counts)
# ──────────────────────────────────────────────────────────────────────────────
_FIRST_NAMES = ["JAY", "ANA", "KIM", "LEE", "OMAR", "SARA", "NIA", "LIV", "RAJ"]
_LAST_NAMES = ["SMITH", "NG", "GARCIA", "BROWN", "TAYLOR", "KHAN", "LI", "LEE"]
_STATES = ["AL", "AK", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI", "IA",
           "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO",
           "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK",
           "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY"]

import random as _r

def _synth_value(kind: str, i: int) -> str:
    kind = (kind or "").lower()
    if "email" in kind:
        return f"user{i}@example.com"
    if "first" in kind and "name" in kind:
        return _r.choice(_FIRST_NAMES)
    if "last" in kind and "name" in kind:
        return _r.choice(_LAST_NAMES)
    if "phone" in kind:
        return f"{_r.randint(200, 989)}-{_r.randint(100, 999)}-{_r.randint(1000, 9999)}"
    if "address" in kind:
        return f"{_r.randint(100, 9999)} Main St, City, {_r.choice(_STATES)} {_r.randint(10000, 99999)}"
    if "amount" in kind or "loan" in kind or "balance" in kind:
        return f"{_r.randint(100, 99999)}.{_r.randint(0, 99):02d}"
    return f"value_{i}"

def _synth_dataframe(n: int, columns: list[str]) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append([_synth_value(col, i) for col in columns])
    return pd.DataFrame(rows, columns=columns)


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
        ACCENT = wx.Colour(70, 130, 180)

        self.SetBackgroundColour(BG)
        main = wx.BoxSizer(wx.VERTICAL)

        # Header row: banner + centered title (no overlays)
        header_bg = wx.Colour(28, 28, 28)
        header_row = wx.BoxSizer(wx.HORIZONTAL)

        self.banner = HeaderBanner(self, height=160, bg=header_bg)
        header_row.Add(self.banner, 0, wx.EXPAND)

        title_panel = wx.Panel(self)
        title_panel.SetBackgroundColour(header_bg)
        title = wx.StaticText(title_panel, label="Sidecar Application: Data Governance")
        title.SetFont(wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(wx.Colour(240, 240, 240))
        tps = wx.BoxSizer(wx.HORIZONTAL)
        tps.AddStretchSpacer()
        tps.Add(title, 0, wx.ALIGN_CENTER_VERTICAL)
        tps.AddStretchSpacer()
        title_panel.SetSizer(tps)

        header_row.Add(title_panel, 1, wx.EXPAND)
        main.Add(header_row, 0, wx.EXPAND)

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

        # Toolbar
        toolbar_panel = wx.Panel(self)
        toolbar_panel.SetBackgroundColour(PANEL)
        toolbar = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(label, handler):
            b = wx.Button(toolbar_panel, label=label)
            b.SetBackgroundColour(ACCENT)
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
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
        lab.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        hz.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)

        self.knowledge_line = wx.StaticText(info_panel, label="(none)")
        self.knowledge_line.SetForegroundColour(wx.Colour(210, 210, 210))
        self.knowledge_line.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
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
        self.grid.SetLabelFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)

        vbox.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)
        grid_panel.SetSizer(vbox)
        main.Add(grid_panel, 1, wx.EXPAND)

        self.SetSizer(main)

    # -------------------------------------------- actions
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

    def on_load_s3(self, _):
        uri = wx.GetTextFromUser("Enter HTTP(S) or S3 URI:", "Load from URI/S3")
        if not uri:
            return
        try:
            text = download_text_from_uri(uri)
            self.headers, self.raw_data = detect_and_split_data(text)
            self._display(self.headers, self.raw_data)
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
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                    for r in range(self.grid.GetNumberRows())]
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
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                    for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep="\t")
            wx.MessageBox("TXT exported.", "Export", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, _):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                for r in range(self.grid.GetNumberRows())]
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

    # ------------------------------- grid utils
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
