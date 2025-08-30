import os
import re
import json
import base64
import threading
import tempfile
import requests
import wx
import wx.richtext as rt

# Optional audio / speech libs
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

from app.settings import defaults


# ──────────────────────────────────────────────────────────────────────────────
# Quality Rule Assignment (unchanged style)
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
        self.preview.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
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
            b.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
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
# Little Buddy: faster streaming replies + image generation + TTS/STT
# ──────────────────────────────────────────────────────────────────────────────
class DataBuddyDialog(wx.Dialog):
    def __init__(self, parent, data=None, headers=None, knowledge=None):
        super().__init__(parent, title="Little Buddy", size=(900, 700),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.session = requests.Session()  # keep-alive for faster first byte
        self.data = data
        self.headers = headers
        self.knowledge = knowledge or []

        self._tts_file = None
        self._tts_thread = None
        self._listening = False
        self._stop_listening = None

        self.COLORS = {
            "bg": wx.Colour(35, 35, 35),
            "panel": wx.Colour(38, 38, 38),
            "text": wx.Colour(230, 230, 230),
            "muted": wx.Colour(190, 190, 190),
            "accent": wx.Colour(70, 130, 180),
            "input_bg": wx.Colour(50, 50, 50),
            "input_fg": wx.Colour(240, 240, 240),
            "reply_bg": wx.Colour(28, 28, 28),
            "reply_fg": wx.Colour(255, 255, 255),
        }

        self.SetBackgroundColour(self.COLORS["bg"])
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(self.COLORS["panel"])
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(pnl, label="Little Buddy")
        title.SetForegroundColour(self.COLORS["text"])
        title.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        vbox.Add(title, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        opts = wx.BoxSizer(wx.HORIZONTAL)
        self.voice = wx.Choice(pnl, choices=["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"])
        self.voice.SetSelection(1)
        self.voice.SetBackgroundColour(self.COLORS["input_bg"])
        self.voice.SetForegroundColour(self.COLORS["input_fg"])
        self.voice.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        opts.Add(self.voice, 0, wx.RIGHT | wx.EXPAND, 6)

        self.tts_checkbox = wx.CheckBox(pnl, label="🔊 Speak Reply")
        self.tts_checkbox.SetValue(True)
        self.tts_checkbox.SetForegroundColour(self.COLORS["text"])
        opts.Add(self.tts_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        self.tts_status = wx.StaticText(pnl, label="TTS: idle")
        self.tts_status.SetForegroundColour(self.COLORS["muted"])
        self.tts_status.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        opts.Add(self.tts_status, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)

        vbox.Add(opts, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.persona = wx.ComboBox(
            pnl,
            choices=["Data Architect", "Data Engineer", "Data Quality Expert", "Data Scientist", "Yoda"],
            style=wx.CB_READONLY,
        )
        self.persona.SetSelection(0)
        self.persona.SetBackgroundColour(self.COLORS["input_bg"])
        this_fg = self.COLORS["input_fg"]
        self.persona.SetForegroundColour(this_fg)
        self.persona.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        vbox.Add(self.persona, 0, wx.EXPAND | wx.ALL, 5)

        row = wx.BoxSizer(wx.HORIZONTAL)
        ask_lbl = wx.StaticText(pnl, label="Ask:")
        ask_lbl.SetForegroundColour(self.COLORS["muted"])
        ask_lbl.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        row.Add(ask_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.prompt = wx.TextCtrl(pnl, style=wx.TE_PROCESS_ENTER)
        self.prompt.SetBackgroundColour(self.COLORS["input_bg"])
        self.prompt.SetForegroundColour(this_fg)
        self.prompt.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
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

        # New: image generation button
        self.img_btn = wx.Button(pnl, label="🎨 Generate Image")
        self.img_btn.SetBackgroundColour(wx.Colour(90, 110, 160))
        self.img_btn.SetForegroundColour(wx.WHITE)
        self.img_btn.Bind(wx.EVT_BUTTON, self.on_generate_image)
        row.Add(self.img_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)

        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 5)

        self.reply = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE)
        self.reply.SetBackgroundColour(self.COLORS["reply_bg"])
        self.reply.SetForegroundColour(self.COLORS["reply_fg"])
        self._reset_reply_style()
        vbox.Add(self.reply, 1, wx.EXPAND | wx.ALL, 6)

        pnl.SetSizer(vbox)
        self._write_reply("Hi, I'm Little Buddy!")

    # ---------- helpers
    def _current_attr(self):
        attr = rt.RichTextAttr()
        attr.SetTextColour(self.COLORS["reply_fg"])
        attr.SetFontSize(11)
        attr.SetFontFaceName("Segoe UI")
        return attr

    def _reset_reply_style(self):
        attr = self._current_attr()
        self.reply.SetDefaultStyle(attr)
        self.reply.SetBasicStyle(attr)

    def _write_reply(self, text, newline=False):
        attr = self._current_attr()
        self.reply.BeginStyle(attr)
        try:
            self.reply.WriteText(text + ("\n" if newline else ""))
        finally:
            self.reply.EndStyle()

    def _set_tts_status(self, msg):
        try:
            self.tts_status.SetLabel(f"TTS: {msg}")
            self.tts_status.GetParent().Layout()
        except Exception:
            pass

    def _build_knowledge_context(self, max_chars=1200):
        if not self.knowledge:
            return ""
        chunks = []
        per_file = max(180, max_chars // max(1, len(self.knowledge)))
        for f in self.knowledge:
            name = f.get("name", "file")
            content = f.get("content")
            if content and isinstance(content, str):
                snippet = content[:min(len(content), per_file)].strip()
                chunks.append(f"File: {name}\n{snippet}")
            else:
                chunks.append(f"File: {name} (image or binary)")
        text = "\n\n".join(chunks)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(truncated)…"
        return text

    # ---------- chat
    def on_ask(self, _):
        q = self.prompt.GetValue().strip()
        self.prompt.SetValue("")
        if not q:
            return
        self.reply.Clear()
        self._reset_reply_style()
        self._write_reply("Thinking…\n")

        threading.Thread(target=self._answer_streaming, args=(q,), daemon=True).start()

    def _answer_streaming(self, q: str):
        """Streams tokens so reply starts immediately."""
        persona = self.persona.GetValue()
        prompt = f"As a {persona}, {q}" if persona else q

        if self.data:
            prompt += "\n\nData sample:\n" + "; ".join(map(str, self.data[0]))

        kn = self._build_knowledge_context()
        if kn:
            prompt += "\n\nKnowledge files:\n" + kn

        url = defaults.get("url", "").strip()
        headers = {
            "Authorization": f"Bearer {defaults.get('api_key','')}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": defaults.get("default_model", "gpt-4o-mini"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(defaults.get("max_tokens", 800)),
            "temperature": float(defaults.get("temperature", 0.6)),
            "stream": True,
        }

        buf = []

        try:
            with self.session.post(url, headers=headers, json=payload, stream=True, timeout=(10, 90), verify=False) as r:
                r.raise_for_status()
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw:
                        continue
                    if raw.startswith("data: "):
                        raw = raw[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                        # OpenAI chat-completions delta format
                        delta = obj["choices"][0].get("delta", {}).get("content")
                        if delta:
                            buf.append(delta)
                            wx.CallAfter(self._write_reply, delta)
                    except Exception:
                        continue
        except Exception as e:
            wx.CallAfter(self.reply.Clear)
            wx.CallAfter(self._write_reply, f"Error: {e}")
            return

        answer = "".join(buf)
        if self.tts_checkbox.GetValue() and answer.strip():
            wx.CallAfter(lambda: self.speak(answer))

    # ---------- image generation
    def on_generate_image(self, _):
        prompt = self.prompt.GetValue().strip()
        if not prompt:
            wx.MessageBox("Enter a description in the Ask field first.", "No Prompt", wx.OK | wx.ICON_INFORMATION)
            return
        threading.Thread(target=self._gen_image_worker, args=(prompt,), daemon=True).start()

    def _gen_image_worker(self, prompt: str):
        url = defaults.get("image_generation_url", "").strip()
        headers = {
            "Authorization": f"Bearer {defaults.get('api_key','')}",
            "Content-Type": "application/json",
        }
        # Try modern format first (with model), fall back to classic
        body = {
            "model": defaults.get("image_model", "gpt-image-1"),
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        try:
            resp = self.session.post(url, headers=headers, json=body, timeout=120, verify=False)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                raise RuntimeError("No image returned.")
            b64 = data[0].get("b64_json")
            if not b64:
                # some providers return 'url' instead of base64
                img_url = data[0].get("url")
                if not img_url:
                    raise RuntimeError("No image payload.")
                img_bytes = requests.get(img_url, timeout=60).content
            else:
                img_bytes = base64.b64decode(b64)

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.write(img_bytes)
            tmp.close()
            wx.CallAfter(self._show_image_preview, tmp.name)
        except Exception as e:
            wx.CallAfter(wx.MessageBox, f"Image generation failed:\n{e}", "Image Error", wx.OK | wx.ICON_ERROR)

    def _show_image_preview(self, path: str):
        dlg = wx.Dialog(self, title="Generated Image", size=(700, 700),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        pnl = wx.Panel(dlg)
        pnl.SetBackgroundColour(wx.Colour(30, 30, 30))
        v = wx.BoxSizer(wx.VERTICAL)
        bmp = wx.Image(path, wx.BITMAP_TYPE_ANY).Scale(660, 620, wx.IMAGE_QUALITY_HIGH)
        v.Add(wx.StaticBitmap(pnl, bitmap=wx.Bitmap(bmp)), 1, wx.ALL | wx.EXPAND, 10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        save = wx.Button(pnl, label="Save As…")
        close = wx.Button(pnl, label="Close")
        btns.Add(save, 0, wx.ALL, 6)
        btns.Add(close, 0, wx.ALL, 6)
        v.Add(btns, 0, wx.ALIGN_CENTER)

        def on_save(_):
            s = wx.FileDialog(dlg, "Save Image", wildcard="PNG|*.png", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
            if s.ShowModal() == wx.ID_OK:
                try:
                    with open(path, "rb") as fsrc, open(s.GetPath(), "wb") as fdst:
                        fdst.write(fsrc.read())
                    wx.MessageBox("Saved.", "Image", wx.OK | wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"Failed to save: {e}", "Error", wx.OK | wx.ICON_ERROR)
            s.Destroy()

        save.Bind(wx.EVT_BUTTON, on_save)
        close.Bind(wx.EVT_BUTTON, lambda e: dlg.Destroy())
        pnl.SetSizer(v)
        dlg.ShowModal()

    # ---------- TTS (same multi-engine with inline status)
    def _clear_edge_azure_env(self):
        for k in ("SPEECH_KEY", "SPEECH_REGION", "AZURE_TTS_KEY", "AZURE_TTS_REGION", "EDGE_TTS_KEY", "EDGE_TTS_REGION"):
            try:
                os.environ.pop(k, None)
            except Exception:
                pass

    def speak(self, text: str):
        self._stop_playback()

        def worker():
            engine_name = "idle"
            ok = False

            key = (defaults.get("azure_tts_key") or os.environ.get("SPEECH_KEY") or "").strip()
            region = (defaults.get("azure_tts_region") or os.environ.get("SPEECH_REGION") or "").strip()
            if edge_tts and key and region and not ok:
                import asyncio

                async def _azure():
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    tmp.close()
                    voice = self.voice.GetStringSelection() or "en-US-GuyNeural"
                    communicate = edge_tts.Communicate(text, voice, key=key, region=region)
                    await communicate.save(tmp.name)
                    return tmp.name

                try:
                    try:
                        self._tts_file = asyncio.run(_azure())
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(_azure())
                        loop.close()
                    ok = True
                    engine_name = "Azure"
                except Exception:
                    ok = False

            if edge_tts and not ok:
                import asyncio

                async def _edge_public():
                    self._clear_edge_azure_env()
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    tmp.close()
                    voice = self.voice.GetStringSelection() or "en-US-GuyNeural"
                    communicate = edge_tts.Communicate(text, voice)
                    await communicate.save(tmp.name)
                    return tmp.name

                try:
                    try:
                        self._tts_file = asyncio.run(_edge_public())
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(_edge_public())
                        loop.close()
                    ok = True
                    engine_name = "Edge"
                except Exception:
                    ok = False

            if gTTS and not ok:
                try:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    tmp.close()
                    voice_val = self.voice.GetStringSelection() or "en-US-GuyNeural"
                    lang = voice_val.split("-", 1)[0].lower() if "-" in voice_val else "en"
                    gTTS(text=text, lang=lang).save(tmp.name)
                    self._tts_file = tmp.name
                    ok = True
                    engine_name = "gTTS"
                except Exception:
                    ok = False

            if pyttsx3 and not ok:
                try:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                    tmp.close()
                    engine = pyttsx3.init()
                    engine.save_to_file(text, tmp.name)
                    engine.runAndWait()
                    self._tts_file = tmp.name
                    ok = True
                    engine_name = "Offline"
                except Exception:
                    ok = False

            wx.CallAfter(self._set_tts_status, engine_name if ok else "error")
            if ok and self._tts_file:
                try:
                    if not pygame:
                        return
                    if not pygame.mixer.get_init():
                        pygame.mixer.init()
                    pygame.mixer.music.load(self._tts_file)
                    pygame.mixer.music.play()
                except Exception:
                    pass

        self._tts_thread = threading.Thread(target=worker, daemon=True)
        self._tts_thread.start()

    def _stop_playback(self):
        try:
            if pygame and pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        if self._tts_file and os.path.exists(self._tts_file):
            try:
                os.remove(self._tts_file)
            except Exception:
                pass
        self._tts_file = None

    # ---------- STT
    def on_mic_toggle(self, _):
        if not sr:
            wx.MessageBox("Speech-to-text requires 'SpeechRecognition'.\nInstall with: pip install SpeechRecognition",
                          "STT Not Available", wx.OK | wx.ICON_WARNING)
            return

        if not self._listening:
            try:
                recognizer = sr.Recognizer()
                mic = sr.Microphone()
                with mic as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)

                def callback(rec, audio):
                    try:
                        text = rec.recognize_google(audio)
                    except Exception:
                        text = ""
                    if text:
                        wx.CallAfter(self.prompt.SetValue, text)

                self._stop_listening = recognizer.listen_in_background(mic, callback, phrase_time_limit=12)
                self._listening = True
                self.mic_btn.SetLabel("Stop Mic")
            except Exception as e:
                wx.MessageBox(f"Microphone error: {e}", "STT Error", wx.OK | wx.ICON_ERROR)
        else:
            self._stop_stt()

    def _stop_stt(self):
        if self._stop_listening:
            try:
                self._stop_listening(wait_for_stop=False)
            except Exception:
                pass
        self._stop_listening = None
        self._listening = False
        self.mic_btn.SetLabel("🎙 Speak")

    def on_stop_voice(self, _):
        self._stop_playback()
        self._stop_stt()
        try:
            wx.Bell()
        except Exception:
            pass
        self.prompt.SetFocus()


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic Data Dialog
# ──────────────────────────────────────────────────────────────────────────────
class SyntheticDataDialog(wx.Dialog):
    def __init__(self, parent, fields):
        super().__init__(parent, title="Generate Synthetic Data", size=(520, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        BG = wx.Colour(38, 38, 38)
        PANEL = wx.Colour(38, 38, 38)
        TXT = wx.Colour(235, 235, 235)
        INPUT_BG = wx.Colour(50, 50, 50)
        INPUT_TXT = wx.Colour(240, 240, 240)
        ACCENT = wx.Colour(70, 130, 180)

        self.SetBackgroundColour(BG)

        top = wx.BoxSizer(wx.VERTICAL)
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(PANEL)
        top.Add(pnl, 1, wx.EXPAND)
        s = wx.BoxSizer(wx.VERTICAL)
        pnl.SetSizer(s)

        box1 = wx.StaticBox(pnl, label="How many records?")
        box1.SetForegroundColour(TXT)
        s1 = wx.StaticBoxSizer(box1, wx.HORIZONTAL)
        self.count = wx.SpinCtrl(pnl, min=1, max=1_000_000, initial=100)
        self.count.SetBackgroundColour(INPUT_BG)
        self.count.SetForegroundColour(INPUT_TXT)
        self.count.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        s1.Add(self.count, 1, wx.ALL | wx.EXPAND, 6)
        s.Add(s1, 0, wx.EXPAND | wx.ALL, 8)

        box2 = wx.StaticBox(pnl, label="Choose fields to include")
        box2.SetForegroundColour(TXT)
        s2 = wx.StaticBoxSizer(box2, wx.VERTICAL)
        self.chk = wx.CheckListBox(pnl, choices=list(fields))
        self.chk.SetBackgroundColour(INPUT_BG)
        self.chk.SetForegroundColour(INPUT_TXT)
        self.chk.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        for i in range(len(fields)):
            self.chk.Check(i, True)
        s2.Add(self.chk, 1, wx.ALL | wx.EXPAND, 6)

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

        btns = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(pnl, wx.ID_OK)
        cancel_btn = wx.Button(pnl, wx.ID_CANCEL)
        for b in (ok_btn, cancel_btn):
            b.SetBackgroundColour(ACCENT)
            b.SetForegroundColour(wx.WHITE)
            b.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        btns.AddButton(ok_btn)
        btns.AddButton(cancel_btn)
        btns.Realize()
        s.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizerAndFit(top)

    def get_values(self):
        n = int(self.count.GetValue())
        selected = [self.chk.GetString(i) for i in range(self.chk.GetCount()) if self.chk.IsChecked(i)]
        return n, selected
