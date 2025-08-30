import wx
import wx.richtext as rt
import re
import json
import threading
import requests

# Optional audio (reserved for future voice UI)
try:
    import pygame
except Exception:
    pygame = None

from app.settings import defaults


# ──────────────────────────────────────────────────────────────────────────────
# Quality Rule Assignment Dialog (dark theme)
# ──────────────────────────────────────────────────────────────────────────────
class QualityRuleDialog(wx.Dialog):
    def __init__(self, parent, fields, current_rules):
        super().__init__(
            parent,
            title="Quality Rule Assignment",
            size=(740, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.fields = fields
        self.current_rules = current_rules
        self.loaded_rules = {}

        # Theme
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

        # Fields list
        fbox = wx.StaticBox(pnl, label="Fields")
        fbox.SetForegroundColour(TXT)
        fsz = wx.StaticBoxSizer(fbox, wx.HORIZONTAL)

        self.field_list = wx.ListBox(pnl, choices=list(fields), style=wx.LB_EXTENDED)
        self.field_list.SetBackgroundColour(INPUT_BG)
        self.field_list.SetForegroundColour(INPUT_TXT)
        self.field_list.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        fsz.Add(self.field_list, 1, wx.EXPAND | wx.ALL, 5)
        main.Add(fsz, 1, wx.EXPAND | wx.ALL, 5)

        # Rule input
        g = wx.FlexGridSizer(2, 2, 5, 5)
        g.AddGrowableCol(1, 1)

        lbl1 = wx.StaticText(pnl, label="Select loaded rule:")
        lbl1.SetForegroundColour(TXT)
        g.Add(lbl1, 0, wx.ALIGN_CENTER_VERTICAL)

        self.rule_choice = wx.ComboBox(pnl, style=wx.CB_READONLY)
        self.rule_choice.SetBackgroundColour(INPUT_BG)
        self.rule_choice.SetForegroundColour(INPUT_TXT)
        self.rule_choice.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        self.rule_choice.Bind(wx.EVT_COMBOBOX, self.on_pick_rule)
        g.Add(self.rule_choice, 0, wx.EXPAND)

        lbl2 = wx.StaticText(pnl, label="Or enter regex pattern:")
        lbl2.SetForegroundColour(TXT)
        g.Add(lbl2, 0, wx.ALIGN_CENTER_VERTICAL)

        self.pattern_txt = wx.TextCtrl(pnl)
        self.pattern_txt.SetBackgroundColour(INPUT_BG)
        self.pattern_txt.SetForegroundColour(INPUT_TXT)
        self.pattern_txt.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        g.Add(self.pattern_txt, 0, wx.EXPAND)
        main.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # JSON preview
        pbox = wx.StaticBox(pnl, label="Loaded JSON preview")
        pbox.SetForegroundColour(TXT)
        pv = wx.StaticBoxSizer(pbox, wx.VERTICAL)
        self.preview = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
        self.preview.SetBackgroundColour(wx.Colour(35, 35, 35))
        self.preview.SetForegroundColour(wx.Colour(230, 230, 230))
        self.preview.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        pv.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(pv, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Assignments
        abox = wx.StaticBox(pnl, label="Assignments")
        abox.SetForegroundColour(TXT)
        asz = wx.StaticBoxSizer(abox, wx.VERTICAL)
        self.assign_view = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.assign_view.InsertColumn(0, "Field", width=180)
        self.assign_view.InsertColumn(1, "Assigned Pattern", width=440)
        asz.Add(self.assign_view, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(asz, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Buttons
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
# Little Buddy Chat Dialog (high-contrast + knowledge files context)
# ──────────────────────────────────────────────────────────────────────────────
class DataBuddyDialog(wx.Dialog):
    def __init__(self, parent, data=None, headers=None, knowledge=None):
        super().__init__(
            parent,
            title="Little Buddy",
            size=(820, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.data = data
        self.headers = headers
        self.knowledge = knowledge or []  # list of dicts: {name, path, type, content}

        # High-contrast theme for readability
        self.COLORS = {
            "bg": wx.Colour(35, 35, 35),
            "panel": wx.Colour(38, 38, 38),
            "text": wx.Colour(230, 230, 230),
            "muted": wx.Colour(190, 190, 190),
            "accent": wx.Colour(70, 130, 180),
            "input_bg": wx.Colour(50, 50, 50),
            "input_fg": wx.Colour(240, 240, 240),
            "reply_bg": wx.Colour(28, 28, 28),
            "reply_fg": wx.Colour(255, 255, 255),  # pure white for contrast
        }

        self.SetBackgroundColour(self.COLORS["bg"])
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(self.COLORS["panel"])
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Title
        title = wx.StaticText(pnl, label="Little Buddy")
        title.SetForegroundColour(self.COLORS["text"])
        title.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_BOLD))
        vbox.Add(title, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        # (Optional) audio init protected
        try:
            if pygame and not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            pass

        # Voice selector
        self.voice = wx.Choice(pnl, choices=["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"])
        self.voice.SetSelection(1)
        self.voice.SetBackgroundColour(self.COLORS["input_bg"])
        self.voice.SetForegroundColour(self.COLORS["input_fg"])
        self.voice.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        vbox.Add(self.voice, 0, wx.EXPAND | wx.ALL, 5)

        # Persona selector
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

        # Prompt row
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
        send_btn.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        send_btn.Bind(wx.EVT_BUTTON, self.on_ask)
        row.Add(send_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 5)

        # Reply area (RichText)
        self.reply = rt.RichTextCtrl(
            pnl,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE
        )
        self.reply.SetBackgroundColour(self.COLORS["reply_bg"])
        self.reply.SetForegroundColour(self.COLORS["reply_fg"])
        self._reset_reply_style()
        vbox.Add(self.reply, 1, wx.EXPAND | wx.ALL, 6)

        pnl.SetSizer(vbox)

        # Initial message
        self._write_reply("Hi, I'm Little Buddy!")

    # ----- styling helpers -------------------------------------------------
    def _current_attr(self):
        attr = rt.RichTextAttr()
        attr.SetTextColour(self.COLORS["reply_fg"])  # white text
        attr.SetFontSize(11)                         # readable size
        attr.SetFontFaceName("Segoe UI")             # clean Windows font
        return attr

    def _reset_reply_style(self):
        """Reapply both default and basic styles so new text is white."""
        attr = self._current_attr()
        self.reply.SetDefaultStyle(attr)  # affects subsequent inserts
        self.reply.SetBasicStyle(attr)    # base style of the control

    def _write_reply(self, text: str, newline: bool = False):
        """Write with a forced style block to avoid theme overrides."""
        attr = self._current_attr()
        self.reply.BeginStyle(attr)
        try:
            self.reply.WriteText(text + ("\n" if newline else ""))
        finally:
            self.reply.EndStyle()

    # ----- knowledge context ----------------------------------------------
    def _build_knowledge_context(self, max_chars=1500):
        """
        Build a compact textual context from the loaded knowledge files:
        - CSV/JSON/TXT: include a truncated snippet.
        - Images/binary: include filename only.
        """
        if not self.knowledge:
            return ""
        chunks = []
        for f in self.knowledge:
            name = f.get("name", "file")
            typ = (f.get("type") or "").lower()
            content = f.get("content")
            if content and isinstance(content, str):
                # allocate space across files fairly
                per_file = max(200, max_chars // max(1, len(self.knowledge)))
                snippet = content[:min(len(content), per_file)].strip()
                chunks.append(f"File: {name}\n{snippet}")
            else:
                # image or unreadable: just reference it
                chunks.append(f"File: {name} (image or binary)")
        text = "\n\n".join(chunks)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(truncated)…"
        return text

    # ----- events ----------------------------------------------------------
    def on_ask(self, _):
        q = self.prompt.GetValue().strip()
        self.prompt.SetValue("")
        if not q:
            return
        self.reply.Clear()
        self._reset_reply_style()
        self._write_reply("Thinking...")

        threading.Thread(target=self._answer, args=(q,), daemon=True).start()

    def _answer(self, q: str):
        persona = self.persona.GetValue()
        prompt = f"As a {persona}, {q}" if persona else q

        if self.data:
            prompt += "\n\nData sample:\n" + "; ".join(map(str, self.data[0]))

        # Include knowledge files context
        kn = self._build_knowledge_context()
        if kn:
            prompt += "\n\nKnowledge files:\n" + kn

        try:
            resp = requests.post(
                defaults["url"],
                headers={
                    "Authorization": f"Bearer {defaults['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": defaults["default_model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": int(defaults["max_tokens"]),
                    "temperature": float(defaults["temperature"]),
                },
                timeout=60,
                verify=False,
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            answer = f"Error: {e}"

        def render():
            self.reply.Clear()
            self._reset_reply_style()
            self._write_reply(answer)

        wx.CallAfter(render)


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic Data Dialog (choose record count and fields) — fixed parent/sizer
# ──────────────────────────────────────────────────────────────────────────────
class SyntheticDataDialog(wx.Dialog):
    """Popup to choose how many synthetic rows to generate and which fields to include."""
    def __init__(self, parent, fields):
        super().__init__(
            parent,
            title="Generate Synthetic Data",
            size=(520, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        # Theme (match app)
        BG = wx.Colour(38, 38, 38)
        PANEL = wx.Colour(38, 38, 38)
        TXT = wx.Colour(235, 235, 235)
        INPUT_BG = wx.Colour(50, 50, 50)
        INPUT_TXT = wx.Colour(240, 240, 240)
        ACCENT = wx.Colour(70, 130, 180)

        self.SetBackgroundColour(BG)

        # Top-level sizer for the dialog
        top = wx.BoxSizer(wx.VERTICAL)

        # All controls live on this panel; its sizer manages them
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(PANEL)
        top.Add(pnl, 1, wx.EXPAND)
        s = wx.BoxSizer(wx.VERTICAL)
        pnl.SetSizer(s)

        # How many rows
        box1 = wx.StaticBox(pnl, label="How many records?")
        box1.SetForegroundColour(TXT)
        s1 = wx.StaticBoxSizer(box1, wx.HORIZONTAL)
        self.count = wx.SpinCtrl(pnl, min=1, max=1_000_000, initial=100)
        self.count.SetBackgroundColour(INPUT_BG)
        self.count.SetForegroundColour(INPUT_TXT)
        self.count.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        s1.Add(self.count, 1, wx.ALL | wx.EXPAND, 6)
        s.Add(s1, 0, wx.EXPAND | wx.ALL, 8)

        # Which fields
        box2 = wx.StaticBox(pnl, label="Choose fields to include")
        box2.SetForegroundColour(TXT)
        s2 = wx.StaticBoxSizer(box2, wx.VERTICAL)
        self.chk = wx.CheckListBox(pnl, choices=list(fields))
        self.chk.SetBackgroundColour(INPUT_BG)
        self.chk.SetForegroundColour(INPUT_TXT)
        self.chk.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        for i in range(len(fields)):
            self.chk.Check(i, True)  # default: all selected
        s2.Add(self.chk, 1, wx.ALL | wx.EXPAND, 6)

        # quick select buttons
        row = wx.BoxSizer(wx.HORIZONTAL)
        btn_all = wx.Button(pnl, label="Select All")
        btn_none = wx.Button(pnl, label="Clear")
        for b in (btn_all, btn_none):
            b.SetBackgroundColour(ACCENT)
            b.SetForegroundColour(wx.WHITE)
        btn_all.Bind(wx.EVT_BUTTON, lambda e: [self.chk.Check(i, True) for i in range(self.chk.GetCount())])
        btn_none.Bind(wx.EVT_BUTTON, lambda e: [self.chk.Check(i, False) for i in range(self.chk.GetCount())])
        row.Add(btn_all, 0, wx.RIGHT, 6)
        row.Add(btn_none, 0)
        s2.Add(row, 0, wx.LEFT | wx.BOTTOM, 6)

        s.Add(s2, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # OK/Cancel buttons — IMPORTANT: children of pnl (not self)
        btns = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(pnl, wx.ID_OK)
        cancel_btn = wx.Button(pnl, wx.ID_CANCEL)
        for b in (ok_btn, cancel_btn):
            b.SetBackgroundColour(ACCENT)
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT_NORMAL))
        btns.AddButton(ok_btn)
        btns.AddButton(cancel_btn)
        btns.Realize()
        s.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        # Finish layout
        self.SetSizerAndFit(top)

    def get_values(self):
        n = int(self.count.GetValue())
        selected = [self.chk.GetString(i) for i in range(self.chk.GetCount()) if self.chk.IsChecked(i)]
        return n, selected
