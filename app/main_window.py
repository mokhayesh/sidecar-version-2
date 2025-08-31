import os
import io
import csv
import re
import random
from datetime import datetime, timedelta

import wx
import wx.grid as gridlib
import pandas as pd

from app.settings import SettingsWindow, save_defaults, defaults
from app.dialogs import QualityRuleDialog, DataBuddyDialog, SyntheticDataDialog
from app.analysis import (
    detect_and_split_data,
    profile_analysis,
    quality_analysis,
    catalog_analysis,
    compliance_analysis
)
from app.s3_utils import download_text_from_uri, upload_to_s3


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for synthetic data generation (no external deps)
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
    """Infer a simple semantic type from a column name."""
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
    # crude numeric heuristic
    if any(tok in name for tok in ("number","count","qty","age","zip","score")):
        return "number"
    return "text"

def synth_value(kind: str, i: int) -> str:
    """Create a realistic-ish value by type."""
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
        # 50% single initial; 50% name
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
        # amounts in the 1000 - 100k range with cents
        return f"{random.uniform(1000, 100000):.2f}"
    if kind == "date":
        base = datetime.now() - timedelta(days=random.randint(0, 4*365))
        return base.strftime("%Y-%m-%d")
    if kind == "id":
        return f"{random.randint(10_000_000, 99_999_999)}"
    if kind == "number":
        return str(random.randint(0, 1000))
    # default text
    return f"{_slugify(kind) or 'value'}_{i}"

def synth_dataframe(n: int, columns: list[str]) -> pd.DataFrame:
    """Generate n rows for the provided column list, using inferred types."""
    df = pd.DataFrame(index=range(n))
    for col in columns:
        kind = infer_field_type(col)
        df[col] = [synth_value(kind, i+1) for i in range(n)]
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────

class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sidecar Data Quality", size=(1200, 820))

        # App icon (top-left)
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

    # ───────── UI
    def _build_ui(self):
        pnl = wx.Panel(self)
        pnl.SetBackgroundColour(wx.Colour(40, 40, 40))
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Title
        title = wx.StaticText(pnl, label="🏍️🛺  Sidecar Data Quality")
        title.SetFont(wx.Font(15, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(wx.Colour(240, 240, 240))
        vbox.Add(title, 0, wx.ALIGN_CENTER | wx.ALL, 8)

        # Menu
        mb = wx.MenuBar()
        m_file, m_set = wx.Menu(), wx.Menu()
        m_file.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), id=wx.ID_EXIT)
        m_set.Append(wx.ID_PREFERENCES, "Settings")
        self.Bind(wx.EVT_MENU, self.on_settings, id=wx.ID_PREFERENCES)
        mb.Append(m_file, "&File"); mb.Append(m_set, "&Settings"); self.SetMenuBar(mb)

        # Toolbar row
        buttons = [
            ("Load Knowledge Files", self.on_load_knowledge),
            ("Load File", self.on_load_file),
            ("Load from URI/S3", self.on_load_s3),
            ("Generate Synthetic Data", self.on_generate_synth),
            ("Quality Rule Assignment", self.on_rules),
            ("Profile", self.do_analysis, "Profile"),
            ("Quality", self.do_analysis, "Quality"),
            ("Detect Anomalies", self.on_detect_anomalies),
            ("Catalog", self.do_analysis, "Catalog"),
            ("Compliance", self.do_analysis, "Compliance"),
            ("Little Buddy", self.on_buddy),
            ("Export CSV", self.on_export_csv),
            ("Export TXT", self.on_export_txt),
            ("Upload to S3", self.on_upload_s3),
        ]
        toolbar = wx.WrapSizer(wx.HORIZONTAL)
        for label, fn, *rest in buttons:
            btn = wx.Button(pnl, label=label)
            btn.SetBackgroundColour(wx.Colour(70, 130, 180))
            btn.SetForegroundColour(wx.WHITE)
            btn.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, fn)
            if rest:
                btn.process = rest[0]
            toolbar.Add(btn, 0, wx.ALL, 3)
        vbox.Add(toolbar, 0, wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Knowledge file list
        self.knowledge_lbl = wx.StaticText(pnl, label="Knowledge Files: (none)")
        self.knowledge_lbl.SetForegroundColour(wx.Colour(200, 200, 200))
        vbox.Add(self.knowledge_lbl, 0, wx.LEFT | wx.BOTTOM, 6)

        # Grid
        self.grid = gridlib.Grid(pnl)
        self.grid.CreateGrid(0, 0)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_resize)
        # dark theme grid
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(55, 55, 55))
        self.grid.SetDefaultCellTextColour(wx.Colour(230, 230, 230))
        self.grid.SetLabelBackgroundColour(wx.Colour(80, 80, 80))
        self.grid.SetLabelTextColour(wx.Colour(245, 245, 245))
        self.grid.SetLabelFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE.NORMAL, wx.FONTWEIGHT.BOLD))
        vbox.Add(self.grid, 1, wx.EXPAND | wx.ALL, 6)

        pnl.SetSizer(vbox)

    # ───────── Grid helpers
    def _display(self, hdr, data):
        # clear
        self.grid.ClearGrid()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        # setup
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

    def on_load_knowledge(self, _):
        dlg = wx.FileDialog(self, "Select Knowledge Files",
                            wildcard="All Supported|*.txt;*.json;*.csv;*.png;*.jpg;*.jpeg;*.gif|"
                                     "Text|*.txt|JSON|*.json|CSV|*.csv|Images|*.png;*.jpg;*.jpeg;*.gif",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dlg.ShowModal() != wx.ID_OK:
            return
        paths = dlg.GetPaths()
        dlg.Destroy()

        for p in paths:
            name = os.path.basename(p)
            try:
                if os.path.splitext(name)[1].lower() in (".png",".jpg",".jpeg",".gif",".bmp",".tif",".tiff"):
                    # store as path only (binary)
                    self.knowledge_files.append({"name": name, "path": p})
                else:
                    content = open(p, "r", encoding="utf-8", errors="ignore").read()
                    self.knowledge_files.append({"name": name, "content": content})
            except Exception:
                self.knowledge_files.append({"name": name, "path": p})

        self._refresh_knowledge_label()

    def _refresh_knowledge_label(self):
        if not self.knowledge_files:
            self.knowledge_lbl.SetLabel("Knowledge Files: (none)")
            return
        names = "  ·  ".join([k["name"] for k in self.knowledge_files])
        self.knowledge_lbl.SetLabel(f"Knowledge Files:  {names}")

    def do_analysis(self, evt):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        proc = evt.GetEventObject().process
        self.current_process = proc
        df = pd.DataFrame(self.raw_data, columns=self.headers)
        func = {
            "Profile": profile_analysis,
            "Quality": lambda d: quality_analysis(d, self.quality_rules),
            "Catalog": catalog_analysis,
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
            selected = list(self.headers)  # default to all

        try:
            df = synth_dataframe(n, selected)
            self.headers = selected
            self.raw_data = df.astype(str).values.tolist()
            self._display(self.headers, self.raw_data)
            wx.MessageBox(f"Generated {n:,} synthetic rows for {len(selected)} field(s).",
                          "Synthetic Data", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Generation failed: {e}", "Error", wx.OK | wx.ICON_ERROR)

    # ───────── Simple anomaly detector (placeholder)
    def on_detect_anomalies(self, _):
        if not self.headers:
            wx.MessageBox("Load data first.", "No data", wx.OK | wx.ICON_WARNING)
            return
        df = pd.DataFrame(self.raw_data, columns=self.headers)

        findings = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for col in df.columns:
            s = df[col].astype(str).str.strip()
            blanks = int((s == "").sum())
            nulls = int((s.str.lower() == "nan").sum())
            # simple numeric anomaly: negative or huge values
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().any():
                neg = int((numeric < 0).sum())
                huge = int((numeric > numeric.mean(skipna=True) + 6*(numeric.std(skipna=True) or 0)).sum())
            else:
                neg = huge = 0

            # email format issues
            bad_email = 0
            if "email" in col.lower():
                bad_email = int(~s.str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", regex=True, na=True).sum())

            if blanks or nulls or neg or huge or bad_email:
                reason = []
                if blanks: reason.append(f"{blanks} blank")
                if nulls: reason.append(f"{nulls} 'nan'")
                if neg: reason.append(f"{neg} negative")
                if huge: reason.append(f"{huge} outlier")
                if bad_email: reason.append(f"{bad_email} invalid email")
                rec = "Review source, add validation, and backfill where possible."
                findings.append([col, " | ".join(reason), rec, now])

        if not findings:
            findings = [["(none)", "No obvious anomalies found", "No action", now]]

        hdr = ["Field", "Reason", "Recommendation", "Detected At"]
        self._display(hdr, findings)

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
