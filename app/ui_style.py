# ui_style.py
import wx, wx.adv

# ---------- THEME ----------
PURPLE_900 = wx.Colour(58, 35, 102)
PURPLE_700 = wx.Colour(88, 53, 150)
PURPLE_600 = wx.Colour(108, 66, 185)
PURPLE_100 = wx.Colour(238, 232, 246)
INK_900    = wx.Colour(33, 33, 33)
INK_600    = wx.Colour(95, 95, 95)
SURFACE    = wx.Colour(252, 252, 254)
BORDER     = wx.Colour(224, 224, 232)
WHITE      = wx.Colour(255, 255, 255)

class Theme:
    BG          = SURFACE
    Card        = WHITE
    Border      = BORDER
    Text        = INK_900
    MutedText   = INK_600
    Primary     = PURPLE_700
    PrimaryDark = PURPLE_900
    PrimaryFg   = WHITE
    AccentBg    = PURPLE_100

# ---------- UTIL ----------
def _round(dc, rect, radius=10):
    path = wx.GraphicsRenderer.GetDefaultRenderer().CreatePath()
    x,y,w,h = rect
    r = radius
    path.MoveToPoint(x+r, y)
    path.AddLineToPoint(x+w-r, y)
    path.AddArcToPoint(x+w, y, x+w, y+r, r)
    path.AddLineToPoint(x+w, y+h-r)
    path.AddArcToPoint(x+w, y+h, x+w-r, y+h, r)
    path.AddLineToPoint(x+r, y+h)
    path.AddArcToPoint(x, y+h, x, y+h-r, r)
    path.AddLineToPoint(x, y+r)
    path.AddArcToPoint(x, y, x+r, y, r)
    path.CloseSubpath()
    dc.FillPath(path)
    dc.StrokePath(path)

# ---------- WIDGETS ----------
class CardPanel(wx.Panel):
    """Rounded white card with thin border."""
    def __init__(self, parent, padding=12, radius=10):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.padding = padding
        self.radius = radius
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.AddSpacer(self.padding)
        self.SetSizer(self.sizer)

    def _on_paint(self, evt):
        w,h = self.GetClientSize()
        mdc = wx.AutoBufferedPaintDC(self)
        mdc.Clear()
        gc = wx.GraphicsContext.Create(mdc)
        gc.SetPen(wx.Pen(Theme.Border, 1))
        gc.SetBrush(wx.Brush(Theme.Card))
        _round(gc, (0,0,w-1,h-1), self.radius)

class PillTag(wx.Panel):
    """Small rounded chip (e.g., attached file)."""
    def __init__(self, parent, label, icon=wx.ART_NORMAL_FILE):
        super().__init__(parent)
        self.SetBackgroundColour(Theme.AccentBg)
        self.SetForegroundColour(Theme.PrimaryDark)
        s = wx.BoxSizer(wx.HORIZONTAL)
        bmp = wx.ArtProvider.GetBitmap(icon, wx.ART_OTHER, (14,14))
        s.Add(wx.StaticBitmap(self, -1, bmp), 0, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER, 6)
        s.Add(wx.StaticText(self, -1, label), 0, wx.RIGHT|wx.ALIGN_CENTER, 8)
        self.SetSizer(s)
        self.SetWindowStyleFlag(wx.BORDER_NONE)
        self.SetMinSize((-1, 26))
        self.SetOwnForegroundColour(Theme.PrimaryDark)

class PrimaryButton(wx.Button):
    def __init__(self, parent, label, **kwargs):
        super().__init__(parent, label=label, **kwargs)
        self.SetBackgroundColour(Theme.Primary)
        self.SetForegroundColour(Theme.PrimaryFg)
        self.SetFont(wx.Font(wx.FontInfo(10).Bold()))
        self.SetWindowStyleFlag(wx.BORDER_NONE)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.SetMinSize((110,34))

class GhostButton(wx.Button):
    def __init__(self, parent, label):
        super().__init__(parent, label=label)
        self.SetBackgroundColour(Theme.Card)
        self.SetForegroundColour(Theme.Text)
        self.SetMinSize((84,34))

class Toolbar(wx.Panel):
    """Top purple header bar with app title."""
    def __init__(self, parent, title="Data Buddy"):
        super().__init__(parent)
        self.SetBackgroundColour(Theme.PrimaryDark)
        s = wx.BoxSizer(wx.HORIZONTAL)
        hdr = wx.StaticText(self, -1, title)
        hdr.SetForegroundColour(Theme.PrimaryFg)
        hdr.SetFont(wx.Font(wx.FontInfo(14).Bold()))
        s.Add(hdr, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 10)
        s.AddStretchSpacer()
        self.SetSizer(s)

class Dropdown(wx.ComboBox):
    def __init__(self, parent, choices, value=""):
        super().__init__(parent, choices=choices, value=value, style=wx.CB_READONLY)
        self.SetMinSize((260, 30))

class Input(wx.TextCtrl):
    def __init__(self, parent, value=""):
        super().__init__(parent, value=value, style=wx.TE_PROCESS_ENTER)
        self.SetMinSize((360, 30))

class FloatingPanel(wx.Frame):
    """A small movable utility window that looks like the 'Little Buddy' card."""
    def __init__(self, parent, title="Little Buddy"):
        style = (wx.CAPTION | wx.FRAME_FLOAT_ON_PARENT |
                 wx.FRAME_NO_TASKBAR | wx.RESIZE_BORDER)
        super().__init__(parent, title="", style=style)
        self.SetBackgroundColour(Theme.Card)
        self.SetSize((420, 360))

        # Header
        header = wx.Panel(self)
        header.SetBackgroundColour(Theme.PrimaryDark)
        hsz = wx.BoxSizer(wx.HORIZONTAL)
        txt = wx.StaticText(header, -1, title)
        txt.SetForegroundColour(Theme.PrimaryFg)
        txt.SetFont(wx.Font(wx.FontInfo(10).Bold()))
        close = GhostButton(header, "✕")
        close.Bind(wx.EVT_BUTTON, lambda e: self.Hide())
        hsz.Add(txt, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 8)
        hsz.AddStretchSpacer()
        hsz.Add(close, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 6)
        header.SetSizer(hsz)

        # Body
        card = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(header, 0, wx.EXPAND)
        s.Add(card, 1, wx.ALL|wx.EXPAND, 10)
        self.SetSizer(s)

        cs = wx.BoxSizer(wx.VERTICAL)
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(wx.StaticText(card, -1, "Persona"), 0, wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 8)
        self.dd = Dropdown(card, ["Search Guide","Data Architect","Data Quality Expert"], "Search Guide")
        row1.Add(self.dd, 0)
        cs.Add(row1, 0, wx.BOTTOM, 8)

        cs.Add(wx.StaticText(card, -1, "Enter Query"), 0, wx.BOTTOM, 4)
        self.query = Input(card, "")
        cs.Add(self.query, 0, wx.EXPAND|wx.BOTTOM, 8)

        # Example chip row (knowledge file)
        chip_row = wx.BoxSizer(wx.HORIZONTAL)
        chip_row.Add(PillTag(card, "Databuddy Cataloging CLI Commands"), 0)
        cs.Add(chip_row, 0, wx.BOTTOM, 8)

        self.btn = PrimaryButton(card, "Search")
        cs.Add(self.btn, 0, wx.ALIGN_RIGHT)

        card.SetSizer(cs)

    def bind_search(self, handler):
        self.btn.Bind(wx.EVT_BUTTON, handler)
        self.query.Bind(wx.EVT_TEXT_ENTER, handler)

    def get_persona(self): return self.dd.GetValue()
    def get_query(self):   return self.query.GetValue()
