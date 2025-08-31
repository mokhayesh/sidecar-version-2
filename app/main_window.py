import os
import re
import random
from datetime import datetime, timedelta

import wx
import wx.grid as gridlib
import pandas as pd

# Optional modules for richer header media
try:
    import wx.html2 as webview  # HTML5 video via Edge WebView2
except Exception:
    webview = None

try:
    import wx.adv as wxadv  # GIF animation fallback
except Exception:
    wxadv = None

from app.settings import SettingsWindow, defaults
from app.dialogs import QualityRuleDialog, DataBuddyDialog, SyntheticDataDialog
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,     # kept for completeness
    compliance_analysis,
    ai_catalog_analysis,  # AI-powered
    ai_detect_anomalies,  # AI-powered
)
from app.s3_utils import download_text_from_uri, upload_to_s3


# ──────────────────────────────────────────────────────────────────────────────
# App metadata (credits & naming)
# ──────────────────────────────────────────────────────────────────────────────
APP_NAME = "Sidecar Application: Data Governance"
APP_VERSION = "1.0"
APP_AUTHOR = "Salah Aldin Mokhayesh"
APP_COMPANY = "Aldin AI LLC"


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic data helpers (no external deps)
# ──────────────────────────────────────────────────────────────────────────────
_FIRST_NAMES = [
    "Alex", "Sam", "Taylor", "Jordan", "Casey", "Jamie", "Riley", "Avery", "Cameron",
    "Morgan", "Harper", "Quinn", "Reese", "Sawyer", "Skyler", "Rowan", "Elliot",
    "Logan", "Mason", "Olivia", "Liam", "Emma", "Noah", "Sophia", "James", "Amelia",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Garcia",
    "Rodriguez", "Wilson", "Martinez", "Anderson", "Taylor", "Thomas", "Hernandez",
    "Moore", "Martin", "Jackson", "Thompson", "White", "Lopez", "Lee", "Gonzalez",
]
_STREETS = [
    "Oak", "Maple", "Pine", "Cedar", "Elm", "Walnut", "Willow", "Ash", "Birch", "Cherry",
    "Lake", "Hill", "River", "Sunset", "Highland", "Meadow", "Forest", "Glen", "Fairview",
]
_CITIES = ["Austin", "Seattle", "Denver", "Chicago", "Miami", "Phoenix", "Boston", "Portland", "Dallas", "Atlanta"]
_STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA",
           "MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY","OH",
           "OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","WY"]
_DOMAINS = ["example.com", "mail.com", "test.org", "demo.net", "sample.io", "data.dev"]

def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def infer_field_type(col: str) -> str:
    name = col.lower().strip()
    if "email" in name:
        return "email"
    if "phone" in name or "tel" in name:
        return "phone"
    if "first" in name and "name" in name:
        return "first_name"
    if "last" in name and "name" in name:
        return "last_name"
    if "middle" in name and "name" in name:
        return "middle_name"
    if "address" in name:
        return "address"
    if "amount" in name or "balance" in name or "price" in name or "total" in name:
        return "amount"
    if "date" in name or "timestamp" in name:
        return "date"
    if name.endswith("_id") or name == "id":
        return "id"
    if any(tok in name for tok in ("number","count","qty","age","zip","score")):
        return "number"
    return "text"

def synth_value(kind: str, i: int) -> str:
    if kind == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last = random.choice(_LAST_NAMES).lower()
        dom = random.choice(_DOMAINS)
        return f"{first}.{last}{i}@{dom}"
    if kind == "phone":
        return f"{random.randint(200,989):03d}-{random.randint(200,989):03d}-{random.randint(1000,9999):04d}"
    if kind == "first_name":
        return random.choice(_FIRST_NAMES)
    if kind == "last_name":
        return random.choice(_LAST_NAMES)
    if kind == "middle_name":
        return random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") if random.random() < 0.5 else random.choice(_FIRST_NAMES)
    if kind == "address":
        num = random.randint(100, 9999)
        st = random.choice(_STREETS)
        typ = random.choice(["St", "Ave", "Rd", "Blvd", "Ln", "Way"])
        city = random.choice(_CITIES)
        state = random.choice(_STATES)
        zipc = random.randint(10000, 99999)
        return f"{num} {st} {typ}, {city}, {state} {zipc}"
    if kind == "amount":
        return f"{random.uniform(1000, 100000):.2f}"
    if kind == "date":
        base = datetime.now() - timedelta(days=random.randint(0, 4*365))
        return base.strftime("%Y-%m-%d")
    if kind == "id":
        return f"{random.randint(10_000_000, 99_999_999)}"
    if kind == "number":
        return str(random.randint(0, 1000))
    return f"{_slugify(kind) or 'value'}_{i}"

def synth_dataframe(n: int, columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(index=range(n))
    for col in columns:
        kind = infer_field_type(col)
        df[col] = [synth_value(kind, i+1) for i in range(n)]
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Header media panel: HTML5 video (WebView2) -> GIF -> static image
# ──────────────────────────────────────────────────────────────────────────────
class HeaderMedia(wx.Panel):
    def __init__(self, parent, width=160, height=120):
        super().__init__(parent)
        self.SetMinSize((width, height))
        self.SetBackgroundColour(wx.Colour(26, 26, 26))
        s = wx.BoxSizer(wx.VERTICAL)

        assets = "assets"
        mp4_path = os.path.join(assets, "sidecar.mp4")
        gif_path = os.path.join(assets, "sidecar.gif")

        used = False

        # 1) Try WebView2 HTML5 video
        if not used and webview is not None and os.path.exists(mp4_path):
            try:
                wv = webview.WebView.New(self, style=wx.NO_BORDER)
                # Minimal HTML that autoplays a muted looping video
                abs_mp4 = os.path.abspath(mp4_path).replace("\\", "/")
                html = f"""
                <html>
                  <head>
                    <meta http-equiv='X-UA-Compatible' content='IE=edge'/>
                    <style>
                      html, body {{
                        margin: 0; padding: 0; overflow: hidden;
                        background: #1a1a1a;
                      }}
                      video {{
                        width: {width}px; height: {height}px;
                        object-fit: cover;
                        display: block;
                        background: #1a1a1a;
                      }}
                    </style>
                  </head>
                  <body>
                    <video autoplay loop muted playsinline>
                      <source src="file:///{abs_mp4}" type="video/mp4"/>
                    </video>
                  </body>
                </html>
                """
                wv.SetPage(html, "")
                wv.SetMinSize((width, height))
                s.Add(wv, 0, wx.ALL, 0)
                used = True
            except Exception:
                used = False

        # 2) Try GIF animation
        if not used and wxadv is not None and os.path.exists(gif_path):
            try:
                anim = wxadv.Animation(gif_path)
                ctrl = wxadv.AnimationCtrl(self, -1, anim, style=wx.NO_BORDER)
                ctrl.SetMinSize((width, height))
                ctrl.Play()
                s.Add(ctrl, 0, wx.ALL, 0)
                used = True
            except Exception:
                used = False

        # 3) Fallback static image
        if not used:
            bmp = self._load_bitmap_scaled(height)
            if bmp and bmp.IsOk():
                s.Add(wx.StaticBitmap(self, bitmap=bmp), 0, wx.ALL, 0)
            else:
                s.AddSpacer(height)

        self.SetSizer(s)

    def _load_bitmap_scaled(self, target_h: int) -> wx.Bitmap | None:
        for p in ("assets/sidecar-01.png", "assets/sidecar-01.jpg", "assets/sidecar-01.jpeg", "assets/sidecar-01.ico"):
            if os.path.exists(p):
                try:
                    if p.endswith(".ico"):
                        bmp = wx.Bitmap(p, wx.BITMAP_TYPE_ICO)
                    else:
                        bmp = wx.Bitmap(p)
                    if target_h > 0 and bmp.IsOk():
                        img = bmp.ConvertToImage()
                        bw, bh = img.GetWidth(), img.GetHeight()
                        if bh > 0:
                            scale = min(target_h / bh, 1.0)
                            sw, sh = int(bw * scale), int(bh * scale)
                            img = img.Scale(sw, sh, wx.IMAGE_QUALITY_HIGH)
                            return wx.Bitmap(img)
                        return bmp
                except Exception:
                    return None
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(1200, 820))

        # Title-bar icon must be .ico (OS requirement)
        try:
            icon = wx.Icon("assets/sidecar-01.ico", wx.BITMAP_TYPE_ICO)
            self.SetIcon(icon)
        except Exception:
            pass

        self.raw_data: list[list[str]] = []
        self.headers: list[str] = []
        self.current_process = ""
        self.quality_rules = {}
        self.knowledge_files = []  # [{name, content|path}]

        self._build_ui()
        self.Centre()
        self.Show()

        # Status bar (credits bottom-right)
        self.CreateStatusBar(2)
        self.SetStatusWidths([-1, 420])
        self.SetStatusText(f"v{APP_VERSION}  |  Created by {APP_AUTHOR} ({APP_COMPANY})", 1)

    def _build_ui(self):
        root = wx.Panel(self)
        root.SetBackgroundColour(wx.Colour(40, 40, 40))
        root.SetDoubleBuffered(True)
        root_v = wx.BoxSizer(wx.VERTICAL)

        # ── Header panel with fixed left media, centered title, right spacer
        header = wx.Panel(root)
        header.SetBackgroundColour(wx.Colour(26, 26, 26))
        header.SetDoubleBuffered(True)
        header_s = wx.BoxSizer(wx.HORIZONTAL)

        media_w, media_h = 160, 120
        media_left = HeaderMedia(header, width=media_w, height=media_h)
        header_s.Add(media_left, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 8)

        center_panel = wx.Panel(header)
        center_panel.SetBackgroundColour(wx.Colour(26, 26, 26))
        center_panel.SetDoubleBuffered(True)
        csz = wx.BoxSizer(wx.HORIZONTAL)
        csz.AddStretchSpacer(1)

        title = wx.StaticText(center_panel, label=APP_NAME)
        title.SetForegroundColour(wx.Colour(240, 240, 240))
        title.SetFont(wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        csz.Add(title, 0, wx.ALIGN_CENTER_VERTICAL)

        csz.AddStretchSpacer(1)
        center_panel.SetSizer(csz)
        header_s.Add(center_panel, 1, wx.EXPAND)

        # right spacer equals media width to visually center title
        header_s.AddSpacer(media_w + 16)

        header.SetSizer(header_s)
        root_v.Add(header, 0, wx.EXPAND)

        # ── Menu bar
        mb = wx.MenuBar()
        m_file, m_set, m_help = wx.Menu(), wx.Menu(), wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        about_item = m_help.Append(wx.ID_ABOUT, "About")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        mb.Append(m_file, "&File")
        mb.Append(m_set, "&Settings")
        mb.Append(m_help, "&Help")
        self.SetMenuBar(mb)

        # ── Toolbar panel
        toolbar_panel = wx.Panel(root)
        toolbar_panel.SetBackgroundColour(wx.Colour(48, 48, 48))
        toolbar_panel.SetDoubleBuffered(True)
        tools = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(text, handler, process=None):
            btn = wx.Button(toolbar_panel, label=text)
            btn.SetBackgroundColour(wx.Colour(70, 130, 180))
            btn.SetForegroundColour(wx.WHITE)
            btn.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, handler)
            if process:
                btn.process = process
            tools.Add(btn, 0, wx.ALL, 4)

        add_btn("Load Knowledge Files", self.on_load_knowledge)
        add_btn("Load File", self.on_load_file)
        add_btn("Load from URI/S3", self.on_load_s3)
        add_btn("Generate Synthetic Data", self.on_generate_synth)
        add_btn("Quality Rule Assignment", self.on_rules)
        add_btn("Profile", self.do_analysis, "Profile")
        add_btn("Quality", self.do_analysis, "Quality")
        add_btn("Detect Anomalies", self.on_detect_anomalies)   # AI-backed
        add_btn("Catalog", self.do_analysis, "Catalog")          # AI-backed via map
        add_btn("Compliance", self.do_analysis, "Compliance")
        add_btn("Little Buddy", self.on_buddy)
        add_btn("Export CSV", self.on_export_csv)
        add_btn("Export TXT", self.on_export_txt)
        add_btn("Upload to S3", self.on_upload_s3)

        toolbar_panel.SetSizer(tools)
        root_v.Add(toolbar_panel, 0, wx.EXPAND)

        # ── Knowledge banner
        info_panel = wx.Panel(root)
        info_panel.SetBackgroundColour(wx.Colour(40, 40, 40))
        info_panel.SetDoubleBuffered(True)
        info_s = wx.BoxSizer(wx.HORIZONTAL)
        self.knowledge_lbl = wx.StaticText(info_panel, label="Knowledge Files: (none)")
        self.knowledge_lbl.SetForegroundColour(wx.Colour(200, 200, 200))
        self.knowledge_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        info_s.Add(self.knowledge_lbl, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)
        info_panel.SetSizer(info_s)
        root_v.Add(info_panel, 0, wx.EXPAND)

        # ── Grid
        grid_panel = wx.Panel(root)
        grid_panel.SetBackgroundColour(wx.Colour(40, 40, 40))
        grid_panel.SetDoubleBuffered(True)
        grid_s = wx.BoxSizer(wx.VERTICAL)

        self.grid = gridlib.Grid(grid_panel)
        self.grid.CreateGrid(0, 0)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(55, 55, 55))
        self.grid.SetDefaultCellTextColour(wx.Colour(230, 230, 230))
        self.grid.SetLabelBackgroundColour(wx.Colour(80, 80, 80))
        self.grid.SetLabelTextColour(wx.Colour(245, 245, 245))
        self.grid.SetLabelFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        grid_s.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)

        grid_panel.SetSizer(grid_s)
        root_v.Add(grid_panel, 1, wx.EXPAND)

        root.SetSizer(root_v)

    # ───────── About dialog
    def on_about(self, _):
        msg = (
            f"{APP_NAME}\n\n"
            f"Version: {APP_VERSION}\n"
            f"Created by {APP_AUTHOR} ({APP_COMPANY})"
        )
        dlg = wx.MessageDialog(self, msg, "About", wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    # ───────── Knowledge files
    def _refresh_knowledge_label(self):
        if not self.knowledge_files:
            self.knowledge_lbl.SetLabel("Knowledge Files: (none)")
        else:
            names = "  ·  ".join([k["name"] for k in self.knowledge_files])
            self.knowledge_lbl.SetLabel(f"Knowledge Files:  {names}")
        self.knowledge_lbl.GetParent().Layout()

    def on_load_knowledge(self, _):
        dlg = wx.FileDialog(
            self,
            "Select Knowledge Files",
            wildcard=("All Supported|*.txt;*.json;*.csv;*.png;*.jpg;*.jpeg;*.gif|"
                      "Text|*.txt|JSON|*.json|CSV|*.csv|Images|*.png;*.jpg;*.jpeg;*.gif"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
        )
        if dlg.ShowModal() != wx.ID_OK:
            return
        paths = dlg.GetPaths()
        dlg.Destroy()

        for p in paths:
            name = os.path.basename(p)
            ext = os.path.splitext(name)[1].lower()
            try:
                if ext in (".png",".jpg",".jpeg",".gif",".bmp",".tif",".tiff"):
                    self.knowledge_files.append({"name": name, "path": p})
                else:
                    content = open(p, "r", encoding="utf-8", errors="ignore").read()
                    self.knowledge_files.append({"name": name, "content": content})
            except Exception:
                self.knowledge_files.append({"name": name, "path": p})

        self._refresh_knowledge_label()

    # ───────── Grid helpers
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

    # ───────── Menu / toolbar handlers
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

        # Route Catalog through AI; others as before
        func = {
            "Profile": profile_analysis,
            "Quality": lambda d: quality_analysis(d, self.quality_rules),
            "Catalog": lambda d: ai_catalog_analysis(d, defaults),   # AI-backed
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
        DataBuddyDialog(self, self.raw_data, self.headers, knowledge=self.knowledge_files).ShowModal()

    # ───────── Synthetic Data
    def on_generate_synth(self, _):
        if not self.headers:
            wx.MessageBox("Load a dataset first so I can see field names.", "No data", wx.OK | wx.ICON_WARNING)
            return

        dlg = SyntheticDataDialog(self, self.headers)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        n, selected = dlg.get_values()
        dlg.Destroy()

        if not selected:
            selected = list(self.headers)

        try:
            df = synth_dataframe(n, selected)
            self.headers = selected
            self.raw_data = df.astype(str).values.tolist()
            self._display(self.headers, self.raw_data)
            wx.MessageBox(f"Generated {n:,} synthetic rows for {len(selected)} field(s).",
                          "Synthetic Data", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Generation failed: {e}", "Error", wx.OK | wx.ICON_ERROR)

    # ───────── AI Anomalies (with fallback inside ai_detect_anomalies)
    def on_detect_anomalies(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        df = pd.DataFrame(self.raw_data, columns=self.headers)
        hdr, rows = ai_detect_anomalies(df, defaults)
        self._display(hdr, rows)

    # ───────── Export / Upload
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


if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
