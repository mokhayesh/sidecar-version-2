# app/dialogs.py
import os
import re
import json
import base64
import random
import string
import threading
import tempfile
import requests
from datetime import datetime

import wx
import wx.richtext as rt
import pandas as pd

# Optional audio / speech libs (graceful fallbacks)
try:
    import pygame
except Exception:
    pygame = None

try:
    import speech_recognition as sr
except Exception:
    sr = None

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

from app.settings import defaults


# ──────────────────────────────────────────────────────────────────────────────
# Quality Rule Assignment
# ──────────────────────────────────────────────────────────────────────────────
class QualityRuleDialog(wx.Dialog):
    def __init__(self, parent, fields, current_rules):
        super().__init__(parent, title="Quality Rule Assignment",
                         size=(760, 580),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.fields = fields
        self.current_rules = current_rules
        self.loaded_rules = {}

        BG = wx.Colour(245, 245, 245)
        PANEL = wx.Colour(255, 255, 255)
        TXT = wx.Colour(45, 45, 45)
        INPUT_BG = wx.Colour(255, 255, 255)
        INPUT_TXT = wx.Colour(45, 45, 45)
        ACCENT = wx.Colour(132, 86, 255)

        self.SetBackgroundColour(BG)
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(PANEL)
        main = wx.BoxSizer(wx.VERTICAL)

        fbox = wx.StaticBox(pnl, label="Fields")
        fbox.SetForegroundColour(TXT)
        fsz = wx.StaticBoxSizer(fbox, wx.HORIZONTAL)
        self.field_list = wx.ListBox(pnl, choices=list(fields), style=wx.LB_EXTENDED)
        self.field_list.SetBackgroundColour(INPUT_BG)
        self.field_list.SetForegroundColour(INPUT_TXT)
        self.field_list.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        fsz.Add(self.field_list, 1, wx.EXPAND | wx.ALL, 5)
        main.Add(fsz, 1, wx.EXPAND | wx.ALL, 5)

        g = wx.FlexGridSizer(2, 2, 5, 5)
        g.AddGrowableCol(1, 1)

        s1 = wx.StaticText(pnl, label="Select loaded rule:")
        s1.SetForegroundColour(TXT)
        g.Add(s1, 0, wx.ALIGN_CENTER_VERTICAL)

        self.rule_choice = wx.ComboBox(pnl, style=wx.CB_READONLY)
        self.rule_choice.SetBackgroundColour(INPUT_BG)
        self.rule_choice.SetForegroundColour(INPUT_TXT)
        self.rule_choice.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.rule_choice.Bind(wx.EVT_COMBOBOX, self.on_pick_rule)
        g.Add(self.rule_choice, 0, wx.EXPAND)

        s2 = wx.StaticText(pnl, label="Or enter regex pattern:")
        s2.SetForegroundColour(TXT)
        g.Add(s2, 0, wx.ALIGN_CENTER_VERTICAL)

        self.pattern_txt = wx.TextCtrl(pnl)
        self.pattern_txt.SetBackgroundColour(INPUT_BG)
        self.pattern_txt.SetForegroundColour(INPUT_TXT)
        self.pattern_txt.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        g.Add(self.pattern_txt, 0, wx.EXPAND)

        main.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        pbox = wx.StaticBox(pnl, label="Loaded JSON preview")
        pbox.SetForegroundColour(TXT)
        pv = wx.StaticBoxSizer(pbox, wx.VERTICAL)
        self.preview = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
        self.preview.SetBackgroundColour(wx.Colour(250, 250, 250))
        self.preview.SetForegroundColour(wx.Colour(40, 40, 40))
        self.preview.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        pv.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(pv, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        abox = wx.StaticBox(pnl, label="Assignments")
        abox.SetForegroundColour(TXT)
        asz = wx.StaticBoxSizer(abox, wx.VERTICAL)
        self.assign_view = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.assign_view.InsertColumn(0, "Field", width=180)
        self.assign_view.InsertColumn(1, "Assigned Pattern", width=460)
        asz.Add(self.assign_view, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(asz, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(pnl, label="Load Rules JSON")
        assign_btn = wx.Button(pnl, label="Assign To Selected Field(s)")
        close_btn = wx.Button(pnl, label="Save / Close")
        for b in (load_btn, assign_btn, close_btn):
            b.SetBackgroundColour(ACCENT)
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        load_btn.Bind(wx.EVT_BUTTON, self.on_load_rules)
        assign_btn.Bind(wx.EVT_BUTTON, self.on_assign)
        close_btn.Bind(wx.EVT_BUTTON, lambda _: self.EndModal(wx.ID_OK))
        for b in (load_btn, assign_btn, close_btn):
            btns.Add(b, 0, wx.ALL, 5)
        main.Add(btns, 0, wx.ALIGN_CENTER)

        pnl.SetSizer(main)
        self._refresh_view()

    def _refresh_view(self):
        self.assign_view.DeleteAllItems()
        for fld in self.fields:
            idx = self.assign_view.InsertItem(self.assign_view.GetItemCount(), fld)
            pat = self.current_rules.get(fld)
            self.assign_view.SetItem(idx, 1, pat.pattern if pat else "")

    def on_load_rules(self, _):
        dlg = wx.FileDialog(self, "Open JSON rules file", wildcard="JSON|*.json",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            data = json.load(open(path, "r", encoding="utf-8"))
            self.loaded_rules = {k: (v if isinstance(v, str) else v.get("pattern", "")) for k, v in data.items()}
            self.rule_choice.Clear()
            self.rule_choice.Append(list(self.loaded_rules))
            self.preview.SetValue(json.dumps(data, indent=2))
            wx.MessageBox(f"Loaded {len(self.loaded_rules)} rule(s).", "Rules loaded", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Failed to load: {e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_pick_rule(self, _):
        name = self.rule_choice.GetValue()
        if name in self.loaded_rules:
            self.pattern_txt.SetValue(self.loaded_rules[name])

    def on_assign(self, _):
        sel = self.field_list.GetSelections()
        if not sel:
            wx.MessageBox("Select at least one field.", "No field", wx.OK | wx.ICON_WARNING)
            return
        pat = self.pattern_txt.GetValue().strip()
        if not pat:
            wx.MessageBox("Enter or choose a regex pattern.", "No pattern", wx.OK | wx.ICON_WARNING)
            return
        try:
            compiled = re.compile(pat)
        except re.error as e:
            wx.MessageBox(f"Invalid regex: {e}", "Regex error", wx.OK | wx.ICON_ERROR)
            return
        for i in sel:
            self.current_rules[self.fields[i]] = compiled
        self._refresh_view()
        wx.MessageBox(f"Assigned to {len(sel)} field(s).", "Assigned", wx.OK | wx.ICON_INFORMATION)


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic Data
# ──────────────────────────────────────────────────────────────────────────────
class SyntheticDataDialog(wx.Dialog):
    """
    Minimal synthetic data generator used by MainWindow.on_generate_synth().
    - Uses current dataset's columns when available.
    - Heuristics on column names to generate plausible values.
    """
    def __init__(self, parent, sample_df: pd.DataFrame | None):
        super().__init__(parent, title="Synthetic Data", size=(600, 480),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self._df = None
        self.sample_cols = list(sample_df.columns) if isinstance(sample_df, pd.DataFrame) and len(sample_df.columns) else []

        pnl = wx.Panel(self)
        v = wx.BoxSizer(wx.VERTICAL)

        row_box = wx.BoxSizer(wx.HORIZONTAL)
        row_box.Add(wx.StaticText(pnl, label="Number of rows:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.rows_spin = wx.SpinCtrl(pnl, min=1, max=100000, initial=100)
        row_box.Add(self.rows_spin, 0, wx.RIGHT, 12)
        v.Add(row_box, 0, wx.ALL, 10)

        v.Add(wx.StaticText(pnl, label="Columns (from current dataset if loaded):"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.cols_list = wx.ListBox(pnl, choices=self.sample_cols or ["col1", "col2", "col3"], style=wx.LB_EXTENDED)
        v.Add(self.cols_list, 1, wx.EXPAND | wx.ALL, 10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        gen = wx.Button(pnl, label="Generate")
        ok = wx.Button(pnl, label="OK")
        cancel = wx.Button(pnl, label="Cancel")
        btns.Add(gen, 0, wx.ALL, 5)
        btns.Add(ok, 0, wx.ALL, 5)
        btns.Add(cancel, 0, wx.ALL, 5)
        v.Add(btns, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)

        gen.Bind(wx.EVT_BUTTON, self._on_generate)
        ok.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK) if self._df is not None else wx.MessageBox("Click Generate first.", "No data", wx.OK | wx.ICON_INFORMATION))
        cancel.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

        pnl.SetSizer(v)

    def get_dataframe(self) -> pd.DataFrame:
        return self._df if isinstance(self._df, pd.DataFrame) else pd.DataFrame()

    def _on_generate(self, _):
        cols = self.sample_cols or [self.cols_list.GetString(i) for i in range(self.cols_list.GetCount())]
        n = int(self.rows_spin.GetValue())
        data = {c: [self._fake_value_for(c, i) for i in range(n)] for c in cols}
        self._df = pd.DataFrame(data)
        wx.MessageBox(f"Generated {len(self._df)} rows, {len(self._df.columns)} cols.", "Synthetic Data", wx.OK | wx.ICON_INFORMATION)

    def _fake_value_for(self, col: str, _i: int):
        name = col.lower().strip()
        if "email" in name:
            user = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
            domain = random.choice(["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"])
            return f"{user}@{domain}"
        if "phone" in name or "tel" in name:
            return f"{random.randint(100,999)}-{random.randint(100,999)}-{random.randint(1000,9999)}"
        if "first" in name and "name" in name:
            return random.choice(["ALICE","BOB","CAROL","DAVE","ERIN","FRANK","GRACE","HEIDI","IVAN","JUDY"])
        if "last" in name and "name" in name:
            return random.choice(["SMITH","JOHNSON","BROWN","WILLIAMS","JONES","MILLER","DAVIS","GARCIA","RODRIGUEZ","WILSON"])
        if "address" in name:
            return f"{random.randint(100,9999)} {random.choice(['E','W','N','S'])} {random.choice(['1ST','2ND','MAPLE','OAK','PINE','CEDAR'])} ST, CITY, ST {random.randint(10000,99999)}"
        if "loan" in name or "amount" in name or "amt" in name or "balance" in name:
            return round(random.uniform(2500, 30000), 2)
        if "date" in name or "dt" in name:
            base = datetime(2021, 1, 1)
            return (base.replace(year=2021 + random.randint(0, 4)) + pd.to_timedelta(random.randint(0, 364), unit="D")).date().isoformat()
        return "".join(random.choice(string.ascii_uppercase) for _ in range(4))


# ──────────────────────────────────────────────────────────────────────────────
# ChatView — lavender speech bubbles with tails (auto-wrap, autoscroll)
# ──────────────────────────────────────────────────────────────────────────────
class ChatView(wx.ScrolledWindow):
    def __init__(self, parent, colors):
        super().__init__(parent, style=wx.VSCROLL | wx.WANTS_CHARS)
        self.COL = colors
        self.SetBackgroundColour(self.COL["panel"])
        self.font = wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.messages = []          # list of {"sender": "user"|"bot", "text": str}
        self._stream_index = None   # index of bubble being streamed
        self._layout = []           # cached layout items from last paint

        self.SetScrollRate(0, 12)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self._reflow(), e.Skip()))
        self.Bind(wx.EVT_SHOW, lambda e: (self._reflow(), e.Skip()))

    # public API used by dialog
    def add_message(self, sender: str, text: str):
        self.messages.append({"sender": sender, "text": str(text)})
        self._reflow(scroll_to_end=True)

    def start_bubble(self, sender: str):
        self._stream_index = len(self.messages)
        self.messages.append({"sender": sender, "text": ""})
        self._reflow(scroll_to_end=True)

    def write_stream(self, chunk: str):
        if self._stream_index is None:
            return
        self.messages[self._stream_index]["text"] += str(chunk)
        self._reflow(scroll_to_end=True)

    def end_bubble(self):
        self._stream_index = None
        self._reflow(scroll_to_end=True)

    # layout & paint
    def _wrap_lines(self, dc, text, max_w):
        lines = []
        for para in str(text).split("\n"):
            words = para.split(" ")
            line = ""
            for w in words:
                test = (line + " " + w) if line else w
                tw, _ = dc.GetTextExtent(test)
                if tw <= max_w:
                    line = test
                else:
                    if line:
                        lines.append(line)
                    line = w
            lines.append(line)
        return lines

    def _reflow(self, scroll_to_end=False):
        dc = wx.ClientDC(self)
        self.PrepareDC(dc)
        dc.SetFont(self.font)

        width = self.GetClientSize().GetWidth()
        if width <= 20:
            # best guess before first layout
            width = max(400, self.GetParent().GetClientSize().GetWidth() - 24)

        margin = 14
        spacing = 10
        pad = 10
        maxw = min(int(width * 0.72), 720)
        y = margin
        self._layout = []

        for msg in self.messages:
            lines = self._wrap_lines(dc, msg["text"], maxw - pad * 2)
            lh = dc.GetTextExtent("Ag")[1]
            text_w = 0
            for ln in lines:
                tw, _ = dc.GetTextExtent(ln)
                text_w = max(text_w, tw)
            bw = min(maxw, max(text_w + pad * 2, 40))
            bh = lh * len(lines) + pad * 2

            left_align = (msg["sender"] == "bot")
            x = margin if left_align else (width - bw - margin)

            self._layout.append({
                "x": x, "y": y, "w": bw, "h": bh,
                "lines": lines, "lh": lh,
                "sender": msg["sender"]
            })
            y += bh + spacing

        total_h = y + margin
        self.SetVirtualSize((width, total_h))
        if scroll_to_end:
            self.Scroll(0, self.GetScrollRange(wx.VERTICAL))
        self.Refresh(False)

    def on_paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        self.PrepareDC(dc)
        dc.Clear()
        dc.SetBackground(wx.Brush(self.COL["panel"]))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        gc.SetFont(self.font, self.COL["text"])

        width = max(20, self.GetClientSize().GetWidth())
        border = self.COL["border"]
        # canvas area (white)
        gc.SetPen(wx.Pen(border))
        gc.SetBrush(wx.Brush(self.COL["reply_bg"]))
        gc.DrawRectangle(1, 1, width - 2, self.GetClientSize().GetHeight() - 2)

        # draw bubbles
        r = 10
        pad = 10
        for it in self._layout:
            x, y, w, h = it["x"], it["y"], it["w"], it["h"]
            left = (it["sender"] == "bot")
            bg = self.COL["bubble_bot_bg"] if left else self.COL["bubble_user_bg"]
            fg = self.COL["bubble_bot_fg"] if left else self.COL["bubble_user_fg"]

            # tail
            path_tail = gc.CreatePath()
            if left:
                path_tail.MoveToPoint(x + 8, y + h - 12)
                path_tail.AddLineToPoint(x - 2, y + h - 6)
                path_tail.AddLineToPoint(x + 8, y + h - 2)
            else:
                path_tail.MoveToPoint(x + w - 8, y + h - 12)
                path_tail.AddLineToPoint(x + w + 2, y + h - 6)
                path_tail.AddLineToPoint(x + w - 8, y + h - 2)
            path_tail.CloseSubpath()

            gc.SetPen(wx.Pen(bg))
            gc.SetBrush(wx.Brush(bg))
            gc.FillPath(path_tail)

            # rounded rect bubble
            gc.SetPen(wx.Pen(bg))
            gc.SetBrush(wx.Brush(bg))
            gc.DrawRoundedRectangle(x, y, w, h, r)

            # text
            gc.SetPen(wx.Pen(fg))
            gc.SetBrush(wx.Brush(fg))
            gc.SetFont(self.font, fg)
            ty = y + pad
            for ln in it["lines"]:
                gc.DrawText(ln, x + pad, ty)
                ty += it["lh"]


# ──────────────────────────────────────────────────────────────────────────────
# Little Buddy — white window + lavender bubbles + streaming + TTS + images
# ──────────────────────────────────────────────────────────────────────────────
class DataBuddyDialog(wx.Dialog):
    def __init__(self, parent, data=None, headers=None, knowledge=None):
        super().__init__(parent, title="Little Buddy", size=(920, 720),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.session = requests.Session()
        self.data = data
        self.headers = headers
        self.knowledge = list(knowledge or [])
        kpath = os.environ.get("SIDECAR_KERNEL_PATH", "")
        if kpath and kpath not in self.knowledge:
            self.knowledge.append(kpath)

        self.kernel = None
        self._tts_thread = None

        # White base with lavender accents to match app
        self.COLORS = {
            "bg":        wx.Colour(255, 255, 255),
            "panel":     wx.Colour(255, 255, 255),
            "text":      wx.Colour(44, 31, 72),
            "muted":     wx.Colour(94, 64, 150),
            "accent":    wx.Colour(132, 86, 255),
            "accent_hi": wx.Colour(150, 104, 255),
            "input_bg":  wx.Colour(255, 255, 255),
            "input_fg":  wx.Colour(44, 31, 72),

            # chat area canvas + border
            "reply_bg": wx.Colour(255, 255, 255),
            "border":   wx.Colour(208, 198, 246),

            # bubbles
            "bubble_user_bg": wx.Colour(235, 228, 255),
            "bubble_user_fg": wx.Colour(44, 31, 72),
            "bubble_bot_bg":  wx.Colour(216, 204, 255),
            "bubble_bot_fg":  wx.Colour(44, 31, 72),
        }

        self.SetBackgroundColour(self.COLORS["bg"])
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(self.COLORS["panel"])
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(pnl, label="Little Buddy")
        title.SetForegroundColour(self.COLORS["muted"])
        title.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        vbox.Add(title, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        # Options row
        opts = wx.BoxSizer(wx.HORIZONTAL)

        self.voice = wx.Choice(pnl, choices=["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"])
        self.voice.SetSelection(1)
        self.voice.SetBackgroundColour(self.COLORS["input_bg"])
        self.voice.SetForegroundColour(self.COLORS["input_fg"])
        self.voice.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        opts.Add(self.voice, 0, wx.RIGHT | wx.EXPAND, 6)

        self.tts_checkbox = wx.CheckBox(pnl, label="🔊 Speak Reply")
        self.tts_checkbox.SetValue(True)
        self.tts_checkbox.SetForegroundColour(self.COLORS["text"])
        self.tts_checkbox.SetBackgroundColour(self.COLORS["panel"])
        opts.Add(self.tts_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        self.fast_mode = wx.CheckBox(pnl, label="⚡ Fast Mode")
        self.fast_mode.SetValue(True)
        self.fast_mode.SetForegroundColour(self.COLORS["text"])
        self.fast_mode.SetBackgroundColour(self.COLORS["panel"])
        opts.Add(self.fast_mode, 0, wx.ALIGN_CENTER_VERTICAL)

        self.tts_status = wx.StaticText(pnl, label="TTS: idle")
        self.tts_status.SetForegroundColour(self.COLORS["muted"])
        self.tts_status.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        opts.Add(self.tts_status, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)

        vbox.Add(opts, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.persona = wx.ComboBox(
            pnl,
            choices=["Data Architect", "Data Engineer", "Data Quality Expert", "Data Scientist", "Yoda"],
            style=wx.CB_READONLY,
        )
        self.persona.SetSelection(0)
        self.persona.SetBackgroundColour(self.COLORS["input_bg"])
        self.persona.SetForegroundColour(self.COLORS["input_fg"])
        self.persona.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        vbox.Add(self.persona, 0, wx.EXPAND | wx.ALL, 5)

        row = wx.BoxSizer(wx.HORIZONTAL)
        ask_lbl = wx.StaticText(pnl, label="Ask:")
        ask_lbl.SetForegroundColour(self.COLORS["muted"])
        ask_lbl.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        row.Add(ask_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.prompt = wx.TextCtrl(pnl, style=wx.TE_PROCESS_ENTER)
        self.prompt.SetBackgroundColour(self.COLORS["input_bg"])
        self.prompt.SetForegroundColour(self.COLORS["input_fg"])
        self.prompt.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        self.prompt.SetHint("Type your question and press Enter…")
        self.prompt.Bind(wx.EVT_TEXT_ENTER, self.on_ask)
        row.Add(self.prompt, 1, wx.EXPAND | wx.RIGHT, 6)

        def _style_btn(b: wx.Button):
            b.SetForegroundColour(wx.WHITE)
            b.SetBackgroundColour(self.COLORS["accent"])
            b.Bind(wx.EVT_ENTER_WINDOW, lambda e, bb=b: (bb.SetBackgroundColour(self.COLORS["accent_hi"]), bb.Refresh()))
            b.Bind(wx.EVT_LEAVE_WINDOW, lambda e, bb=b: (bb.SetBackgroundColour(self.COLORS["accent"]), bb.Refresh()))

        send_btn = wx.Button(pnl, label="Send")
        _style_btn(send_btn)
        send_btn.Bind(wx.EVT_BUTTON, self.on_ask)
        row.Add(send_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.mic_btn = wx.Button(pnl, label="🎙 Speak")
        self.mic_btn.SetForegroundColour(wx.WHITE)
        self.mic_btn.SetBackgroundColour(wx.Colour(96, 148, 118))
        self.mic_btn.Bind(wx.EVT_BUTTON, self.on_mic_toggle)
        row.Add(self.mic_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.stop_btn = wx.Button(pnl, label="Stop")
        self.stop_btn.SetForegroundColour(wx.WHITE)
        self.stop_btn.SetBackgroundColour(wx.Colour(150, 60, 60))
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop_voice)
        row.Add(self.stop_btn, 0, wx.ALIGN_CENTER_VERTICAL, 0)

        self.img_btn = wx.Button(pnl, label="🎨 Generate Image")
        self.img_btn.SetForegroundColour(wx.WHITE)
        self.img_btn.SetBackgroundColour(wx.Colour(90, 110, 160))
        self.img_btn.Bind(wx.EVT_BUTTON, self.on_generate_image)
        row.Add(self.img_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)

        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 5)

        # Chat area — bubbles
        self.chat = ChatView(pnl, self.COLORS)
        vbox.Add(self.chat, 1, wx.EXPAND | wx.ALL, 6)

        pnl.SetBackgroundColour(self.COLORS["panel"])
        pnl.SetSizer(vbox)

        # Greet
        self.chat.add_message("user", "Hi!")
        self.chat.add_message("bot", "Hi, I'm Little Buddy!")

    # external setters
    def set_kernel(self, kernel):
        self.kernel = kernel
        try:
            kpath = kernel.path
            if kpath and kpath not in self.knowledge:
                self.knowledge.append(kpath)
        except Exception:
            pass

    def set_knowledge_files(self, files):
        try:
            self.knowledge = list(files or [])
        except Exception:
            self.knowledge = []

    # ---------- chat entrypoint
    def on_ask(self, _):
        q = self.prompt.GetValue().strip()
        self.prompt.SetValue("")
        if not q:
            return
        self.chat.add_message("user", q)
        threading.Thread(target=self._answer_dispatch, args=(q,), daemon=True).start()

    def _build_knowledge_context(self, max_chars=1600):
        if not self.knowledge:
            return ""
        chunks = []
        per_file = max(220, max_chars // max(1, len(self.knowledge)))
        for item in self.knowledge:
            try:
                path = str(item)
                name = os.path.basename(path) or "file"
                if os.path.exists(path) and os.path.splitext(path)[1].lower() in (".txt",".md",".json",".csv",".tsv",".log"):
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        data = fh.read(per_file)
                    chunks.append(f"File: {name}\n{data.strip()}")
                else:
                    chunks.append(f"File: {name} (binary or missing)")
            except Exception:
                continue
        text = "\n\n".join(chunks)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(truncated)…"
        return text

    def _answer_dispatch(self, q: str):
        persona = self.persona.GetValue()
        system_prefix = (
            "You are 'Little Buddy', the in-app assistant for the Sidecar data application. "
            "PRIORITY: Use the 'Knowledge files' provided below (including kernel.json) as the "
            "primary source of truth about the app, its features, and user context."
        )

        prompt = f"{system_prefix}\n\nUser question (as a {persona}): {q}"

        if self.data:
            try:
                sample = "; ".join(map(str, self.data[0]))
                prompt += "\n\nData sample:\n" + sample
            except Exception:
                pass

        kn = self._build_knowledge_context()
        if kn:
            prompt += "\n\nKnowledge files (use these first):\n" + kn

        provider = (defaults.get("provider") or "auto").lower().strip()
        if provider == "gemini":
            self._chat_gemini_streaming(prompt)
            return

        ok = self._chat_openai_streaming(prompt)
        if not ok and provider == "auto" and defaults.get("gemini_api_key"):
            self.chat.add_message("bot", "(Falling back to Gemini…)")
            self._chat_gemini_streaming(prompt)

    # ---------- OpenAI streaming
    def _chat_openai_streaming(self, prompt: str) -> bool:
        model_default = defaults.get("default_model", "gpt-4o-mini")
        model_fast = defaults.get("fast_model", "gpt-4o-mini")
        model = model_fast if self.fast_mode.GetValue() else model_default

        url = (defaults.get("url") or "").strip()
        api_key = (defaults.get("api_key") or "").strip()
        if not url or not api_key:
            self.chat.add_message(
                "bot",
                "I don't see an API endpoint or API key in Settings. "
                "Open Settings → Preferences and fill in the provider URL and API key to chat."
            )
            return False

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        org = (defaults.get("openai_org") or "").strip()
        if org:
            headers["OpenAI-Organization"] = org

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(defaults.get("max_tokens", 800)),
            "temperature": float(defaults.get("temperature", 0.6)),
            "stream": True,
        }

        try:
            with self.session.post(url, headers=headers, json=payload, stream=True, timeout=(8, 90), verify=False) as r:
                if r.status_code in (401, 403):
                    raise requests.HTTPError(f"{r.status_code} auth error", response=r)
                r.raise_for_status()
                wx.CallAfter(self.chat.start_bubble, "bot")
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw:
                        continue
                    if raw.startswith("data: "):
                        raw = raw[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                        delta = obj["choices"][0].get("delta", {}).get("content")
                        if delta:
                            wx.CallAfter(self.chat.write_stream, delta)
                    except Exception:
                        continue
        except Exception as e:
            wx.CallAfter(self.chat.end_bubble)
            wx.CallAfter(self.chat.add_message, "bot", f"Error (OpenAI): {e}")
            return False

        wx.CallAfter(self.chat.end_bubble)
        return True

    # ---------- Gemini streaming
    def _gemini_model(self) -> str:
        return defaults.get("fast_model" if self.fast_mode.GetValue() else "default_model", "gemini-1.5-flash")

    def _gemini_base(self) -> str:
        return (defaults.get("gemini_text_url") or "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")

    def _chat_gemini_streaming(self, prompt: str):
        key = (defaults.get("gemini_api_key") or "").strip()
        if not key:
            self.chat.add_message("bot", "Gemini API key is not set in Settings.")
            return

        model = self._gemini_model()
        base = self._gemini_base()
        url = f"{base}/{model}:streamGenerateContent?alt=SSE&key={key}"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}

        try:
            with self.session.post(url, headers={"Content-Type": "application/json"},
                                   json=body, stream=True, timeout=(8, 90)) as r:
                if r.status_code in (404, 400):
                    raise requests.HTTPError("SSE not available", response=r)
                r.raise_for_status()
                wx.CallAfter(self.chat.start_bubble, "bot")
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        # extract text parts
                        text = None
                        cands = obj.get("candidates") or []
                        if cands:
                            parts = cands[0].get("content", {}).get("parts", [])
                            out = []
                            for p in parts:
                                if "text" in p:
                                    out.append(p["text"])
                            text = "".join(out) if out else None
                        if text:
                            wx.CallAfter(self.chat.write_stream, text)
                    except Exception:
                        continue
        except Exception as e:
            wx.CallAfter(self.chat.end_bubble)
            wx.CallAfter(self.chat.add_message, "bot", f"Error (Gemini): {e}")
            return

        wx.CallAfter(self.chat.end_bubble)

    # ---------- Image generation with fallbacks (OpenAI → Gemini → offline)
    def on_generate_image(self, _):
        prompt = self.prompt.GetValue().strip()
        if not prompt:
            wx.MessageBox("Enter a description in the Ask field first.", "No Prompt", wx.OK | wx.ICON_INFORMATION)
            return
        threading.Thread(target=self._gen_image_worker, args=(prompt,), daemon=True).start()

    def _gen_image_worker(self, prompt: str):
        provider = (defaults.get("image_provider") or os.environ.get("IMAGE_PROVIDER") or "openai").lower().strip()
        order = ["openai", "gemini"] if provider in ("auto", "openai") else [provider]
        if provider == "auto":
            order.append("offline")

        for prov in order:
            try:
                if prov == "openai":
                    path = self._generate_image_openai(prompt)
                elif prov == "gemini":
                    path = self._generate_image_gemini(prompt)
                elif prov == "offline":
                    path = self._generate_image_offline(prompt)
                else:
                    continue
                wx.CallAfter(self._show_image_preview, path)
                return
            except Exception:
                continue
        wx.CallAfter(wx.MessageBox, "Image generation failed.", "Image Error", wx.OK | wx.ICON_ERROR)

    def _generate_image_openai(self, prompt: str) -> str:
        url = (defaults.get("image_generation_url") or "https://api.openai.com/v1/images/generations").strip()
        headers = {"Authorization": f"Bearer {defaults.get('api_key','')}", "Content-Type": "application/json"}
        body = {"model": defaults.get("image_model", "gpt-image-1"), "prompt": prompt, "n": 1, "size": "1024x1024"}
        resp = self.session.post(url, headers=headers, json=body, timeout=120, verify=False)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            raise RuntimeError("No image data returned.")
        b64 = data[0].get("b64_json")
        if b64:
            img_bytes = base64.b64decode(b64)
        else:
            img_url = data[0].get("url")
            img_bytes = requests.get(img_url, timeout=60).content
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(img_bytes)
        tmp.close()
        return tmp.name

    def _generate_image_gemini(self, prompt: str) -> str:
        key = (defaults.get("gemini_api_key") or "").strip()
        if not key:
            raise RuntimeError("No Gemini API key configured.")
        base = (defaults.get("gemini_text_url") or "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")
        model = defaults.get("image_model", "gemini-1.5-flash")
        url = f"{base}/{model}:generateContent?key={key}"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "image/png"}}
        r = self.session.post(url, headers={"Content-Type": "application/json"}, json=body, timeout=120)
        r.raise_for_status()
        obj = r.json()
        cands = obj.get("candidates") or []
        parts = cands[0]["content"]["parts"]
        inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
        img_bytes = base64.b64decode(inline.get("data", ""))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(img_bytes)
        tmp.close()
        return tmp.name

    def _generate_image_offline(self, prompt: str) -> str:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.close()
        if Image and ImageDraw:
            img = Image.new("RGB", (1024, 1024), (32, 36, 44))
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("arial.ttf", 28)
            except Exception:
                font = ImageFont.load_default()
            draw.multiline_text((40, 40), f"[Offline Placeholder]\n{prompt}",
                                fill=(220, 230, 255), font=font, spacing=6)
            img.save(tmp.name, "PNG")
        else:
            bmp = wx.Bitmap(1024, 1024)
            dc = wx.MemoryDC(bmp)
            dc.SetBackground(wx.Brush(wx.Colour(32, 36, 44)))
            dc.Clear()
            dc.SetTextForeground(wx.Colour(220, 230, 255))
            dc.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_BOLD))
            dc.DrawText("[Offline Placeholder]", 40, 40)
            dc.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
            dc.DrawText(prompt, 40, 80)
            dc.SelectObject(wx.NullBitmap)
            bmp.SaveFile(tmp.name, wx.BITMAP_TYPE_PNG)
        return tmp.name

    def _show_image_preview(self, path: str):
        dlg = wx.Dialog(self, title="Generated Image", size=(720, 740),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        pnl = wx.Panel(dlg)
        pnl.SetBackgroundColour(wx.Colour(30, 30, 30))
        v = wx.BoxSizer(wx.VERTICAL)
        img = wx.Image(path, wx.BITMAP_TYPE_ANY)
        w = min(680, img.GetWidth())
        h = int(w * img.GetHeight() / max(1, img.GetWidth()))
        img = img.Scale(w, h, wx.IMAGE_QUALITY_HIGH)
        v.Add(wx.StaticBitmap(pnl, bitmap=wx.Bitmap(img)), 1, wx.ALL | wx.EXPAND, 10)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        save = wx.Button(pnl, label="Save As…")
        close = wx.Button(pnl, label="Close")
        btns.Add(save, 0, wx.ALL, 6)
        btns.Add(close, 0, wx.ALL, 6)
        v.Add(btns, 0, wx.ALIGN_CENTER)

        def on_save(_):
            s = wx.FileDialog(dlg, "Save Image", wildcard="PNG|*.png", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
            if s.ShowModal() == wx.ID_OK:
                wx.Image(path).SaveFile(s.GetPath(), wx.BITMAP_TYPE_PNG)
            s.Destroy()

        save.Bind(wx.EVT_BUTTON, on_save)
        close.Bind(wx.EVT_BUTTON, lambda _: dlg.Destroy())
        pnl.SetSizer(v)
        dlg.ShowModal()

    # --- Voice
    def speak(self, text: str):
        if not text:
            return

        def run_tts():
            try:
                if edge_tts:
                    voice = self.voice.GetStringSelection() or "en-US-GuyNeural"
                    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
                    import asyncio

                    async def _edge():
                        comm = edge_tts.Communicate(text, voice=voice)
                        await comm.save(out)

                    asyncio.run(_edge())
                    self._play_file(out)
                    return
                if gTTS:
                    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
                    gTTS(text).save(out)
                    self._play_file(out)
                    return
                if pyttsx3:
                    eng = pyttsx3.init()
                    eng.say(text)
                    eng.runWait()
                    return
            except Exception:
                pass

        t = threading.Thread(target=run_tts, daemon=True)
        t.start()

    def _play_file(self, path):
        if not pygame:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        except Exception:
            pass

    # --- Speech recog toggle (optional)
    def on_mic_toggle(self, _):
        if not sr:
            wx.MessageBox("SpeechRecognition not installed.", "Mic", wx.OK | wx.ICON_INFORMATION)
            return
        threading.Thread(target=self._sr_worker, daemon=True).start()

    def _sr_worker(self):
        try:
            r = sr.Recognizer()
            with sr.Microphone() as src:
                self.tts_status.SetLabel("TTS: listening…")
                audio = r.listen(src, timeout=4, phrase_time_limit=8)
            text = r.recognize_google(audio)
            self.tts_status.SetLabel("TTS: idle")
            wx.CallAfter(self.prompt.SetValue, text)
            wx.CallAfter(self.on_ask, None)
        except Exception:
            wx.CallAfter(self.tts_status.SetLabel, "TTS: idle")

    def on_stop_voice(self, _):
        try:
            if pygame and pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
