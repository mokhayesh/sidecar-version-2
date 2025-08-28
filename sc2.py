
import wx

import wx.grid as gridlib

import wx.richtext as rt

import pandas as pd

import re, csv, io, os, json, threading, requests, boto3, urllib3

from datetime import datetime

from botocore import UNSIGNED

from botocore.config import Config

import speech_recognition as sr          # reserved for future voice UI

import edge_tts                          # reserved for future voice UI

import pygame                            # reserved for future audio playback

 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

 

# ─────────────────────────────────────────────────────────────────────────

#  Defaults & persistence

# ─────────────────────────────────────────────────────────────────────────

DEFAULTS_FILE = "defaults.json"

defaults = {

    "api_key": "",

    "filepath": os.path.expanduser("~"),

    "default_model": "gpt-4", "max_tokens": "800", "temperature": "0.6",

    "top_p": "1.0", "frequency_penalty": "0.0", "presence_penalty": "0.0",

    "url": "https://api.openai.com/v1/chat/completions",


    "image_generation_url": "https://api.openai.com/v1/images/generations",

    # AWS & S3

    "aws_access_key_id": "", "aws_secret_access_key": "", "aws_session_token": "",

    "aws_s3_region": "us-east-1",

    "aws_profile_bucket": "", "aws_quality_bucket": "",

    "aws_catalog_bucket": "", "aws_compliance_bucket": "",

    # mail

    "smtp_server": "", "smtp_port": "", "email_username": "",

    "email_password": "", "from_email": "", "to_email": ""

}

if os.path.exists(DEFAULTS_FILE):

    defaults.update(json.load(open(DEFAULTS_FILE)))

 

def save_defaults() -> None:

    json.dump(defaults, open(DEFAULTS_FILE, "w"), indent=2)

    wx.MessageBox("Settings saved.", "Settings", wx.OK | wx.ICON_INFORMATION)

 

# ─────────────────────────────────────────────────────────────────────────

#  Settings window

# ─────────────────────────────────────────────────────────────────────────

class SettingsWindow(wx.Frame):

    def __init__(self, parent):

        super().__init__(parent, title="Settings", size=(520, 670))

        panel, sizer = wx.Panel(self), wx.GridBagSizer(5, 5)

        fields = [

            ("API Key", "api_key"), ("Model", "default_model"),

            ("Max Tokens", "max_tokens"), ("Temperature", "temperature"),

            ("Top P", "top_p"), ("Frequency Penalty", "frequency_penalty"),

            ("Presence Penalty", "presence_penalty"),

            ("Chat URL", "url"), ("Image URL", "image_generation_url"),

            ("AWS Access Key", "aws_access_key_id"), ("AWS Secret Key", "aws_secret_access_key"),

            ("AWS Session Token", "aws_session_token"), ("AWS Region", "aws_s3_region"),

            ("Profile Bucket", "aws_profile_bucket"), ("Quality Bucket", "aws_quality_bucket"),

            ("Catalog Bucket", "aws_catalog_bucket"), ("Compliance Bucket", "aws_compliance_bucket"),

            ("SMTP Server", "smtp_server"), ("SMTP Port", "smtp_port"),

            ("Email Username", "email_username"), ("Email Password", "email_password"),

            ("From Email", "from_email"), ("To Email", "to_email"),

        ]

        row = 0

        for label, key in fields:

            sizer.Add(wx.StaticText(panel, label=label + ":"), (row, 0),

                      flag=wx.ALIGN_RIGHT | wx.TOP, border=5)

            style = wx.TE_PASSWORD if "password" in key or "secret" in key else 0

            ctrl = wx.TextCtrl(panel, value=str(defaults.get(key, "")), size=(320, -1), style=style)

            setattr(self, f"{key}_ctrl", ctrl)

            sizer.Add(ctrl, (row, 1), flag=wx.EXPAND | wx.TOP, border=5)

            row += 1

        save_btn = wx.Button(panel, label="Save")

        save_btn.Bind(wx.EVT_BUTTON, self.on_save)

        sizer.Add(save_btn, (row, 0), span=(1, 2),

                  flag=wx.ALIGN_CENTER | wx.TOP, border=10)

        panel.SetSizerAndFit(sizer)

 

    def on_save(self, _):

        for attr in dir(self):

            if attr.endswith("_ctrl"):

                key = attr[:-5]

                defaults[key] = getattr(self, attr).GetValue()

        save_defaults()

        self.Close()

 

# ─────────────────────────────────────────────────────────────────────────

#  Helpers

# ─────────────────────────────────────────────────────────────────────────

def detect_and_split_data(text: str):

    lines = text.strip().splitlines()

    if not lines:

        return [], []

    delim = "," if "," in lines[0] else "|"

    rows = list(csv.reader(lines, delimiter=delim))

    return (rows[0], rows[1:]) if len(rows) > 1 else ([], [])

 

_SPLIT_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')

def _split_words(col: str) -> str:

    return _SPLIT_CAMEL.sub(" ", col.replace("_", " "))

 

# ─────────────────────────────────────────────────────────────────────────

#  Analyses – Profile

# ─────────────────────────────────────────────────────────────────────────

def profile_analysis(df: pd.DataFrame):

    now, total = datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(df)

    rows = []

    for col in df.columns:

        s = df[col]

        nulls = int(s.isnull().sum())

        blanks = int((s.astype(str).str.strip() == "").sum())

        uniq = int(s.nunique(dropna=True))

        comp = round(100 * (total - nulls - blanks) / total, 2) if total else 0

        if pd.api.types.is_numeric_dtype(s):

            vals = pd.to_numeric(s, errors="coerce").dropna()

            stats = (vals.min(), vals.max(), vals.median(), vals.std()) if not vals.empty else ("N/A",) * 4

        else:

            lengths = s.dropna().astype(str).str.strip().replace("", pd.NA).dropna().str.len()

            stats = (

                lengths.min() if not lengths.empty else "N/A",

                lengths.max() if not lengths.empty else "N/A",

                lengths.median() if not lengths.empty else "N/A",

                "N/A"

            )

        rows.append([col, total, uniq, comp, nulls, blanks, *stats, now])

    hdr = ["Field", "Total", "Unique", "Completeness (%)",

           "Nulls", "Blanks", "Min", "Max", "Median", "Std", "Analysis Date"]

    return hdr, rows

 

# ─────────────────────────────────────────────────────────────────────────

#  Analyses – Quality

# ─────────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

_DATE_PARSE = lambda x: pd.to_datetime(x, errors="coerce")

 

def _default_valid_count(s: pd.Series) -> int:

    if pd.api.types.is_numeric_dtype(s):

        return pd.to_numeric(s, errors="coerce").notna().sum()

    if "date" in s.name.lower() or pd.api.types.is_datetime64_any_dtype(s):

        return _DATE_PARSE(s).notna().sum()

    if "email" in s.name.lower():

        return s.astype(str).str.match(_EMAIL_RE).sum()

    return s.astype(str).str.strip().ne("").sum()

 

def quality_analysis(df: pd.DataFrame, rules: dict[str, re.Pattern] | None = None):

    now, total = datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(df)

    rows = []

    for col in df.columns:

        s = df[col]

        nulls = int(s.isnull().sum())

        blanks = int((s.astype(str).str.strip() == "").sum())

        comp_pct = round(100 * (total - nulls - blanks) / total, 2) if total else 0

        uniq_pct = round(100 * s.nunique(dropna=True) / total, 2) if total else 0

        if rules and col in rules:

            valid_cnt = s.dropna().astype(str).str.match(rules[col]).sum()

        else:

            valid_cnt = _default_valid_count(s)

        valid_pct = round(100 * valid_cnt / total, 2) if total else 0

        score = round((comp_pct + valid_pct) / 2, 2)

        rows.append([col, total, comp_pct, uniq_pct, valid_pct, score, now])

    hdr = ["Field", "Total", "Completeness (%)", "Uniqueness (%)",

           "Validity (%)", "Quality Score (%)", "Analysis Date"]

    return hdr, rows

 

# ─────────────────────────────────────────────────────────────────────────

#  Analyses – Catalog

# ─────────────────────────────────────────────────────────────────────────

def _business_description(col: str) -> str:

    name = col.lower()

    clean = re.sub(r'[^a-z0-9_]', ' ', name)

    tokens = [t for t in re.split(r'[_\s]+', clean) if t]

    if not tokens:

        return "Field describing the record."

    noun = " ".join(tokens).replace(" id", "").strip()

    if tokens[-1] == "id":

        ent = " ".join(tokens[:-1]) or "record"

        return f"Unique identifier for each {ent}."

    if "email" in tokens:

        return f"Email address of the {noun}."

    if any(t in tokens for t in ("phone", "tel", "telephone")):

        return f"Telephone number associated with the {noun}."

    if "date" in tokens or "timestamp" in tokens:

        return f"Date or time related to the {noun}."

    if {"amount","total","price","cost","balance"} & set(tokens):

        return f"Monetary amount representing the {noun}."

    if {"qty","quantity","count","number"} & set(tokens):

        return f"Number of {noun}."

    if "status" in tokens:

        return f"Current status of the {noun}."

    if "flag" in tokens:

        return f"Indicator flag for the {noun}."

    if "type" in tokens or "category" in tokens:

        return f"Classification type of the {noun}."

    if "code" in tokens:

        return f"Standard code representing the {noun}."

    return f"{_split_words(col).title()} for each record."

 

def catalog_analysis(df: pd.DataFrame):

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []

    for col in df.columns:

        s = df[col]

        friendly = _split_words(col).title()

        descr = _business_description(col)

        dtype = ("Numeric" if pd.api.types.is_numeric_dtype(s)

                 else "Date" if "date" in descr else "Text")

        nullable = "Yes" if s.isnull().any() else "No"

        example = str(s.dropna().iloc[0]) if not s.dropna().empty else ""

        rows.append([col, friendly, descr, dtype, nullable, example, now])

    hdr = ["Field", "Friendly Name", "Description",

           "Data Type", "Nullable", "Example", "Analysis Date"]

    return hdr, rows

 

# ─────────────────────────────────────────────────────────────────────────

#  Analyses – Compliance

# ─────────────────────────────────────────────────────────────────────────

def compliance_analysis(_df: pd.DataFrame):

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = [

        ["Quality","MyApp","DataLake","Table","85%","80%","✔","Meets SLA",now],

        ["Completeness","MyApp","DataLake","Table","85%","80%","✔","Meets SLA",now],

        ["Validity","MyApp","DataLake","Table","85%","80%","✔","Meets SLA",now],

        ["GLBA","MyApp","DataLake","Table","85%","80%","✔","Meets SLA",now],

        ["CCPA","MyApp","DataLake","Table","70%","80%","✘","Below SLA",now],

    ]

    hdr = ["Aspect","Application","Layer","Table",

           "Score","SLA","Compliant","Notes","Analysis Date"]

    return hdr, rows

 

# ─────────────────────────────────────────────────────────────────────────

#  S3 helpers

# ─────────────────────────────────────────────────────────────────────────

def _make_s3_client(anonymous: bool = False):

    if anonymous:

        return boto3.client("s3", config=Config(signature_version=UNSIGNED))

    return boto3.Session(

        aws_access_key_id=defaults["aws_access_key_id"] or None,

        aws_secret_access_key=defaults["aws_secret_access_key"] or None,

        aws_session_token=defaults["aws_session_token"] or None,

        region_name=defaults["aws_s3_region"] or None,

    ).client("s3")

 

def download_text_from_uri(uri: str) -> str:

    if uri.startswith("s3://"):

        _, rest = uri.split("s3://", 1)

        bucket, key = rest.split("/", 1)

        for anonymous in (False, True):

            try:

                obj = _make_s3_client(anonymous).get_object(Bucket=bucket, Key=key)

                return obj["Body"].read().decode()

            except Exception:

                if anonymous:

                    region = defaults.get("aws_s3_region", "us-east-1")

                    url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

                    r = requests.get(url, verify=False, timeout=60); r.raise_for_status()

                    return r.text

                continue

    r = requests.get(uri, verify=False, timeout=60); r.raise_for_status()

    return r.text

 

def upload_to_s3(process: str, headers, data):

    bucket = defaults.get(f"aws_{process.lower()}_bucket", "").strip()

    if not bucket:

        return f"No bucket configured for {process}"

    buf = io.StringIO(); csv.writer(buf).writerows([headers, *data])

    key = f"{process}_{datetime.now():%Y%m%d_%H%M%S}.csv"

    try:

        _make_s3_client().put_object(Bucket=bucket, Key=key, Body=buf.getvalue())

        return f"Uploaded to s3://{bucket}/{key}"

    except Exception as e:

        return f"S3 upload failed: {e}"

 

# ─────────────────────────────────────────────────────────────────────────

#  Quality Rule Assignment dialog

# ─────────────────────────────────────────────────────────────────────────

class QualityRuleDialog(wx.Dialog):

    def __init__(self, parent, fields, current_rules):

        super().__init__(parent, title="Quality Rule Assignment",

                         size=(740, 560),

                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.fields, self.current_rules = fields, current_rules

        self.loaded_rules = {}

        pnl, main = wx.Panel(self), wx.BoxSizer(wx.VERTICAL)

 

        fbox = wx.StaticBox(pnl, label="Fields")

        fsz = wx.StaticBoxSizer(fbox, wx.HORIZONTAL)

        self.field_list = wx.ListBox(pnl, choices=list(fields), style=wx.LB_EXTENDED)

        fsz.Add(self.field_list, 1, wx.EXPAND | wx.ALL, 5)

        main.Add(fsz, 1, wx.EXPAND | wx.ALL, 5)

 

        g = wx.FlexGridSizer(2, 2, 5, 5); g.AddGrowableCol(1, 1)

        g.Add(wx.StaticText(pnl, label="Select loaded rule:"), 0, wx.ALIGN_CENTER_VERTICAL)

        self.rule_choice = wx.ComboBox(pnl, style=wx.CB_READONLY)

        self.rule_choice.Bind(wx.EVT_COMBOBOX, self.on_pick_rule)

        g.Add(self.rule_choice, 0, wx.EXPAND)

        g.Add(wx.StaticText(pnl, label="Or enter regex pattern:"), 0, wx.ALIGN_CENTER_VERTICAL)

        self.pattern_txt = wx.TextCtrl(pnl)

        g.Add(self.pattern_txt, 0, wx.EXPAND)

        main.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

 

        pbox = wx.StaticBox(pnl, label="Loaded JSON preview")

        pv = wx.StaticBoxSizer(pbox, wx.VERTICAL)

        self.preview = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))

        pv.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)

        main.Add(pv, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

 

        abox = wx.StaticBox(pnl, label="Assignments")

        asz = wx.StaticBoxSizer(abox, wx.VERTICAL)

        self.assign_view = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)

        self.assign_view.InsertColumn(0, "Field", width=180)

        self.assign_view.InsertColumn(1, "Assigned Pattern", width=440)

        asz.Add(self.assign_view, 1, wx.EXPAND | wx.ALL, 4)

        main.Add(asz, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

 

        btns = wx.BoxSizer(wx.HORIZONTAL)

        load_btn = wx.Button(pnl, label="Load Rules JSON"); load_btn.Bind(wx.EVT_BUTTON, self.on_load_rules)

        assign_btn = wx.Button(pnl, label="Assign To Selected Field(s)"); assign_btn.Bind(wx.EVT_BUTTON, self.on_assign)

        close_btn = wx.Button(pnl, label="Save / Close"); close_btn.Bind(wx.EVT_BUTTON,

                                                                         lambda _: self.EndModal(wx.ID_OK))

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

            dlg.Destroy(); return

        path = dlg.GetPath(); dlg.Destroy()

        try:

            data = json.load(open(path, "r", encoding="utf-8"))

            self.loaded_rules = {k: (v if isinstance(v, str) else v.get("pattern", "")) for k, v in data.items()}

            self.rule_choice.Clear(); self.rule_choice.Append(list(self.loaded_rules))

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

 

# ─────────────────────────────────────────────────────────────────────────

#  Little Buddy chat dialog

# ─────────────────────────────────────────────────────────────────────────

class DataBuddyDialog(wx.Dialog):

    def __init__(self, parent, data=None, headers=None):

        super().__init__(parent, title="Little Buddy", size=(800, 600),

                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.data, self.headers = data, headers

        pnl = wx.Panel(self); pnl.SetBackgroundColour(wx.Colour(30, 30, 30))

        vbox = wx.BoxSizer(wx.VERTICAL)

 

        pygame.mixer.init()

        voice = wx.Choice(pnl, choices=["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"])

        voice.SetSelection(1); vbox.Add(voice, 0, wx.EXPAND | wx.ALL, 5)

 

        self.persona = wx.ComboBox(pnl, choices=[

            "Data Architect", "Data Engineer", "Data Quality Expert", "Data Scientist", "Yoda"],

            style=wx.CB_READONLY)

        self.persona.SetSelection(0); vbox.Add(self.persona, 0, wx.EXPAND | wx.ALL, 5)

 

        h = wx.BoxSizer(wx.HORIZONTAL)

        h.Add(wx.StaticText(pnl, label="Ask:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        self.prompt = wx.TextCtrl(pnl, style=wx.TE_PROCESS_ENTER)

        self.prompt.Bind(wx.EVT_TEXT_ENTER, self.on_ask)

        h.Add(self.prompt, 1, wx.EXPAND | wx.RIGHT, 5)

        send_btn = wx.Button(pnl, label="Send"); send_btn.Bind(wx.EVT_BUTTON, self.on_ask)

        h.Add(send_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        vbox.Add(h, 0, wx.EXPAND | wx.ALL, 5)

 

        self.reply = rt.RichTextCtrl(pnl, style=wx.TE_MULTILINE | wx.TE_READONLY)

        self.reply.SetBackgroundColour(wx.Colour(50, 50, 50))

        self.reply.SetForegroundColour(wx.Colour(255, 255, 255))

        vbox.Add(self.reply, 1, wx.EXPAND | wx.ALL, 5)

 

        pnl.SetSizer(vbox)

        self.reply.WriteText("Hi, I'm Little Buddy!")

 

    def on_ask(self, _):

        q = self.prompt.GetValue().strip(); self.prompt.SetValue("")

        if not q: return

        self.reply.Clear(); self.reply.WriteText("Thinking...")

        threading.Thread(target=self._answer, args=(q,), daemon=True).start()

 

    def _answer(self, q: str):

        persona = self.persona.GetValue()

        prompt = f"As a {persona}, {q}" if persona else q

        if self.data:

            prompt += "\nData sample:\n" + "; ".join(map(str, self.data[0]))

        try:

            resp = requests.post(

                defaults["url"],

                headers={"Authorization": f"Bearer {defaults['api_key']}",

                         "Content-Type": "application/json"},

                json={

                    "model": defaults["default_model"],

                    "messages": [{"role": "user", "content": prompt}],

                    "max_tokens": int(defaults["max_tokens"]),

                    "temperature": float(defaults["temperature"]),

                },

                timeout=60, verify=False

            )

            resp.raise_for_status()

            answer = resp.json()["choices"][0]["message"]["content"]

        except Exception as e:

            answer = f"Error: {e}"

        wx.CallAfter(self.reply.Clear)

        wx.CallAfter(self.reply.WriteText, answer)

 

# ─────────────────────────────────────────────────────────────────────────

#  Main application window with auto‑resizing grid

# ─────────────────────────────────────────────────────────────────────────

class MainWindow(wx.Frame):

    def __init__(self):

        super().__init__(None, title="Sidecar Data Quality", size=(1120, 780))

        self.raw_data = []; self.headers = []

        self.current_process = ""; self.quality_rules = {}

        self._build_ui(); self.Centre(); self.Show()

 

    def _build_ui(self):

        pnl = wx.Panel(self); vbox = wx.BoxSizer(wx.VERTICAL)

 

        title = wx.StaticText(pnl, label="🚀  Sidecar Data Quality")

        title.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        title.SetForegroundColour(wx.RED)

        vbox.Add(title, 0, wx.ALIGN_CENTER | wx.ALL, 5)

 

        # menu bar

        mb = wx.MenuBar(); m_file, m_set = wx.Menu(), wx.Menu()

        m_file.Append(wx.ID_EXIT, "Exit")

        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)

        m_set.Append(wx.ID_PREFERENCES, "Settings")

        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)

        mb.Append(m_file, "&File"); mb.Append(m_set, "&Settings"); self.SetMenuBar(mb)

 

        # toolbar

        buttons = [

            ("Load File", self.on_load_file),

            ("Load from URI/S3", self.on_load_s3),

            ("Quality Rule Assignment", self.on_rules),

            ("Profile", self.do_analysis, "Profile"),

            ("Quality", self.do_analysis, "Quality"),

            ("Catalog", self.do_analysis, "Catalog"),

            ("Compliance", self.do_analysis, "Compliance"),

            ("Little Buddy", self.on_buddy),

            ("Export CSV", self.on_export_csv),

            ("Export TXT", self.on_export_txt),

            ("Upload to S3", self.on_upload_s3),

        ]

        toolbar = wx.WrapSizer(wx.HORIZONTAL)

        for label, fn, *rest in buttons:

            btn = wx.Button(pnl, label=label); btn.Bind(wx.EVT_BUTTON, fn)

            if rest: btn.process = rest[0]

            toolbar.Add(btn, 0, wx.ALL, 4)

        vbox.Add(toolbar, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 4)

 

        # data grid

        self.grid = gridlib.Grid(pnl)

        self.grid.CreateGrid(0, 0)

        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)

        vbox.Add(self.grid, 1, wx.EXPAND | wx.ALL, 5)

 

        pnl.SetSizer(vbox)

 

    def _display(self, hdr, data):

        # clear

        self.grid.ClearGrid()

        if self.grid.GetNumberRows(): self.grid.DeleteRows(0, self.grid.GetNumberRows())

        if self.grid.GetNumberCols(): self.grid.DeleteCols(0, self.grid.GetNumberCols())

        # setup new

        self.grid.AppendCols(len(hdr))

        for i, h in enumerate(hdr): self.grid.SetColLabelValue(i, h)

        self.grid.AppendRows(len(data))

        for r, row in enumerate(data):

            for c, val in enumerate(row):

                self.grid.SetCellValue(r, c, str(val))

        # stretch to fit

        self.adjust_grid()

 

    def adjust_grid(self):

        cols = self.grid.GetNumberCols()

        if cols == 0: return

        total_w = self.grid.GetClientSize().GetWidth()

        usable = max(0, total_w - self.grid.GetRowLabelSize())

        w = max(60, usable // cols)

        for c in range(cols):

            self.grid.SetColSize(c, w)

 

    def on_grid_resize(self, event):

        event.Skip()

        wx.CallAfter(self.adjust_grid)

 

    # menu / toolbar handlers

    def on_settings(self, _): SettingsWindow(self).Show()

    def on_load_file(self, _):

        dlg = wx.FileDialog(self, "Open CSV/TXT", wildcard="CSV/TXT|*.csv;*.txt",

                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)

        if dlg.ShowModal() != wx.ID_OK: return

        text = open(dlg.GetPath(), "r", encoding="utf-8").read(); dlg.Destroy()

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

 

    def do_analysis(self, evt):

        if not self.headers:

            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING); return

        proc = evt.GetEventObject().process; self.current_process = proc

        df = pd.DataFrame(self.raw_data, columns=self.headers)

        func = {

            "Profile": profile_analysis,

            "Quality": lambda d: quality_analysis(d, self.quality_rules),

            "Catalog": catalog_analysis,

            "Compliance": compliance_analysis

        }[proc]

        hdr, data = func(df); self._display(hdr, data)

        wx.MessageBox(upload_to_s3(proc, hdr, data), "Analysis", wx.OK | wx.ICON_INFORMATION)

 

    def on_rules(self, _):

        if not self.headers:

            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING); return

        QualityRuleDialog(self, self.headers, self.quality_rules).ShowModal()

 

    def on_buddy(self, _):

        DataBuddyDialog(self, self.raw_data, self.headers).ShowModal()

 

    def _export(self, path, sep):

        hdr = [self.grid.GetColLabelValue(i) for i in range(self.grid.GetNumberCols())]

        data = [[self.grid.GetCellValue(r, c) for c in range(len(hdr))]

                for r in range(self.grid.GetNumberRows())]

        pd.DataFrame(data, columns=hdr).to_csv(path, index=False, sep=sep)

 

    def on_export_csv(self, _):

        dlg = wx.FileDialog(self, "Save CSV", wildcard="CSV|*.csv",

                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)

        if dlg.ShowModal() != wx.ID_OK: return

        self._export(dlg.GetPath(), ","); dlg.Destroy()

        wx.MessageBox("CSV exported.", "Export", wx.OK | wx.ICON_INFORMATION)

 

    def on_export_txt(self, _):

        dlg = wx.FileDialog(self, "Save TXT", wildcard="TXT|*.txt",

                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)

        if dlg.ShowModal() != wx.ID_OK: return

        self._export(dlg.GetPath(), "\t"); dlg.Destroy()

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

 

 