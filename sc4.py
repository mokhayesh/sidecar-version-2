import wx

import wx.adv

import wx.lib.agw.aui as aui

import wx.grid as gridlib

import pandas as pd

import numpy as np

import json

import logging

import re

import random

import csv

import os

import string

import uuid

import boto3  # boto3 for AWS connectivity

from botocore.exceptions import ClientError  # For AWS error handling

from datetime import datetime

from faker import Faker

 

# Initialize Faker for synthetic data generation

fake = Faker()

 

# Configure logging

logging.basicConfig(

    filename='rdb.log',

    level=logging.DEBUG,

    format='%(asctime)s %(levelname)s: %(message)s'

)

 

# Configuration file path and defaults

CONFIG_FILE = 'config.json'

default_values = {

    "aws_access_key_id": "",

    "aws_secret_access_key": "",

    "aws_session_token": "",

    "aws_s3_bucket": "",

    "aws_s3_region": ""

}

 

# Field specification file

FIELDSPEC_FILE = "fieldspec.json"

 

# Load configuration if it exists

if os.path.exists(CONFIG_FILE):

    try:

        with open(CONFIG_FILE, 'r') as f:

            user_config = json.load(f)

            default_values.update(user_config)

            logging.info("Configuration loaded from config.json.")

    except Exception as e:

        logging.error(f"Failed to load config file: {e}")

 

def save_config():

    """Save updated configuration to file."""

    try:

        with open(CONFIG_FILE, 'w') as f:

            json.dump(default_values, f, indent=4)

        logging.info("Configuration saved successfully.")

    except Exception as e:

        logging.error(f"Failed to save config file: {e}")

 

def normalize_name(name):

    """Normalize a string by removing non-alphanumeric characters and lowercasing."""

    return re.sub(r'\W+', '', name).lower()

 

def detect_date_format(sample_value):

    """

    Attempt to guess a date format from the sample string.

    Returns a format string for use with strftime.

    """

    if not sample_value or not isinstance(sample_value, str):

        return "%Y-%m-%d"

    if ":" in sample_value:

        if "/" in sample_value:

            return "%m/%d/%Y %H:%M:%S"

        elif "-" in sample_value:

            return "%Y-%m-%d %H:%M:%S"

        else:

            return "%Y-%m-%d %H:%M:%S"

    else:

        if "/" in sample_value:

            return "%m/%d/%Y"

        elif "-" in sample_value:

            return "%Y-%m-%d"

        elif "." in sample_value:

            return "%d.%m.%Y"

        else:

            return "%Y-%m-%d"

 

def generate_synthetic_value(column_name, sample_value=None, field_type=None, constraints=None):

    """

    Generate a synthetic value based on the column name, sample value, field type, and constraints.

    Respects a user-provided list of example values if present to mirror original data distribution.

    """

    # If user overrode dtype

    if constraints and "dtype_override" in constraints and constraints["dtype_override"]:

        field_type = constraints["dtype_override"]

 

    # If user provided explicit example values list, sample from that

    if constraints and "values" in constraints and isinstance(constraints["values"], list) and constraints["values"]:

        return random.choice(constraints["values"])

 

    result = None

    norm = normalize_name(column_name)

 

    # Fallback default sample_value if missing

    if sample_value in (None, "", np.nan):

        if "phone" in norm:

            sample_value = "1-555-123-4567"

        elif "address" in norm:

            sample_value = "1234 Main St, Anytown, USA"

        elif "email" in norm:

            sample_value = user@example.com

        elif "first" in norm and "name" in norm:

            sample_value = "John"

        elif "last" in norm and "name" in norm:

            sample_value = "Doe"

        elif "date" in norm:

            sample_value = "2020-01-01"

        elif "time" in norm:

            sample_value = "00:00:00"

        elif "age" in norm or "int" in norm or "number" in norm or (field_type and str(field_type).lower() in ["integer", "float"]):

            sample_value = 30

        elif "gender" in norm:

            sample_value = "Male"

        elif "id" in norm or "hash" in norm:

            sample_value = "0123456789abcdef0123456789abcdef"

        elif "country" in norm:

            sample_value = "USA"

        else:

            sample_value = column_name

 

    # Generate based on cues

    if 'phone' in norm:

        area = random.randint(200, 999)

        exch = random.randint(200, 999)

        subs = random.randint(1000, 9999)

        result = f"1-{area:03d}-{exch:03d}-{subs:04d}"

    elif 'address' in norm:

        result = fake.address().replace('\n', ', ')

    elif 'email' in norm:

        result = fake.email()

    elif 'first' in norm and 'name' in norm:

        result = fake.first_name()

    elif 'last' in norm and 'name' in norm:

        result = fake.last_name()

    elif 'hash' in norm or 'id' in norm:

        if isinstance(sample_value, str) and re.fullmatch(r'[0-9a-fA-F]+', sample_value):

            length = len(sample_value)

            result = ''.join(random.choices('0123456789abcdef', k=length))

        elif isinstance(sample_value, (int, float)):

            try:

                si = int(sample_value)

                digits = len(str(abs(si))) if si != 0 else 1

                lo = 10**(digits-1) if digits>1 else 0

                hi = 10**digits - 1

                result = random.randint(lo, hi)

            except:

                result = ''.join(random.choices(string.hexdigits.lower(), k=32))

        else:

            result = ''.join(random.choices(string.hexdigits.lower(), k=32))

    elif 'postal' in norm or 'zip' in norm:

        if isinstance(sample_value, str) and re.fullmatch(r'\d{5}(-\d{4})?', sample_value):

            parts = sample_value.split('-')

            if len(parts) == 1:

                result = f"{random.randint(10000, 99999)}"

            else:

                result = f"{random.randint(10000, 99999)}-{random.randint(1000, 9999)}"

        else:

            result = fake.postcode()

    elif ('birth' in norm and 'date' in norm) or 'dob' in norm:

        dob = fake.date_of_birth(minimum_age=18, maximum_age=90)

        if isinstance(sample_value, str):

            fmt = detect_date_format(sample_value)

            result = dob.strftime(fmt)

        else:

            result = dob

    elif 'date' in norm or 'time' in norm:

        fmt = (constraints.get("format") or detect_date_format(sample_value)) if (constraints and sample_value) else "%Y-%m-%d"

        if constraints and constraints.get("start_date") and constraints.get("end_date"):

            try:

                sd = datetime.strptime(constraints["start_date"], fmt)

                ed = datetime.strptime(constraints["end_date"], fmt)

                dt = fake.date_time_between_dates(datetime_start=sd, datetime_end=ed)

                result = dt.strftime(fmt)

            except:

                result = fake.date_time_between(start_date='-10y', end_date='now').strftime(fmt)

        else:

            result = fake.date_time_between(start_date='-10y', end_date='now').strftime(fmt)

    elif field_type and str(field_type).lower().startswith(("int", "float")):

        if constraints and constraints.get("min") != "" and constraints.get("max") != "":

            try:

                lo = float(constraints["min"])

                hi = float(constraints["max"])

                if str(field_type).lower().startswith("int"):

                    result = random.randint(int(lo), int(hi))

                else:

                    val = random.uniform(lo, hi)

                    decimals = len(str(sample_value).split('.')[1]) if isinstance(sample_value, float) and '.' in str(sample_value) else 2

                    result = round(val, decimals)

            except:

                result = fake.random_number(digits=5)

        elif isinstance(sample_value, (int, float)):

            if isinstance(sample_value, int):

                digits = len(str(abs(sample_value))) if sample_value != 0 else 1

                lo = 10**(digits-1) if digits>1 else 0

                hi = 10**digits - 1

                result = random.randint(lo, hi)

            else:

                low = sample_value * 0.9

                high = sample_value * 1.1

                decimals = len(str(sample_value).split('.')[1]) if '.' in str(sample_value) else 2

                result = round(random.uniform(low, high), decimals)

        else:

            result = fake.random_number(digits=5)

    elif 'name' in norm:

        result = fake.name()

    elif 'company' in norm:

        result = fake.company()

    elif 'city' in norm:

        result = fake.city()

    elif 'state' in norm:

        result = fake.state()

    else:

        result = fake.word()

 

    # Apply any user-specified format

    if constraints and "format" in constraints:

        fmt = constraints["format"]

        try:

            if isinstance(result, (int, float)):

                result = format(result, fmt)

            elif isinstance(result, datetime):

                result = result.strftime(fmt)

            elif isinstance(result, str) and '{}' in fmt:

                result = fmt.format(result)

        except Exception as e:

            logging.error(f"Error applying format '{fmt}' to value {result}: {e}")

 

    # Cast to specified dtype_override

    if field_type:

        ft = str(field_type).lower()

        try:

            if ft in ("integer", "int"):

                result = int(result)

            elif ft == "float":

                result = float(result)

            elif ft in ("date", "datetime"):

                if isinstance(result, datetime):

                    result = result.strftime("%Y-%m-%d")

                else:

                    try:

                        dt = datetime.strptime(str(result), detect_date_format(result))

                        result = dt.strftime("%Y-%m-%d")

                    except:

                        pass

            elif ft in ("string", "email"):

                result = str(result)

        except Exception as e:

            logging.error(f"Failed to cast value {result} to {field_type}: {e}")

 

    return result

 

def generate_unique_synthetic_value(column_name, sample_value, field_type, constraints, unique_set, max_attempts=100):

    """

    Generate a synthetic value that is not already in unique_set.

    """

    attempts = 0

    value = generate_synthetic_value(column_name, sample_value, field_type, constraints)

    while value in unique_set and attempts < max_attempts:

        value = generate_synthetic_value(column_name, sample_value, field_type, constraints)

        attempts += 1

    unique_set.add(value)

    return value

 

# ---------------------------------------------------------------------

# Dialog for selecting columns

# ---------------------------------------------------------------------

class ColumnSelectionDialog(wx.Dialog):

    def __init__(self, parent, columns):

        super().__init__(parent, title="Select Columns for Synthetic Replacement", size=(400, 300))

        panel = wx.Panel(self)

        sizer = wx.BoxSizer(wx.VERTICAL)

 

        info = wx.StaticText(panel, label="Select the columns to replace with synthetic data:")

        sizer.Add(info, flag=wx.ALL, border=10)

 

        self.checklist = wx.CheckListBox(panel, choices=columns)

        sizer.Add(self.checklist, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

 

        btnSizer = wx.BoxSizer(wx.HORIZONTAL)

        okBtn = wx.Button(panel, wx.ID_OK, label="OK")

        cancelBtn = wx.Button(panel, wx.ID_CANCEL, label="Cancel")

        btnSizer.Add(okBtn, flag=wx.RIGHT, border=5)

        btnSizer.Add(cancelBtn, flag=wx.LEFT, border=5)

        sizer.Add(btnSizer, flag=wx.ALIGN_CENTER|wx.ALL, border=10)

 

        panel.SetSizer(sizer)

 

    def get_selected_columns(self):

        return [self.checklist.GetString(i) for i in self.checklist.GetCheckedItems()]

 

# ---------------------------------------------------------------------

# Dialog for field specifications

# ---------------------------------------------------------------------

class FieldSpecDialog(wx.Dialog):

    def __init__(self, parent, field_info):

        super().__init__(parent, title="Field Specifications", size=(850, 500))

        self.field_info = field_info

        panel = wx.Panel(self)

        mainSizer = wx.BoxSizer(wx.VERTICAL)

 

        instructions = wx.StaticText(panel, label="Specify data types, key settings, constraints, and example values:")

        mainSizer.Add(instructions, flag=wx.ALL, border=10)

 

        scrolled = wx.ScrolledWindow(panel, style=wx.VSCROLL)

        scrolled.SetScrollRate(0, 10)

        grid = wx.GridBagSizer(5, 5)

 

        headers = ["Field", "Data Type", "Primary Key", "Foreign Key", "Min/Start", "Max/End", "Example Values"]

        for idx, h in enumerate(headers):

            grid.Add(wx.StaticText(scrolled, label=h), pos=(0, idx), flag=wx.ALL, border=5)

 

        self.controls = {}

        data_types = ["Auto", "Integer", "Float", "String", "Email", "Date", "DateTime",

                      "Phone", "Address", "Name", "Company", "City", "State"]

 

        row = 1

        for col, info in field_info.items():

            self.controls[col] = {}

            grid.Add(wx.StaticText(scrolled, label=col),

                     pos=(row, 0), flag=wx.ALL|wx.ALIGN_CENTER_VERTICAL, border=5)

 

            # Data Type choice

            norm = normalize_name(col)

            dtype_current = info.get("dtype", "").lower()

            if "email" in norm:

                default = "Email"

            elif "int" in dtype_current:

                default = "Integer"

            elif "float" in dtype_current:

                default = "Float"

            elif "date" in norm or "time" in norm:

                default = "DateTime"

            elif "phone" in norm:

                default = "Phone"

            elif "address" in norm:

                default = "Address"

            elif "name" in norm:

                default = "Name"

            elif "company" in norm:

                default = "Company"

            elif "city" in norm:

                default = "City"

            elif "state" in norm:

                default = "State"

            else:

                default = "Auto"

 

            dtype_choice = wx.Choice(scrolled, choices=data_types)

            dtype_choice.SetStringSelection(default if default in data_types else "Auto")

            self.controls[col]["dtype"] = dtype_choice

            grid.Add(dtype_choice, pos=(row, 1), flag=wx.ALL|wx.EXPAND, border=5)

 

            # Primary Key

            pk = wx.CheckBox(scrolled)

            self.controls[col]["primary_key"] = pk

            grid.Add(pk, pos=(row, 2), flag=wx.ALL|wx.ALIGN_CENTER, border=5)

 

            # Foreign Key

            fk = wx.CheckBox(scrolled)

            self.controls[col]["foreign_key"] = fk

            grid.Add(fk, pos=(row, 3), flag=wx.ALL|wx.ALIGN_CENTER, border=5)

 

            # Min/Start and Max/End

            if default in ["Integer", "Float"]:

                min_ctrl = wx.TextCtrl(scrolled, value=str(info.get("min", "")))

                max_ctrl = wx.TextCtrl(scrolled, value=str(info.get("max", "")))

                self.controls[col]["min"] = min_ctrl

                self.controls[col]["max"] = max_ctrl

                grid.Add(min_ctrl, pos=(row, 4), flag=wx.ALL|wx.EXPAND, border=5)

                grid.Add(max_ctrl, pos=(row, 5), flag=wx.ALL|wx.EXPAND, border=5)

            elif default in ["Date", "DateTime"]:

                sd = wx.adv.DatePickerCtrl(scrolled)

                ed = wx.adv.DatePickerCtrl(scrolled)

                self.controls[col]["start_date"] = sd

                self.controls[col]["end_date"] = ed

                grid.Add(sd, pos=(row, 4), flag=wx.ALL|wx.EXPAND, border=5)

                grid.Add(ed, pos=(row, 5), flag=wx.ALL|wx.EXPAND, border=5)

            else:

                grid.Add(wx.StaticText(scrolled, label="N/A"),

                         pos=(row, 4), flag=wx.ALL|wx.ALIGN_CENTER_VERTICAL, border=5)

                grid.Add(wx.StaticText(scrolled, label="N/A"),

                         pos=(row, 5), flag=wx.ALL|wx.ALIGN_CENTER_VERTICAL, border=5)

 

            # Example Values

            ev = wx.TextCtrl(scrolled, value=str(info.get("example_values", "")))

            self.controls[col]["example_values"] = ev

            grid.Add(ev, pos=(row, 6), flag=wx.ALL|wx.EXPAND, border=5)

 

            row += 1

 

        grid.AddGrowableCol(6, 1)

        scrolled.SetSizer(grid)

        scrolled.FitInside()

        mainSizer.Add(scrolled, 1, wx.ALL|wx.EXPAND, 10)

 

        btns = wx.BoxSizer(wx.HORIZONTAL)

        save = wx.Button(panel, wx.ID_OK, label="Save")

        cancel = wx.Button(panel, wx.ID_CANCEL, label="Cancel")

        btns.Add(save, flag=wx.ALL, border=5)

        btns.Add(cancel, flag=wx.ALL, border=5)

        mainSizer.Add(btns, flag=wx.ALIGN_CENTER)

 

        panel.SetSizer(mainSizer)

 

    def get_field_specs(self):

        specs = {}

        for col, ctrls in self.controls.items():

            s = {}

            s["dtype_override"] = ctrls["dtype"].GetStringSelection()

            s["primary_key"] = ctrls["primary_key"].GetValue()

            s["foreign_key"] = ctrls["foreign_key"].GetValue()

            if "min" in ctrls and "max" in ctrls:

                s["min"] = ctrls["min"].GetValue().strip()

                s["max"] = ctrls["max"].GetValue().strip()

            if "start_date" in ctrls and "end_date" in ctrls:

                d1 = ctrls["start_date"].GetValue()

                d2 = ctrls["end_date"].GetValue()

                s["start_date"] = datetime(d1.GetYear(), d1.GetMonth()+1, d1.GetDay()).strftime("%Y-%m-%d")

                s["end_date"] = datetime(d2.GetYear(), d2.GetMonth()+1, d2.GetDay()).strftime("%Y-%m-%d")

            ev_raw = ctrls["example_values"].GetValue().strip()

            s["example_values"] = ev_raw

            # parse into list for sampling

            if ev_raw:

                s["values"] = [v.strip() for v in ev_raw.split(",") if v.strip()]

            specs[col] = s

        return specs

 

# ---------------------------------------------------------------------

# Settings Dialog

# ---------------------------------------------------------------------

class SettingsDialog(wx.Dialog):

    def __init__(self, parent):

        super().__init__(parent, title="Settings", size=(450, 350))

        panel = wx.Panel(self)

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.controls = {}

        fields = [

            ("AWS Access Key ID:", "aws_access_key_id"),

            ("AWS Secret Access Key:", "aws_secret_access_key"),

            ("AWS Session Token:", "aws_session_token"),

            ("AWS S3 Bucket:", "aws_s3_bucket"),

            ("AWS S3 Region:", "aws_s3_region")

        ]

        grid = wx.FlexGridSizer(rows=len(fields), cols=2, hgap=10, vgap=10)

        for label, key in fields:

            grid.Add(wx.StaticText(panel, label=label), flag=wx.ALIGN_CENTER_VERTICAL)

            txt = wx.TextCtrl(panel, value=default_values.get(key, ""))

            self.controls[key] = txt

            grid.Add(txt, proportion=1, flag=wx.EXPAND)

        grid.AddGrowableCol(1, 1)

        sizer.Add(grid, flag=wx.ALL|wx.EXPAND, border=20)

 

        btns = wx.BoxSizer(wx.HORIZONTAL)

        save = wx.Button(panel, label="Save")

        cancel = wx.Button(panel, label="Cancel")

        btns.Add(save, flag=wx.RIGHT, border=10)

        btns.Add(cancel, flag=wx.LEFT, border=10)

        sizer.Add(btns, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=20)

 

        panel.SetSizer(sizer)

        save.Bind(wx.EVT_BUTTON, self.on_save)

        cancel.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

 

    def on_save(self, event):

        for key, ctrl in self.controls.items():

            default_values[key] = ctrl.GetValue().strip()

        save_config()

        wx.MessageBox("Settings saved successfully!", "Settings", wx.OK|wx.ICON_INFORMATION)

        self.EndModal(wx.ID_OK)

 

# ---------------------------------------------------------------------

# Main application frame

# ---------------------------------------------------------------------

class MainFrame(wx.Frame):

    def __init__(self):

        super().__init__(None, title="RDB (Rocket Synthetic Data Broker)", size=(1200, 800))

        self._mgr = aui.AuiManager(self)

        self.original_headers = []

        self.uploaded_data = []

        self.uploaded_df = None

        self.field_info = {}

        self.table_data = []

        self.selected_columns = []

        self.repo_filename = "syn-data-repo.csv"

        self.anomaly_info = {}

        self.create_menu()

        self.create_toolbar()

        self.create_panes()

        self.CreateStatusBar()

        self.SetStatusText("Welcome to RDB!")

        self._mgr.Update()

        self.Center()

 

    def load_field_specifications(self):

        """Load saved field specs."""

        if os.path.exists(FIELDSPEC_FILE):

            try:

                with open(FIELDSPEC_FILE, 'r') as f:

                    saved = json.load(f)

                for col in self.original_headers:

                    if col in saved:

                        self.field_info[col].update(saved[col])

                logging.info("Field specifications loaded.")

            except Exception as e:

                logging.error(f"Failed to load field specs: {e}")

 

    def save_field_specifications(self):

        """Save field specs."""

        try:

            with open(FIELDSPEC_FILE, 'w') as f:

                json.dump(self.field_info, f, indent=4)

            logging.info("Field specifications saved.")

        except Exception as e:

            logging.error(f"Failed to save field specs: {e}")

 

    def create_menu(self):

        mb = wx.MenuBar()

        fileMenu = wx.Menu()

        u1 = fileMenu.Append(wx.ID_OPEN, "&Upload Data\tCtrl+U")

        u2 = fileMenu.Append(wx.ID_ANY, "Load from S3")

        fileMenu.AppendSeparator()

        s1 = fileMenu.Append(wx.ID_SAVE, "&Save to Repo\tCtrl+S")

        e1 = fileMenu.Append(wx.ID_ANY, "&Export Data")

        u3 = fileMenu.Append(wx.ID_ANY, "Upload Repo to S3")

        fileMenu.AppendSeparator()

        x1 = fileMenu.Append(wx.ID_EXIT, "E&xit")

        mb.Append(fileMenu, "&File")

 

        editMenu = wx.Menu()

        g1 = editMenu.Append(wx.ID_ANY, "Generate Synthetic Data")

        s2 = editMenu.Append(wx.ID_ANY, "Select Columns...")

        a1 = editMenu.Append(wx.ID_ANY, "Anonymization")

        f1 = editMenu.Append(wx.ID_ANY, "Field Specifications...")

        d1 = editMenu.Append(wx.ID_ANY, "Anomaly Detection")

        mb.Append(editMenu, "&Edit")

 

        settingsMenu = wx.Menu()

        settingsMenu.Append(wx.ID_PREFERENCES, "&Settings")

        mb.Append(settingsMenu, "&Settings")

 

        self.SetMenuBar(mb)

        self.Bind(wx.EVT_MENU, self.on_upload_data, u1)

        self.Bind(wx.EVT_MENU, self.on_load_from_s3, u2)

        self.Bind(wx.EVT_MENU, self.on_save_to_repo, s1)

        self.Bind(wx.EVT_MENU, self.on_export_data, e1)

        self.Bind(wx.EVT_MENU, self.on_upload_to_s3, u3)

        self.Bind(wx.EVT_MENU, lambda e: self.Close(), x1)

        self.Bind(wx.EVT_MENU, self.on_generate_all, g1)

        self.Bind(wx.EVT_MENU, self.on_select_columns, s2)

        self.Bind(wx.EVT_MENU, self.on_anonymization, a1)

        self.Bind(wx.EVT_MENU, self.on_field_specifications, f1)

        self.Bind(wx.EVT_MENU, self.on_anomaly_detection, d1)

        self.Bind(wx.EVT_MENU, self.on_settings, settingsMenu.FindItemById(wx.ID_PREFERENCES))

 

    def create_toolbar(self):

        tb = self.CreateToolBar()

        tb.SetToolBitmapSize((24, 24))

        tb.AddTool(wx.ID_OPEN, "Upload", wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN))

        tb.AddTool(wx.ID_ANY, "Generate", wx.ArtProvider.GetBitmap(wx.ART_NEW))

        tb.AddTool(wx.ID_ANY, "Select Columns", wx.ArtProvider.GetBitmap(wx.ART_HELP_SETTINGS))

        tb.AddTool(wx.ID_ANY, "Anonymization", wx.ArtProvider.GetBitmap(wx.ART_REPORT_VIEW))

        tb.AddTool(wx.ID_SAVE, "Save Repo", wx.ArtProvider.GetBitmap(wx.ART_FILE_SAVE))

        tb.AddTool(wx.ID_ANY, "Export", wx.ArtProvider.GetBitmap(wx.ART_REPORT_VIEW))

        tb.AddTool(wx.ID_ANY, "Anomaly Detection", wx.ArtProvider.GetBitmap(wx.ART_FIND))

        tb.Realize()

        tb.Bind(wx.EVT_TOOL, self.on_upload_data, id=wx.ID_OPEN)

        tb.Bind(wx.EVT_TOOL, self.on_generate_all, id=wx.ID_ANY)

        tb.Bind(wx.EVT_TOOL, self.on_select_columns, id=wx.ID_ANY)

        tb.Bind(wx.EVT_TOOL, self.on_anonymization, id=wx.ID_ANY)

        tb.Bind(wx.EVT_TOOL, self.on_save_to_repo, id=wx.ID_SAVE)

        tb.Bind(wx.EVT_TOOL, self.on_export_data, id=wx.ID_ANY)

        tb.Bind(wx.EVT_TOOL, self.on_anomaly_detection, id=wx.ID_ANY)

 

    def create_panes(self):

        control = wx.Panel(self)

        cs = wx.BoxSizer(wx.VERTICAL)

        for lbl, handler in [("Upload Data", self.on_upload_data),

                             ("Generate Synthetic Data", self.on_generate_all),

                             ("Select Columns", self.on_select_columns),

                             ("Anonymization", self.on_anonymization),

                             ("Save to Repo", self.on_save_to_repo),

                             ("Export Data", self.on_export_data),

                             ("Anomaly Detection", self.on_anomaly_detection)]:

            btn = wx.Button(control, label=lbl)

            cs.Add(btn, flag=wx.EXPAND|wx.ALL, border=5)

            btn.Bind(wx.EVT_BUTTON, handler)

        control.SetSizer(cs)

        self.gridPanel = wx.Panel(self)

        gs = wx.BoxSizer(wx.VERTICAL)

        self.dataGrid = gridlib.Grid(self.gridPanel)

        self.dataGrid.CreateGrid(0, 0)

        self.dataGrid.EnableEditing(False)

        gs.Add(self.dataGrid, 1, wx.EXPAND|wx.ALL, 5)

        self.gridPanel.SetSizer(gs)

 

        self.repoPanel = wx.Panel(self)

        rs = wx.BoxSizer(wx.VERTICAL)

        rs.Add(wx.StaticText(self.repoPanel, label="Synthetic Data Repository"), flag=wx.ALL, border=5)

        self.repoGrid = gridlib.Grid(self.repoPanel)

        self.repoGrid.CreateGrid(0, 0)

        self.repoGrid.EnableEditing(False)

        rs.Add(self.repoGrid, 1, wx.EXPAND|wx.ALL, 5)

        self.repoPanel.SetSizer(rs)

 

        self._mgr.AddPane(control, aui.AuiPaneInfo().Name("controls").Left().Caption("Operations").MinSize((200,200)))

        self._mgr.AddPane(self.gridPanel, aui.AuiPaneInfo().Name("grid").Center().Caption("Synthetic Data"))

        self._mgr.AddPane(self.repoPanel, aui.AuiPaneInfo().Name("repo").Bottom().Caption("Repository").MinSize((400,200)))

 

    def display_grid(self, headers, data, grid):

        # Clear & rebuild

        if grid.GetNumberRows() > 0:

            grid.DeleteRows(0, grid.GetNumberRows(), True)

        if grid.GetNumberCols() > 0:

            grid.DeleteCols(0, grid.GetNumberCols(), True)

        grid.AppendCols(len(headers))

        grid.AppendRows(len(data))

        for c, h in enumerate(headers):

            grid.SetColLabelValue(c, h)

        for r, row in enumerate(data):

            for c, val in enumerate(row):

                grid.SetCellValue(r, c, str(val))

        grid.AutoSizeColumns()

        grid.AutoSizeRows()

        self._mgr.Update()

 

    def display_repo(self):

        if not os.path.exists(self.repo_filename):

            self.repoGrid.ClearGrid()

            return

        try:

            df = pd.read_csv(self.repo_filename).replace(["nan","NaN"], "")

            self.display_grid(df.columns.tolist(), df.values.tolist(), self.repoGrid)

        except Exception as e:

            wx.MessageBox(f"Failed to load repository: {e}", "Error", wx.OK|wx.ICON_ERROR)

            logging.error(f"Repo load error: {e}")

 

    def on_upload_data(self, event):

        with wx.FileDialog(self, "Open CSV or TXT file",

                           wildcard="CSV (*.csv)|*.csv|Text (*.txt)|*.txt",

                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dlg:

            if dlg.ShowModal() != wx.ID_OK:

                return

            path = dlg.GetPath()

            try:

                ext = os.path.splitext(path)[1].lower()

                delim = ',' if ext=='.csv' else None

                df = pd.read_csv(path, delimiter=delim)

                if df.empty:

                    raise ValueError("File is empty.")

                self.original_headers = df.columns.tolist()

                self.uploaded_data = df.values.tolist()

                self.uploaded_df = df.copy()

                self.field_info = {}

                for col in self.original_headers:

                    sample = next((v for v in df[col] if pd.notnull(v)), None)

                    values = df[col].dropna().tolist()

                    self.field_info[col] = {

                        "sample": sample,

                        "dtype": str(df[col].dtype),

                        "values": values

                    }

                self.load_field_specifications()

                self.table_data = self.uploaded_data.copy()

                self.display_grid(self.original_headers, self.table_data, self.dataGrid)

                self.SetStatusText(f"Uploaded: {os.path.basename(path)}")

                logging.info(f"Uploaded file: {path}")

            except Exception as e:

                wx.MessageBox(f"Failed to load file: {e}", "Error", wx.OK|wx.ICON_ERROR)

                logging.error(f"Upload error: {e}")

 

    def on_load_from_s3(self, event):

        dlg = wx.TextEntryDialog(self, "Enter S3 URI (s3://bucket/key.csv):", "Load from S3")

        if dlg.ShowModal() != wx.ID_OK:

            return

        uri = dlg.GetValue().strip()

        if not uri.lower().startswith("s3://"):

            wx.MessageBox("Invalid S3 URI.", "Error", wx.OK|wx.ICON_ERROR)

            return

        from urllib.parse import urlparse

        parsed = urlparse(uri)

        bucket, key = parsed.netloc, parsed.path.lstrip('/')

        if not bucket or not key:

            wx.MessageBox("Invalid S3 URI.", "Error", wx.OK|wx.ICON_ERROR)

            return

        try:

            creds = {

                "aws_access_key_id": default_values["aws_access_key_id"],

                "aws_secret_access_key": default_values["aws_secret_access_key"]

            }

            if default_values.get("aws_session_token"):

                creds["aws_session_token"] = default_values["aws_session_token"]

            if default_values.get("aws_s3_region"):

                creds["region_name"] = default_values["aws_s3_region"]

            session = boto3.session.Session(**creds)

            s3 = session.client("s3")

            resp = s3.list_objects_v2(Bucket=bucket, Prefix=key)

            if 'Contents' not in resp or not any(o['Key']==key for o in resp['Contents']):

                raise FileNotFoundError(f"{key} not found in {bucket}")

            tmp = os.path.join(os.getcwd(), f"_s3_{os.path.basename(key)}")

            s3.download_file(bucket, key, tmp)

            ext = os.path.splitext(tmp)[1].lower()

            delim = ',' if ext=='.csv' else None

            df = pd.read_csv(tmp, delimiter=delim)

            os.remove(tmp)

            if df.empty:

                raise ValueError("Downloaded file is empty.")

            self.original_headers = df.columns.tolist()

            self.uploaded_data = df.values.tolist()

            self.uploaded_df = df.copy()

            self.field_info = {}

            for col in self.original_headers:

                sample = next((v for v in df[col] if pd.notnull(v)), None)

                values = df[col].dropna().tolist()

                self.field_info[col] = {

                    "sample": sample,

                    "dtype": str(df[col].dtype),

                    "values": values

                }

            self.load_field_specifications()

            self.table_data = self.uploaded_data.copy()

            self.display_grid(self.original_headers, self.table_data, self.dataGrid)

            self.SetStatusText(f"S3 loaded: {key}")

            logging.info(f"Loaded from S3: {uri}")

        except Exception as e:

            wx.MessageBox(f"S3 load error: {e}", "Error", wx.OK|wx.ICON_ERROR)

            logging.error(f"S3 error: {e}")

 

    def on_generate_all(self, event):

        if not self.original_headers:

            wx.MessageBox("Upload data first.", "Error", wx.OK|wx.ICON_WARNING)

            return

        count = wx.GetNumberFromUser("Number of records:", "Count:", "Generate Synthetic Data", 10, 1, 10000, self)

        if count <= 0:

            return

        headers = ["Unique ID"] + self.original_headers if "Unique ID" not in self.original_headers else self.original_headers.copy()

        synthetic = []

        unique_sets = {}

        for col in self.original_headers:

            if self.field_info[col].get("primary_key"):

                unique_sets[col] = set()

        for _ in range(count):

            uid = str(uuid.uuid4())

            row = [uid] if "Unique ID" not in self.original_headers else []

            for col in self.original_headers:

                sv = self.field_info[col]["sample"]

                ft = self.field_info[col]["dtype"]

                cons = self.field_info[col]

                if cons.get("primary_key"):

                    val = generate_unique_synthetic_value(col, sv, ft, cons, unique_sets[col])

                else:

                    val = generate_synthetic_value(col, sv, ft, cons)

                row.append(val)

            synthetic.append(row)

        self.table_data = synthetic

        self.display_grid(headers, self.table_data, self.dataGrid)

        self.SetStatusText("Synthetic data generated.")

        logging.info("Generated synthetic data.")

 

    def on_select_columns(self, event):

        if not self.original_headers:

            wx.MessageBox("Upload data first.", "Error", wx.OK|wx.ICON_WARNING)

            return

        dlg = ColumnSelectionDialog(self, self.original_headers)

        if dlg.ShowModal() == wx.ID_OK:

            self.selected_columns = dlg.get_selected_columns()

            self.SetStatusText("Selected: " + ", ".join(self.selected_columns) if self.selected_columns else "No columns selected.")

        dlg.Destroy()

 

    def on_anonymization(self, event):

        if not self.uploaded_data:

            wx.MessageBox("Upload data first.", "Error", wx.OK|wx.ICON_WARNING)

            return

        if not self.selected_columns:

            wx.MessageBox("Select columns first.", "Error", wx.OK|wx.ICON_WARNING)

            return

        headers = ["Unique ID"] + self.original_headers if "Unique ID" not in self.original_headers else self.original_headers.copy()

        new_data = []

        unique_sets = {}

        for col in self.selected_columns:

            if self.field_info[col].get("primary_key"):

                unique_sets[col] = set()

        for row in self.uploaded_data:

            base = [str(uuid.uuid4())] + row if "Unique ID" not in self.original_headers else list(row)

            for col in self.selected_columns:

                idx = self.original_headers.index(col)

                orig = row[idx]

                sv = orig if pd.notnull(orig) else self.field_info[col]["sample"]

                ft = self.field_info[col]["dtype"]

                cons = self.field_info[col]

                if cons.get("primary_key"):

                    v = generate_unique_synthetic_value(col, sv, ft, cons, unique_sets[col])

                else:

                    v = generate_synthetic_value(col, sv, ft, cons)

                base[idx + (0 if "Unique ID" in self.original_headers else 1)] = v

            new_data.append(base)

        self.table_data = new_data

        self.display_grid(headers, self.table_data, self.dataGrid)

        self.SetStatusText("Anonymization completed.")

        logging.info("Anonymization done.")

 

    def on_field_specifications(self, event):

        if not self.field_info:

            wx.MessageBox("Upload data first.", "Error", wx.OK|wx.ICON_WARNING)

            return

        dlg = FieldSpecDialog(self, self.field_info)

        if dlg.ShowModal() == wx.ID_OK:

            specs = dlg.get_field_specs()

            for col, spec in specs.items():

                self.field_info[col].update(spec)

            self.save_field_specifications()

            if self.uploaded_df is not None:

                self.refresh_data_with_field_specs()

            self.SetStatusText("Field specs updated.")

        dlg.Destroy()

 

    def refresh_data_with_field_specs(self):

        if self.uploaded_df is None:

            return

        df = self.uploaded_df.copy()

        for col in self.original_headers:

            spec = self.field_info.get(col, {})

            if spec.get("dtype_override","Auto")!="Auto" or spec.get("min","")!="" or spec.get("start_date","")!="":

                new_vals = []

                for val in df[col]:

                    sv = val if pd.notnull(val) else spec.get("sample")

                    ft = spec.get("dtype_override", spec.get("dtype"))

                    new_vals.append(generate_synthetic_value(col, sv, ft, spec))

                df[col] = new_vals

        self.uploaded_df = df

        self.table_data = df.values.tolist()

        self.display_grid(df.columns.tolist(), self.table_data, self.dataGrid)

        self.SetStatusText("Applied field specs.")

        logging.info("Applied field specs.")

 

    def on_anomaly_detection(self, event):

        if self.uploaded_df is None or self.uploaded_df.empty:

            wx.MessageBox("Upload data first.", "Error", wx.OK|wx.ICON_WARNING)

            return

        info = {}

        df = self.uploaded_df.copy()

        # numeric outliers

        for col in df.select_dtypes(include=[np.number]).columns:

            ser = pd.to_numeric(df[col], errors='coerce')

            mean, std = ser.mean(), ser.std()

            if std and not np.isnan(std):

                lb, ub = mean-3*std, mean+3*std

                inds = ser[(ser<lb)|(ser>ub)].index.tolist()

                if inds:

                    info[col] = {"indices": inds, "median": ser.median()}

        # constraints violations

        for col in df.columns:

            spec = self.field_info.get(col,{})

            dtype_spec = spec.get("dtype_override",spec.get("dtype",""))

            # numeric min/max

            if pd.api.types.is_numeric_dtype(df[col]) and spec.get("min","")!="" and spec.get("max","")!="":

                try:

                    lo, hi = float(spec["min"]), float(spec["max"])

                    bad = [i for i,v in df[col].items() if pd.notnull(v) and (v<lo or v>hi)]

                    if bad:

                        if col in info:

                            info[col]["indices"] = list(set(info[col]["indices"]+bad))

                        else:

                            info[col] = {"indices": bad, "median": pd.to_numeric(df[col],errors='coerce').median()}

                except: pass

            # email format

            if dtype_spec.lower()=="email" or "email" in normalize_name(col):

                bad = [i for i,v in df[col].items() if pd.notnull(v) and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",str(v))]

                if bad: info[col] = {"indices": bad, "note": "Invalid email format"}

            # date range

            if dtype_spec.lower() in ("date","datetime") and spec.get("start_date","") and spec.get("end_date",""):

                try:

                    sd = datetime.strptime(spec["start_date"],"%Y-%m-%d")

                    ed = datetime.strptime(spec["end_date"],"%Y-%m-%d")

                    bad = []

                    for i,v in df[col].items():

                        if isinstance(v,str) and v.strip():

                            try:

                                dt = datetime.strptime(v,detect_date_format(v))

                                if dt<sd or dt>ed:

                                    bad.append(i)

                            except:

                                bad.append(i)

                    if bad: info[col] = {"indices": bad, "note": f"Date outside {spec['start_date']} to {spec['end_date']}"}

                except: pass

        self.anomaly_info = info

        if info:

            msgs = ["Anomalies detected:"]

            for c,i in info.items():

                cnt = len(i["indices"])

                note = i.get("note",f"median replacement")

                msgs.append(f" - {c}: {cnt} anomalies; {note}")

            wx.MessageBox("\n".join(msgs),"Anomaly Detection", wx.OK|wx.ICON_INFORMATION)

            self.SetStatusText("Anomalies found. Use Cleanse Data.")

            self.btnCleanse.Enable()

        else:

            wx.MessageBox("No anomalies detected.","Anomaly Detection",wx.OK|wx.ICON_INFORMATION)

            self.SetStatusText("No anomalies.")

            self.btnCleanse.Disable()

 

    def on_cleanse_data(self, event):

        if not self.anomaly_info:

            wx.MessageBox("Run anomaly detection first.","Error",wx.OK|wx.ICON_WARNING)

            return

        df = self.uploaded_df.copy()

        for col, detail in self.anomaly_info.items():

            inds = detail["indices"]

            if "median" in detail:

                df.loc[inds, col] = detail["median"]

            else:

                for i in inds:

                    sv = self.field_info[col]["sample"]

                    ft = self.field_info[col]["dtype"]

                    cons = self.field_info[col]

                    df.at[i, col] = generate_synthetic_value(col, sv, ft, cons)

        self.uploaded_df = df

        self.table_data = df.values.tolist()

        self.display_grid(df.columns.tolist(), self.table_data, self.dataGrid)

        self.SetStatusText("Data cleansed.")

        logging.info("Applied cleansing.")

        self.btnCleanse.Disable()

 

    def on_save_to_repo(self, event):

        try:

            headers = [self.dataGrid.GetColLabelValue(i) for i in range(self.dataGrid.GetNumberCols())]

            df_new = pd.DataFrame(self.table_data, columns=headers).replace("", pd.NA).dropna(axis=1, how="all").fillna("")

            if not os.path.exists(self.repo_filename):

                df_new.to_csv(self.repo_filename, index=False)

            else:

                df_old = pd.read_csv(self.repo_filename).replace(["nan","NaN"], "")

                for c in df_new.columns:

                    if c not in df_old.columns:

                        df_old[c] = ""

                df_new = df_new.reindex(columns=df_old.columns, fill_value="")

                df_concat = pd.concat([df_old, df_new], ignore_index=True).fillna("")

                df_concat.to_csv(self.repo_filename, index=False)

            self.SetStatusText("Saved to repo.")

            logging.info("Saved to repository.")

            self.display_repo()

        except Exception as e:

            wx.MessageBox(f"Save error: {e}","Error",wx.OK|wx.ICON_ERROR)

            logging.error(f"Save repo error: {e}")

 

    def on_export_data(self, event):

        if not self.table_data:

            wx.MessageBox("No data to export.","Error",wx.OK|wx.ICON_WARNING)

            return

        wildcard = "CSV (*.csv)|*.csv|Text (*.txt)|*.txt|Excel (*.xlsx)|*.xlsx"

        with wx.FileDialog(self, "Export Data", wildcard=wildcard,

                           style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dlg:

            if dlg.ShowModal()!=wx.ID_OK:

                return

            path = dlg.GetPath()

            try:

                ext = os.path.splitext(path)[1].lower()

                headers = [self.dataGrid.GetColLabelValue(i) for i in range(self.dataGrid.GetNumberCols())]

                if ext==".csv":

                    with open(path,'w',newline='',encoding='utf-8') as f:

                       w=csv.writer(f); w.writerow(headers); w.writerows(self.table_data)

                elif ext==".txt":

                    with open(path,'w',encoding='utf-8') as f:

                        f.write("\t".join(headers)+"\n")

                        for row in self.table_data:

                            f.write("\t".join(map(str,row))+"\n")

                elif ext==".xlsx":

                    pd.DataFrame(self.table_data,columns=headers).to_excel(path,index=False)

                else:

                    raise ValueError("Unsupported format")

                self.SetStatusText(f"Exported to {os.path.basename(path)}")

                logging.info(f"Exported to {path}")

            except Exception as e:

                wx.MessageBox(f"Export failed: {e}","Error",wx.OK|wx.ICON_ERROR)

                logging.error(f"Export error: {e}")

 

    def on_upload_to_s3(self, event):

        if not os.path.exists(self.repo_filename):

            wx.MessageBox("Repo not found.","Error",wx.OK|wx.ICON_ERROR)

            return

        creds = {

            "aws_access_key_id": default_values["aws_access_key_id"],

            "aws_secret_access_key": default_values["aws_secret_access_key"]

        }

        if default_values.get("aws_session_token"):

            creds["aws_session_token"] = default_values["aws_session_token"]

        if default_values.get("aws_s3_region"):

            creds["region_name"] = default_values["aws_s3_region"]

        try:

            session = boto3.session.Session(**creds)

            s3 = session.client("s3")

            bucket = default_values["aws_s3_bucket"]

            if not bucket:

                raise ValueError("No bucket configured")

            key = os.path.basename(self.repo_filename)

            s3.upload_file(self.repo_filename, bucket, key)

            wx.MessageBox("Uploaded to S3.","Info",wx.OK|wx.ICON_INFORMATION)

            logging.info(f"Uploaded repo to S3://{bucket}/{key}")

        except Exception as e:

            wx.MessageBox(f"S3 upload error: {e}","Error",wx.OK|wx.ICON_ERROR)

            logging.error(f"S3 upload error: {e}")

 

    def on_settings(self, event):

        dlg = SettingsDialog(self)

        if dlg.ShowModal()==wx.ID_OK:

            pass

        dlg.Destroy()

 

    def OnClose(self, event):

        self._mgr.UnInit()

        self.Destroy()

 

class RDBApp(wx.App):

    def OnInit(self):

        frame = MainFrame()

        frame.Show()

        return True

 

if __name__ == '__main__':

    app = RDBApp(False)

    app.MainLoop()

 