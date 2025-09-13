# app/preview_lavender.py
import os
import sys
import wx
import wx.grid as gridlib

# --- Robust imports so it works whether you run from repo root or from app/ ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(THIS_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    # Works when you run from the repo root:  python -m app.preview_lavender
    from app.theme_lavender import LavTheme, CardButton, KPIChipLight, ChipTag, LittleBuddyDock
except ModuleNotFoundError:
    # Works when you run from inside app/:  python preview_lavender.py
    from theme_lavender import LavTheme, CardButton, KPIChipLight, ChipTag, LittleBuddyDock


class LavenderPreviewFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Data Buddy — Lavender Preview", size=(1080, 720))
        self.SetBackgroundColour(LavTheme.bg)
        v = wx.BoxSizer(wx.VERTICAL)

        # Header band
        header = wx.Panel(self)
        header.SetBackgroundColour(LavTheme.panel)
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        title = wx.StaticText(header, label="Data Buddy")
        title.SetFont(wx.Font(18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(LavTheme.purple)

        hbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)
        hbox.AddStretchSpacer()

        self.help_btn = CardButton(header, "Little Buddy", handler=self._toggle_buddy, width=140)
        hbox.Add(self.help_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        header.SetSizer(hbox)
        v.Add(header, 0, wx.EXPAND)

        # KPI row (8 cards)
        kpis = wx.BoxSizer(wx.HORIZONTAL)
        self.k_rows = KPIChipLight(self, "Rows", "2734")
        self.k_cols = KPIChipLight(self, "Columns", "12")
        self.k_null = KPIChipLight(self, "Null %", "1.2%")
        self.k_uniq = KPIChipLight(self, "Uniqueness", "91.4%")
        self.k_dq   = KPIChipLight(self, "DQ Score", "86.3")
        self.k_val  = KPIChipLight(self, "Validity", "88.0%")
        self.k_cmp  = KPIChipLight(self, "Completeness", "96.2%")
        self.k_anom = KPIChipLight(self, "Anomalies", "12")
        for c in (self.k_rows, self.k_cols, self.k_null, self.k_uniq,
                  self.k_dq, self.k_val, self.k_cmp, self.k_anom):
            kpis.Add(c, 0, wx.ALL, LavTheme.gap)
        v.Add(kpis, 0, wx.LEFT | wx.RIGHT | wx.TOP, LavTheme.gap)

        # App buttons row (white cards)
        tools = wx.WrapSizer(wx.HORIZONTAL)

        def noop(_):
            wx.MessageBox("Preview only — your real handlers stay untouched.", "Preview")

        for label in ("Upload", "Profile", "Quality", "Catalog", "Anomalies", "Optimizer", "To Do"):
            tools.Add(CardButton(self, label, handler=noop, width=120), 0, wx.ALL, LavTheme.gap)
        v.Add(tools, 0, wx.LEFT | wx.RIGHT | wx.TOP, LavTheme.gap)

        # “Cataloging complete.” & table
        body = wx.BoxSizer(wx.VERTICAL)
        done = wx.StaticText(self, label="Cataloging complete.")
        done.SetForegroundColour(LavTheme.text)
        done.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        body.Add(done, 0, wx.LEFT | wx.TOP, 14)

        grid = gridlib.Grid(self)
        grid.CreateGrid(0, 0)
        grid.AppendCols(3)
        for i, l in enumerate(["Title", "Rows", "Description"]):
            grid.SetColLabelValue(i, l)
        rows = [
            ["Knowledge Base", "2734", "Knowledge docs and policies"],
            ["Employees.csv",  "418",  "HR employee roster"],
        ]
        grid.AppendRows(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                grid.SetCellValue(r, c, str(val))
        grid.SetLabelBackgroundColour(wx.Colour(245, 245, 252))
        grid.SetLabelTextColour(LavTheme.muted)
        grid.SetDefaultCellBackgroundColour(wx.Colour(255, 255, 255))
        grid.SetDefaultCellTextColour(LavTheme.text)
        grid.EnableEditing(False)
        grid.SetRowLabelSize(0)
        grid.AutoSizeColumns(False)
        grid.SetColSize(0, 260)
        grid.SetColSize(1, 80)
        grid.SetColSize(2, 400)
        body.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        v.Add(body, 1, wx.EXPAND)

        # Knowledge Files chips
        chips_panel = wx.Panel(self)
        chips_panel.SetBackgroundColour(LavTheme.bg)
        chips = wx.WrapSizer(wx.HORIZONTAL)
        chips.Add(ChipTag(chips_panel, "Kernel.json"), 0, wx.ALL, 4)
        chips.Add(ChipTag(chips_panel, "vacation-policy.pdf"), 0, wx.ALL, 4)
        chips_panel.SetSizer(chips)
        v.Add(chips_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.SetSizer(v)
        self.CenterOnScreen()

        # Little Buddy fly-out
        self._dock = LittleBuddyDock(self, self._on_buddy_search)
        self._dock.Hide()

    def _toggle_buddy(self, _evt):
        if self._dock.IsShown():
            self._dock.Hide()
            return
        scr = self.GetClientSize()
        pos = self.ClientToScreen(wx.Point(scr.x - 380, 160))
        self._dock.SetPosition(pos)
        self._dock.Show()

    def _on_buddy_search(self, query):
        wx.MessageBox(
            f"Preview would open your real Little Buddy with query:\n\n{query}",
            "Little Buddy (Preview)"
        )

if __name__ == "__main__":
    app = wx.App(False)
    LavenderPreviewFrame().Show()
    app.MainLoop()
