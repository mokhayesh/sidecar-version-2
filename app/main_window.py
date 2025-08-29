import os
import wx
import wx.grid as gridlib
import pandas as pd

from app.settings import SettingsWindow
from app.dialogs import QualityRuleDialog, DataBuddyDialog, SyntheticDataDialog
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,
    compliance_analysis,
)
from app.s3_utils import download_text_from_uri, upload_to_s3


class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Data Quality", size=(1200, 800))

        # App icon (tries several common locations)
        for p in [
            os.path.join("assets", "sidecar.ico"),
            os.path.join("assets", "sidecar-01.ico"),
            "/mnt/data/sidecar-01.ico",
            "sidecar.ico",
        ]:
            if os.path.exists(p):
                try:
                    self.SetIcon(wx.Icon(p, wx.BITMAP_TYPE_ICO))
                    break
                except Exception:
                    pass

        self.raw_data = []
        self.headers = []
        self.current_process = ""
        self.quality_rules = {}

        self._build_ui()
        self.Centre()
        self.Show()

    def _build_ui(self):
        # Palette
        BG_FRAME   = wx.Colour(26, 26, 26)   # window frame
        BG_PANEL   = wx.Colour(32, 32, 32)   # main content panel (sides)
        BG_HEADER  = wx.Colour(22, 22, 22)   # header band (title + buttons) → darker grey
        TXT_PRIMARY = wx.Colour(225, 225, 225)
        ACCENT     = wx.Colour(70, 130, 180)

        GRID_BG      = wx.Colour(45, 45, 45)
        GRID_ALT     = wx.Colour(40, 40, 40)
        GRID_TXT     = wx.Colour(235, 235, 235)
        GRID_HDR_BG  = wx.Colour(58, 58, 58)  # column/row label background (side darker)
        GRID_HDR_TXT = wx.Colour(245, 245, 245)

        self.SetBackgroundColour(BG_FRAME)

        # Root content panel (so sides/outside grid are dark)
        root = wx.Panel(self)
        root.SetBackgroundColour(BG_PANEL)
        root_sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Header band (darker grey) ───────────────────────────────────────
        header = wx.Panel(root)
        header.SetBackgroundColour(BG_HEADER)
        header_sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(header, label="🏍️🛺  Sidecar Data Quality")
        title.SetFont(wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(TXT_PRIMARY)
        header_sizer.Add(title, 0, wx.ALIGN_CENTER | wx.ALL, 8)

        # Toolbar container so we can color its background
        tb_panel = wx.Panel(header)
        tb_panel.SetBackgroundColour(BG_HEADER)
        tb_sizer = wx.WrapSizer(wx.HORIZONTAL)

        buttons = [
            ("Load File", self.on_load_file),
            ("Load from URI/S3", self.on_load_s3),

            ("Generate Synthetic Data", self.on_generate_synth),  # ← new button

            ("Quality Rule Assignment", self.on_rules),
            ("Profile", self.do_analysis, "Profile"),
            ("Quality", self.do_analysis, "Quality"),
            ("Catalog", self.do_analysis, "Catalog"),
            ("Compliance", self.do_analysis, "Compliance"),
            ("Little Buddy", self.on_buddy),
            ("Export CSV", self.on_export_csv),
            ("Export TXT", self.on_export_txt),
            ("Upload to S3", self.on_upload_s3),
        ]
        for label, fn, *rest in buttons:
            btn = wx.Button(tb_panel, label=label)
            btn.SetBackgroundColour(ACCENT)
            btn.SetForegroundColour(wx.WHITE)
            btn.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, fn)
            if rest:
                btn.process = rest[0]
            tb_sizer.Add(btn, 0, wx.ALL, 4)

        tb_panel.SetSizer(tb_sizer)
        header_sizer.Add(tb_panel, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)
        header.SetSizer(header_sizer)

        # ── Menu bar (OS-styled; colors typically unmanaged) ───────────────
        mb = wx.MenuBar()
        m_file, m_set = wx.Menu(), wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        mb.Append(m_file, "&File")
        mb.Append(m_set, "&Settings")
        self.SetMenuBar(mb)

        # ── Grid (side/labels now darker via GRID_HDR_BG) ───────────────────
        self.grid = gridlib.Grid(root)
        self.grid.CreateGrid(0, 0)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)

        self.grid.SetDefaultCellBackgroundColour(GRID_BG)
        self.grid.SetDefaultCellTextColour(GRID_TXT)
        self.grid.SetGridLineColour(wx.Colour(80, 80, 80))

        # darken both column and row labels (left “side” too)
        self.grid.SetLabelBackgroundColour(GRID_HDR_BG)
        self.grid.SetLabelTextColour(GRID_HDR_TXT)
        self.grid.SetLabelFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        # optional: widen row-label area a touch and center text
        self.grid.SetRowLabelSize(46)
        self.grid.SetRowLabelAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)

        # layout
        root_sizer.Add(header, 0, wx.EXPAND)                           # dark header band
        root_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)            # content
        root.SetSizer(root_sizer)

    # ── Display helpers ─────────────────────────────────────────────────────
    def _display(self, hdr, data):
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        self.grid.AppendCols(len(hdr))
        for i, h in enumerate(hdr):
            self.grid.SetColLabelValue(i, h)

        self.grid.AppendRows(len(data))
        for r, row in enumerate(data):
            for c, val in enumerate(row):
                self.grid.SetCellValue(r, c, str(val))
                if r % 2 == 0:
                    self.grid.SetCellBackgroundColour(r, c, wx.Colour(40, 40, 40))  # alternate darker stripe
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

    # ── Menu / toolbar handlers ─────────────────────────────────────────────
    def on_settings(self, _):
        SettingsWindow(self).Show()

    def on_load_file(self, _):
        dlg = wx.FileDialog(self, "Open CSV/TXT", wildcard="CSV/TXT|*.csv;*.txt",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            return
        text = open(dlg.GetPath(), "r", encoding="utf-8").read()
        dlg.Destroy()
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

    def do_analysis(self, evt):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        proc = evt.GetEventObject().process
        self.current_process = proc
        df = pd.DataFrame(self.raw_data, columns=self.headers)
        func = {
            "Profile": profile_analysis,
            "Quality": lambda d: quality_analysis(d, self.quality_rules),
            "Catalog": catalog_analysis,
            "Compliance": compliance_analysis,
        }[proc]
        hdr, data = func(df)
        self._display(hdr, data)
        wx.MessageBox(upload_to_s3(proc, hdr, data), "Analysis", wx.OK | wx.ICON_INFORMATION)

    def on_rules(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

    def on_buddy(self, _):
        DataBuddyDialog(self, self.raw_data, self.headers).ShowModal()

    def _export(self, path, sep):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                for r in range(self.grid.GetNumberRows())]
        pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=sep)

    def on_export_csv(self, _):
        dlg = wx.FileDialog(self, "Save CSV", wildcard="CSV|*.csv",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return
        self._export(dlg.GetPath(), ",")
        dlg.Destroy()
        wx.MessageBox("CSV exported.", "Export", wx.OK | wx.ICON_INFORMATION)

    def on_export_txt(self, _):
        dlg = wx.FileDialog(self, "Save TXT", wildcard="TXT|*.txt",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return
        self._export(dlg.GetPath(), "\t")
        dlg.Destroy()
        wx.MessageBox("TXT exported.", "Export", wx.OK | wx.ICON_INFORMATION)

    def on_upload_s3(self, _):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                for r in range(self.grid.GetNumberRows())]
        wx.MessageBox(
            upload_to_s3(self.current_process or "Unknown", hdr, data),
            "Upload",
            wx.OK | wx.ICON_INFORMATION,
        )

    # ── Synthetic data generation ───────────────────────────────────────────
    def on_generate_synth(self, _):
        if not self.headers or not self.raw_data:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return

        dlg = SyntheticDataDialog(self, self.headers)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        n, fields = dlg.get_values()
        dlg.Destroy()
        if not fields:
            wx.MessageBox("Select at least one field.", "No fields selected", wx.OK | wx.ICON_WARNING)
            return

        df = pd.DataFrame(self.raw_data, columns=self.headers)
        synth = self._generate_synthetic_df(df, fields, n)

        # show the generated dataset
        self.headers = list(synth.columns)
        self.raw_data = synth.values.tolist()
        self._display(self.headers, self.raw_data)

        wx.MessageBox(f"Generated {n} synthetic record(s) using {len(fields)} field(s).",
                      "Synthetic Data", wx.OK | wx.ICON_INFORMATION)

    def _generate_synthetic_df(self, df: pd.DataFrame, fields, n_rows: int) -> pd.DataFrame:
        """
        Generate synthetic data by bootstrapping (sample with replacement) each selected column.
        This preserves the empirical distribution without inventing unseen categories/values.
        """
        out = {}
        for col in fields:
            s = df[col]
            s_nonnull = s.dropna()

            # If column is empty, fill blanks
            if s_nonnull.empty:
                out[col] = [""] * n_rows
                continue

            # Date/time handling
            if pd.api.types.is_datetime64_any_dtype(s) or "date" in col.lower() or "time" in col.lower():
                dt = pd.to_datetime(s_nonnull, errors="coerce").dropna()
                if dt.empty:
                    out[col] = s_nonnull.astype(str).sample(n=n_rows, replace=True).reset_index(drop=True).tolist()
                else:
                    sampled = dt.sample(n=n_rows, replace=True).reset_index(drop=True)
                    out[col] = sampled.dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
                continue

            # Numeric
            if pd.api.types.is_numeric_dtype(s):
                sampled = s_nonnull.sample(n=n_rows, replace=True).reset_index(drop=True)
                if pd.api.types.is_integer_dtype(s.dtype):
                    sampled = sampled.round(0).astype("Int64").astype(object).where(sampled.notna(), None)
                out[col] = sampled.tolist()
                continue

            # Text / categorical
            out[col] = s_nonnull.astype(str).sample(n=n_rows, replace=True).reset_index(drop=True).tolist()

        return pd.DataFrame(out)
