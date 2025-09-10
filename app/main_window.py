# app/main_window.py
import wx
import wx.grid as gridlib
import pandas as pd
from datetime import datetime
import os

# ============================================================
# Font helper (compatible with wx 4.x)
# ============================================================
def mkfont(size=9, bold=False):
    return wx.Font(
        pointSize=size,
        family=wx.FONTFAMILY_SWISS,
        style=wx.FONTSTYLE_NORMAL,
        weight=(wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL),
    )

# ============================================================
# Header helpers (pill, metric cards, quick buttons)
# ============================================================
class Pill(wx.Panel):
    def __init__(self, parent, label, color=wx.Colour(90, 72, 198)):
        super().__init__(parent)
        self.SetBackgroundColour(color)
        s = wx.BoxSizer(wx.HORIZONTAL)

        self.dot = wx.Panel(self, size=(8, 8))
        self.dot.SetBackgroundColour(wx.Colour(102, 255, 153))
        self.dot.Bind(wx.EVT_PAINT, self._paint_dot)

        txt = wx.StaticText(self, label=label.upper())
        txt.SetFont(mkfont(8, True))
        txt.SetForegroundColour(wx.WHITE)

        s.Add(self.dot, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        s.Add(txt, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 10)
        self.SetSizer(s)

    def _paint_dot(self, evt):
        dc = wx.PaintDC(self.dot)
        w, h = self.dot.GetClientSize()
        dc.SetBrush(wx.Brush(self.dot.GetBackgroundColour()))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawCircle(w // 2, h // 2, min(w, h) // 2)

    def set_ok(self, ok: bool):
        self.dot.SetBackgroundColour(wx.Colour(102, 255, 153) if ok else wx.Colour(255, 102, 102))
        self.dot.Refresh()


class MetricCard(wx.Panel):
    def __init__(self, parent, title, value="—", accent=wx.Colour(120, 99, 255)):
        super().__init__(parent)
        self.SetBackgroundColour(wx.Colour(46, 46, 56))
        v = wx.BoxSizer(wx.VERTICAL)

        t = wx.StaticText(self, label=title.upper())
        t.SetFont(mkfont(8, True))
        t.SetForegroundColour(wx.Colour(190, 190, 198))

        self.val = wx.StaticText(self, label=str(value))
        self.val.SetFont(mkfont(14, True))
        self.val.SetForegroundColour(wx.WHITE)

        bar = wx.Panel(self, size=(-1, 3))
        bar.SetBackgroundColour(accent)

        v.Add(t, 0, wx.ALL, 6)
        v.Add(self.val, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        v.Add(bar, 0, wx.EXPAND)
        self.SetSizer(v)

    def set(self, value):
        self.val.SetLabel(str(value))


class QuickBtn(wx.Button):
    def __init__(self, parent, label, handler):
        super().__init__(parent, label=label, style=wx.BU_EXACTFIT)
        self.SetMinSize((140, 34))
        self.SetBackgroundColour(wx.Colour(236, 230, 255))
        self.SetForegroundColour(wx.Colour(45, 33, 88))
        self.SetFont(mkfont(9, True))
        self.Bind(wx.EVT_BUTTON, handler)


# ============================================================
# Main Window
# ============================================================
class MainWindow(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, title="Data Buddy — Sidecar Application",
                          size=(1280, 800))
        self.Centre()
        self.SetBackgroundColour(wx.Colour(32, 32, 38))

        # dataset
        self.current_path = None
        self.df: pd.DataFrame | None = None

        self._build_ui()
        self.Show()

    # ---------------- UI build ----------------
    def _build_ui(self):
        main = wx.BoxSizer(wx.VERTICAL)

        # Header band (professional command center)
        header = self._build_header(self)
        main.Add(header, 0, wx.EXPAND)

        # Toolbar (your existing buttons)
        toolbar = self._build_toolbar(self)
        main.Add(toolbar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Knowledge files label strip (kept to match your layout)
        kn_panel = wx.Panel(self)
        kn_panel.SetBackgroundColour(wx.Colour(40, 40, 48))
        kn_s = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(kn_panel, label="Knowledge Files:")
        lab.SetFont(mkfont(9, True))
        lab.SetForegroundColour(wx.Colour(210, 210, 220))
        self.kn_list = wx.StaticText(kn_panel, label="(none)")
        self.kn_list.SetFont(mkfont(9))
        self.kn_list.SetForegroundColour(wx.Colour(190, 190, 200))
        kn_s.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        kn_s.Add(self.kn_list, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        kn_panel.SetSizer(kn_s)
        main.Add(kn_panel, 0, wx.EXPAND)

        # Insights drawer (collapsible)
        self.insights = wx.CollapsiblePane(self, label="Insights from last run")
        pane = self.insights.GetPane()
        box = wx.BoxSizer(wx.VERTICAL)
        self.insights_out = wx.TextCtrl(
            pane, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.insights_out.SetMinSize((100, 80))
        self.insights_out.SetBackgroundColour(wx.Colour(46, 46, 54))
        self.insights_out.SetForegroundColour(wx.Colour(230, 230, 238))
        self.insights_out.SetFont(mkfont(9))
        box.Add(self.insights_out, 1, wx.EXPAND)
        pane.SetSizer(box)
        main.Add(self.insights, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Grid (central data area)
        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 0)
        self.grid.EnableEditing(False)
        self.grid.SetDefaultCellAlignment(wx.ALIGN_LEFT, wx.ALIGN_CENTER_VERTICAL)
        main.Add(self.grid, 1, wx.EXPAND | wx.ALL, 6)

        self.SetSizer(main)

    def _build_header(self, parent):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(wx.Colour(36, 36, 44))
        s = wx.BoxSizer(wx.VERTICAL)

        # Top row: Title + env pill + search
        top = wx.BoxSizer(wx.HORIZONTAL)

        title = wx.StaticText(panel, label="Data Buddy — Sidecar Application")
        title.SetFont(mkfont(16, True))
        title.SetForegroundColour(wx.WHITE)

        self.env_pill = Pill(panel, "LOCAL")
        self.search = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Search or type /command…")
        self.search.SetMinSize((360, -1))
        self.search.Bind(wx.EVT_TEXT_ENTER, self._on_header_search)

        top.Add(title, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        top.AddSpacer(10)
        top.Add(self.env_pill, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        top.AddStretchSpacer(1)
        top.Add(self.search, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)

        # KPI strip
        kpis = wx.BoxSizer(wx.HORIZONTAL)
        self.card_rows    = MetricCard(panel, "Rows", "—", wx.Colour(120, 99, 255))
        self.card_cols    = MetricCard(panel, "Columns", "—", wx.Colour(151, 133, 255))
        self.card_nulls   = MetricCard(panel, "Null %", "—", wx.Colour(187, 168, 255))
        self.card_quality = MetricCard(panel, "DQ Score", "—", wx.Colour(255, 207, 92))
        self.card_anoms   = MetricCard(panel, "Anomalies", "—", wx.Colour(255, 113, 113))
        for c in (self.card_rows, self.card_cols, self.card_nulls, self.card_quality, self.card_anoms):
            kpis.Add(c, 0, wx.ALL, 6)

        # Quick actions
        qa = wx.BoxSizer(wx.HORIZONTAL)
        qa.Add(QuickBtn(panel, "Profile",            self.on_profile), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Quality",            self.on_quality), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Catalog",            self.on_catalog), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Detect Anomalies",   self.on_anomalies), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Compliance",         self.on_compliance), 0, wx.ALL, 4)

        # Build header
        s.Add(top, 0, wx.EXPAND)
        s.Add(kpis, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        s.Add(qa,   0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # bottom hairline
        rule = wx.Panel(panel, size=(-1, 1))
        rule.SetBackgroundColour(wx.Colour(58, 58, 66))
        s.Add(rule, 0, wx.EXPAND)

        panel.SetSizer(s)
        return panel

    def _build_toolbar(self, parent):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(wx.Colour(40, 40, 48))
        s = wx.WrapSizer(wx.HORIZONTAL)

        # match your existing labels
        def add_btn(label, handler):
            b = wx.Button(panel, label=label)
            b.SetBackgroundColour(wx.Colour(121, 103, 255))
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(mkfont(9, True))
            b.SetMinSize((160, 36))
            b.Bind(wx.EVT_BUTTON, handler)
            s.Add(b, 0, wx.ALL, 6)
            return b

        add_btn("Load Knowledge Files", self.on_load_knowledge)
        add_btn("Load File",            self.on_load_file)
        add_btn("Load from URI/S3",     self.on_load_from_uri)
        add_btn("Generate Synthetic Data", self.on_generate_synth)
        add_btn("Quality Rule Assignment", self.on_quality_rules)
        add_btn("Profile",              self.on_profile)
        add_btn("Quality",              self.on_quality)
        add_btn("DetectAnomalies",      self.on_anomalies)
        add_btn("Catalog",              self.on_catalog)
        add_btn("Compliance",           self.on_compliance)
        add_btn("Little Buddy",         self.on_little_buddy)
        add_btn("Export CSV",           self.on_export_csv)
        add_btn("Export TXT",           self.on_export_txt)
        add_btn("Upload to S3",         self.on_upload_s3)

        panel.SetSizer(s)
        return panel

    # ---------------- Header hooks ----------------
    def _on_header_search(self, evt):
        q = self.search.GetValue().strip()
        if not q:
            return
        if q.startswith("/"):
            cmd = q[1:].lower()
            mapping = {
                "profile": self.on_profile,
                "quality": self.on_quality,
                "catalog": self.on_catalog,
                "anomalies": self.on_anomalies,
                "compliance": self.on_compliance,
                "open": self.on_load_file,
            }
            if cmd in mapping:
                mapping[cmd](None)
            else:
                wx.MessageBox(f"Unknown command: {cmd}", "Command",
                              wx.OK | wx.ICON_INFORMATION)
        else:
            # hook to your knowledge/file search if desired
            wx.MessageBox(f"Search: {q}", "Search",
                          wx.OK | wx.ICON_INFORMATION)

    def update_header_stats(self, *, rows=None, cols=None, null_pct=None, dq_score=None, anomalies=None):
        if rows      is not None: self.card_rows.set(rows)
        if cols      is not None: self.card_cols.set(cols)
        if null_pct  is not None: self.card_nulls.set(f"{null_pct:.1f}%")
        if dq_score  is not None: self.card_quality.set(f"{dq_score:.0f}")
        if anomalies is not None: self.card_anoms.set(anomalies)

    def update_last_run(self, when: str | None = None):
        when = when or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.search.SetDescriptiveText(f"Search or type /command…  (Last run: {when})")

    def set_environment(self, name="LOCAL", ok=True):
        # relabel pill (simple rebuild of child text)
        parent = self.env_pill.GetParent()
        self.env_pill.Destroy()
        self.env_pill = Pill(parent, name, wx.Colour(90, 72, 198))
        self.env_pill.set_ok(ok)
        parent.Layout()

    def insights_append(self, msg: str):
        self.insights_out.AppendText(msg.rstrip() + "\n")

    # ---------------- Data helpers ----------------
    def _load_dataframe_to_grid(self, df: pd.DataFrame):
        # reset grid
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows(), True)
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols(), True)

        if df is None or df.empty:
            return

        self.grid.AppendCols(len(df.columns))
        self.grid.AppendRows(len(df.index))

        # headers
        for c, name in enumerate(df.columns):
            self.grid.SetColLabelValue(c, str(name))

        # data
        for r in range(len(df.index)):
            for c in range(len(df.columns)):
                self.grid.SetCellValue(r, c, "" if pd.isna(df.iat[r, c]) else str(df.iat[r, c]))

        self.grid.AutoSizeColumns()
        self.grid.ForceRefresh()

        # Update header KPIs quickly
        rows = len(df.index)
        cols = len(df.columns)
        null_pct = float(df.isna().sum().sum()) / (rows * cols) * 100 if rows and cols else 0.0
        self.update_header_stats(rows=rows, cols=cols, null_pct=null_pct)
        self.update_last_run()

    # ---------------- Button handlers ----------------
    def on_load_knowledge(self, evt):
        # Example: pick files and show names as chips/text
        with wx.FileDialog(self, "Select knowledge files", wildcard="All files (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_MULTIPLE) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                files = dlg.GetPaths()
                if files:
                    self.kn_list.SetLabel(", ".join([os.path.basename(f) for f in files]))
                    self.insights_append(f"Loaded knowledge files: {len(files)}")

    def on_load_file(self, evt):
        with wx.FileDialog(self, "Open CSV", wildcard="CSV files (*.csv)|*.csv|All files (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                self.current_path = path
                try:
                    df = pd.read_csv(path)
                    self.df = df
                    self._load_dataframe_to_grid(df)
                    self.insights_append(f"Loaded file: {os.path.basename(path)}")
                except Exception as e:
                    wx.MessageBox(f"Failed to read file.\n{e}", "Error",
                                  wx.OK | wx.ICON_ERROR)

    def on_load_from_uri(self, evt):
        wx.MessageBox("Load from URI/S3 not yet implemented in this demo.",
                      "Info", wx.OK | wx.ICON_INFORMATION)

    def on_generate_synth(self, evt):
        wx.MessageBox("Generate Synthetic Data placeholder.",
                      "Info", wx.OK | wx.ICON_INFORMATION)

    def on_quality_rules(self, evt):
        wx.MessageBox("Quality Rule Assignment placeholder.",
                      "Info", wx.OK | wx.ICON_INFORMATION)

    def on_profile(self, evt):
        if self.df is None:
            wx.MessageBox("Load a dataset first.", "Profile",
                          wx.OK | wx.ICON_INFORMATION)
            return
        # quick sample profile
        rows, cols = self.df.shape
        null_pct = float(self.df.isna().sum().sum()) / (rows * cols) * 100 if rows and cols else 0.0
        self.update_header_stats(rows=rows, cols=cols, null_pct=null_pct)
        self.insights_append(f"Profiled dataset — rows: {rows}, cols: {cols}, null %: {null_pct:.1f}")

    def on_quality(self, evt):
        if self.df is None:
            wx.MessageBox("Load a dataset first.", "Quality",
                          wx.OK | wx.ICON_INFORMATION)
            return
        # Example: naive score (100 - null penalty)
        rows, cols = self.df.shape
        null_pct = float(self.df.isna().sum().sum()) / (rows * cols) * 100 if rows and cols else 0.0
        score = max(0, 100 - int(null_pct))
        self.update_header_stats(dq_score=score)
        self.insights_append(f"Data Quality score computed: {score}")

    def on_anomalies(self, evt):
        if self.df is None:
            wx.MessageBox("Load a dataset first.", "Anomalies",
                          wx.OK | wx.ICON_INFORMATION)
            return
        # Placeholder: report 0 anomalies
        anoms = 0
        self.update_header_stats(anomalies=anoms)
        self.insights_append("Anomaly detection run complete (0 found in demo).")

    def on_catalog(self, evt):
        wx.MessageBox("Catalog operation placeholder.",
                      "Info", wx.OK | wx.ICON_INFORMATION)

    def on_compliance(self, evt):
        wx.MessageBox("Compliance check placeholder.",
                      "Info", wx.OK | wx.ICON_INFORMATION)

    def on_little_buddy(self, evt):
        wx.MessageBox("Little Buddy (conversational assistant) placeholder.",
                      "Info", wx.OK | wx.ICON_INFORMATION)

    def on_export_csv(self, evt):
        if self.df is None:
            wx.MessageBox("Nothing to export.", "Export CSV",
                          wx.OK | wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Save CSV", wildcard="CSV files (*.csv)|*.csv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                try:
                    self.df.to_csv(path, index=False)
                    self.insights_append(f"Exported CSV: {os.path.basename(path)}")
                except Exception as e:
                    wx.MessageBox(f"Export failed.\n{e}", "Error",
                                  wx.OK | wx.ICON_ERROR)

    def on_export_txt(self, evt):
        if self.df is None:
            wx.MessageBox("Nothing to export.", "Export TXT",
                          wx.OK | wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Save TXT", wildcard="Text files (*.txt)|*.txt",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(self.df.to_string(index=False))
                    self.insights_append(f"Exported TXT: {os.path.basename(path)}")
                except Exception as e:
                    wx.MessageBox(f"Export failed.\n{e}", "Error",
                                  wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, evt):
        wx.MessageBox("Upload to S3 placeholder.",
                      "Info", wx.OK | wx.ICON_INFORMATION)


# If you run this file directly (optional dev convenience)
if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
