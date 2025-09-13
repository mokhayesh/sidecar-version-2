# app/theme_lavender.py
import wx

# --- Cross-version font helpers (handles wx that lacks wx.FONTSTYLE namespace) ---
_FAMILY = wx.FONTFAMILY_SWISS
_STYLE_NORMAL = getattr(wx, "FONTSTYLE_NORMAL", getattr(wx, "NORMAL", 0))
_WEIGHT_NORMAL = getattr(wx, "FONTWEIGHT_NORMAL", getattr(wx, "NORMAL", 0))
_WEIGHT_BOLD = getattr(wx, "FONTWEIGHT_BOLD", getattr(wx, "BOLD", 0))

def _font(size, bold=False):
    return wx.Font(size, _FAMILY, _STYLE_NORMAL, _WEIGHT_BOLD if bold else _WEIGHT_NORMAL)

class LavTheme:
    bg     = wx.Colour(246, 238, 255)   # page bg (lavender)
    panel  = wx.Colour(251, 246, 255)   # header band
    purple = wx.Colour(92, 61, 196)
    plum   = wx.Colour(116, 82, 221)
    white  = wx.Colour(255, 255, 255)
    text   = wx.Colour(44, 44, 56)
    muted  = wx.Colour(112, 112, 126)
    line   = wx.Colour(220, 220, 234)
    kpiBar = wx.Colour(125, 93, 230)
    radius = 12
    gap    = 8

def _shadow(dc, x, y, w, h, r=12, alpha=90):
    gc = wx.GraphicsContext.Create(dc)
    gc.SetPen(wx.NullPen)
    g = gc.CreateRadialGradientBrush(
        x + w*0.5, y + h, x + w*0.5, y + h, max(24, h),
        wx.Colour(0, 0, 0, alpha), wx.Colour(0, 0, 0, 0)
    )
    gc.SetBrush(g)
    gc.DrawRoundedRectangle(x, y+2, w, h, r)

class CardButton(wx.Control):
    """Rounded white ‘app’ button."""
    def __init__(self, parent, label, handler=None, icon: wx.Bitmap=None, width=120):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.label, self.handler, self.icon = label, handler, icon
        self.hover = False
        self.down = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((width, 42))
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: (setattr(self, "hover", True), self.Refresh()))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: (setattr(self, "hover", False), self.Refresh()))
        self.Bind(wx.EVT_LEFT_DOWN,   self._down_evt)
        self.Bind(wx.EVT_LEFT_UP,     self._up)
        self.Bind(wx.EVT_PAINT,       self._paint)

    def _down_evt(self, _):
        self.down = True
        self.CaptureMouse()
        self.Refresh()

    def _up(self, e):
        if self.HasCapture():
            self.ReleaseMouse()
        was = self.down
        self.down = False
        self.Refresh()
        if was and self.GetClientRect().Contains(e.GetPosition()) and callable(self.handler):
            self.handler(e)

    def _paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        w, h = self.GetClientSize()
        _shadow(dc, 0, 0, w, h, r=LavTheme.radius, alpha=80)

        gc = wx.GraphicsContext.Create(dc)
        border = wx.Colour(230, 230, 240)
        body   = LavTheme.white if not self.down else wx.Colour(246, 243, 255)
        gc.SetPen(wx.Pen(border))
        gc.SetBrush(wx.Brush(body))
        gc.DrawRoundedRectangle(0, 0, w, h, LavTheme.radius)

        gc.SetFont(_font(10, bold=True), LavTheme.text if not self.hover else LavTheme.purple)
        tw, th = gc.GetTextExtent(self.label)
        ix = 12
        if self.icon and self.icon.IsOk():
            gc.DrawBitmap(self.icon, 12, (h-18)//2, 18, 18)
            ix = 12 + 18 + 6
        gc.DrawText(self.label, ix + (w - ix - tw)//2, (h - th)//2)

class KPIChipLight(wx.Panel):
    """White KPI cards with tiny progress line."""
    def __init__(self, parent, title, value="—"):
        super().__init__(parent)
        self.title, self.value = title, value
        self.SetMinSize((170, 92))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)

    def SetValue(self, v):
        self.value = v
        self.Refresh()

    def _paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        w, h = self.GetClientSize()
        _shadow(dc, 0, 0, w, h, r=LavTheme.radius, alpha=90)

        gc = wx.GraphicsContext.Create(dc)
        gc.SetPen(wx.Pen(wx.Colour(228, 228, 240)))
        gc.SetBrush(wx.Brush(LavTheme.white))
        gc.DrawRoundedRectangle(0, 0, w, h, LavTheme.radius)

        gc.SetFont(_font(8, bold=False), LavTheme.muted)
        gc.DrawText(self.title.upper(), 14, 10)

        gc.SetFont(_font(16, bold=True), LavTheme.text)
        gc.DrawText(str(self.value), 14, 30)

        gc.SetPen(wx.Pen(LavTheme.line, 6))
        y = h - 18
        gc.StrokeLine(12, y, w - 12, y)
        gc.SetPen(wx.Pen(LavTheme.kpiBar, 6))
        try:
            pct = max(0.0, min(1.0, float(str(self.value).replace("%", "")) / 100.0))
            gc.StrokeLine(12, y, 12 + int((w - 24) * pct), y)
        except Exception:
            pass

class ChipTag(wx.Control):
    """Rounded mini chip for knowledge files."""
    def __init__(self, parent, text):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.text = text
        self.hover = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: (setattr(self, "hover", True), self.Refresh()))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: (setattr(self, "hover", False), self.Refresh()))
        self.Bind(wx.EVT_PAINT, self._paint)

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(_font(9, bold=False))
        tw, th = dc.GetTextExtent(self.text)
        return wx.Size(tw + 20, th + 10)

    def _paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        w, h = self.GetClientSize()
        gc = wx.GraphicsContext.Create(dc)
        gc.SetPen(wx.Pen(LavTheme.plum if self.hover else LavTheme.purple))
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.DrawRoundedRectangle(0, 0, w, h, 10)
        gc.SetFont(_font(9, bold=True), LavTheme.purple if not self.hover else LavTheme.plum)
        tw, th = gc.GetTextExtent(self.text)
        gc.DrawText(self.text, 10, (h - th)//2)

class LittleBuddyDock(wx.MiniFrame):
    """Fly-out dock like the mock. ‘Search’ just pops a message in preview."""
    def __init__(self, parent, on_search):
        super().__init__(parent, title="Little Buddy", size=(360, 320),
                         style=wx.CAPTION | wx.STAY_ON_TOP | wx.FRAME_NO_TASKBAR)
        p = wx.Panel(self)
        p.SetBackgroundColour(LavTheme.white)
        v = wx.BoxSizer(wx.VERTICAL)

        bar = wx.Panel(p)
        bar.SetBackgroundColour(LavTheme.purple)
        cap = wx.StaticText(bar, label="Little Buddy")
        cap.SetForegroundColour(wx.WHITE)
        cap.SetFont(_font(10, bold=True))
        hs = wx.BoxSizer(wx.HORIZONTAL)
        hs.Add(cap, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        bar.SetSizer(hs)
        v.Add(bar, 0, wx.EXPAND)

        body = wx.BoxSizer(wx.VERTICAL)
        self.persona = wx.ComboBox(p, style=wx.CB_READONLY,
                                   choices=["Search Guide", "Data Architect", "DQ Expert"])
        self.persona.SetSelection(0)
        self.query = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.query.SetHint("Which link do I click to…")
        go = wx.Button(p, label="Search")

        body.Add(self.persona, 0, wx.ALL | wx.EXPAND, 8)
        body.Add(self.query,   0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        body.Add(go, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_RIGHT, 8)
        v.Add(body, 1, wx.EXPAND)

        p.SetSizer(v)

        # Wire actions
        self.query.Bind(wx.EVT_TEXT_ENTER, lambda e: on_search(self.query.GetValue()))
        go.Bind(wx.EVT_BUTTON,           lambda e: on_search(self.query.GetValue()))
