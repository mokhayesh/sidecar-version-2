import wx
import wx.grid as gridlib
import pandas as pd
import csv
from datetime import datetime

from app.settings import SettingsWindow, save_defaults, defaults
from app.dialogs import QualityRuleDialog, DataBuddyDialog
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,
    compliance_analysis
)
from app.s3_utils import download_text_from_uri, upload_to_s3

class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1120, 780))
        self.raw_data = []
        self.headers = []
        self.current_process = ""
        self.quality_rules = {}
        self._build_ui()
        self.Centre()
        self.Show()

    def _build_ui(self):
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(wx.Colour(245, 245, 245))  # light neutral gray
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(pnl, label="🚀  Sidecar Application: Data Governance")
        title_font = wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        title.SetForegroundColour(wx.Colour(40, 50, 75))  # professional slate blue
        vbox.Add(title, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        # menu bar
        mb = wx.MenuBar()
        m_file, m_set = wx.Menu(), wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        mb.Append(m_file, "&File")
        mb.Append(m_set, "&Settings")
        self.SetMenuBar(mb)

        # toolbar
        buttons = [
            ("Load File", self.on_load_file),
            ("Load from URI/S3", self.on_load_s3),
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
        toolbar = wx.WrapSizer(wx.HORIZONTAL)
        for label, fn, *rest in buttons:
            btn = wx.Button(pnl, label=label)
            btn.SetBackgroundColour(wx.Colour(70, 130, 180))  # steel blue
            btn.SetForegroundColour(wx.WHITE)
            btn.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM))
            btn.Bind(wx.EVT_BUTTON, fn)
            if rest:
                btn.process = rest[0]
            toolbar.Add(btn, 0, wx.ALL, 4)
        vbox.Add(toolbar, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 6)

        # data grid
        self.grid = gridlib.Grid(pnl)
        self.grid.CreateGrid(0, 0)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(255, 255, 255))
        self.grid.SetDefaultCellTextColour(wx.Colour(0, 0, 0))
        self.grid.SetLabelBackgroundColour(wx.Colour(230, 230, 230))
        self.grid.SetLabelFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        vbox.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)

        pnl.SetSizer(vbox)

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
                    self.grid.SetCellBackgroundColour(r, c, wx.Colour(245, 245, 245))  # alternate row color

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
            "Compliance": compliance_analysis
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
        wx.MessageBox(upload_to_s3(self.current_process or "Unknown", hdr, data),
                      "Upload", wx.OK | wx.ICON_INFORMATION)
