import wx
import wx.richtext as rt
import re
import json
import threading
import requests
import pygame
from app.settings import defaults

class QualityRuleDialog(wx.Dialog):
    def __init__(self, parent, fields, current_rules):
        super().__init__(parent, title="Quality Rule Assignment", size=(740, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.fields = fields
        self.current_rules = current_rules
        self.loaded_rules = {}

        pnl = wx.Panel(self)
        main = wx.BoxSizer(wx.VERTICAL)

        # Field list
        fbox = wx.StaticBox(pnl, label="Fields")
        fsz = wx.StaticBoxSizer(fbox, wx.HORIZONTAL)
        self.field_list = wx.ListBox(pnl, choices=list(fields), style=wx.LB_EXTENDED)
        fsz.Add(self.field_list, 1, wx.EXPAND | wx.ALL, 5)
        main.Add(fsz, 1, wx.EXPAND | wx.ALL, 5)

        # Rule input
        g = wx.FlexGridSizer(2, 2, 5, 5)
        g.AddGrowableCol(1, 1)
        g.Add(wx.StaticText(pnl, label="Select loaded rule:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.rule_choice = wx.ComboBox(pnl, style=wx.CB_READONLY)
        self.rule_choice.Bind(wx.EVT_COMBOBOX, self.on_pick_rule)
        g.Add(self.rule_choice, 0, wx.EXPAND)
        g.Add(wx.StaticText(pnl, label="Or enter regex pattern:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.pattern_txt = wx.TextCtrl(pnl)
        g.Add(self.pattern_txt, 0, wx.EXPAND)
        main.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Rule preview
        pbox = wx.StaticBox(pnl, label="Loaded JSON preview")
        pv = wx.StaticBoxSizer(pbox, wx.VERTICAL)
        self.preview = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
        pv.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(pv, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Assigned rules
        abox = wx.StaticBox(pnl, label="Assignments")
        asz = wx.StaticBoxSizer(abox, wx.VERTICAL)
        self.assign_view = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.assign_view.InsertColumn(0, "Field", width=180)
        self.assign_view.InsertColumn(1, "Assigned Pattern", width=440)
        asz.Add(self.assign_view, 1, wx.EXPAND | wx.ALL, 4)
        main.Add(asz, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Buttons
        btns = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(pnl, label="Load Rules JSON")
        load_btn.Bind(wx.EVT_BUTTON, self.on_load_rules)
        assign_btn = wx.Button(pnl, label="Assign To Selected Field(s)")
        assign_btn.Bind(wx.EVT_BUTTON, self.on_assign)
        close_btn = wx.Button(pnl, label="Save / Close")
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


class DataBuddyDialog(wx.Dialog):
    def __init__(self, parent, data=None, headers=None):
        super().__init__(parent, title="Little Buddy", size=(800, 600),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.data = data
        self.headers = headers

        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(wx.Colour(30, 30, 30))
        vbox = wx.BoxSizer(wx.VERTICAL)

        pygame.mixer.init()
        voice = wx.Choice(pnl, choices=["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"])
        voice.SetSelection(1)
        vbox.Add(voice, 0, wx.EXPAND | wx.ALL, 5)

        self.persona = wx.ComboBox(pnl, choices=[
            "Data Architect", "Data Engineer", "Data Quality Expert", "Data Scientist", "Yoda"],
            style=wx.CB_READONLY)
        self.persona.SetSelection(0)
        vbox.Add(self.persona, 0, wx.EXPAND | wx.ALL, 5)

        h = wx.BoxSizer(wx.HORIZONTAL)
        h.Add(wx.StaticText(pnl, label="Ask:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.prompt = wx.TextCtrl(pnl, style=wx.TE_PROCESS_ENTER)
        self.prompt.Bind(wx.EVT_TEXT_ENTER, self.on_ask)
        h.Add(self.prompt, 1, wx.EXPAND | wx.RIGHT, 5)
        send_btn = wx.Button(pnl, label="Send")
        send_btn.Bind(wx.EVT_BUTTON, self.on_ask)
        h.Add(send_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(h, 0, wx.EXPAND | wx.ALL, 5)

        self.reply = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.reply.SetBackgroundColour(wx.Colour(50, 50, 50))
        self.reply.SetForegroundColour(wx.Colour(255, 255, 255))
        vbox.Add(self.reply, 1, wx.EXPAND | wx.ALL, 5)

        pnl.SetSizer(vbox)
        self.reply.WriteText("Hi, I'm Little Buddy!")

    def on_ask(self, _):
        q = self.prompt.GetValue().strip()
        self.prompt.SetValue("")
        if not q:
            return
        self.reply.Clear()
        self.reply.WriteText("Thinking...")
        threading.Thread(target=self._answer, args=(q,), daemon=True).start()

    def _answer(self, q):
        persona = self.persona.GetValue()
        prompt = f"As a {persona}, {q}" if persona else q
        if self.data:
            prompt += "\nData sample:\n" + "; ".join(map(str, self.data[0]))

        try:
            resp = requests.post(
                defaults["url"],
                headers={
                    "Authorization": f"Bearer {defaults['api_key']}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": defaults["default_model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": int(defaults["max_tokens"]),
                    "temperature": float(defaults["temperature"])
                },
                timeout=60,
                verify=False
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            answer = f"Error: {e}"

        wx.CallAfter(self.reply.Clear)
        wx.CallAfter(self.reply.WriteText, answer)
