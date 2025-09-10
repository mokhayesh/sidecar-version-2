# app/main_window.py
import os
import wx
import wx.grid as gridlib
import pandas as pd
import math
import random as _r

from app.settings import SettingsWindow
from app.dialogs import QualityRuleDialog, DataBuddyDialog, SyntheticDataDialog
from app.s3_utils import download_text_from_uri, upload_to_s3
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,
    compliance_analysis,
)

# Try anomalies under either name; provide a safe fallback if not present.
try:
    from app.analysis import anomalies_analysis as detect_anomalies_analysis
except Exception:
    try:
        from app.analysis import detect_anomalies as detect_anomalies_analysis
    except Exception:
        def detect_anomalies_analysis(df: pd.DataFrame):
            hdr = ["Issue", "Details"]
            data = [["No analyzer", "Define detect_anomalies() or anomalies_analysis() in app.analysis"]]
            return hdr, data


# ──────────────────────────────────────────────────────────────────────────────
# Theme (cartoon/arcade style)
# ──────────────────────────────────────────────────────────────────────────────
class CartoonTheme:
    BG           = wx.Colour(22, 18, 32)      # deep violet
    PANEL        = wx.Colour(28, 24, 40)      # card background
    BLUE         = wx.Colour(66, 133, 244)    # primary
    BLUE_DARK    = wx.Colour(37, 95, 192)
    BLUE_LIGHT   = wx.Colour(124, 178, 255)
    GLOW         = wx.Colour(0, 0, 0, 28)
    TEXT         = wx.Colour(240, 240, 248)
    GOOD_GREEN   = wx.Colour(72, 199, 142)
    ACCENT_PURP  = wx.Colour(162, 120, 255)
    WARN_ORANGE  = wx.Colour(255, 183, 77)
    DANGER_RED   = wx.Colour(255, 113, 113)
    CARD_EDGE    = wx.Colour(15, 12, 24)

def mkfont(size: int, *, bold: bool = False, italic: bool = False,
           family: int = wx.FONTFAMILY_SWISS) -> wx.Font:
    info = wx.FontInfo(size).Family(family)
    if italic:
        info = info.Italic()
    if bold:
        info = info.Bold()
    return wx.Font(info)


# ──────────────────────────────────────────────────────────────────────────────
# Banner (thin)
# ──────────────────────────────────────────────────────────────────────────────
class HeaderBanner(wx.Panel):
    def __init__(self, parent, height=56, bg=CartoonTheme.PANEL):
        super().__init__(parent, size=(-1, height), style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._bg = bg
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        dc.GradientFillLinear((0, 0, w, h), CartoonTheme.PANEL, CartoonTheme.BG, wx.SOUTH)
        # subtle bottom highlight line
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 18)))
        dc.DrawLine(0, h-1, w, h-1)


# ──────────────────────────────────────────────────────────────────────────────
# Glossy “cartoon” button with hover bounce & glow
# ──────────────────────────────────────────────────────────────────────────────
class GlossyButton(wx.Control):
    def __init__(self, parent, label, handler,
                 colour=CartoonTheme.BLUE, radius=18, glow=10):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.label = label
        self.colour = colour
        self.radius = radius
        self.glow = glow
        self._font = mkfont(10, bold=True)
        self._hover = False
        self._pulse = 0.0
        self._timer = wx.Timer(self)
        self.SetMinSize((170, 42))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.Bind(wx.EVT_LEFT_DOWN, handler)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_hover)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._off_hover)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_TIMER, self._tick, self._timer)

    def _on_hover(self, _):
        self._hover = True
        if not self._timer.IsRunning():
            self._timer.Start(16)

    def _off_hover(self, _):
        self._hover = False

    def _tick(self, _):
        # simple harmonic pulse
        self._pulse += 0.12
        if not self._hover and self._pulse > math.pi * 2:
            self._timer.Stop()
            self._pulse = 0.0
        self.Refresh(False)

    def _on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        rect = self.GetClientRect()

        # clear
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()

        # pulse scale
        scale = 1.0 + (0.02 * math.sin(self._pulse)) if self._hover else 1.0
        w, h = rect.width, rect.height
        pad = int(4 * (1/scale))
        x, y = pad, pad
        w2, h2 = w - pad*2, h - pad*2

        # shadow/glow
        for i in range(self.glow, 0, -1):
            alpha = int(22 * (i / self.glow)) + 8
            dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, alpha)))
            dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, alpha)))
            dc.DrawRoundedRectangle(x+i, y+i, w2-2*i, h2-2*i, self.radius + i)

        # button body gradient
        top = self.colour
        bottom = CartoonTheme.BLUE_DARK if self.colour == CartoonTheme.BLUE else self.colour
        dc.SetPen(wx.Pen(top))
        path_rect = (x, y, w2, h2)
        dc.GradientFillLinear(path_rect, top, bottom, wx.SOUTH)
        dc.DrawRoundedRectangle(x, y, w2, h2, self.radius)

        # glossy highlight
        shine_h = max(10, h2//2)
        dc.GradientFillLinear((x+6, y+6, w2-12, shine_h),
                              wx.Colour(255, 255, 255, 120),
                              wx.Colour(255, 255, 255, 0),
                              wx.SOUTH)
        # label
        dc.SetFont(self._font)
        dc.SetTextForeground(wx.WHITE)
        tw, th = dc.GetTextExtent(self.label)
        dc.DrawText(self.label, x + (w2 - tw)//2, y + (h2 - th)//2)


# ──────────────────────────────────────────────────────────────────────────────
# Rounded shadow container (for grid)
# ──────────────────────────────────────────────────────────────────────────────
class ShadowPanel(wx.Panel):
    def __init__(self, parent, *, radius=18, shadow=12,
                 body_bg=wx.Colour(38, 34, 52)):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.radius = radius
        self.shadow = shadow
        self.body_bg = body_bg
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

        self.body = wx.Panel(self, style=wx.BORDER_NONE)
        self.body.SetBackgroundColour(self.body_bg)
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(self.body, 1, wx.EXPAND | wx.ALL, self.shadow)
        self.SetSizer(s)

    def _on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        rect = self.GetClientRect()
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        # soft halo
        for i in range(self.shadow, 0, -1):
            alpha = int(18 * (i / self.shadow)) + 10
            dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, alpha)))
            dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, alpha)))
            dc.DrawRoundedRectangle(i, i, rect.width - 2*i, rect.height - 2*i, self.radius + i)
        # body
        dc.SetPen(wx.Pen(wx.Colour(80, 70, 110)))
        dc.SetBrush(wx.Brush(self.body_bg))
        dc.DrawRoundedRectangle(self.shadow, self.shadow,
                                rect.width - 2*self.shadow, rect.height - 2*self.shadow,
                                self.radius)


# ──────────────────────────────────────────────────────────────────────────────
# KPI Cartoon Card
# ──────────────────────────────────────────────────────────────────────────────
class CartoonCard(wx.Panel):
    def __init__(self, parent, title: str, value: str, accent: wx.Colour, *, min_w=150):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.title = title.upper()
        self.value = str(value)
        self.accent = accent
        self.SetMinSize((min_w, 70))
        self._title_font = mkfont(8, bold=True)
        self._value_font = mkfont(18, bold=True)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def SetValue(self, text: str):
        self.value = str(text)
        self.Refresh(False)

    def _on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()

        # card body gradient
        dc.GradientFillLinear((0, 0, w, h), wx.Colour(54, 48, 74), wx.Colour(40, 36, 56), wx.SOUTH)
        # border
        dc.SetPen(wx.Pen(wx.Colour(15, 12, 24)))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRoundedRectangle(0, 0, w, h, 14)
        # highlight bar
        dc.SetPen(wx.Pen(self.accent))
        dc.SetBrush(wx.Brush(self.accent))
        dc.DrawRoundedRectangle(14, h-10, w-28, 6, 3)

        # glossy arc at top
        dc.GradientFillLinear((10, 8, w-20, 16),
                              wx.Colour(255, 255, 255, 50),
                              wx.Colour(255, 255, 255, 0), wx.SOUTH)

        # title
        dc.SetFont(self._title_font)
        dc.SetTextForeground(wx.Colour(188, 192, 210))
        dc.DrawText(self.title, 16, 8)

        # value (slight text outline for pop)
        dc.SetFont(self._value_font)
        x = 16; y = 26
        for dx, dy in ((1,0),(0,1),(-1,0),(0,-1)):
            dc.SetTextForeground(wx.Colour(0, 0, 0, 90))
            dc.DrawText(self.value, x+dx, y+dy)
        dc.SetTextForeground(wx.WHITE)
        dc.DrawText(self.value, x, y)


# ──────────────────────────────────────────────────────────────────────────────
# Simple synthetic data fallback (unchanged)
# ──────────────────────────────────────────────────────────────────────────────
_FIRST_NAMES = ["JAY", "ANA", "KIM", "LEE", "OMAR", "SARA", "NIA", "LIV", "RAJ"]
_LAST_NAMES  = ["SMITH", "NG", "GARCIA", "BROWN", "TAYLOR", "KHAN", "LI", "LEE"]
_STATES = ["AL","AK","AZ","CA","CO","CT","DC","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY",
           "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY",
           "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","WY"]

def _synth_value(kind: str, i: int) -> str:
    k = (kind or "").lower()
    if "email" in k:
        return f"user{i}@example.com"
    if "first" in k and "name" in k:
        return _r.choice(_FIRST_NAMES)
    if "last" in k and "name" in k:
        return _r.choice(_LAST_NAMES)
    if "phone" in k:
        return f"{_r.randint(200, 989)}-{_r.randint(100, 999)}-{_r.randint(1000, 9999)}"
    if "address" in k:
        return f"{_r.randint(100, 9999)} Main St, City, {_r.choice(_STATES)} {_r.randint(10000, 99999)}"
    if "amount" in k or "loan" in k or "balance" in k:
        return f"{_r.randint(100, 99999)}.{_r.randint(0, 99):02d}"
    return f"value_{i}"

def _synth_dataframe(n: int, columns: list[str]) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append([_synth_value(col, i) for col in columns])
    return pd.DataFrame(rows, columns=columns)


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Application: Data Governance", size=(1220, 840))

        # Icon (best-effort)
        for p in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "assets", "sidecar-01.ico"),
            os.path.join(os.getcwd(), "sidecar-01.ico"),
        ):
            if os.path.exists(p):
                try:
                    self.SetIcon(wx.Icon(p, wx.BITMAP_TYPE_ICO))
                    break
                except Exception:
                    pass

        self.raw_data: list[list[str]] = []
        self.headers: list[str] = []
        self.current_process: str = ""
        self.quality_rules: dict = {}
        self.knowledge_files: list[dict] = []

        self._build_ui()
        self.Centre()
        self.Show()

    def _build_ui(self):
        self.SetBackgroundColour(CartoonTheme.BG)
        main = wx.BoxSizer(wx.VERTICAL)

        # Header strip
        main.Add(HeaderBanner(self), 0, wx.EXPAND)

        # Title
        title_panel = wx.Panel(self)
        title_panel.SetBackgroundColour(CartoonTheme.PANEL)
        tbox = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(title_panel, label="Data Buddy — Sidecar Application")
        title.SetFont(mkfont(18, bold=True))
        title.SetForegroundColour(CartoonTheme.TEXT)
        tbox.AddStretchSpacer()
        tbox.Add(title, 0, wx.ALL, 10)
        tbox.AddStretchSpacer()
        title_panel.SetSizer(tbox)
        main.Add(title_panel, 0, wx.EXPAND | wx.BOTTOM, 6)

        # ── KPI BAR + Buddy button ─────────────────────────────────────────
        kpi_bar = wx.Panel(self)
        kpi_bar.SetBackgroundColour(CartoonTheme.PANEL)
        kbar = wx.BoxSizer(wx.HORIZONTAL)

        kpi_panel = wx.Panel(kpi_bar)
        kpi_panel.SetBackgroundColour(CartoonTheme.PANEL)
        kpis = wx.BoxSizer(wx.HORIZONTAL)

        self.card_rows     = CartoonCard(kpi_panel, "Rows", "—", CartoonTheme.ACCENT_PURP, min_w=180)
        self.card_cols     = CartoonCard(kpi_panel, "Columns", "—", CartoonTheme.BLUE_LIGHT, min_w=160)
        self.card_nulls    = CartoonCard(kpi_panel, "Null %", "—", CartoonTheme.WARN_ORANGE, min_w=160)
        self.card_quality  = CartoonCard(kpi_panel, "DQ Score", "—", CartoonTheme.GOOD_GREEN, min_w=170)
        self.card_complete = CartoonCard(kpi_panel, "Completeness", "—", CartoonTheme.BLUE, min_w=190)
        self.card_anoms    = CartoonCard(kpi_panel, "Anomalies", "—", CartoonTheme.DANGER_RED, min_w=170)

        for c in (self.card_rows, self.card_cols, self.card_nulls, self.card_quality,
                  self.card_complete, self.card_anoms):
            kpis.Add(c, 1, wx.ALL | wx.EXPAND, 6)

        kpi_panel.SetSizer(kpis)

        # Buddy top-right
        buddy_host = wx.Panel(kpi_bar)
        buddy_host.SetBackgroundColour(CartoonTheme.PANEL)
        right = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_buddy = GlossyButton(buddy_host, "Little Buddy",
                                      lambda e: self.on_buddy(e),
                                      colour=CartoonTheme.BLUE)
        right.AddStretchSpacer()
        right.Add(self.btn_buddy, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        buddy_host.SetSizer(right)
        buddy_host.SetMinSize((220, -1))

        kbar.Add(kpi_panel, 1, wx.EXPAND | wx.RIGHT, 4)
        kbar.Add(buddy_host, 0, wx.EXPAND)
        kpi_bar.SetSizer(kbar)
        main.Add(kpi_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

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

        # Toolbar (cartoon buttons)
        tb_panel = wx.Panel(self)
        tb_panel.SetBackgroundColour(CartoonTheme.PANEL)
        wrap = wx.WrapSizer(wx.HORIZONTAL)

        def add_btn(label, handler, colour=CartoonTheme.BLUE):
            b = GlossyButton(tb_panel, label, handler, colour=colour)
            wrap.Add(b, 0, wx.ALL, 6)
            return b

        add_btn("Load Knowledge Files", self.on_load_knowledge)
        add_btn("Load File", self.on_load_file)
        add_btn("Load from URI/S3", self.on_load_s3)
        add_btn("Generate Synthetic Data", self.on_generate_synth, colour=CartoonTheme.ACCENT_PURP)
        add_btn("Quality Rule Assignment", self.on_rules, colour=CartoonTheme.ACCENT_PURP)
        add_btn("Profile", lambda e: self.do_analysis_process("Profile"), colour=CartoonTheme.GOOD_GREEN)
        add_btn("Quality", lambda e: self.do_analysis_process("Quality"), colour=CartoonTheme.GOOD_GREEN)
        add_btn("Detect Anomalies", lambda e: self.do_analysis_process("Detect Anomalies"), colour=CartoonTheme.DANGER_RED)
        add_btn("Catalog", lambda e: self.do_analysis_process("Catalog"))
        add_btn("Compliance", lambda e: self.do_analysis_process("Compliance"))
        add_btn("Export CSV", self.on_export_csv)
        add_btn("Export TXT", self.on_export_txt)
        add_btn("Upload to S3", self.on_upload_s3)

        tb_panel.SetSizer(wrap)
        main.Add(tb_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Knowledge line
        info = wx.Panel(self)
        info.SetBackgroundColour(wx.Colour(36, 32, 50))
        hz = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(info, label="Knowledge Files:")
        lab.SetFont(mkfont(10, bold=True))
        lab.SetForegroundColour(wx.Colour(210, 210, 230))
        self.knowledge_line = wx.StaticText(info, label="(none)")
        self.knowledge_line.SetForegroundColour(wx.Colour(200, 200, 220))
        self.knowledge_line.SetFont(mkfont(9))
        hz.Add(lab, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        hz.Add(self.knowledge_line, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        info.SetSizer(hz)
        main.Add(info, 0, wx.EXPAND)

        # Grid in rounded shell
        shell = ShadowPanel(self, body_bg=wx.Colour(44, 40, 60))
        host = shell.body
        v = wx.BoxSizer(wx.VERTICAL)
        self.grid = gridlib.Grid(host)
        self.grid.CreateGrid(0, 0)
        self.grid.SetLabelBackgroundColour(CartoonTheme.BLUE)
        self.grid.SetLabelTextColour(wx.WHITE)
        self.grid.SetLabelFont(mkfont(9, bold=True))
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(55, 51, 70))
        self.grid.SetDefaultCellTextColour(wx.Colour(230, 230, 240))
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        v.Add(self.grid, 1, wx.EXPAND | wx.ALL, 10)
        host.SetSizer(v)
        main.Add(shell, 1, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(main)

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────
    def on_settings(self, _):
        SettingsWindow(self).Show()

    def on_load_file(self, _):
        dlg = wx.FileDialog(self, "Open CSV/TXT", wildcard="CSV/TXT|*.csv;*.txt",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        path = dlg.GetPath(); dlg.Destroy()
        text = open(path, "r", encoding="utf-8").read()
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

    def on_load_knowledge(self, _):
        dlg = wx.FileDialog(self, "Add Knowledge Files",
                            wildcard="All|*.*",
                            style=wx.FD_OPEN | wx.FD_MULTIPLE)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy(); return
        paths = dlg.GetPaths(); dlg.Destroy()

        added = []
        for p in paths:
            try:
                ext = os.path.splitext(p)[1].lower()
                if ext in (".txt", ".csv", ".json", ".md"):
                    content = open(p, "r", encoding="utf-8", errors="ignore").read()
                    self.knowledge_files.append({"name": os.path.basename(p), "content": content})
                else:
                    self.knowledge_files.append({"name": os.path.basename(p), "path": p, "content": None})
                added.append(os.path.basename(p))
            except Exception:
                pass
        if added:
            self.knowledge_line.SetLabel("  • " + "  •  ".join(added))
            self.Layout()

    def on_rules(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
        else:
            QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

    def on_buddy(self, _):
        DataBuddyDialog(self, self.raw_data, self.headers, knowledge=self.knowledge_files).ShowModal()

    def do_analysis_process(self, name: str):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        self.current_process = name
        df = pd.DataFrame(self.raw_data, columns=self.headers)
        if name == "Profile":
            func = profile_analysis
        elif name == "Quality":
            func = lambda d: quality_analysis(d, self.quality_rules)
        elif name == "Catalog":
            func = catalog_analysis
        elif name == "Compliance":
            func = compliance_analysis
        elif name == "Detect Anomalies":
            func = detect_anomalies_analysis
        else:
            func = profile_analysis
        try:
            hdr, data = func(df)
        except Exception as e:
            hdr, data = ["Error"], [[str(e)]]
        self._display(hdr, data)

    def on_export_csv(self, _):
        dlg = wx.FileDialog(self, "Save CSV", wildcard="CSV|*.csv",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK: return
        path = dlg.GetPath(); dlg.Destroy()
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=",")
            wx.MessageBox("CSV exported.", "Export", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_export_txt(self, _):
        dlg = wx.FileDialog(self, "Save TXT", wildcard="TXT|*.txt",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK: return
        path = dlg.GetPath(); dlg.Destroy()
        try:
            hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
            data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
            pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep="\t")
            wx.MessageBox("TXT exported.", "Export", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Export failed: {e}", "Export", wx.OK | wx.ICON_ERROR)

    def on_upload_s3(self, _):
        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]
        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))] for r in range(self.grid.GetNumberRows())]
        try:
            msg = upload_to_s3(self.current_process or "Unknown", hdr, data)
            wx.MessageBox(msg, "Upload", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Upload failed: {e}", "Upload", wx.OK | wx.ICON_ERROR)

    # ──────────────────────────────────────────────────────────────────────
    # Grid + KPI helpers
    # ──────────────────────────────────────────────────────────────────────
    def _display(self, hdr, data):
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        if not hdr:
            self.update_kpis([], [])
            return

        self.grid.AppendCols(len(hdr))
        for i, h in enumerate(hdr):
            self.grid.SetColLabelValue(i, str(h))

        self.grid.AppendRows(len(data))
        for r, row in enumerate(data):
            for c, val in enumerate(row):
                self.grid.SetCellValue(r, c, str(val))
                if r % 2 == 0:
                    self.grid.SetCellBackgroundColour(r, c, wx.Colour(50, 47, 66))
        self.adjust_grid()
        self.update_kpis(hdr, data)

    def update_kpis(self, hdr, data):
        rows = len(data)
        cols = len(hdr)
        self.card_rows.SetValue(rows if rows else "0")
        self.card_cols.SetValue(cols if cols else "0")

        total_cells = rows * max(cols, 1)
        empty = 0
        if total_cells > 0:
            for r in data:
                for v in r:
                    if v is None or str(v).strip() == "":
                        empty += 1
        null_pct = (empty / total_cells * 100.0) if total_cells else 0.0
        dq = max(0.0, 100.0 - null_pct)
        completeness = 100.0 - null_pct

        self.card_nulls.SetValue(f"{null_pct:.1f}%")
        self.card_quality.SetValue(f"{dq:.1f}")
        self.card_complete.SetValue(f"{completeness:.1f}")

        anoms = 0
        if self.current_process.lower().startswith("detect"):
            anoms = rows
        else:
            lower_hdr = [str(h).lower() for h in hdr]
            if any(("anomaly" in h or "issue" in h or "error" in h) for h in lower_hdr):
                anoms = rows
        self.card_anoms.SetValue(str(anoms))

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


if __name__ == "__main__":
    app = wx.App(False)
    MainWindow()
    app.MainLoop()
