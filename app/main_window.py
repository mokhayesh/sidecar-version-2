# app/main_window.py

import os
import csv
from datetime import datetime

import wx
import wx.adv as adv               # <-- needed for AnimationCtrl (GIF)
import wx.grid as gridlib
import pandas as pd

# ---- local modules you already have in your repo ----
from app.settings import SettingsWindow, defaults, save_defaults
from app.dialogs import QualityRuleDialog, DataBuddyDialog, SyntheticDataDialog
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,
    compliance_analysis,
)
from app.s3_utils import download_text_from_uri, upload_to_s3


# -----------------------------
# Utility: fonts (avoid wx.FONTSTYLE typo)
# -----------------------------
def _font(size=10, weight="normal"):
    w = {
        "normal": wx.FONTWEIGHT_NORMAL,
        "medium": getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL),
        "bold": wx.FONTWEIGHT_BOLD,
    }.get(weight, wx.FONTWEIGHT_NORMAL)
    return wx.Font(pointSize=size,
                   family=wx.FONTFAMILY_SWISS,
                   style=wx.FONTSTYLE_NORMAL,
                   weight=w)


# -----------------------------
# Minimal anomaly detection (local)
# -----------------------------
def _detect_anomalies_simple(df: pd.DataFrame):
    """
    Returns (headers, rows) with simple reasons + recommendations.
    """
    out_rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    email_like = df.columns[df.columns.str.contains("email", case=False, regex=True)]

    for col in df.columns:
        s = df[col]
        reasons = []
        recs = []

        # empties
        empties = int((s.astype(str).str.strip() == "").sum())
        if empties:
            reasons.append(f"{empties} blank values")
            recs.append("Fill missing values or drop rows if appropriate.")

        # nulls
        nulls = int(s.isnull().sum())
        if nulls:
            reasons.append(f"{nulls} nulls")
            recs.append("Impute nulls or enforce NOT NULL constraint.")

        # type checks
        if pd.api.types.is_numeric_dtype(s):
            vals = pd.to_numeric(s, errors="coerce")
            # outliers by z-score
            z = (vals - vals.mean()) / (vals.std(ddof=0) if vals.std(ddof=0) else 1)
            outl = int((z.abs() > 3).sum())
            if outl:
                reasons.append(f"{outl} possible outliers")
                recs.append("Review thresholds; consider winsorization or robust scaling.")
        else:
            # maybe it's a date
            if "date" in col.lower() or "timestamp" in col.lower():
                parsed = pd.to_datetime(s, errors="coerce")
                bad = int(parsed.isna().sum())
                if bad:
                    reasons.append(f"{bad} unparseable dates")
                    recs.append("Normalize date formats; parse with a single standard.")
            # maybe it's an email
            if col in email_like:
                ok = s.astype(str).str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", na=False)
                bad = int((~ok).sum())
                if bad:
                    reasons.append(f"{bad} invalid emails")
                    recs.append("Validate email structure or correct user input.")

        # uniqueness
        if s.nunique(dropna=True) < len(s) * 0.2:
            reasons.append("low uniqueness")
            recs.append("Check if this field should be categorical; if not, investigate duplication.")

        if not reasons:
            reasons = ["No major anomalies detected"]
            recs = ["Monitor periodically"]

        out_rows.append([col, "; ".join(reasons), "; ".join(sorted(set(recs))), now])

    hdr = ["Field", "Reason", "Recommendation", "Analysis Date"]
    return hdr, out_rows


# --------------------------------
# Paths we’ll search for media
# --------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(APP_DIR)
ASSETS_DIR = os.path.join(BASE_DIR, "assets")


# --------------------------------
# Header with GIF-first media
# --------------------------------
class HeaderMedia(wx.Panel):
    """
    Prefer an animated GIF (sidecar.gif) using wx.adv.AnimationCtrl.
    Falls back to static PNG/JPG/ICO and finally a placeholder.
    Writes what it loaded to StatusBar (field 1).
    """
    def __init__(self, parent, width=220, height=120):
        super().__init__(parent)
        self.width, self.height = width, height
        self.SetMinSize((width, height))
        self.SetBackgroundColour(wx.Colour(26, 26, 26))

        s = wx.BoxSizer(wx.VERTICAL)
        self.anim_ctrl = None  # keep ref to avoid GC
        loaded_desc = None

        # 1) GIF first — you said you renamed to sidecar.gif
        search_dirs = [ASSETS_DIR, BASE_DIR, APP_DIR, os.getcwd()]
        gif_names = ["sidecar.gif"]  # primary name you’re using
        gif_path = next(
            (os.path.join(d, n) for d in search_dirs for n in gif_names if os.path.exists(os.path.join(d, n))),
            None
        )

        if gif_path:
            try:
                anim = adv.Animation(gif_path)
                if anim.IsOk():
                    self.anim_ctrl = adv.AnimationCtrl(self, -1, anim)
                    self.anim_ctrl.Play()
                    s.Add(self.anim_ctrl, 0, wx.ALL, 0)
                    loaded_desc = f"Header (GIF): {gif_path}"
                else:
                    gif_path = None
            except Exception as e:
                gif_path = None
                loaded_desc = f"GIF load error: {e}"

        # 2) If no GIF, try static bitmap and scale once
        if not gif_path:
            bitmap_candidates = []
            for d in search_dirs:
                bitmap_candidates += [
                    os.path.join(d, "sidecar-01.png"),
                    os.path.join(d, "sidecar.png"),
                    os.path.join(d, "sidecar-01.jpg"),
                    os.path.join(d, "sidecar.jpg"),
                    os.path.join(d, "sidecar-01.ico"),
                    os.path.join(d, "sidecar.ico"),
                ]
            chosen = next((p for p in bitmap_candidates if os.path.exists(p)), None)
            if chosen:
                bmp = self._load_bitmap_exact_size(chosen, self.width, self.height)
                if bmp and bmp.IsOk():
                    s.Add(wx.StaticBitmap(self, bitmap=bmp), 0, wx.ALL, 0)
                    loaded_desc = f"Header (image): {chosen}"
                else:
                    chosen = None

            # 3) Final fallback: placeholder
            if not chosen:
                ph = wx.Panel(self, size=(self.width, self.height))
                ph.SetBackgroundColour(wx.Colour(32, 32, 32))
                msg = wx.StaticText(
                    ph,
                    label="Add assets/sidecar.gif"
                )
                msg.SetForegroundColour(wx.Colour(235, 235, 235))
                msg.SetFont(_font(9, "bold"))
                hs = wx.BoxSizer(wx.VERTICAL)
                hs.AddStretchSpacer()
                hs.Add(msg, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT, 6)
                hs.AddStretchSpacer()
                ph.SetSizer(hs)
                s.Add(ph, 1, wx.EXPAND | wx.ALL, 0)
                loaded_desc = "Header: no media found"

        self.SetSizer(s)

        # status bar diagnostics
        frame = self.GetTopLevelParent()
        try:
            frame.SetStatusText(loaded_desc or "Header ready", 1)
        except Exception:
            pass

    @staticmethod
    def _load_bitmap_exact_size(path: str, w: int, h: int) -> wx.Bitmap | None:
        try:
            img = wx.Image(path, wx.BITMAP_TYPE_ANY)
            if not img.IsOk():
                return None
            img = img.Scale(max(1, w), max(1, h), wx.IMAGE_QUALITY_HIGH)
            return wx.Bitmap(img)
        except Exception:
            return None


# --------------------------------
# Main window
# --------------------------------
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1200, 780))

        # status bar with 2 fields: left free, right for diagnostics
        sb = self.CreateStatusBar(2)
        sb.SetStatusWidths([-1, 500])

        self.raw_data = []
        self.headers = []
        self.current_process = ""
        self.quality_rules = {}
        self.knowledge_files = []  # for Little Buddy reference

        self._build_ui()
        self.Centre()
        self.Show()

    # ----------------------------
    # UI
    # ----------------------------
    def _build_ui(self):
        root = wx.Panel(self)
        root.SetBackgroundColour(wx.Colour(26, 26, 26))
        main = wx.BoxSizer(wx.VERTICAL)

        # Header (GIF left + centered title)
        header = wx.Panel(root)
        header.SetBackgroundColour(wx.Colour(26, 26, 26))
        header_s = wx.BoxSizer(wx.HORIZONTAL)

        # Left: media
        media = HeaderMedia(header, width=220, height=120)
        header_s.Add(media, 0, wx.ALL, 0)

        # Center: title
        center = wx.Panel(header)
        center.SetBackgroundColour(wx.Colour(26, 26, 26))
        cs = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(center, label="Sidecar Application: Data Governance")
        title.SetFont(_font(16, "bold"))
        title.SetForegroundColour(wx.Colour(235, 235, 235))
        cs.AddStretchSpacer()
        cs.Add(title, 0, wx.ALIGN_CENTER)
        cs.AddStretchSpacer()
        center.SetSizer(cs)
        header_s.Add(center, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        header.SetSizer(header_s)
        main.Add(header, 0, wx.EXPAND | wx.ALL, 0)

        # Menu bar
        mb = wx.MenuBar()
        m_file = wx.Menu()
        m_set = wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        mb.Append(m_file, "&File")
        mb.Append(m_set, "&Settings")
        self.SetMenuBar(mb)

        # Toolbar / buttons (wrap)
        buttons = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(label, handler, process=None):
            btn = wx.Button(root, label=label)
            btn.SetBackgroundColour(wx.Colour(70, 130, 180))
            btn.SetForegroundColour(wx.WHITE)
            btn.SetFont(_font(9, "medium"))
            btn.Bind(wx.EVT_BUTTON, handler)
            if process:
                btn.process = process
            buttons.Add(btn, 0, wx.ALL, 4)

        add_btn("Load Knowledge Files", self.on_load_knowledge)
        add_btn("Load File", self.on_load_file)
        add_btn("Load from URI/S3", self.on_load_s3)
        add_btn("Generate Synthetic Data", self.on_generate_synth)
        add_btn("Quality Rule Assignment", self.on_rules)
        add_btn("Profile", lambda e: self.do_analysis(e, "Profile"))
        add_btn("Quality", lambda e: self.do_analysis(e, "Quality"))
        add_btn("Detect Anomalies", self.on_detect_anomalies)
        add_btn("Catalog", lambda e: self.do_analysis(e, "Catalog"))
        add_btn("Compliance", lambda e: self.do_analysis(e, "Compliance"))
        add_btn("Little Buddy", self.on_buddy)
        add_btn("Export CSV", self.on_export_csv)
        add_btn("Export TXT", self.on_export_txt)
        add_btn("Upload to S3", self.on_upload_s3)

        main.Add(buttons, 0, wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Knowledge file list line
        kline = wx.BoxSizer(wx.HORIZONTAL)
        self.klabel = wx.StaticText(root, label="Knowledge Files: (none)")
        self.klabel.SetForegroundColour(wx.Colour(200, 200, 200))
        self.klabel.SetFont(_font(9))
        kline.Add(self.klabel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        main.Add(kline, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # Data grid
        self.grid = gridlib.Grid(root)
        self.grid.CreateGrid(0, 0)
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(55, 55, 55))
        self.grid.SetDefaultCellTextColour(wx.Colour(220, 220, 220))
        self.grid.SetLabelBackgroundColour(wx.Colour(80, 80, 80))
        self.grid.SetLabelTextColour(wx.Colour(240, 240, 240))
        self.grid.SetLabelFont(_font(9, "bold"))
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        main.Add(self.grid, 1, wx.EXPAND | wx.ALL, 6)

        root.SetSizer(main)

    # ----------------------------
    # Display grid
    # ----------------------------
    def _display(self, hdr, data):
        g = self.grid
        g.ClearGrid()
        if g.GetNumberRows():
            g.DeleteRows(0, g.GetNumberRows())
        if g.GetNumberCols():
            g.DeleteCols(0, g.GetNumberCols())

        if not hdr:
            return

        g.AppendCols(len(hdr))
        for i, h in enumerate(hdr):
            g.SetColLabelValue(i, h)

        if data:
            g.AppendRows(len(data))
            for r, row in enumerate(data):
                for c, val in enumerate(row):
                    g.SetCellValue(r, c, "" if val is None else str(val))
                    if r % 2 == 0:
                        g.SetCellBackgroundColour(r, c, wx.Colour(45, 45, 45))
        self.adjust_grid()

    def adjust_grid(self):
        cols = self.grid.GetNumberCols()
        if cols == 0:
            return
        total_w = self.grid.GetClientSize().GetWidth()
        usable = max(0, total_w - self.grid.GetRowLabelSize())
        w = max(80, usable // cols)
        for c in range(cols):
            self.grid.SetColSize(c, w)

    def on_grid_resize(self, event):
        event.Skip()
        wx.CallAfter(self.adjust_grid)

    # ----------------------------
    # Handlers
    # ----------------------------
    def on_settings(self, _):
        SettingsWindow(self).Show()

    def on_load_knowledge(self, _):
        """Allow selecting multiple knowledge files (images/csv/json/txt)."""
        wildcard = "All Supported|*.png;*.jpg;*.jpeg;*.gif;*.csv;*.json;*.txt|" \
                   "Images|*.png;*.jpg;*.jpeg;*.gif|CSV|*.csv|JSON|*.json|Text|*.txt|All|*.*"
        dlg = wx.FileDialog(self, "Select knowledge files", wildcard=wildcard,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        files = dlg.GetPaths(); dlg.Destroy()

        # keep unique, preserve order
        seen = set(self.knowledge_files)
        for p in files:
            if p not in seen:
                self.knowledge_files.append(p)
                seen.add(p)

        # update label
        names = [os.path.basename(p) for p in self.knowledge_files]
        self.klabel.SetLabel("Knowledge Files: " + (",  ".join(names) if names else "(none)"))

    def on_load_file(self, _):
        dlg = wx.FileDialog(self, "Open CSV/TXT", wildcard="CSV/TXT|*.csv;*.txt",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        path = dlg.GetPath(); dlg.Destroy()
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
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
            wx.MessageBox("Load data first so we can mirror its columns.", "No data", wx.OK | wx.ICON_WARNING)
            return
        dlg = SyntheticDataDialog(self, self.headers)
        if dlg.ShowModal() == wx.ID_OK:
            df = dlg.get_dataframe()  # dialog returns a DataFrame
            hdr = list(df.columns)
            rows = df.astype(str).values.tolist()
            self._display(hdr, rows)
        dlg.Destroy()

    def on_rules(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

    def on_buddy(self, _):
        DataBuddyDialog(self, self.raw_data, self.headers, knowledge=self.knowledge_files).ShowModal()

    def do_analysis(self, _evt, kind: str):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        df = pd.DataFrame(self.raw_data, columns=self.headers)

        if kind == "Profile":
            hdr, data = profile_analysis(df)
        elif kind == "Quality":
            hdr, data = quality_analysis(df, self.quality_rules)
        elif kind == "Catalog":
            hdr, data = catalog_analysis(df)
        elif kind == "Compliance":
            hdr, data = compliance_analysis(df)
        else:
            return

        self.current_process = kind
        self._display(hdr, data)
        wx.MessageBox(upload_to_s3(kind, hdr, data), "Analysis", wx.OK | wx.ICON_INFORMATION)

    def on_detect_anomalies(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        df = pd.DataFrame(self.raw_data, columns=self.headers)
        hdr, data = _detect_anomalies_simple(df)
        self.current_process = "DetectAnomalies"
        self._display(hdr, data)
        wx.MessageBox(upload_to_s3("DetectAnomalies", hdr, data), "Analysis", wx.OK | wx.ICON_INFORMATION)

    def _export(self, path, sep):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                for r in range(self.grid.GetNumberRows())]
        pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=sep)

    def on_export_csv(self, _):
        dlg = wx.FileDialog(self, "Save CSV", wildcard="CSV|*.csv",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        self._export(dlg.GetPath(), ",")
        dlg.Destroy()
        wx.MessageBox("CSV exported.", "Export", wx.OK | wx.ICON_INFORMATION)

    def on_export_txt(self, _):
        dlg = wx.FileDialog(self, "Save TXT", wildcard="TXT|*.txt",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        self._export(dlg.GetPath(), "\t")
        dlg.Destroy()
        wx.MessageBox("TXT exported.", "Export", wx.OK | wx.ICON_INFORMATION)

    def on_upload_s3(self, _):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]
                for r in range(self.grid.GetNumberRows())]
        wx.MessageBox(upload_to_s3(self.current_process or "Unknown", hdr, data),
                      "Upload", wx.OK | wx.ICON_INFORMATION)
