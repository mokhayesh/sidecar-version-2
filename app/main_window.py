# main_window.py
# Tabbed "Data Buddy" UI with header banner and per-tab grids.
# Dependencies: wxPython (pip install wxPython), optionally pandas for DataFrame display.

import wx
import wx.grid as gridlib

try:
    import pandas as pd  # Optional; used only if you pass DataFrames to _display
except Exception:  # pragma: no cover
    pd = None


# ---------------------------
# Helper widgets and utilities
# ---------------------------

class HeaderBanner(wx.Panel):
    """Simple top banner with title/subtitle in a dark purple theme."""
    def __init__(self, parent, title="Data Buddy", subtitle="AI-assisted Data Governance"):
        super().__init__(parent)
        self.SetBackgroundColour(wx.Colour(45, 35, 75))  # dark purple

        title_lbl = wx.StaticText(self, label=title)
        title_lbl.SetForegroundColour(wx.Colour(240, 236, 255))
        tf = title_lbl.GetFont()
        tf.PointSize += 8
        tf.MakeBold()
        title_lbl.SetFont(tf)

        sub_lbl = None
        if subtitle:
            sub_lbl = wx.StaticText(self, label=subtitle)
            sub_lbl.SetForegroundColour(wx.Colour(200, 196, 230))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.AddSpacer(6)
        sizer.Add(title_lbl, 0, wx.LEFT | wx.RIGHT, 16)
        if sub_lbl:
            sizer.AddSpacer(2)
            sizer.Add(sub_lbl, 0, wx.LEFT | wx.RIGHT, 16)
        sizer.AddSpacer(8)
        self.SetSizer(sizer)


def call_if_exists(obj, name, *args, **kwargs):
    """Safely call a method if it exists; show info if not implemented."""
    fn = getattr(obj, name, None)
    if callable(fn):
        return fn(*args, **kwargs)
    wx.MessageBox(f"Handler '{name}' not implemented yet.", "Info", wx.OK | wx.ICON_INFORMATION)


def create_grid(parent):
    """Create a clean grid. Your handlers can resize/fill it as needed."""
    grid = gridlib.Grid(parent)
    grid.CreateGrid(0, 0)
    grid.EnableEditing(False)
    grid.SetDefaultCellAlignment(wx.ALIGN_LEFT, wx.ALIGN_CENTER_VERTICAL)
    grid.SetGridLineColour(wx.Colour(220, 220, 230))
    grid.SetDefaultCellBackgroundColour(wx.Colour(248, 248, 252))
    grid.SetDefaultCellTextColour(wx.BLACK)
    return grid


class ToolTab(wx.Panel):
    """
    Generic tab panel with a small flat toolbar and a content area containing a wx.Grid.
    actions: list[tuple[str, str]] -> (button label, handler name on owner)
    """
    def __init__(self, parent, owner, actions):
        super().__init__(parent)
        self.owner = owner

        root = wx.BoxSizer(wx.VERTICAL)

        # Toolbar row
        bar = wx.Panel(self)
        bar.SetBackgroundColour(wx.Colour(247, 246, 252))
        bar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in actions:
            btn = wx.Button(bar, label=label, style=wx.BORDER_NONE)
            btn.Bind(wx.EVT_BUTTON, lambda evt, h=handler: call_if_exists(self.owner, h))
            bar_sizer.Add(btn, 0, wx.ALL, 4)
        bar.SetSizer(bar_sizer)

        # Content area with grid
        content = wx.Panel(self)
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.grid = create_grid(content)
        content_sizer.Add(self.grid, 1, wx.EXPAND)
        content.SetSizer(content_sizer)

        root.Add(bar, 0, wx.EXPAND)
        root.Add(content, 1, wx.EXPAND | wx.TOP, 6)
        self.SetSizer(root)


# ---------------------------
# Main window
# ---------------------------

class MainWindow(wx.Frame):
    def __init__(self, *args, **kwargs):
        super().__init__(None, title="Data Buddy", size=(1180, 780), style=wx.DEFAULT_FRAME_STYLE)
        self.CentreOnScreen()

        # Keep references to tabs so handlers can access their grids
        self.upload_tab = None
        self.profile_tab = None
        self.quality_tab = None
        self.catalog_tab = None
        self.anomalies_tab = None
        self.compliance_tab = None
        self.optimizer_tab = None
        self.todo_tab = None
        self.buddy_panel = None
        self.persona = None
        self.ask_input = None
        self.chat_out = None

        # Your "current" data (fill it however your app works)
        self.current_df = None  # pandas.DataFrame or list[dict]

        self._build_ui()

    # ---------------------------
    # UI layout
    # ---------------------------

    def _build_ui(self):
        self.SetBackgroundColour(wx.Colour(252, 252, 255))
        root = wx.BoxSizer(wx.VERTICAL)

        # Header
        header = HeaderBanner(self, title="Data Buddy", subtitle="AI-assisted Data Governance")
        root.Add(header, 0, wx.EXPAND)

        # Notebook with tabs
        nb = wx.Notebook(self, style=wx.NB_TOP)
        root.Add(nb, 1, wx.EXPAND)

        # Upload
        self.upload_tab = ToolTab(
            nb, self,
            actions=[
                ("Select File", "on_upload"),
                ("Load Knowledge", "on_load_knowledge"),
                ("Remove Knowledge", "on_remove_knowledge"),
            ],
        )
        nb.AddPage(self.upload_tab, "Upload")

        # Profile
        self.profile_tab = ToolTab(
            nb, self,
            actions=[
                ("Run Profile", "on_profile"),
                ("Export CSV", "on_export_csv"),
                ("Export TXT", "on_export_txt"),
            ],
        )
        nb.AddPage(self.profile_tab, "Profile")

        # Quality
        self.quality_tab = ToolTab(
            nb, self,
            actions=[
                ("Run Quality", "on_quality"),
                ("Rules", "on_quality_rules"),
                ("Exceptions", "on_quality_exceptions"),
            ],
        )
        nb.AddPage(self.quality_tab, "Quality")

        # Catalog
        self.catalog_tab = ToolTab(
            nb, self,
            actions=[
                ("Build Catalog", "on_catalog"),
                ("Publish", "on_catalog_publish"),
            ],
        )
        nb.AddPage(self.catalog_tab, "Catalog")

        # Anomalies
        self.anomalies_tab = ToolTab(
            nb, self,
            actions=[
                ("Detect", "on_anomalies"),
                ("Drift vs Baseline", "on_drift"),
            ],
        )
        nb.AddPage(self.anomalies_tab, "Anomalies")

        # Compliance
        self.compliance_tab = ToolTab(
            nb, self,
            actions=[
                ("Check Compliance", "on_compliance"),
                ("Export Evidence", "on_export_txt"),
            ],
        )
        nb.AddPage(self.compliance_tab, "Compliance")

        # Optimizer
        self.optimizer_tab = ToolTab(
            nb, self,
            actions=[
                ("Optimize", "on_optimize"),
                ("Recommendations", "on_recommendations"),
            ],
        )
        nb.AddPage(self.optimizer_tab, "Optimizer")

        # To Do
        self.todo_tab = ToolTab(
            nb, self,
            actions=[
                ("Run Tasks", "on_run_tasks"),
                ("Open tasks.txt", "on_open_tasks"),
            ],
        )
        nb.AddPage(self.todo_tab, "To Do")

        # Little Buddy (inline chat area)
        self.buddy_panel = wx.Panel(nb)
        nb.AddPage(self.buddy_panel, "Little Buddy")
        buddy_sizer = wx.BoxSizer(wx.VERTICAL)

        persona_row = wx.BoxSizer(wx.HORIZONTAL)
        persona_row.Add(wx.StaticText(self.buddy_panel, label="Persona:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.persona = wx.ComboBox(
            self.buddy_panel,
            choices=["Search Guide", "Data Architect", "Data Quality Expert"],
            style=wx.CB_READONLY,
        )
        self.persona.SetSelection(0)
        persona_row.Add(self.persona, 0)

        ask_row = wx.BoxSizer(wx.HORIZONTAL)
        ask_row.Add(wx.StaticText(self.buddy_panel, label="Ask:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.ask_input = wx.TextCtrl(self.buddy_panel)
        ask_row.Add(self.ask_input, 1, wx.EXPAND | wx.RIGHT, 6)
        ask_btn = wx.Button(self.buddy_panel, label="Send")
        ask_btn.Bind(wx.EVT_BUTTON, lambda evt: call_if_exists(self, "on_little_buddy_send"))
        ask_row.Add(ask_btn, 0)

        self.chat_out = wx.TextCtrl(self.buddy_panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.chat_out.SetMinSize((100, 220))

        buddy_sizer.AddSpacer(6)
        buddy_sizer.Add(persona_row, 0, wx.LEFT | wx.RIGHT, 8)
        buddy_sizer.AddSpacer(6)
        buddy_sizer.Add(ask_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        buddy_sizer.AddSpacer(6)
        buddy_sizer.Add(self.chat_out, 1, wx.EXPAND | wx.ALL, 8)
        self.buddy_panel.SetSizer(buddy_sizer)

        self.SetSizer(root)
        self.Layout()

    # ---------------------------
    # Display helpers
    # ---------------------------

    def _display(self, grid: gridlib.Grid, data):
        """
        Render a pandas DataFrame or list[dict] into the provided wx.Grid.
        """
        # Normalize into rows/cols
        if pd is not None and isinstance(data, pd.DataFrame):
            cols = list(map(str, data.columns))
            rows = data.astype(str).values.tolist()
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            cols = list(map(str, data[0].keys()))
            rows = [[str(r.get(c, "")) for c in cols] for r in data]
        else:
            # Fallback to empty grid
            cols, rows = [], []

        # Reset grid
        if grid.GetNumberRows() > 0:
            grid.DeleteRows(0, grid.GetNumberRows())
        if grid.GetNumberCols() > 0:
            grid.DeleteCols(0, grid.GetNumberCols())

        # Create columns/rows
        if cols:
            grid.AppendCols(len(cols))
            for i, c in enumerate(cols):
                grid.SetColLabelValue(i, c)

        if rows:
            grid.AppendRows(len(rows))
            for r_i, r in enumerate(rows):
                for c_i, val in enumerate(r):
                    grid.SetCellValue(r_i, c_i, val)

        grid.AutoSizeColumns()
        grid.ForceRefresh()

    # ---------------------------
    # Example handlers (replace with your own logic)
    # ---------------------------

    def on_upload(self):
        with wx.FileDialog(self, "Select file", wildcard="*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                # Load the file however your app expects
                # For demo, create tiny preview
                data = [
                    {"file": path.split("/")[-1], "path": path, "status": "Loaded"}
                ]
                self.current_df = data
                self._display(self.upload_tab.grid, self.current_df)

    def on_load_knowledge(self):
        wx.MessageBox("Load Knowledge clicked", "Info")

    def on_remove_knowledge(self):
        wx.MessageBox("Remove Knowledge clicked", "Info")

    def on_profile(self):
        # Run profiling logic, then render to the Profile tab
        sample = [
            {"column": "id", "type": "int", "nulls": 0, "unique": 100},
            {"column": "email", "type": "string", "nulls": 2, "unique": 98},
        ]
        self._display(self.profile_tab.grid, sample)

    def on_export_csv(self):
        wx.MessageBox("Export CSV clicked", "Info")

    def on_export_txt(self):
        wx.MessageBox("Export TXT clicked", "Info")

    def on_quality(self):
        sample = [
            {"rule": "Not Null(email)", "violations": 2, "pass_rate": "96%"},
            {"rule": "Valid Phone", "violations": 1, "pass_rate": "98%"},
        ]
        self._display(self.quality_tab.grid, sample)

    def on_quality_rules(self):
        wx.MessageBox("Open Quality Rules", "Info")

    def on_quality_exceptions(self):
        wx.MessageBox("Open Quality Exceptions", "Info")

    def on_catalog(self):
        sample = [
            {"table": "employees", "rows": 418, "description": "HR employee master"},
            {"table": "knowledge_base", "rows": 2734, "description": "KB articles"},
        ]
        self._display(self.catalog_tab.grid, sample)

    def on_catalog_publish(self):
        wx.MessageBox("Publish Catalog clicked", "Info")

    def on_anomalies(self):
        sample = [
            {"metric": "dq_score", "zscore": 3.1, "flag": "outlier"},
            {"metric": "row_count", "shift": "+12%", "flag": "level-shift"},
        ]
        self._display(self.anomalies_tab.grid, sample)

    def on_drift(self):
        wx.MessageBox("Drift vs Baseline requested", "Info")

    def on_compliance(self):
        sample = [
            {"check": "Overall Quality Score", "status": "Meets SLA", "threshold": "80%"},
            {"check": "CCPA", "status": "Below SLA", "threshold": "80%"},
        ]
        self._display(self.compliance_tab.grid, sample)

    def on_optimize(self):
        sample = [
            {"recommendation": "Add index on email", "impact": "High", "effort": "Low"},
            {"recommendation": "Partition by date", "impact": "Med", "effort": "Med"},
        ]
        self._display(self.optimizer_tab.grid, sample)

    def on_recommendations(self):
        wx.MessageBox("Open Recommendations panel", "Info")

    def on_run_tasks(self):
        sample = [
            {"task": "upload file", "status": "done"},
            {"task": "profile", "status": "done"},
            {"task": "quality", "status": "todo"},
        ]
        self._display(self.todo_tab.grid, sample)

    def on_open_tasks(self):
        wx.MessageBox("Open tasks.txt", "Info")

    def on_little_buddy_send(self):
        persona = self.persona.GetStringSelection() if self.persona else "Unknown"
        text = self.ask_input.GetValue() if self.ask_input else ""
        if self.chat_out:
            self.chat_out.AppendText(f"[{persona}] {text}\n")
            self.chat_out.AppendText("→ (assistant) This is where your response would appear.\n\n")
        if self.ask_input:
            self.ask_input.SetValue("")


# ---------------------------
# App entry point (for testing)
# ---------------------------

if __name__ == "__main__":
    app = wx.App(False)
    win = MainWindow()
    win.Show()
    app.MainLoop()
