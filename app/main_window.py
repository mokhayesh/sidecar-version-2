import os
import csv
from datetime import datetime

import wx
import wx.adv as adv
import wx.grid as gridlib
import pandas as pd

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


def _detect_anomalies_simple(df: pd.DataFrame):
    out_rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    email_like = df.columns[df.columns.str.contains("email", case=False, regex=True)]

    for col in df.columns:
        s = df[col]
        reasons, recs = [], []

        empties = int((s.astype(str).str.strip() == "").sum())
        if empties:
            reasons.append(f"{empties} blank values")
            recs.append("Fill missing values or drop rows if appropriate.")

        nulls = int(s.isnull().sum())
        if nulls:
            reasons.append(f"{nulls} nulls")
            recs.append("Impute nulls or enforce NOT NULL constraint.")

        if pd.api.types.is_numeric_dtype(s):
            vals = pd.to_numeric(s, errors="coerce")
            zden = vals.std(ddof=0) if vals.std(ddof=0) else 1
            z = (vals - vals.mean()) / zden
            outl = int((z.abs() > 3).sum())
            if outl:
                reasons.append(f"{outl} possible outliers")
                recs.append("Review thresholds; consider winsorization or robust scaling.")
        else:
            if "date" in col.lower() or "timestamp" in col.lower():
                bad = int(pd.to_datetime(s, errors="coerce").isna().sum())
                if bad:
                    reasons.append(f"{bad} unparseable dates")
                    recs.append("Normalize date formats; parse with a single standard.")
            if col in email_like:
                ok = s.astype(str).str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", na=False)
                bad = int((~ok).sum())
                if bad:
                    reasons.append(f"{bad} invalid emails")
                    recs.append("Validate email structure or correct user input.")

        if s.nunique(dropna=True) < len(s) * 0.2:
            reasons.append("low uniqueness")
            recs.append("Check if this field should be categorical; if not, investigate duplication.")

        if not reasons:
            reasons = ["No major anomalies detected"]
            recs = ["Monitor periodically"]

        out_rows.append([col, "; ".join(reasons), "; ".join(sorted(set(recs))), now])

    hdr = ["Field", "Reason", "Recommendation", "Analysis Date"]
    return hdr, out_rows


APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(APP_DIR)
ASSETS_DIR = os.path.join(BASE_DIR, "assets")


class HeaderMedia(wx.Panel):
    def __init__(self, parent, max_w=360, max_h=180):
        super().__init__(parent)
        self.SetBackgroundColour(wx.Colour(26, 26, 26))
        self.SetDoubleBuffered(True)

        s = wx.BoxSizer(wx.VERTICAL)
        self.anim_ctrl = None

        gif_path = None
        for d in (ASSETS_DIR, BASE_DIR, APP_DIR, os.getcwd()):
            p = os.path.join(d, "sidecar.gif")
            if os.path.exists(p):
                gif_path = p
                break

        if gif_path:
            try:
                anim = adv.Animation(gif_path)
                if anim.IsOk():
                    nat = anim.GetSize() if hasattr(anim, "GetSize") else wx.Size(320, 214)
                    w = min(nat.width, max_w)
                    h = min(nat.height, max_h)
                    self.SetMinSize((w, h))
                    self.SetSize((w, h))

                    self.anim_ctrl = adv.AnimationCtrl(self, -1, anim, style=wx.BORDER_NONE)
                    self.anim_ctrl.SetBackgroundColour(wx.Colour(26, 26, 26))
                    self.anim_ctrl.Play()

                    # center inside panel if letterboxed
                    hs = wx.BoxSizer(wx.VERTICAL)
                    hs.AddStretchSpacer()
                    row = wx.BoxSizer(wx.HORIZONTAL)
                    row.AddStretchSpacer()
                    row.Add(self.anim_ctrl, 0, wx.ALIGN_CENTER)
                    row.AddStretchSpacer()
                    hs.Add(row, 0, wx.ALIGN_CENTER)
                    hs.AddStretchSpacer()
                    self.SetSizer(hs)
                    return
            except Exception:
                pass

        # fallback static image
        bmp = None
        candidates = []
        for d in (ASSETS_DIR, BASE_DIR, APP_DIR, os.getcwd()):
            candidates += [
                os.path.join(d, "sidecar-01.png"),
                os.path.join(d, "sidecar.png"),
                os.path.join(d, "sidecar-01.jpg"),
                os.path.join(d, "sidecar.jpg"),
                os.path.join(d, "sidecar-01.ico"),
                os.path.join(d, "sidecar.ico"),
            ]
        chosen = next((p for p in candidates if os.path.exists(p)), None)
        if chosen:
            bmp = self._load_bitmap_fit(chosen, max_w, max_h)
        if bmp and bmp.IsOk():
            self.SetMinSize((bmp.GetWidth(), bmp.GetHeight()))
            s.Add(wx.StaticBitmap(self, bitmap=bmp), 0)
            self.SetSizer(s)
        else:
            self.SetMinSize((max_w, max_h))
            ph = wx.Panel(self, size=(max_w, max_h))
            ph.SetBackgroundColour(wx.Colour(32, 32, 32))
            msg = wx.StaticText(ph, label="Add assets/sidecar.gif")
            msg.SetForegroundColour(wx.Colour(235, 235, 235))
            msg.SetFont(_font(9, "bold"))
            hs = wx.BoxSizer(wx.VERTICAL)
            hs.AddStretchSpacer()
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.AddStretchSpacer()
            row.Add(msg, 0, wx.ALIGN_CENTER)
            row.AddStretchSpacer()
            hs.Add(row, 0, wx.ALIGN_CENTER)
            hs.AddStretchSpacer()
            ph.SetSizer(hs)
            s.Add(ph, 1, wx.EXPAND)
            self.SetSizer(s)

    @staticmethod
    def _load_bitmap_fit(path: str, max_w: int, max_h: int) -> wx.Bitmap | None:
        try:
            img = wx.Image(path, wx.BITMAP_TYPE_ANY)
            if not img.IsOk(): return None
            iw, ih = img.GetWidth(), img.GetHeight()
            if iw == 0 or ih == 0: return None
            scale = min(max_w / iw, max_h / ih, 1.0)
            w = max(1, int(iw * scale))
            h = max(1, int(ih * scale))
            img = img.Scale(w, h, wx.IMAGE_QUALITY_HIGH)
            return wx.Bitmap(img)
        except Exception:
            return None


class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1200, 780))

        self._set_window_icon()

        sb = self.CreateStatusBar(2)
        sb.SetStatusWidths([-1, 500])

        # swallow Alt/Menu so Windows doesn't show key-tip overlays
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self.raw_data = []
        self.headers = []
        self.current_process = ""
        self.quality_rules = {}
        self.knowledge_files = []

        self._build_ui()
        self.Centre()
        self.Show()

    def _on_char_hook(self, evt: wx.KeyEvent):
        key = evt.GetKeyCode()
        if key in (wx.WXK_ALT, wx.WXK_MENU):
            # eat the Alt key so OS key-tips (black/yellow squares) never appear
            return
        evt.Skip()

    def _set_window_icon(self):
        ico = None
        for d in (ASSETS_DIR, BASE_DIR, APP_DIR, os.getcwd()):
            for name in ("sidecar.ico", "sidecar-01.ico"):
                p = os.path.join(d, name)
                if os.path.exists(p):
                    try:
                        ico = wx.Icon(p, wx.BITMAP_TYPE_ICO)
                        if ico.IsOk():
                            self.SetIcon(ico)
                            return
                    except Exception:
                        pass

    def _build_ui(self):
        root = wx.Panel(self)
        root.SetBackgroundColour(wx.Colour(26, 26, 26))
        root.SetDoubleBuffered(True)

        main = wx.BoxSizer(wx.VERTICAL)

        header = wx.Panel(root)
        header.SetBackgroundColour(wx.Colour(26, 26, 26))
        header.SetDoubleBuffered(True)

        header_s = wx.BoxSizer(wx.HORIZONTAL)

        media = HeaderMedia(header, max_w=360, max_h=180)
        header_s.Add(media, 0, wx.ALL, 0)

        center = wx.Panel(header)
        center.SetBackgroundColour(wx.Colour(26, 26, 26))
        center.SetDoubleBuffered(True)
        cs = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(center, label="Sidecar Application: Data Governance", style=wx.ST_NO_AUTORESIZE)
        title.SetFont(_font(16, "bold"))
        title.SetForegroundColour(wx.Colour(235, 235, 235))
        cs.AddStretchSpacer()
        cs.Add(title, 0, wx.ALIGN_CENTER)
        cs.AddStretchSpacer()
        center.SetSizer(cs)
        header_s.Add(center, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        header.SetSizer(header_s)
        main.Add(header, 0, wx.EXPAND | wx.ALL, 0)

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

        kline = wx.BoxSizer(wx.HORIZONTAL)
        self.klabel = wx.StaticText(root, label="Knowledge Files: (none)")
        self.klabel.SetForegroundColour(wx.Colour(200, 200, 200))
        self.klabel.SetFont(_font(9))
        kline.Add(self.klabel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        main.Add(kline, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

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

    # ====== handlers (unchanged functionality) ======
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

    def on_settings(self, _): SettingsWindow(self).Show()

    def on_load_knowledge(self, _):
        wildcard = (
            "Knowledge files (*.txt;*.md;*.csv;*.json;*.png;*.jpg;*.jpeg;*.gif)|"
            "*.txt;*.md;*.csv;*.json;*.png;*.jpg;*.jpeg;*.gif|"
            "Text (*.txt;*.md)|*.txt;*.md|"
            "Data (*.csv;*.json)|*.csv;*.json|"
            "Images (*.png;*.jpg;*.jpeg;*.gif)|*.png;*.jpg;*.jpeg;*.gif|"
            "All files (*.*)|*.*"
        )
        dlg = wx.FileDialog(self, "Select knowledge files",
                            wildcard=wildcard,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        chosen = dlg.GetPaths()
        dlg.Destroy()

        allowed_exts = {".txt", ".md", ".csv", ".json", ".png", ".jpg", ".jpeg", ".gif"}
        for p in chosen:
            if os.path.splitext(p)[1].lower() in allowed_exts and p not in self.knowledge_files:
                self.knowledge_files.append(p)

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
        if not uri: return
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
            df = dlg.get_dataframe()
            hdr = list(df.columns)
            rows = df.astype(str).values.tolist()
            self._display(hdr, rows)
        dlg.Destroy()

    def on_rules(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING); return
        QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

    def on_buddy(self, _):
        DataBuddyDialog(self, self.raw_data, self.headers, knowledge=self.knowledge_files).ShowModal()

    def do_analysis(self, _evt, kind: str):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING); return
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
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING); return
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
