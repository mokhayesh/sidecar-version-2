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

# Optional audio / speech libs (gracefully degrade)
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
                         size=(740, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.fields = fields
        self.current_rules = current_rules
        self.loaded_rules = {}

        BG = wx.Colour(45, 45, 45)
        PANEL = wx.Colour(50, 50, 50)
        TXT = wx.Colour(235, 235, 235)
        INPUT_BG = wx.Colour(60, 60, 60)
        INPUT_TXT = wx.Colour(240, 240, 240)
        ACCENT = wx.Colour(70, 130, 180)

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
        self.preview.SetBackgroundColour(wx.Colour(35, 35, 35))
        self.preview.SetForegroundColour(wx.Colour(230, 230, 230))
        self.preview.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.NORMAL))
        pv.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(pv, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        abox = wx.StaticBox(pnl, label="Assignments")
        abox.SetForegroundColour(TXT)
        asz = wx.StaticBoxSizer(abox, wx.VERTICAL)
        self.assign_view = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.assign_view.InsertColumn(0, "Field", width=180)
        self.assign_view.InsertColumn(1, "Assigned Pattern", width=440)
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
# Little Buddy — modern look + streaming + TTS + image generation
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

        self._tts_file = None
        self._tts_thread = None

        self.COLORS = {
            "bg": wx.Colour(35, 35, 35),
            "panel": wx.Colour(38, 38, 38),
            "text": wx.Colour(230, 230, 230),
            "muted": wx.Colour(190, 190, 190),
            "accent": wx.Colour(70, 130, 180),
            "input_bg": wx.Colour(50, 50, 50),
            "input_fg": wx.Colour(240, 240, 240),
            "bubble_user_bg": wx.Colour(44, 62, 80),
            "bubble_user_fg": wx.Colour(240, 240, 240),
            "bubble_bot_bg": wx.Colour(56, 42, 120),
            "bubble_bot_fg": wx.Colour(255, 255, 255),
            "reply_bg": wx.Colour(28, 28, 28),
            "reply_fg": wx.Colour(255, 255, 255),
        }

        self.SetBackgroundColour(self.COLORS["bg"])
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(self.COLORS["panel"])
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(pnl, label="Little Buddy")
        title.SetForegroundColour(self.COLORS["text"])
        title.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_BOLD))
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
        opts.Add(self.tts_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        self.fast_mode = wx.CheckBox(pnl, label="⚡ Fast Mode")
        self.fast_mode.SetValue(True)
        self.fast_mode.SetForegroundColour(self.COLORS["text"])
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

        send_btn = wx.Button(pnl, label="Send")
        send_btn.SetBackgroundColour(self.COLORS["accent"])
        send_btn.SetForegroundColour(wx.WHITE)
        send_btn.Bind(wx.EVT_BUTTON, self.on_ask)
        row.Add(send_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.mic_btn = wx.Button(pnl, label="🎙 Speak")
        self.mic_btn.SetBackgroundColour(wx.Colour(60, 120, 90))
        self.mic_btn.SetForegroundColour(wx.WHITE)
        self.mic_btn.Bind(wx.EVT_BUTTON, self.on_mic_toggle)
        row.Add(self.mic_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.stop_btn = wx.Button(pnl, label="Stop")
        self.stop_btn.SetBackgroundColour(wx.Colour(150, 60, 60))
        self.stop_btn.SetForegroundColour(wx.WHITE)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop_voice)
        row.Add(self.stop_btn, 0, wx.ALIGN_CENTER_VERTICAL, 0)

        self.img_btn = wx.Button(pnl, label="🎨 Generate Image")
        self.img_btn.SetBackgroundColour(wx.Colour(90, 110, 160))
        self.img_btn.SetForegroundColour(wx.WHITE)
        self.img_btn.Bind(wx.EVT_BUTTON, self.on_generate_image)
        row.Add(self.img_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)

        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 5)

        # Chat area
        self.reply = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        self.reply.SetBackgroundColour(self.COLORS["reply_bg"])
        self.reply.SetForegroundColour(self.COLORS["reply_fg"])
        self._reset_reply_style()
        vbox.Add(self.reply, 1, wx.EXPAND | wx.ALL, 6)

        pnl.SetSizer(vbox)

        # Greet
        self._append_user_bubble("Hi!", fake=True)
        self._append_bot_bubble("Hi, I'm Little Buddy!")

    def set_kernel(self, kernel):
        self.kernel = kernel
        try:
            kpath = kernel.path
            if kpath and kpath not in self.knowledge:
                self.knowledge.append(kpath)
        except Exception:
            pass

    # Bubble helpers (chat look)
    def _reset_reply_style(self):
        attr = rt.RichTextAttr()
        attr.SetTextColour(self.COLORS["reply_fg"])
        attr.SetFontSize(11)
        attr.SetFontFaceName("Segoe UI")
        self.reply.SetDefaultStyle(attr)
        self.reply.SetBasicStyle(attr)

    def _start_bubble(self, sender: str):
        if self.reply.GetLastPosition() > 0:
            self.reply.Newline()

        attr = rt.RichTextAttr()
        if sender == "user":
            attr.SetBackgroundColour(self.COLORS["bubble_user_bg"])
            attr.SetTextColour(self.COLORS["bubble_user_fg"])
        else:
            attr.SetBackgroundColour(self.COLORS["bubble_bot_bg"])
            attr.SetTextColour(self.COLORS["bubble_bot_fg"])

        attr.SetLeftIndent(20, 40)
        attr.SetRightIndent(20)
        attr.SetParagraphSpacingAfter(6)
        attr.SetFontSize(11)
        attr.SetFontFaceName("Segoe UI")

        self.reply.BeginStyle(attr)

    def _end_bubble(self):
        self.reply.EndStyle()

    def _append_user_bubble(self, text: str, fake: bool = False):
        self._start_bubble("user")
        self.reply.WriteText(text)
        self._end_bubble()
        if not fake:
            self.reply.Newline()

    def _append_bot_bubble(self, text: str):
        self._start_bubble("bot")
        self.reply.WriteText(text)
        self._end_bubble()
        self.reply.Newline()

    # ---------- chat entrypoint
    def on_ask(self, _):
        q = self.prompt.GetValue().strip()
        self.prompt.SetValue("")
        if not q:
            return
        self._append_user_bubble(q)
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
            self._append_bot_bubble("(Falling back to Gemini…)")
            self._chat_gemini_streaming(prompt)

    # ---------- OpenAI streaming
    def _chat_openai_streaming(self, prompt: str) -> bool:
        model_default = defaults.get("default_model", "gpt-4o-mini")
        model_fast = defaults.get("fast_model", "gpt-4o-mini")
        model = model_fast if self.fast_mode.GetValue() else model_default

        url = defaults.get("url", "").strip()
        headers = {
            "Authorization": f"Bearer {defaults.get('api_key','')}",
            "Content-Type": "application/json",
        }
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

        buf = []
        try:
            with self.session.post(url, headers=headers, json=payload, stream=True, timeout=(8, 90), verify=False) as r:
                if r.status_code in (401, 403):
                    raise requests.HTTPError(f"{r.status_code} auth error", response=r)
                r.raise_for_status()
                self._start_bubble("bot")
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
                            buf.append(delta)
                            wx.CallAfter(self.reply.WriteText, delta)
                    except Exception:
                        continue
        except Exception as e:
            wx.CallAfter(self._end_bubble)
            wx.CallAfter(self._append_bot_bubble, f"Error (OpenAI): {e}")
            return False

        wx.CallAfter(self._end_bubble)
        answer = "".join(buf)
        if self.tts_checkbox.GetValue() and answer.strip():
            wx.CallAfter(lambda: self.speak(answer))
        return True

    # ---------- Gemini streaming
    def _gemini_model(self) -> str:
        return defaults.get("fast_model" if self.fast_mode.GetValue() else "default_model",
                            "gemini-1.5-flash")

    def _gemini_base(self) -> str:
        return (defaults.get("gemini_text_url") or "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")

    def _chat_gemini_streaming(self, prompt: str):
        key = (defaults.get("gemini_api_key") or "").strip()
        if not key:
            self._append_bot_bubble("Error: Gemini API key is not set in Settings.")
            return

        model = self._gemini_model()
        base = self._gemini_base()
        url = f"{base}/{model}:streamGenerateContent?alt=SSE&key={key}"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}

        buf = []
        try:
            with self.session.post(url, headers={"Content-Type": "application/json"},
                                   json=body, stream=True, timeout=(8, 90)) as r:
                if r.status_code in (404, 400):
                    raise requests.HTTPError("SSE not available", response=r)
                r.raise_for_status()
                self._start_bubble("bot")
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
                        text = self._extract_gemini_text(obj)
                        if text:
                            buf.append(text)
                            wx.CallAfter(self.reply.WriteText, text)
                    except Exception:
                        continue
        except Exception:
            try:
                url2 = f"{base}/{model}:generateContent?key={key}"
                r2 = self.session.post(url2, headers={"Content-Type": "application/json"},
                                       json=body, timeout=90)
                r2.raise_for_status()
                obj = r2.json()
                text = self._extract_gemini_text(obj) or ""
                wx.CallAfter(self._append_bot_bubble, text)
                buf = [text]
            except Exception as e2:
                wx.CallAfter(self._append_bot_bubble, f"Error (Gemini): {e2}")
                return

        wx.CallAfter(self._end_bubble)
        answer = "".join(buf)
        if self.tts_checkbox.GetValue() and answer.strip():
            wx.CallAfter(lambda: self.speak(answer))

    @staticmethod
    def _extract_gemini_text(obj) -> str | None:
        try:
            cands = obj.get("candidates") or []
            if not cands:
                return None
            content = cands[0].get("content") or {}
            parts = content.get("parts") or []
            out = []
            for p in parts:
                if "text" in p:
                    out.append(p["text"])
            return "".join(out) if out else None
        except Exception:
            return None

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

    # ---------- Voice (three fallbacks; keeps current behavior)
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
                    eng.runAndWait()
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

    # STT (optional)
    def on_mic_toggle(self, _evt):
        if not sr:
            wx.MessageBox("SpeechRecognition not installed.", "Speak", wx.OK | wx.ICON_INFORMATION)
            return
        r = sr.Recognizer()
        with sr.Microphone() as source:
            self.tts_status.SetLabel("TTS: listening…")
            audio = r.listen(source, phrase_time_limit=6)
        try:
            text = r.recognize_google(audio)
            self.prompt.SetValue(text)
            self.on_ask(None)
        except Exception as e:
            wx.MessageBox(f"STT failed: {e}", "Speak", wx.OK | wx.ICON_ERROR)

    def on_stop_voice(self, _evt):
        try:
            if pygame and pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
