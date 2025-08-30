import os
import csv
import wx
import wx.grid as gridlib
import pandas as pd

from app.settings import SettingsWindow, save_defaults, defaults
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
        super().__init__(None, title="Sidecar Data Quality", size=(1120, 780))

        # App icon (upper-left corner)
        try:
            icon = wx.Icon("assets/sidecar-01.ico", wx.BITMAP_TYPE_ICO)
            self.SetIcon(icon)
        except Exception:
            pass

        self.raw_data = []
        self.headers = []
        self.current_process = ""
        self.quality_rules = {}

        # Knowledge files live here: list[dict(name,path,type,content?)]
        self.knowledge_files = []

        self._build_ui()
        self.Centre()
        self.Show()

    # ────────────────────────────────────────────────────────────────── UI
    def _build_ui(self):
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(wx.Colour(40, 40, 40))
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Title row
        title = wx.StaticText(pnl, label="🏍️🛺 Sidecar Data Quality")
        title.SetFont(wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(wx.Colour(230, 230, 230))
        vbox.Add(title, 0, wx.ALIGN_CENTER | wx.ALL, 8)

        # Menu
        mb = wx.MenuBar()
        m_file, m_set = wx.Menu(), wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        mb.Append(m_file, "&File")
        mb.Append(m_set, "&Settings")
        self.SetMenuBar(mb)

        # Toolbar (dark chip row)
        toolbar_bg = wx.Panel(pnl)
        toolbar_bg.SetBackgroundColour(wx.Colour(28, 28, 28))
        tb = wx.WrapSizer(wx.HORIZONTAL)
        toolbar_bg.SetSizer(tb)

        def make_btn(lbl, handler, process: str | None = None):
            btn = wx.Button(toolbar_bg, label=lbl)
            btn.SetBackgroundColour(wx.Colour(70, 130, 180))
            btn.SetForegroundColour(wx.WHITE)
            btn.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, handler)
            if process:
                btn.process = process
            tb.Add(btn, 0, wx.ALL, 4)
            return btn

        # Buttons (order matters)
        self.btn_load_knowledge = make_btn("Load Knowledge Files", self.on_load_knowledge)
        make_btn("Load File", self.on_load_file)
        make_btn("Load from URI/S3", self.on_load_s3)
        make_btn("Generate Synthetic Data", self.on_generate_synth)
        make_btn("Quality Rule Assignment", self.on_rules)
        make_btn("Profile", self.do_analysis, "Profile")
        make_btn("Quality", self.do_analysis, "Quality")
        # Detect Anomalies button
        make_btn("Detect Anomalies", self.on_detect_anomalies)
        make_btn("Catalog", self.do_analysis, "Catalog")
        make_btn("Compliance", self.do_analysis, "Compliance")
        make_btn("Little Buddy", self.on_buddy)
        make_btn("Export CSV", self.on_export_csv)
        make_btn("Export TXT", self.on_export_txt)
        make_btn("Upload to S3", self.on_upload_s3)

        vbox.Add(toolbar_bg, 0, wx.EXPAND)

        # Knowledge strip (separate row so it never overlaps toolbar)
        strip = wx.Panel(pnl)
        strip.SetBackgroundColour(wx.Colour(36, 36, 36))
        strip_sizer = wx.BoxSizer(wx.HORIZONTAL)
        strip.SetSizer(strip_sizer)

        lbl = wx.StaticText(strip, label="Knowledge Files:")
        lbl.SetForegroundColour(wx.Colour(180, 200, 225))
        lbl.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        strip_sizer.Add(lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)

        self.knowledge_label = wx.StaticText(strip, label="None")
        self.knowledge_label.SetForegroundColour(wx.Colour(215, 215, 215))
        self.knowledge_label.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        strip_sizer.Add(self.knowledge_label, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)

        vbox.Add(strip, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

        # Data grid
        self.grid = gridlib.Grid(pnl)
        self.grid.CreateGrid(0, 0)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(55, 55, 55))
        self.grid.SetDefaultCellTextColour(wx.Colour(220, 220, 220))
        self.grid.SetLabelBackgroundColour(wx.Colour(80, 80, 80))
        self.grid.SetLabelTextColour(wx.Colour(240, 240, 240))
        self.grid.SetLabelFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        vbox.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)

        pnl.SetSizer(vbox)

    # ─────────────────────────────────────────────────────── knowledge strip
    def _refresh_knowledge_strip(self):
        if not self.knowledge_files:
            txt = "None"
        else:
            names = [kf["name"] for kf in self.knowledge_files]
            txt = "   •   ".join(names)
        self.knowledge_label.SetLabel(txt)
        try:
            width = self.GetClientSize().GetWidth() - 150
            if width > 150:
                self.knowledge_label.Wrap(width)
        except Exception:
            pass
        self.Layout()

    # ────────────────────────────────────────────────────────── data render
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

    # ───────────────────────────────────────────────────── menu / toolbar
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

    def on_generate_synth(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        dlg = SyntheticDataDialog(self, self.headers)
        if dlg.ShowModal() == wx.ID_OK:
            n, fields = dlg.get_values()
            # simple synthetic generation: repeat the header values with counters
            rows = []
            for i in range(n):
                row = []
                for col in self.headers:
                    if col not in fields:
                        row.append("")
                    else:
                        row.append(f"Synth_{col}_{i+1}")
                rows.append(row)
            self._display(self.headers, rows)
            wx.MessageBox(upload_to_s3("Synthetic", self.headers, rows), "Synthetic", wx.OK | wx.ICON_INFORMATION)
        dlg.Destroy()

    def on_rules(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

    def on_buddy(self, _):
        DataBuddyDialog(self, self.raw_data, self.headers, knowledge=self.knowledge_files).ShowModal()

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
        wx.MessageBox(upload_to_s3(self.current_process or "Unknown", hdr, data),
                      "Upload", wx.OK | wx.ICON_INFORMATION)

    # ───────────────────────────────────────────────── knowledge loading
    def on_load_knowledge(self, _):
        """Allow selecting multiple files and show their names under the toolbar."""
        wildcard = (
            "Knowledge files (*.txt;*.csv;*.json;*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp)|"
            "*.txt;*.csv;*.json;*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp|"
            "All files (*.*)|*.*"
        )
        dlg = wx.FileDialog(
            self,
            "Select Knowledge Files",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        paths = dlg.GetPaths()
        dlg.Destroy()

        added = 0
        for p in paths:
            try:
                base = os.path.basename(p)
                ext = os.path.splitext(base)[1].lower()

                # Avoid duplicates by path
                if any(kf["path"] == p for kf in self.knowledge_files):
                    continue

                entry = {"name": base, "path": p, "type": "binary", "content": None}

                if ext in {".txt", ".csv", ".json"}:
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            entry["content"] = f.read(100_000)  # keep first 100 KB
                        entry["type"] = "text"
                    except Exception:
                        entry["type"] = "text"
                        entry["content"] = None
                elif ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
                    entry["type"] = "image"
                else:
                    entry["type"] = "binary"

                self.knowledge_files.append(entry)
                added += 1
            except Exception:
                continue

        self._refresh_knowledge_strip()
        if added:
            wx.MessageBox(f"Loaded {added} knowledge file(s).", "Knowledge", wx.OK | wx.ICON_INFORMATION)

    # ───────────────────────────────────────────────────── analyses & misc
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

    def on_detect_anomalies(self, _):
        """Simple anomaly detector: flags empty values and overly long strings."""
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        df = pd.DataFrame(self.raw_data, columns=self.headers)

        rows = []
        for r_idx, row in df.iterrows():
            for col, val in row.items():
                s = str(val)
                reason = None
                rec = None
                if s.strip() == "" or s.lower() in {"nan", "none", "null"}:
                    reason = "Missing/blank value"
                    rec = f"Impute or remove row; ensure '{col}' has required data"
                elif len(s) > 128:
                    reason = "Unusually long value"
                    rec = f"Trim or validate length for '{col}'"
                if reason:
                    rows.append([r_idx + 1, col, val, reason, rec])

        hdr = ["Row", "Field", "Value", "Reason", "Recommendation"]
        self._display(hdr, rows if rows else [["-", "-", "-", "No obvious anomalies found", "-"]])
