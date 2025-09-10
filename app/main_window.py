# app/main_window.py
import wx
import wx.grid as gridlib
import pandas as pd
from datetime import datetime
import os
from typing import Any, Callable, Optional

# Optional integrations with your existing code
try:
    from app import analysis as _analysis
except Exception:
    _analysis = None

try:
    from app import dialogs as _dialogs
except Exception:
    _dialogs = None

try:
    from app import s3_utils as _s3utils
except Exception:
    _s3utils = None


# ============================================================
# Font helper (wx 4.x compatible)
# ============================================================
def mkfont(size=9, bold=False):
    return wx.Font(
        pointSize=size,
        family=wx.FONTFAMILY_SWISS,
        style=wx.FONTSTYLE_NORMAL,
        weight=(wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL),
    )


# ============================================================
# Header widgets
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
        wx.Frame.__init__(self, None, title="Data Buddy — Sidecar Application", size=(1280, 800))
        self.Centre()
        self.SetBackgroundColour(wx.Colour(32, 32, 38))

        self.current_path: Optional[str] = None
        self.df: Optional[pd.DataFrame] = None

        self._build_ui()
        self.Show()

    # ---------------- UI build ----------------
    def _build_ui(self):
        main = wx.BoxSizer(wx.VERTICAL)

        header = self._build_header(self)
        main.Add(header, 0, wx.EXPAND)

        toolbar = self._build_toolbar(self)
        main.Add(toolbar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

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

        self.insights = wx.CollapsiblePane(self, label="Insights from last run")
        pane = self.insights.GetPane()
        box = wx.BoxSizer(wx.VERTICAL)
        self.insights_out = wx.TextCtrl(pane, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.insights_out.SetMinSize((100, 80))
        self.insights_out.SetBackgroundColour(wx.Colour(46, 46, 54))
        self.insights_out.SetForegroundColour(wx.Colour(230, 230, 238))
        self.insights_out.SetFont(mkfont(9))
        box.Add(self.insights_out, 1, wx.EXPAND)
        pane.SetSizer(box)
        main.Add(self.insights, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

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

        kpis = wx.BoxSizer(wx.HORIZONTAL)
        self.card_rows    = MetricCard(panel, "Rows", "—", wx.Colour(120, 99, 255))
        self.card_cols    = MetricCard(panel, "Columns", "—", wx.Colour(151, 133, 255))
        self.card_nulls   = MetricCard(panel, "Null %", "—", wx.Colour(187, 168, 255))
        self.card_quality = MetricCard(panel, "DQ Score", "—", wx.Colour(255, 207, 92))
        self.card_anoms   = MetricCard(panel, "Anomalies", "—", wx.Colour(255, 113, 113))
        for c in (self.card_rows, self.card_cols, self.card_nulls, self.card_quality, self.card_anoms):
            kpis.Add(c, 0, wx.ALL, 6)

        qa = wx.BoxSizer(wx.HORIZONTAL)
        qa.Add(QuickBtn(panel, "Profile",            self.on_profile), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Quality",            self.on_quality), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Catalog",            self.on_catalog), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Detect Anomalies",   self.on_anomalies), 0, wx.ALL, 4)
        qa.Add(QuickBtn(panel, "Compliance",         self.on_compliance), 0, wx.ALL, 4)

        s.Add(top, 0, wx.EXPAND)
        s.Add(kpis, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        s.Add(qa,   0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        rule = wx.Panel(panel, size=(-1, 1))
        rule.SetBackgroundColour(wx.Colour(58, 58, 66))
        s.Add(rule, 0, wx.EXPAND)

        panel.SetSizer(s)
        return panel

    def _build_toolbar(self, parent):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(wx.Colour(40, 40, 48))
        s = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(label, handler):
            b = wx.Button(panel, label=label)
            b.SetBackgroundColour(wx.Colour(121, 103, 255))
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(mkfont(9, True))
            b.SetMinSize((160, 36))
            b.Bind(wx.EVT_BUTTON, handler)
            s.Add(b, 0, wx.ALL, 6)

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
            mapping.get(cmd, lambda _e: wx.MessageBox(f"Unknown command: {cmd}", "Command",
                        wx.OK | wx.ICON_INFORMATION))(None)
        else:
            wx.MessageBox(f"Search: {q}", "Search", wx.OK | wx.ICON_INFORMATION)

    # ---------------- Convenience hooks for header ----------------
    def update_header_stats(self, *, rows=None, cols=None, null_pct=None, dq_score=None, anomalies=None):
        if rows      is not None: self.card_rows.set(rows)
        if cols      is not None: self.card_cols.set(cols)
        if null_pct  is not None: self.card_nulls.set(f"{null_pct:.1f}%")
        if dq_score  is not None: self.card_quality.set(f"{dq_score:.0f}")
        if anomalies is not None: self.card_anoms.set(anomalies)

    def update_last_run(self, when: Optional[str] = None):
        when = when or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.search.SetDescriptiveText(f"Search or type /command…  (Last run: {when})")

    def set_environment(self, name="LOCAL", ok=True):
        parent = self.env_pill.GetParent()
        self.env_pill.Destroy()
        self.env_pill = Pill(parent, name, wx.Colour(90, 72, 198))
        self.env_pill.set_ok(ok)
        parent.Layout()

    def insights_append(self, msg: str):
        self.insights_out.AppendText(msg.rstrip() + "\n")

    # ---------------- Data helpers ----------------
    def _load_dataframe_to_grid(self, df: pd.DataFrame):
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows(), True)
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols(), True)

        if df is None or df.empty:
            return

        self.grid.AppendCols(len(df.columns))
        self.grid.AppendRows(len(df.index))

        for c, name in enumerate(df.columns):
            self.grid.SetColLabelValue(c, str(name))

        for r in range(len(df.index)):
            for c in range(len(df.columns)):
                v = df.iat[r, c]
                self.grid.SetCellValue(r, c, "" if pd.isna(v) else str(v))

        self.grid.AutoSizeColumns()
        self.grid.ForceRefresh()

        rows = len(df.index)
        cols = len(df.columns)
        null_pct = float(df.isna().sum().sum()) / (rows * cols) * 100 if rows and cols else 0.0
        self.update_header_stats(rows=rows, cols=cols, null_pct=null_pct)
        self.update_last_run()

    # ---------------- Helper: find & call user functions ----------------
    def _resolve_callable(self, module, names: list[str]) -> Optional[Callable[..., Any]]:
        if module is None:
            return None
        for n in names:
            fn = getattr(module, n, None)
            if callable(fn):
                return fn
        return None

    def _maybe_update_from_result(self, result: Any):
        """
        Accepts common shapes your analysis code might return and updates UI:
          - dict with any of: rows, cols, null_pct, dq_score, anomalies, df, message
          - tuple (df, info_str) or (df,)
          - DataFrame alone
        """
        if isinstance(result, dict):
            if "df" in result and isinstance(result["df"], pd.DataFrame):
                self.df = result["df"]
                self._load_dataframe_to_grid(self.df)
            self.update_header_stats(
                rows=result.get("rows"),
                cols=result.get("cols"),
                null_pct=result.get("null_pct"),
                dq_score=result.get("dq_score"),
                anomalies=result.get("anomalies"),
            )
            if msg := result.get("message"):
                self.insights_append(str(msg))
            return

        if isinstance(result, tuple):
            if len(result) >= 1 and isinstance(result[0], pd.DataFrame):
                self.df = result[0]
                self._load_dataframe_to_grid(self.df)
            if len(result) >= 2 and result[1]:
                self.insights_append(str(result[1]))
            return

        if isinstance(result, pd.DataFrame):
            self.df = result
            self._load_dataframe_to_grid(self.df)
            return

    # ---------------- Button handlers (delegate to your modules if present) ----------------
    def on_load_knowledge(self, evt):
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
                    wx.MessageBox(f"Failed to read file.\n{e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_load_from_uri(self, evt):
        # Try analysis.load_from_uri(self) or .load_from_s3(self)
        fn = self._resolve_callable(_analysis, ["load_from_uri", "load_from_s3", "open_uri"])
        if fn:
            try:
                res = fn(self)  # let your function work with the window
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Load from URI/S3", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Load from URI/S3 not implemented.", "Info", wx.OK | wx.ICON_INFORMATION)

    def on_generate_synth(self, evt):
        fn = self._resolve_callable(_analysis, ["generate_synthetic", "synth_data", "generate_synthetic_data"])
        if fn:
            try:
                res = fn(self.df, self)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Synthetic Data", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Generate Synthetic Data placeholder.", "Info", wx.OK | wx.ICON_INFORMATION)

    def on_quality_rules(self, evt):
        fn = self._resolve_callable(_analysis, ["quality_rule_assignment", "assign_quality_rules"])
        if fn:
            try:
                res = fn(self.df, self)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Quality Rules", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Quality Rule Assignment placeholder.", "Info", wx.OK | wx.ICON_INFORMATION)

    def on_profile(self, evt):
        if self.df is None:
            # If your function loads data itself, allow calling with None
            pass
        fn = self._resolve_callable(_analysis, ["run_profile", "profile", "do_profile"])
        if fn:
            try:
                res = fn(self.df, self) if fn.__code__.co_argcount >= 2 else fn(self.df)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Profile", wx.OK | wx.ICON_ERROR)
                return
        # fallback quick profile
        if self.df is None:
            wx.MessageBox("Load a dataset first.", "Profile", wx.OK | wx.ICON_INFORMATION)
            return
        rows, cols = self.df.shape
        null_pct = float(self.df.isna().sum().sum()) / (rows * cols) * 100 if rows and cols else 0.0
        self.update_header_stats(rows=rows, cols=cols, null_pct=null_pct)
        self.insights_append(f"Profiled dataset — rows: {rows}, cols: {cols}, null %: {null_pct:.1f}")

    def on_quality(self, evt):
        if self.df is None:
            pass
        fn = self._resolve_callable(_analysis, ["run_quality", "quality", "compute_quality"])
        if fn:
            try:
                res = fn(self.df, self) if fn.__code__.co_argcount >= 2 else fn(self.df)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Quality", wx.OK | wx.ICON_ERROR)
                return
        if self.df is None:
            wx.MessageBox("Load a dataset first.", "Quality", wx.OK | wx.ICON_INFORMATION)
            return
        rows, cols = self.df.shape
        null_pct = float(self.df.isna().sum().sum()) / (rows * cols) * 100 if rows and cols else 0.0
        score = max(0, 100 - int(null_pct))
        self.update_header_stats(dq_score=score)
        self.insights_append(f"Data Quality score computed: {score}")

    def on_anomalies(self, evt):
        if self.df is None:
            pass
        fn = self._resolve_callable(_analysis, ["run_anomalies", "detect_anomalies", "anomalies"])
        if fn:
            try:
                res = fn(self.df, self) if fn.__code__.co_argcount >= 2 else fn(self.df)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Anomalies", wx.OK | wx.ICON_ERROR)
                return
        if self.df is None:
            wx.MessageBox("Load a dataset first.", "Anomalies", wx.OK | wx.ICON_INFORMATION)
            return
        self.update_header_stats(anomalies=0)
        self.insights_append("Anomaly detection run complete (0 found in demo).")

    def on_catalog(self, evt):
        fn = self._resolve_callable(_analysis, ["run_catalog", "catalog", "build_catalog"])
        if fn:
            try:
                res = fn(self.df, self) if fn.__code__.co_argcount >= 2 else fn(self.df)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Catalog", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Catalog operation placeholder.", "Info", wx.OK | wx.ICON_INFORMATION)

    def on_compliance(self, evt):
        fn = self._resolve_callable(_analysis, ["run_compliance", "compliance", "check_compliance"])
        if fn:
            try:
                res = fn(self.df, self) if fn.__code__.co_argcount >= 2 else fn(self.df)
                self._maybe_update_from_result(res)
                return
            except Exception as e:
                wx.MessageBox(str(e), "Compliance", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Compliance check placeholder.", "Info", wx.OK | wx.ICON_INFORMATION)

    def on_little_buddy(self, evt):
        # Try to open your dialog if it exists
        dlg_cls = getattr(_dialogs, "LittleBuddyDialog", None) if _dialogs else None
        if dlg_cls:
            try:
                dlg = dlg_cls(self)
                dlg.ShowModal()
                dlg.Destroy()
                return
            except Exception as e:
                wx.MessageBox(str(e), "Little Buddy", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Little Buddy (assistant) placeholder.", "Info", wx.OK | wx.ICON_INFORMATION)

    def on_export_csv(self, evt):
        if self.df is None:
            wx.MessageBox("Nothing to export.", "Export CSV", wx.OK | wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Save CSV", wildcard="CSV files (*.csv)|*.csv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                try:
                    self.df.to_csv(path, index=False)
                    self.insights_append(f"Exported CSV: {os.path.basename(path)}")
                except Exception as e:
                    wx.MessageBox(f"Export failed.\n{e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_export_txt(self, evt):
        if self.df is None:
            wx.MessageBox("Nothing to export.", "Export TXT", wx.OK | wx.ICON_INFORMATION)
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
                    wx.MessageBox(f"Export failed.\n{e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, evt):
        # Try to delegate to s3 utils if available
        fn = self._resolve_callable(_s3utils, ["upload_file_to_s3", "upload_csv", "upload"])
        if fn:
            try:
                with wx.FileDialog(self, "Select file to upload", wildcard="All files (*.*)|*.*",
                                   style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
                    if dlg.ShowModal() == wx.ID_OK:
                        path = dlg.GetPath()
                        res = fn(path, self) if fn.__code__.co_argcount >= 2 else fn(path)
                        if isinstance(res, dict) and res.get("ok"):
                            self.insights_append(f"Uploaded to S3: {os.path.basename(path)}")
                        else:
                            self.insights_append(f"Upload attempted: {os.path.basename(path)}")
                return
            except Exception as e:
                wx.MessageBox(str(e), "Upload to S3", wx.OK | wx.ICON_ERROR)
                return
        wx.MessageBox("Upload to S3 placeholder.", "Info", wx.OK | wx.ICON_INFORMATION)


# Optional dev entry
if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
