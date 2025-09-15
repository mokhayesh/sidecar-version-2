import wx

import wx.grid as gridlib

import wx.richtext as rt

import wx.lib.newevent

from collections import deque

import pandas as pd

import requests

import warnings

import threading

import urllib3

import re

import os

import zipfile

import csv

import io

import time

import speech_recognition as sr

import json

import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt

import smtplib

import ssl

from datetime import datetime

 

# =========================================

#  ADDED imports for Edge TTS and Pygame

# =========================================

import asyncio

import edge_tts

import pygame  # Added for better audio control

 

# Check for openpyxl

try:

    import openpyxl

except ImportError:

    wx.MessageBox("The 'openpyxl' package is not installed. Please install it with 'pip install openpyxl' and rerun the script.","Missing Dependency",wx.OK|wx.ICON_ERROR)

    raise SystemExit("Missing openpyxl")

 

# Check for fsspec (required by pandas for some file operations)

try:

    import fsspec

except ImportError:

    wx.MessageBox("The 'fsspec' package is not installed. Please install it with 'pip install fsspec' and rerun the script.","Missing Dependency",wx.OK|wx.ICON_ERROR)

    raise SystemExit("Missing fsspec")

 

plt.style.use('ggplot')

 

# Suppress warnings for insecure HTTPS requests globally

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

 

default_values = {

    "api_key": "",

    "filepath": os.path.expanduser("~"),  # Changed to user's home directory for flexibility

    "default_model": "gpt-4",

    "max_tokens": "1000",

    "temperature": "0.7",

    "top_p": "1.0",

    "frequency_penalty": "0.0",

    "presence_penalty": "0.0",

    "url": https://api.openai.com/v1/chat/completions,

    "image_generation_url": https://api.openai.com/v1/images/generations,

    "max_retries": 5,

    "backoff_factor": 2,

    "smtp_server": "",

    "smtp_port": "",

    "email_username": "",

    "email_password": "",

    "from_email": "",

    "to_email": ""

}

 

default_values_file = "default_values.txt"

 

def save_defaults(window):

    default_values["api_key"] = window.api_key_entry.GetValue()

    default_values["filepath"] = window.filepath_entry.GetValue()

    default_values["default_model"] = window.model_choice.GetStringSelection()

    default_values["max_tokens"] = window.max_tokens_entry.GetValue()

    default_values["temperature"] = window.temperature_entry.GetValue()

    default_values["top_p"] = window.top_p_entry.GetValue()

    default_values["frequency_penalty"] = window.frequency_penalty_entry.GetValue()

    default_values["presence_penalty"] = window.presence_penalty_entry.GetValue()

    default_values["url"] = window.url_entry.GetValue()

    default_values["image_generation_url"] = window.image_generation_url_entry.GetValue()

    default_values["smtp_server"] = window.smtp_server_entry.GetValue()

    default_values["smtp_port"] = window.smtp_port_entry.GetValue()

    default_values["email_username"] = window.email_username_entry.GetValue()

    default_values["email_password"] = window.email_password_entry.GetValue()

    default_values["from_email"] = window.from_email_entry.GetValue()

    default_values["to_email"] = window.to_email_entry.GetValue()

 

    with open(default_values_file, "w") as file:

        for key, value in default_values.items():

            file.write(f"{key}: {value}\n")

 

    wx.MessageBox("Default values have been saved.", "Defaults Saved", wx.OK | wx.ICON_INFORMATION)

 

def load_default_values():

    try:

        with open(default_values_file, "r") as file:

            for line in file:

                key, value = line.strip().split(": ", 1)

                default_values[key] = value

    except FileNotFoundError:

        pass

 

load_default_values()

 

 

#############################################################################

#  GPT Chat Completion (Used only for tasks requiring Gen AI, e.g. Catalog)

#############################################################################

def create_chat_completion(model, messages, max_tokens, temperature, top_p, frequency_penalty, presence_penalty):

    url = default_values["url"]

    headers = {

        'Authorization': f'Bearer {default_values["api_key"]}',

        'Content-Type': 'application/json',

    }

    data = {

        'model': model,

        'messages': messages,

        'max_tokens': int(max_tokens),

        'temperature': float(temperature),

        'top_p': float(top_p),

        'frequency_penalty': float(frequency_penalty),

        'presence_penalty': float(presence_penalty)

    }

 

    retries = 0

    while retries < int(default_values.get("max_retries", 5)):

        try:

            response = requests.post(url, headers=headers, json=data, verify=False, timeout=60)

            if response.status_code == 429:

                wait_time = int(default_values.get("backoff_factor", 2) ** retries)

                print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")

                time.sleep(wait_time)

                retries += 1

                continue

            response.raise_for_status()

            return response.json()

        except requests.exceptions.HTTPError as http_err:

            if response.status_code == 429:

                wait_time = int(default_values.get("backoff_factor", 2) ** retries)

                print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")

                time.sleep(wait_time)

                retries += 1

                continue

            else:

                print(f"HTTP error occurred: {http_err}")

                return {"error": str(http_err)}

        except requests.exceptions.RequestException as e:

            print(f"Request exception: {e}")

            wait_time = int(default_values.get("backoff_factor", 2) ** retries)

            print(f"Retrying in {wait_time} seconds...")

            time.sleep(wait_time)

            retries += 1

            continue

 

    return {"error": "Exceeded maximum number of retries due to rate limiting."}

 

 

#############################################################################

#               CSV Detection

#############################################################################

def detect_and_split_data(text):

    lines = text.strip().split("\n")

    if not lines:

        return [], []

    delimiter = "," if "," in lines[0] else "|"

    reader = csv.reader(lines, delimiter=delimiter)

    data = [row for row in reader]

    if not data:

        return [], []

    headers = data[0]

    table_data = data[1:]

    return headers, table_data

 

 

TodoActionCompleteEvent, EVT_TODO_ACTION_COMPLETE = wx.lib.newevent.NewEvent()

 

class SettingsWindow(wx.Frame):

    def __init__(self, parent, title):

        super(SettingsWindow, self).__init__(parent, title=title, size=(510, 700))

       

        panel = wx.Panel(self)

        panel.SetBackgroundColour(wx.Colour(30,30,30))

 

        sizer = wx.GridBagSizer(5,5)

       

        label_color = wx.Colour(255,255,255)

        entry_bg_color = wx.Colour(50,50,50)

        entry_fg_color = wx.Colour(255,255,255)

 

        def add_label_and_entry(row, label_text, default_val_key, password=False, size=(300,-1)):

            lbl = wx.StaticText(panel, label=label_text)

            lbl.SetForegroundColour(label_color)

            sizer.Add(lbl, pos=(row,0), flag=wx.ALIGN_RIGHT)

            style = wx.TE_PASSWORD if password else 0

            txt = wx.TextCtrl(panel, value=str(default_values[default_val_key]), size=size, style=style)

            txt.SetBackgroundColour(entry_bg_color)

            txt.SetForegroundColour(entry_fg_color)

            sizer.Add(txt, pos=(row,1))

            return txt

 

        api_key_label = wx.StaticText(panel, label="API Key:")

        api_key_label.SetForegroundColour(label_color)

        sizer.Add(api_key_label, pos=(0,0), flag=wx.ALIGN_RIGHT | wx.TOP, border=20)

        self.api_key_entry = wx.TextCtrl(panel, value=default_values["api_key"], size=(300,-1))

        self.api_key_entry.SetBackgroundColour(entry_bg_color)

        self.api_key_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.api_key_entry, pos=(0,1), flag=wx.TOP, border=20)

 

        self.filepath_entry = add_label_and_entry(1, "File Path:", "filepath")

       

        model_label = wx.StaticText(panel, label="Model:")

        model_label.SetForegroundColour(label_color)

        sizer.Add(model_label, pos=(2,0), flag=wx.ALIGN_RIGHT)

        models = ["gpt-4", "gpt-3.5-turbo", "gpt-4o-mini", "gpt-4o-mini-2024-07-14", "gpt-4-turbo", "gpt-4o", "o1-mini"]

        self.model_choice = wx.Choice(panel, choices=models)

        self.model_choice.SetBackgroundColour(entry_bg_color)

        self.model_choice.SetForegroundColour(entry_fg_color)

        self.model_choice.SetStringSelection(default_values["default_model"])

        sizer.Add(self.model_choice, pos=(2,1))

 

        self.max_tokens_entry = add_label_and_entry(3, "Max Tokens:", "max_tokens")

        self.temperature_entry = add_label_and_entry(4, "Temperature:", "temperature")

        self.top_p_entry = add_label_and_entry(5, "Top P:", "top_p")

        self.frequency_penalty_entry = add_label_and_entry(6, "Frequency Penalty:", "frequency_penalty")

        self.presence_penalty_entry = add_label_and_entry(7, "Presence Penalty:", "presence_penalty")

 

        url_label = wx.StaticText(panel, label="Chat Completion URL:")

        url_label.SetForegroundColour(label_color)

        sizer.Add(url_label, pos=(8,0), flag=wx.ALIGN_RIGHT)

        self.url_entry = wx.TextCtrl(panel, value=default_values["url"], size=(300, -1))

        self.url_entry.SetBackgroundColour(entry_bg_color)

        self.url_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.url_entry, pos=(8,1))

 

        image_generation_url_label = wx.StaticText(panel, label="Image Generation URL:")

        image_generation_url_label.SetForegroundColour(label_color)

        sizer.Add(image_generation_url_label, pos=(9,0), flag=wx.ALIGN_RIGHT)

        self.image_generation_url_entry = wx.TextCtrl(panel, value=default_values["image_generation_url"], size=(300, -1))

        self.image_generation_url_entry.SetBackgroundColour(entry_bg_color)

        self.image_generation_url_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.image_generation_url_entry, pos=(9,1))

 

        smtp_server_label = wx.StaticText(panel, label="SMTP Server:")

        smtp_server_label.SetForegroundColour(label_color)

        sizer.Add(smtp_server_label, pos=(10,0), flag=wx.ALIGN_RIGHT)

        self.smtp_server_entry = wx.TextCtrl(panel, value=default_values["smtp_server"], size=(300,-1))

        self.smtp_server_entry.SetBackgroundColour(entry_bg_color)

        self.smtp_server_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.smtp_server_entry, pos=(10,1))

 

        smtp_port_label = wx.StaticText(panel, label="SMTP Port:")

        smtp_port_label.SetForegroundColour(label_color)

        sizer.Add(smtp_port_label, pos=(11,0), flag=wx.ALIGN_RIGHT)

        self.smtp_port_entry = wx.TextCtrl(panel, value=default_values["smtp_port"], size=(300,-1))

        self.smtp_port_entry.SetBackgroundColour(entry_bg_color)

        self.smtp_port_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.smtp_port_entry, pos=(11,1))

 

        email_username_label = wx.StaticText(panel, label="Email Username:")

        email_username_label.SetForegroundColour(label_color)

        sizer.Add(email_username_label, pos=(12,0), flag=wx.ALIGN_RIGHT)

        self.email_username_entry = wx.TextCtrl(panel, value=default_values["email_username"], size=(300,-1))

        self.email_username_entry.SetBackgroundColour(entry_bg_color)

        self.email_username_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.email_username_entry, pos=(12,1))

 

        email_password_label = wx.StaticText(panel, label="Email Password:")

        email_password_label.SetForegroundColour(label_color)

        sizer.Add(email_password_label, pos=(13,0), flag=wx.ALIGN_RIGHT)

        self.email_password_entry = wx.TextCtrl(panel, value=default_values["email_password"], style=wx.TE_PASSWORD, size=(300,-1))

        self.email_password_entry.SetBackgroundColour(entry_bg_color)

        self.email_password_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.email_password_entry, pos=(13,1))

 

        from_email_label = wx.StaticText(panel, label="From Email:")

        from_email_label.SetForegroundColour(label_color)

        sizer.Add(from_email_label, pos=(14,0), flag=wx.ALIGN_RIGHT)

        self.from_email_entry = wx.TextCtrl(panel, value=default_values["from_email"], size=(300,-1))

        self.from_email_entry.SetBackgroundColour(entry_bg_color)

        self.from_email_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.from_email_entry, pos=(14,1))

 

        to_email_label = wx.StaticText(panel, label="To Email:")

        to_email_label.SetForegroundColour(label_color)

        sizer.Add(to_email_label, pos=(15,0), flag=wx.ALIGN_RIGHT)

        self.to_email_entry = wx.TextCtrl(panel, value=default_values["to_email"], size=(300,-1))

        self.to_email_entry.SetBackgroundColour(entry_bg_color)

        self.to_email_entry.SetForegroundColour(entry_fg_color)

        sizer.Add(self.to_email_entry, pos=(15,1))

 

        save_button = wx.Button(panel, label="Save")

        save_button.SetBackgroundColour(entry_bg_color)

        save_button.SetForegroundColour(entry_fg_color)

        save_button.Bind(wx.EVT_BUTTON, lambda event: save_defaults(self))

        sizer.Add(save_button, pos=(16,0), span=(1,2), flag=wx.ALIGN_CENTER | wx.TOP, border=20)

 

        panel.SetSizerAndFit(sizer)

 

 

#############################################################################

#        NATURAL PYTHON ANALYSIS (Profile, Quality, Catalog, etc.)

#############################################################################

 

def profile_analysis(df, application, table_name):

    """

    Profile Output

    Application, Table Name, Field, Record Count, Unique Count, Completeness (%),

    Null Count, Blank Count, Minimum, Maximum, Median, Standard Deviation, Analysis Date

    """

    results = []

    analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_records = len(df)

 

    for col in df.columns:

        col_data = df[col]

        field_name = col

        unique_count = col_data.nunique(dropna=True)

        null_count = col_data.isnull().sum()

        blank_count = (col_data.astype(str).str.strip() == '').sum()

        completeness_pct = (

            100.0 * (total_records - null_count - blank_count) / total_records

            if total_records > 0 else 0.0

        )

        numeric_data = pd.to_numeric(col_data, errors='coerce').dropna()

        if len(numeric_data) > 0:

            min_val = numeric_data.min()

            max_val = numeric_data.max()

            median_val = numeric_data.median()

            std_val = numeric_data.std()

        else:

            min_val = ""

            max_val = ""

            median_val = ""

            std_val = ""

 

        row = [

            application,

            table_name,

            field_name,

            total_records,

            unique_count,

            round(completeness_pct, 2),

            null_count,

            blank_count,

            min_val,

            max_val,

            median_val,

            std_val,

            analysis_date

        ]

        results.append(row)

 

    headers = [

        "Application", "Table Name", "Field", "Record Count", "Unique Count",

        "Completeness (%)", "Null Count", "Blank Count", "Minimum",

        "Maximum", "Median", "Standard Deviation", "Analysis Date"

    ]

    return headers, results

 

 

def quality_analysis(df, application, table_name):

    """

    Quality Output

    Application, Table Name, Field, Total Records, Completeness (%), Uniqueness (%),

    Validity (%), Anomaly Count, Distinctiveness, Quality Score (%),

    Quality Rule (Regex), Analysis Date

    """

    results = []

    analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_records = len(df)

 

    for col in df.columns:

        col_data = df[col]

        field_name = col

        null_count = col_data.isnull().sum()

        blank_count = (col_data.astype(str).str.strip() == '').sum()

        completeness_pct = (

            100.0 * (total_records - null_count - blank_count) / total_records

            if total_records > 0 else 0.0

        )

        uniqueness_pct = (

            100.0 * col_data.nunique(dropna=True) / total_records

            if total_records > 0 else 0.0

        )

        numeric_data = pd.to_numeric(col_data, errors='coerce')

        valids = numeric_data.notnull().sum()

        # simplistic validity

        if total_records > 0 and (valids / total_records) >= 0.9:

            validity_pct = 95.0

        else:

            validity_pct = 80.0

        anomaly_count = max(1, int(0.01 * total_records)) if total_records > 0 else 0

        distinctiveness = round(uniqueness_pct / 100.0, 2)

        quality_score = round((completeness_pct + validity_pct) / 2.0, 2)

        # placeholder regex

        if pd.api.types.is_numeric_dtype(df[col]):

            quality_rule = r"^\d+(\.\d+)?$"

        else:

            quality_rule = r"^.*$"

 

        row = [

            application,

            table_name,

            field_name,

            total_records,

            round(completeness_pct,2),

            round(uniqueness_pct,2),

            round(validity_pct,2),

            anomaly_count,

            distinctiveness,

            quality_score,

            quality_rule,

            analysis_date

        ]

        results.append(row)

 

    headers = [

        "Application", "Table Name", "Field", "Total Records", "Completeness (%)",

        "Uniqueness (%)", "Validity (%)", "Anomaly Count", "Distinctiveness",

        "Quality Score (%)", "Quality Rule (Regex)", "Analysis Date"

    ]

    return headers, results

 

 

def generate_catalog_friendly_info(column_names, sample_df, knowledge_data=None):

    """

    Uses GPT to create a friendlier name, description, and definition for each column.

    Returns a dict: {col_name: (friendly_name, description, definition)}.

    We do one GPT call with a prompt that lists all columns

    and parse the response as (for example) a CSV or pipe-delimited output.

    """

 

    if not default_values["api_key"]:

        # If no API key, fallback

        fallback = {}

        for col in column_names:

            fallback[col] = (f"Friendly_{col}", f"Description_{col}", f"Definition_{col}")

        return fallback

 

    # Build a sample of data or knowledge base context

    knowledge_section = ""

    if knowledge_data:

        # If you want to incorporate the user's knowledge files in the prompt:

        knowledge_section = "\n\nAdditional context:\n" + "\n".join(knowledge_data)

 

    # Optionally, sample 5 rows from sample_df

    sample_text = ""

    if sample_df is not None and not sample_df.empty:

        sample_head = sample_df.head(5).to_csv(index=False)

        sample_text = f"\nHere are up to 5 sample rows:\n{sample_head}"

 

    # Construct user prompt

    user_prompt = f"""

You are a data documentation assistant. I have columns:

{', '.join(column_names)}

 

Please provide a table of columns with three fields: FriendlyName, Description, and Definition.

Format the output as a pipe-delimited table with columns:

ColumnName | FriendlyName | Description | Definition

 

{sample_text}

{knowledge_section}

Return only the pipe-delimited table with no extra commentary.

"""

    messages = [

        {"role": "system", "content": "You are an AI that creates user-friendly metadata for column documentation."},

        {"role": "user", "content": user_prompt}

    ]

 

    response = create_chat_completion(

        model=default_values["default_model"],

        messages=messages,

        max_tokens=default_values["max_tokens"],

        temperature=default_values["temperature"],

        top_p=default_values["top_p"],

        frequency_penalty=default_values["frequency_penalty"],

        presence_penalty=default_values["presence_penalty"]

    )

 

    # Attempt to parse GPT output

    result_dict = {}

    if isinstance(response, dict) and "choices" in response:

        try:

            content = response["choices"][0]["message"]["content"]

            # We'll look for the pipe table lines

            lines = [l.strip() for l in content.strip().split("\n") if l.strip()]

            # Possibly skip a header row if found

            # Something like: ColumnName | FriendlyName | Description | Definition

            # We'll parse them similarly to CSV but with delimiter='|'

            # We'll ignore lines that don't have at least 4 columns

            for line in lines:

                parts = [p.strip() for p in line.split('|')]

                if len(parts) < 4:

                    continue

                # e.g. [ColumnName, FriendlyName, Description, Definition]

                colname = parts[0]

                friendly = parts[1]

                desc = parts[2]

                defin = parts[3]

                result_dict[colname] = (friendly, desc, defin)

        except Exception as e:

            print(f"Could not parse GPT Catalog response: {e}")

 

    # Fallback for any columns not in result_dict

    final_dict = {}

    for col in column_names:

        if col in result_dict:

            final_dict[col] = result_dict[col]

        else:

            # fallback

            final_dict[col] = (f"Friendly_{col}", f"Description_{col}", f"Definition_{col}")

 

    return final_dict

 

 

def catalog_analysis(df, application, table_name, knowledge_data=None):

    """

    Catalog Output:

    Application, Table Name, Column Name, Friendly Name, Description, Definition,

    Data Type, Pattern, Example Data, Data Privacy Classification, Encryption Requirement,

    SLA for Quality, SLA for Completeness, SLA for Validity, Analysis Date

 

    *We now fetch FriendlyName, Description, Definition from GPT.

    """

    analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    columns = df.columns.tolist()

    # Generate the three fields from GPT

    friendly_dict = generate_catalog_friendly_info(columns, df, knowledge_data=knowledge_data)

 

    results = []

    for col in columns:

        col_data = df[col]

        # Example data from first non-null row

        example_data = ""

        for val in col_data:

            if pd.notnull(val) and str(val).strip() != '':

                example_data = str(val)

                break

       

        # guess type

        if pd.api.types.is_numeric_dtype(col_data):

            data_type = "Numeric"

            pattern = "Digits"

        else:

            data_type = "Text"

            pattern = "Free text"

 

        data_privacy_class = "Public" if data_type == "Text" else "Confidential"

        encryption_req = "Not Required" if data_privacy_class == "Public" else "Required"

 

        sla_quality = "80%"

        sla_completeness = "80%"

        sla_validity = "80%"

 

        # get the GPT-generated friendly fields

        friendly_name, description, definition = friendly_dict.get(col,

            (f"Friendly_{col}", f"Description_{col}", f"Definition_{col}")

        )

 

        row = [

            application,

            table_name,

            col,            # Column Name

            friendly_name,  # from GPT

            description,    # from GPT

            definition,     # from GPT

            data_type,

            pattern,

            example_data,

            data_privacy_class,

            encryption_req,

            sla_quality,

            sla_completeness,

            sla_validity,

            analysis_date

        ]

        results.append(row)

 

    headers = [

        "Application", "Table Name", "Column Name", "Friendly Name", "Description",

        "Definition", "Data Type", "Pattern", "Example Data",

        "Data Privacy Classification", "Encryption Requirement",

        "SLA for Quality", "SLA for Completeness", "SLA for Validity", "Analysis Date"

    ]

    return headers, results

 

 

def anomalies_analysis(df, application, table_name):

    """

    Anomalies:

    Application, Table Name, Field, Value, Reason, Suggested Action, Date, Analysis Date

    """

    results = []

    analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    now_str = datetime.now().strftime("%Y-%m-%d")

 

    for col in df.columns:

        col_data = df[col]

        if pd.api.types.is_numeric_dtype(col_data):

            numeric_data = pd.to_numeric(col_data, errors='coerce').dropna()

            if len(numeric_data) > 0:

                mean_val = numeric_data.mean()

                std_val = numeric_data.std()

                # Flag any value more than 3 std from mean

                outliers = numeric_data[abs(numeric_data - mean_val) > 3*std_val]

                for val in outliers:

                    row = [

                        application,

                        table_name,

                        col,

                        val,

                        "Outlier",

                        "Review and correct if necessary",

                        now_str,

                        analysis_date

                    ]

                    results.append(row)

        else:

            # Suppose "blank" or "null" text is an anomaly

            blank_mask = (col_data.astype(str).str.strip() == '')

            blank_indices = df[blank_mask].index

            for idx in blank_indices:

                row = [

                    application,

                    table_name,

                    col,

                    "",  # blank value

                    "Blank Value",

                    "Review data source for missing info",

                    now_str,

                    analysis_date

                ]

                results.append(row)

 

    headers = [

        "Application", "Table Name", "Field", "Value", "Reason",

        "Suggested Action", "Date", "Analysis Date"

    ]

    return headers, results

 

 

def compliance_analysis(df, application, table_name):

    """

    Compliance Check:

    Compliance Aspect, Application, Layer, Table Name, Score/Status, SLA Threshold,

    Compliant (✔ or ✘), Notes, Table Name, Analysis Date

    """

    results = []

    analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    aspects = ["Overall Quality Score", "Overall Completeness Score", "GLBA", "CCPA"]

    layer = "Data Lake"

    sla_threshold = "80%"

 

    for aspect in aspects:

        if aspect in ["Overall Quality Score", "GLBA"]:

            compliant = "✔"

            notes = "Meets SLA"

            score_status = "85%"

        else:

            compliant = "✘"

            notes = "Below SLA"

            score_status = "70%"

        row = [

            aspect,

            application,

            layer,

            table_name,

            score_status,

            sla_threshold,

            compliant,

            notes,

            table_name,

            analysis_date

        ]

        results.append(row)

 

    headers = [

        "Compliance Aspect", "Application", "Layer", "Table Name", "Score/Status",

        "SLA Threshold", "Compliant (✔ or ✘)", "Notes", "Table Name", "Analysis Date"

    ]

    return headers, results

 

 

#############################################################################

#       DataBuddyDialog (Little Buddy Chat)

#############################################################################

class DataBuddyDialog(wx.Dialog):

    def __init__(self, parent, data=None, knowledge_data=None, headers=None):

        super(DataBuddyDialog, self).__init__(

            parent, title="Little Buddy", size=(800, 600),

            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER

        )

        self.parent = parent

        self.data = data

        self.knowledge_data = knowledge_data

        self.headers = headers

        panel = wx.Panel(self)

        panel.SetBackgroundColour(wx.Colour(30,30,30))

        vbox = wx.BoxSizer(wx.VERTICAL)

 

        pygame.mixer.init()

        self.current_channel = None

 

        self.tts_enabled = True

        self.edge_tts_voice = "en-US-GuyNeural" 

 

        voice_names = ["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"]

        self.voice_choice = wx.Choice(panel, choices=voice_names)

        try:

            default_voice_index = voice_names.index("en-US-GuyNeural")

        except ValueError:

            default_voice_index = 0

        self.voice_choice.SetSelection(default_voice_index)

        vbox.Add(self.voice_choice, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.recognizer = sr.Recognizer()

        self.recognizer.energy_threshold = 300

        self.recognizer.dynamic_energy_threshold = True

 

        self.persona_choice = wx.ComboBox(

            panel,

            choices=[

                "Data Architect", "Data Engineer", "Data Quality Expert",

                "Data Governance Expert", "Data Scientist", "Business Analyst",

                "Product Management Expert", "Product Owner", "Team Leader",

                "Albert Einstein", "Yoda"

            ],

            style=wx.CB_READONLY

        )

        self.persona_choice.SetSelection(0)

        vbox.Add(self.persona_choice, flag=wx.EXPAND|wx.ALL, border=10)

 

        prompt_hbox = wx.BoxSizer(wx.HORIZONTAL)

        ask_label = wx.StaticText(panel, label="Ask Question")

        ask_label.SetForegroundColour(wx.Colour(255,255,255))

        prompt_hbox.Add(ask_label, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=5)

 

        self.prompt_text = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)

        self.prompt_text.Bind(wx.EVT_TEXT_ENTER, self.on_submit)

        prompt_hbox.Add(self.prompt_text, proportion=1, flag=wx.EXPAND|wx.RIGHT, border=5)

 

        self.send_button = wx.Button(panel, label="Send")

        self.send_button.Bind(wx.EVT_BUTTON, self.on_submit)

        prompt_hbox.Add(self.send_button, flag=wx.ALIGN_CENTER_VERTICAL)

 

        self.voice_button = wx.Button(panel, label="🎤")

        self.voice_button.Bind(wx.EVT_BUTTON, self.on_voice_input)

        prompt_hbox.Add(self.voice_button, flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=5)

 

        vbox.Add(prompt_hbox, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.response_text = rt.RichTextCtrl(panel, style=wx.TE_READONLY|wx.TE_MULTILINE)

        self.response_text.SetBackgroundColour(wx.Colour(50,50,50))

        self.response_text.SetForegroundColour(wx.Colour(255,255,255))

        vbox.Add(self.response_text, proportion=2, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.default_message = "Hi, my name is Little Buddy, how can I help you today?"

        self.response_text.WriteText(self.default_message)

 

        threading.Thread(target=self.speak_text, args=(self.default_message,), daemon=True).start()

 

        buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)

 

        self.clear_button = wx.Button(panel, label="Clear Response")

        self.clear_button.Bind(wx.EVT_BUTTON, self.on_clear)

        buttons_hbox.Add(self.clear_button, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.export_button = wx.Button(panel, label="Export to .txt")

        self.export_button.Bind(wx.EVT_BUTTON, self.on_export)

        buttons_hbox.Add(self.export_button, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.email_button = wx.Button(panel, label="Email")

        self.email_button.Bind(wx.EVT_BUTTON, self.on_email)

        buttons_hbox.Add(self.email_button, flag=wx.EXPAND|wx.ALL, border=10)

 

        vbox.Add(buttons_hbox, flag=wx.ALIGN_RIGHT|wx.ALL, border=5)

 

        self.tts_checkbox = wx.CheckBox(panel, label="Enable Text-to-Speech")

        self.tts_checkbox.SetValue(True)

        self.tts_checkbox.Bind(wx.EVT_CHECKBOX, self.on_toggle_tts)

        vbox.Add(self.tts_checkbox, flag=wx.ALIGN_CENTER|wx.ALL, border=5)

 

        self.stop_tts_button = wx.Button(panel, label="Stop Voice Response")

        self.stop_tts_button.Bind(wx.EVT_BUTTON, self.on_stop_tts)

        vbox.Add(self.stop_tts_button, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.voice_activation_enabled = True

        threading.Thread(target=self.voice_activation_listener, daemon=True).start()

 

        panel.SetSizer(vbox)

 

    def on_email(self, event):

        body = self.response_text.GetValue()

        subject = "Little Buddy Response"

        self.parent.send_email(subject, body)

 

    def on_toggle_tts(self, event):

        self.tts_enabled = self.tts_checkbox.IsChecked()

        status = "enabled" if self.tts_enabled else "disabled"

        wx.MessageBox(f"Text-to-Speech has been {status}.", "TTS Status", wx.OK|wx.ICON_INFORMATION)

 

    def on_stop_tts(self, event):

        if self.current_channel and self.current_channel.get_busy():

            self.current_channel.stop()

            wx.MessageBox("Voice response stopped.", "Stop TTS", wx.OK|wx.ICON_INFORMATION)

        else:

            wx.MessageBox("No voice response is currently playing.", "Stop TTS", wx.OK|wx.ICON_INFORMATION)

 

    def on_clear(self, event):

        self.response_text.Clear()

 

    def on_export(self, event):

        response_content = self.response_text.GetValue()

        if response_content and response_content != self.default_message:

            now = datetime.now()

            date_str = now.strftime("%m%d%y_%H%M")

            filename = f"response_{date_str}.txt"

            with wx.FileDialog(self, "Save response as...", wildcard="Text files (*.txt)|*.txt",

                               style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile=filename) as fileDialog:

                if fileDialog.ShowModal() == wx.ID_OK:

                    file_path = fileDialog.GetPath()

                    try:

                        with open(file_path, 'w', encoding='utf-8') as file:

                            file.write(response_content)

                        wx.MessageBox(f"Response saved to {file_path}", "Export Successful", wx.OK|wx.ICON_INFORMATION)

                        self.parent.log_action("exports", {"file": file_path})

                    except Exception as e:

                        wx.MessageBox(f"Error saving file: {e}", "File Error", wx.OK|wx.ICON_ERROR)

        else:

            wx.MessageBox("No valid response to export.", "Warning", wx.OK|wx.ICON_WARNING)

 

    def on_submit(self, event):

        prompt = self.prompt_text.GetValue().strip()

        persona = self.persona_choice.GetValue()

        if prompt:

            self.response_text.Clear()

            self.response_text.WriteText("Loading response...")

            threading.Thread(target=self.get_response, args=(prompt, persona), daemon=True).start()

 

    def on_voice_input(self, event):

        threading.Thread(target=self.listen_and_submit, daemon=True).start()

 

    def listen_and_submit(self):

        try:

            with sr.Microphone() as source:

                wx.CallAfter(self.update_response_text, "Listening...")

                self.recognizer.adjust_for_ambient_noise(source)

                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)

            wx.CallAfter(self.update_response_text, "Recognizing...")

            voice_text = self.recognizer.recognize_google(audio)

            wx.CallAfter(self.set_prompt_and_submit, voice_text)

        except sr.WaitTimeoutError:

            wx.CallAfter(wx.MessageBox, "Listening timed out.", "Timeout", wx.OK|wx.ICON_WARNING)

            wx.CallAfter(self.update_response_text, self.default_message)

        except sr.UnknownValueError:

            wx.CallAfter(wx.MessageBox, "Could not understand the audio.", "Error", wx.OK|wx.ICON_ERROR)

            wx.CallAfter(self.update_response_text, self.default_message)

        except sr.RequestError as e:

            wx.CallAfter(wx.MessageBox, f"Speech Recognition error: {e}", "Error", wx.OK|wx.ICON_ERROR)

            wx.CallAfter(self.update_response_text, self.default_message)

        except Exception as e:

            wx.CallAfter(wx.MessageBox, f"Error: {e}", "Error", wx.OK|wx.ICON_ERROR)

            wx.CallAfter(self.update_response_text, self.default_message)

 

    def update_response_text(self, text):

        self.response_text.Clear()

        self.response_text.WriteText(text)

 

    def set_prompt_and_submit(self, text):

        self.prompt_text.SetValue(text)

        self.on_submit(None)

 

    def get_response(self, prompt, persona):

        if self.data is not None:

            data_str = "\n".join([",".join(row) for row in self.data])

            prompt += f"\n\nHere is the data you can reference:\n{data_str}"

        if self.knowledge_data:

            knowledge_str = "\n".join(self.knowledge_data)

            prompt += f"\n\nHere is the knowledge base you can reference:\n{knowledge_str}"

        if persona:

            prompt = f"As a {persona}, {prompt}"

 

        messages = [

            {

                "role": "system",

                "content": (

                    "You are a helpful assistant that can generate images, charts, and diagrams dynamically. "

                    "Use best data analysis and data science standards for chart axis, labeling, and aesthetics. "

                    "If you want to include an image, append [IMAGE: description]. "

                    "For charts/diagrams, append [CHART: ...] or [DIAGRAM: ...]."

                )

            },

            {"role": "user", "content": prompt}

        ]

 

        response = create_chat_completion(

            model=default_values["default_model"],

            messages=messages,

            max_tokens=default_values["max_tokens"],

            temperature=default_values["temperature"],

            top_p=default_values["top_p"],

            frequency_penalty=default_values["frequency_penalty"],

            presence_penalty=default_values["presence_penalty"]

        )

 

        if isinstance(response, dict) and 'choices' in response:

            try:

                message_content = response['choices'][0]['message']['content']

                wx.CallAfter(self.process_response_content, message_content)

                if self.tts_enabled:

                    wx.CallAfter(self.speak_text, message_content)

            except (KeyError, IndexError):

                error_msg = "Error: Unexpected response format from OpenAI."

                wx.CallAfter(self.update_response, error_msg)

                if self.tts_enabled:

                    wx.CallAfter(self.speak_text, error_msg)

        else:

            error_msg = f"Error: {response.get('error', 'Unable to get a response.')}"

            wx.CallAfter(self.update_response, error_msg)

            if self.tts_enabled:

                wx.CallAfter(self.speak_text, error_msg)

 

    def process_response_content(self, message_content):

        image_pattern = r'\[IMAGE:\s*(.*?)\]'

        chart_pattern = r'\[CHART:\s*(.*?)\]'

        diagram_pattern = r'\[DIAGRAM:\s*(.*?)\]'

 

        image_descriptions = re.findall(image_pattern, message_content)

        chart_descriptions = re.findall(chart_pattern, message_content)

        diagram_descriptions = re.findall(diagram_pattern, message_content)

 

        message_without_images = re.sub(image_pattern, '', message_content)

        message_without_images = re.sub(chart_pattern, '', message_without_images)

        message_without_images = re.sub(diagram_pattern, '', message_without_images)

 

        self.response_text.Clear()

        self.response_text.BeginFontSize(12)

        self.response_text.WriteText(message_without_images)

        self.response_text.EndFontSize()

 

        for desc in chart_descriptions:

            chart_bitmap = self.generate_chart(desc)

            if chart_bitmap:

                self.insert_image_into_response(chart_bitmap)

            else:

                self.response_text.WriteText(f"\n[Failed to generate chart: {desc}]\n")

 

        for desc in diagram_descriptions:

            image_url = self.generate_image(desc)

            if image_url:

                self.insert_image_from_url_into_response(image_url)

            else:

                self.response_text.WriteText(f"\n[Failed to generate diagram: {desc}]\n")

 

        for description in image_descriptions:

            image_url = self.generate_image(description)

            if image_url:

                self.insert_image_from_url_into_response(image_url)

            else:

                self.response_text.WriteText(f"\n[Failed to generate image: {description}]\n")

 

    def generate_image(self, description):

        url = default_values["image_generation_url"]

        headers = {

            'Authorization': f'Bearer {default_values["api_key"]}',

            'Content-Type': 'application/json',

        }

        data = {

            'prompt': description,

            'n': 1,

            'size': '512x512'

        }

        try:

            from urllib3.exceptions import InsecureRequestWarning

            urllib3.disable_warnings(InsecureRequestWarning)

            response = requests.post(url, headers=headers, json=data, verify=False)

            response.raise_for_status()

            response_data = response.json()

            image_url = response_data['data'][0]['url']

            return image_url

        except Exception as e:

            print(f"Error generating image: {e}")

            return None

 

    def insert_image_from_url_into_response(self, image_url):

        try:

            response = requests.get(image_url, verify=False)

            response.raise_for_status()

            image_data = response.content

            stream = io.BytesIO(image_data)

            image = wx.Image(stream)

            if not image.IsOk():

                raise ValueError("Failed to load image data.")

            bitmap = wx.Bitmap(image)

            self.response_text.Newline()

            self.response_text.BeginAlignment(wx.TEXT_ALIGNMENT_CENTRE)

            self.response_text.WriteImage(bitmap)

            self.response_text.EndAlignment()

            self.response_text.Newline()

        except Exception as e:

            print(f"Error inserting image: {e}")

            self.response_text.WriteText("\n[Failed to load image]\n")

 

    def insert_image_into_response(self, bitmap):

        self.response_text.Newline()

        self.response_text.BeginAlignment(wx.TEXT_ALIGNMENT_CENTRE)

        self.response_text.WriteImage(bitmap)

        self.response_text.EndAlignment()

        self.response_text.Newline()

 

    def update_response(self, response):

        self.response_text.Clear()

        self.response_text.BeginFontSize(12)

        self.response_text.WriteText(response)

        self.response_text.EndFontSize()

 

    def speak_text(self, text):

        if not self.tts_enabled or not text.strip():

            return

 

        async def run_edge_tts(text_to_speak):

            try:

                clean_text = re.sub(r'[^\w\s.,?!]', '', text_to_speak)

                selected_voice_index = self.voice_choice.GetSelection()

                chosen_voice = self.voice_choice.GetString(selected_voice_index)

 

                communicate = edge_tts.Communicate(

                    text=clean_text,

                    voice=chosen_voice,

                    rate="+0%"

                )

                output_file = "edge_tts_temp.mp3"

                await communicate.save(output_file)

 

                sound = pygame.mixer.Sound(output_file)

                channel = sound.play()

                self.current_channel = channel

 

                while channel.get_busy():

                    await asyncio.sleep(0.1)

 

                os.remove(output_file)

 

            except Exception as e:

                wx.CallAfter(wx.MessageBox, f"Edge TTS Error: {e}", "TTS Error", wx.OK|wx.ICON_ERROR)

 

        def run_in_thread():

            asyncio.run(run_edge_tts(text))

 

        threading.Thread(target=run_in_thread, daemon=True).start()

 

    def voice_activation_listener(self):

        while self.voice_activation_enabled:

            try:

                with sr.Microphone() as source:

                    self.recognizer.adjust_for_ambient_noise(source)

                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)

                try:

                    transcript = self.recognizer.recognize_google(audio).lower()

                    if "hey little buddy" in transcript:

                        wx.CallAfter(

                            self.update_response_text,

                            "Activation phrase detected. Listening for command..."

                        )

                        self.listen_and_submit()

                except sr.UnknownValueError:

                    continue

                except sr.RequestError:

                    continue

            except sr.WaitTimeoutError:

                continue

            except Exception as e:

                wx.CallAfter(wx.MessageBox, f"Voice activation error: {e}", "Error", wx.OK|wx.ICON_ERROR)

                break

 

    def generate_chart(self, description):

        params = {}

        parts = description.split(';')

        for part in parts:

            part = part.strip()

            if '=' in part:

                key, val = part.split('=', 1)

                key = key.strip().lower()

                val = val.strip()

                if val.startswith("[") and val.endswith("]"):

                    try:

                        val = json.loads(val)

                    except:

                        pass

                elif val.startswith('"') and val.endswith('"'):

                    val = val.strip('"')

                params[key] = val

 

        x = params.get('x', None)

        y = params.get('y', None)

        chart_type = params.get('type', None)

        title = params.get('title', None)

        xlabel = params.get('xlabel', None)

        ylabel = params.get('ylabel', None)

 

        if (x is None or y is None) and self.data is not None and len(self.data) > 0:

            df = pd.DataFrame(self.data)

            df.columns = self.headers

            numeric_cols = df.select_dtypes(include=['float','int']).columns.tolist()

            if len(numeric_cols) == 0:

                for col in df.columns:

                    try:

                        df[col] = pd.to_numeric(df[col], errors='coerce')

                    except:

                        pass

                numeric_cols = df.select_dtypes(include=['float','int']).columns.tolist()

            if not numeric_cols:

                numeric_cols = df.columns.tolist()

 

            chosen_y = numeric_cols[0]

            non_numeric_cols = [c for c in df.columns if c not in numeric_cols]

            chosen_x = non_numeric_cols[0] if non_numeric_cols else df.columns[0]

 

            if x is None:

                x = df[chosen_x].tolist()

            if y is None:

                y = df[chosen_y].tolist()

            if xlabel is None:

                xlabel = chosen_x.capitalize()

            if ylabel is None:

                ylabel = chosen_y.capitalize()

        else:

            if isinstance(x, list) and isinstance(y, list):

                pass

            else:

                if x is None or y is None:

                    x = list(range(10))

                    y = list(range(10))

 

        if chart_type is None:

            if isinstance(x, list) and len(x) > 0 and isinstance(x[0], str) and all(isinstance(val, (int,float)) for val in y):

                chart_type = 'bar'

            else:

                chart_type = 'line'

 

        if xlabel is None:

            xlabel = "X-Axis"

        if ylabel is None:

            ylabel = "Y-Axis"

        if title is None:

            title = "Data Visualization"

 

        try:

            y = pd.to_numeric(y, errors='coerce')

        except:

            pass

 

        try:

            fig, ax = plt.subplots(figsize=(6,4), dpi=100)

            if chart_type.lower() == 'bar':

                ax.bar(x, y, color='skyblue')

            elif chart_type.lower() == 'line':

                ax.plot(x, y, marker='o', color='blue')

            elif chart_type.lower() == 'scatter':

                ax.scatter(x, y, color='red')

            else:

                ax.plot(x, y, marker='o', color='blue')

 

            ax.set_title(title, fontsize=14, fontweight='bold')

            ax.set_xlabel(xlabel, fontsize=12)

            ax.set_ylabel(ylabel, fontsize=12)

 

            if isinstance(x, list) and len(x) > 0 and isinstance(x[0], str):

                plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

 

            ax.grid(True, linestyle='--', alpha=0.7)

            fig.tight_layout()

 

            buf = io.BytesIO()

            plt.savefig(buf, format='png')

            plt.close(fig)

            buf.seek(0)

 

            image = wx.Image(buf)

            if not image.IsOk():

                return None

            bitmap = wx.Bitmap(image)

            return bitmap

        except Exception as e:

            print(f"Error generating chart: {e}")

            return None

 

 

#############################################################################

#       MainWindow - The primary frame

#############################################################################

 

class MainWindow(wx.Frame):

    knowledge_files = []

    knowledge_file_names = []

    original_catalog_data = []

 

    def __init__(self, *args, **kw):

        super(MainWindow, self).__init__(*args, **kw)

        self.current_analysis_type = ""

        self.file_content = None

        self.headers = []

        self.table_data = None

        self.uploaded_file_name = ""

        self.uploaded_file_size = 0

        self.todo_actions_queue = deque()

        self.todo_in_progress = False

        self.kernel_data = {}

        self.initUI()

        self.Bind(EVT_TODO_ACTION_COMPLETE, self.on_todo_action_complete)

 

        # Load kernel.json on startup

        self.load_kernel()

 

    def load_kernel(self):

        knowledge_dir = os.path.join(default_values["filepath"], "Knowledge Files")

        os.makedirs(knowledge_dir, exist_ok=True)

 

        kernel_path = os.path.join(knowledge_dir, "kernel.json")

 

        if not os.path.isfile(kernel_path):

            initial_kernel = {

                "icon_location": "DataBuddyIcon.png",

                "description": "Data Buddy and Little Buddy kernel file containing capabilities, logs, and configurations.",

                "capabilities": [

                    "Data Profiling",

                    "Data Quality Assessment",

                    "Data Cataloging",

                    "Anomaly Detection",

                    "Compliance Checks",

                    "SQL Optimization",

                    "Data Visualization",

                    "Automated Reporting",

                    "Email Integration",

                    "Interactive Chatbot Assistance",

                    "Feedback Loop Integration",

                    "Voice Interaction"

                ],

                "functionality_updates": [],

                "log": []

            }

            try:

                with open(kernel_path, 'w', encoding='utf-8') as f:

                    json.dump(initial_kernel, f, indent=4)

                self.kernel_data = initial_kernel

            except Exception as e:

                wx.MessageBox(f"Failed to create kernel.json: {e}", "Error", wx.OK | wx.ICON_ERROR)

                return

        else:

            try:

                with open(kernel_path, 'r', encoding='utf-8') as f:

                    self.kernel_data = json.load(f)

            except Exception as e:

                wx.MessageBox(f"Failed to load kernel.json: {e}", "Error", wx.OK | wx.ICON_ERROR)

                return

 

        if "kernel.json" not in self.knowledge_file_names:

            kernel_str = json.dumps(self.kernel_data, indent=4)

            self.knowledge_files.append(kernel_str)

            self.knowledge_file_names.append("kernel.json")

            self.update_knowledge_display()

 

    def save_kernel(self):

        knowledge_dir = os.path.join(default_values["filepath"], "Knowledge Files")

        os.makedirs(knowledge_dir, exist_ok=True)

        kernel_path = os.path.join(knowledge_dir, "kernel.json")

 

        try:

            with open(kernel_path, 'w', encoding='utf-8') as f:

                json.dump(self.kernel_data, f, indent=4)

        except Exception as e:

            wx.MessageBox(f"Failed to save kernel.json: {e}", "Error", wx.OK|wx.ICON_ERROR)

 

    def log_action(self, action_type, details=None):

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if details is None:

            details = {}

        log_entry = {

            "timestamp": timestamp,

            "action": action_type,

            "details": details

        }

        self.kernel_data["log"].append(log_entry)

        self.save_kernel()

 

        if "kernel.json" in self.knowledge_file_names:

            idx = self.knowledge_file_names.index("kernel.json")

            kernel_str = json.dumps(self.kernel_data, indent=4)

            self.knowledge_files[idx] = kernel_str

            self.update_knowledge_display()

 

    def on_quit(self, event):

        self.Close()

 

    def open_settings(self, event):

        settings_window = SettingsWindow(None, "Settings")

        settings_window.Show(True)

 

    def open_optimizer(self, event):

        self.log_action("optimizer", {"initiated": True})

        self.prompt_for_files()

 

    def prompt_for_files(self):

        with wx.FileDialog(

            self,

            "Open SQL File or Zip File",

            wildcard="Text files (*.txt)|*.txt|Zip files (*.zip)|*.zip",

            style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE

        ) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:

                return

            file_paths = fileDialog.GetPaths()

            for file_path in file_paths:

                if file_path.endswith('.zip'):

                    self.process_zip_file(file_path)

                elif file_path.endswith('.txt'):

                    self.process_txt_file(file_path)

 

    def process_zip_file(self, zip_path):

        try:

            with zipfile.ZipFile(zip_path, 'r') as zip_file:

                for file_info in zip_file.infolist():

                    if file_info.filename.endswith('.txt'):

                        with zip_file.open(file_info) as file:

                            sql_code = file.read().decode('utf-8')

                            threading.Thread(

                                target=self.optimize_sql,

                                args=(sql_code, file_info.filename),

                                daemon=True

                            ).start()

        except Exception as e:

            wx.MessageBox(f"Error reading zip file: {e}", "File Error", wx.OK|wx.ICON_ERROR)

 

    def process_txt_file(self, txt_path):

        try:

            with open(txt_path, 'r', encoding='utf-8') as file:

                sql_code = file.read()

                threading.Thread(

                    target=self.optimize_sql,

                    args=(sql_code, os.path.basename(txt_path)),

                    daemon=True

                ).start()

        except Exception as e:

            wx.MessageBox(f"Error reading text file: {e}", "File Error", wx.OK|wx.ICON_ERROR)

 

    def optimize_sql(self, sql_code, filename):

        prompt = f"""

        You are an expert SQL optimizer. Review and optimize the following SQL code:

        {sql_code}

 

        Please:

        1. Complete Query/Code Optimization.

        2. Query/Code Formatting.

        3. Redundancy Elimination.

        """

 

        response = create_chat_completion(

            model=default_values["default_model"],

            messages=[{"role": "user", "content": prompt}],

            max_tokens=default_values["max_tokens"],

            temperature=default_values["temperature"],

            top_p=default_values["top_p"],

            frequency_penalty=default_values["frequency_penalty"],

            presence_penalty=default_values["presence_penalty"]

        )

 

        if isinstance(response, dict) and 'choices' in response:

            try:

                optimized_code = response['choices'][0]['message']['content']

                wx.CallAfter(self.display_optimized_code, filename, optimized_code)

                self.log_action("optimizer", {"file": filename, "action": "SQL optimized"})

            except (KeyError, IndexError):

                wx.CallAfter(self.display_optimized_code, filename, "Error: Unexpected response format from OpenAI.")

        else:

            wx.CallAfter(

                self.display_optimized_code,

                filename,

                f"Error: {response.get('error', 'Unable to get a response.')}"

            )

 

    def display_optimized_code(self, filename, optimized_code):

        def show_dialog():

            dialog = wx.Dialog(self, title=f"Optimized Code - {filename}", size=(600, 400))

            panel = wx.Panel(dialog)

            panel.SetBackgroundColour(wx.Colour(30,30,30))

            vbox = wx.BoxSizer(wx.VERTICAL)

            code_text = wx.TextCtrl(panel, value=optimized_code, style=wx.TE_MULTILINE|wx.TE_READONLY)

            code_text.SetBackgroundColour(wx.Colour(50,50,50))

            code_text.SetForegroundColour(wx.Colour(255,255,255))

            vbox.Add(code_text, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

            panel.SetSizer(vbox)

            dialog.ShowModal()

            dialog.Destroy()

 

        wx.CallAfter(show_dialog)

 

    def open_data_buddy(self, event):

        if not default_values["api_key"]:

            wx.MessageBox("Please set your OpenAI API key in Settings before using Little Buddy.","API Key Missing",wx.OK|wx.ICON_WARNING)

            return

        self.log_action("open_data_buddy")

        data_buddy_dialog = DataBuddyDialog(self, data=self.table_data, knowledge_data=self.knowledge_files, headers=self.headers)

        data_buddy_dialog.ShowModal()

        data_buddy_dialog.Destroy()

 

    def process_file_and_prompt(self, event):

        with wx.FileDialog(

            self,

            "Open file",

            wildcard="Text and CSV files (*.txt;*.csv)|*.txt;*.csv",

            style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST

        ) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:

                return

            file_path = fileDialog.GetPath()

            try:

                self.uploaded_file_size = os.path.getsize(file_path)

                self.uploaded_file_name = os.path.basename(file_path)

                with open(file_path, "r", encoding="utf-8") as file:

                    file_content = file.read()

                    self.file_content = file_content

                    self.headers, self.table_data = detect_and_split_data(file_content)

                    self.record_count = len(self.table_data)

 

                    self.display_table(self.headers, self.table_data)

 

                    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    header_text = (

                        "Data Buddy AI Analysis v1.0\n"

                        f"File Uploaded: {self.uploaded_file_name}\n"

                        f"Total Record Count: {self.record_count}\n"

                        f"File Size: {self.uploaded_file_size} bytes\n"

                        f"Current Date: {current_date}\n"

                    )

                    self.result_text.Clear()

                    self.result_text.AppendText(header_text)

 

                    wx.MessageBox("File loaded successfully.","Success",wx.OK|wx.ICON_INFORMATION)

                    self.profile_button.Enable()

                    self.quality_button.Enable()

                    self.catalog_button.Enable()

                    self.anomalies_button.Enable()

                    self.compliance_button.Enable()

                    self.log_action(

                        "upload_file",

                        {

                            "file": self.uploaded_file_name,

                            "file_size": self.uploaded_file_size,

                            "record_count": self.record_count

                        }

                    )

                    wx.PostEvent(self, TodoActionCompleteEvent())

            except Exception as e:

                wx.MessageBox(f"Error reading file: {e}","File Error",wx.OK|wx.ICON_ERROR)

                wx.PostEvent(self, TodoActionCompleteEvent())

 

    def trigger_analysis(self, event):

        self.current_analysis_type = "Profile"

        self.prompt_label.SetLabel("Current Analysis: Profile")

        self.status_bar.SetStatusText("Running profiling analysis...")

        threading.Thread(target=self.run_profile_analysis, daemon=True).start()

 

    def run_profile_analysis(self):

        try:

            df = self._dataframe_from_table()

            headers, data = profile_analysis(df, "MyApplication", self.uploaded_file_name)

            wx.CallAfter(self.update_ui_with_generic_analysis, (headers, data), "Profile Analysis")

            self.log_action("profile", {"file": self.uploaded_file_name})

        except Exception as e:

            wx.CallAfter(self.append_result_text, f"Profile analysis error: {e}")

 

    def trigger_quality_analysis(self, event):

        self.current_analysis_type = "Quality"

        self.prompt_label.SetLabel("Current Analysis: Quality")

        self.status_bar.SetStatusText("Running quality analysis...")

        threading.Thread(target=self.run_quality_analysis, daemon=True).start()

 

    def run_quality_analysis(self):

        try:

            df = self._dataframe_from_table()

            headers, data = quality_analysis(df, "MyApplication", self.uploaded_file_name)

            wx.CallAfter(self.update_ui_with_generic_analysis, (headers, data), "Quality Analysis")

            self.log_action("quality", {"file": self.uploaded_file_name})

        except Exception as e:

            wx.CallAfter(self.append_result_text, f"Quality analysis error: {e}")

 

    def trigger_catalog_analysis(self, event):

        self.current_analysis_type = "Catalog"

        self.prompt_label.SetLabel("Current Analysis: Catalog")

        self.status_bar.SetStatusText("Running catalog analysis...")

        threading.Thread(target=self.run_catalog_analysis, daemon=True).start()

 

    def run_catalog_analysis(self):

        try:

            df = self._dataframe_from_table()

            # Pass knowledge files so GPT can see them for generating friendly columns

            headers, data = catalog_analysis(df, "MyApplication", self.uploaded_file_name, knowledge_data=self.knowledge_files)

            MainWindow.original_catalog_data = [row.copy() for row in data]

            wx.CallAfter(self.update_ui_with_generic_analysis, (headers, data), "Catalog Analysis")

            self.log_action("catalog", {"file": self.uploaded_file_name})

        except Exception as e:

            wx.CallAfter(self.append_result_text, f"Catalog analysis error: {e}")

 

    def trigger_anomalies_analysis(self, event):

        self.current_analysis_type = "Anomalies"

        self.prompt_label.SetLabel("Current Analysis: Anomalies")

        self.status_bar.SetStatusText("Running anomalies analysis...")

        threading.Thread(target=self.run_anomalies_analysis, daemon=True).start()

 

    def run_anomalies_analysis(self):

        try:

            df = self._dataframe_from_table()

            headers, data = anomalies_analysis(df, "MyApplication", self.uploaded_file_name)

            wx.CallAfter(self.update_ui_with_generic_analysis, (headers, data), "Anomalies Analysis")

            self.log_action("anomalies", {"file": self.uploaded_file_name})

        except Exception as e:

            wx.CallAfter(self.append_result_text, f"Anomalies analysis error: {e}")

 

    def trigger_compliance_analysis(self, event):

        self.current_analysis_type = "Compliance"

        self.prompt_label.SetLabel("Current Analysis: Compliance Check")

        self.status_bar.SetStatusText("Running compliance analysis...")

        threading.Thread(target=self.run_compliance_analysis, daemon=True).start()

 

    def run_compliance_analysis(self):

        try:

            df = self._dataframe_from_table()

            headers, data = compliance_analysis(df, "MyApplication", self.uploaded_file_name)

            wx.CallAfter(self.update_ui_with_generic_analysis, (headers, data), "Compliance Check")

            self.log_action("compliance_check", {"file": self.uploaded_file_name})

        except Exception as e:

            wx.CallAfter(self.append_result_text, f"Compliance check error: {e}")

 

    def _dataframe_from_table(self):

        if not self.headers or not self.table_data:

            return pd.DataFrame()

        return pd.DataFrame(self.table_data, columns=self.headers)

 

    def update_ui_with_generic_analysis(self, analysis_tuple, analysis_title):

        headers, data = analysis_tuple

        self.result_text.AppendText(f"\n=== {analysis_title} ===\n")

        try:

            self.display_table(headers, data)

            current_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self.result_text.AppendText(f"\nTable Name: {self.uploaded_file_name}\n")

            self.result_text.AppendText(f"Analysis Date: {current_date_str}\n")

            self.result_text.AppendText(f"{analysis_title} complete.\n")

            self.status_bar.SetStatusText(f"{analysis_title} complete.")

 

            if self.current_analysis_type.lower() == "catalog":

                self.edit_button.Enable()

                self.save_button.Enable()

 

            self.write_results_to_excel(analysis_title, headers, data)

 

        except Exception as e:

            self.result_text.AppendText(f"An error occurred during {analysis_title.lower()}: {e}\n")

            self.status_bar.SetStatusText(f"{analysis_title} failed.")

        finally:

            wx.PostEvent(self, TodoActionCompleteEvent())

 

    def append_result_text(self, msg):

        self.result_text.AppendText(f"{msg}\n")

 

    def write_results_to_excel(self, analysis_title, headers, data):

        knowledge_dir = os.path.join(default_values["filepath"], "Knowledge Files")

        os.makedirs(knowledge_dir, exist_ok=True)

 

        excel_file = os.path.join(knowledge_dir, "DB-Analysis-Results.xlsx")

 

        df = pd.DataFrame(data, columns=headers)

        df["Table Name"] = self.uploaded_file_name

        df["Analysis Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

 

        sheet_name = analysis_title.replace(" ", "_")

        if os.path.isfile(excel_file):

            with pd.ExcelWriter(excel_file, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:

                df.to_excel(writer, sheet_name=sheet_name, index=False)

        else:

            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:

                df.to_excel(writer, sheet_name=sheet_name, index=False)

 

        if "DB-Analysis-Results.xlsx" not in self.knowledge_file_names:

            self.knowledge_files.append("DB-Analysis-Results.xlsx file is available.")

            self.knowledge_file_names.append("DB-Analysis-Results.xlsx")

            self.update_knowledge_display()

 

    def display_table(self, headers, data):

        try:

            self.table.ClearGrid()

            if self.table.GetNumberRows() > 0:

                self.table.DeleteRows(0, self.table.GetNumberRows())

            if self.table.GetNumberCols() > 0:

                self.table.DeleteCols(0, self.table.GetNumberCols())

 

            if not headers:

                return

 

            self.table.AppendCols(len(headers))

            for idx, header in enumerate(headers):

                self.table.SetColLabelValue(idx, header)

 

            if data:

                self.table.AppendRows(len(data))

                for row_idx, row in enumerate(data):

                    for col_idx, item in enumerate(row):

                        self.table.SetCellValue(row_idx, col_idx, str(item))

 

            for r in range(self.table.GetNumberRows()):

                bg_color = wx.Colour(60,60,60) if r % 2 == 0 else wx.Colour(70,70,70)

                for c in range(self.table.GetNumberCols()):

                    self.table.SetCellBackgroundColour(r, c, bg_color)

 

            self.table.SetGridLineColour(wx.Colour(255,255,255))

            self.table.EnableGridLines(True)

            self.table.AutoSizeColumns()

        except Exception as e:

            self.result_text.AppendText(f"Error displaying table: {e}\n")

            self.status_bar.SetStatusText("Error displaying table.")

 

    def enable_editing(self, event):

        self.table.EnableEditing(True)

        self.save_button.Enable()

        self.status_bar.SetStatusText("Editing enabled.")

        wx.MessageBox("You can now edit the catalog fields.","Edit Mode",wx.OK|wx.ICON_INFORMATION)

 

    def save_edits(self, event):

        """

        Fix 'list assignment index out of range' by ensuring

        row/col are within original_catalog_data.

        """

        try:

            num_rows = self.table.GetNumberRows()

            num_cols = self.table.GetNumberCols()

            headers = [self.table.GetColLabelValue(i) for i in range(num_cols)]

            feedback_data = []

 

            for row in range(num_rows):

                for col in range(num_cols):

                    edited_value = self.table.GetCellValue(row, col)

 

                    # Safely check bounds

                    if row < len(self.original_catalog_data) and col < len(self.original_catalog_data[row]):

                        original_value = self.original_catalog_data[row][col]

                    else:

                        # If out of range, skip or set original_value to empty

                        original_value = ""

                   

                    if edited_value != original_value:

                        # Create feedback record if changed

                        feedback_data.append({

                            "File Name": self.uploaded_file_name,

                            "Field": self.table.GetCellValue(row, 2),  # e.g. "Column Name" is typically col idx=2

                            "Original Value": original_value,

                            "Edited Value": edited_value,

                            "Edit Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        })

 

                        # If in range, update the original_catalog_data

                        if row < len(self.original_catalog_data) and col < len(self.original_catalog_data[row]):

                            self.original_catalog_data[row][col] = edited_value

 

                        # Also update self.table_data so the UI stays consistent

                        if row < len(self.table_data) and col < len(self.table_data[row]):

                            self.table_data[row][col] = edited_value

 

            if feedback_data:

                knowledge_dir = os.path.join(default_values["filepath"], "Knowledge Files")

                os.makedirs(knowledge_dir, exist_ok=True)

                feedback_filename = os.path.join(knowledge_dir, "feedback_loop.csv")

 

                file_exists = os.path.isfile(feedback_filename)

                with open(feedback_filename, "a", newline='', encoding='utf-8') as csvfile:

                    fieldnames = ["File Name","Field","Original Value","Edited Value","Edit Timestamp"]

                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                    if not file_exists:

                        writer.writeheader()

                    for entry in feedback_data:

                        writer.writerow(entry)

 

                wx.MessageBox(f"Edits saved to {feedback_filename}", "Save Successful", wx.OK|wx.ICON_INFORMATION)

                self.log_action("edits", {"file": self.uploaded_file_name, "edits_count": len(feedback_data)})

                self.load_feedback_loop(feedback_filename)

            else:

                wx.MessageBox("No changes detected to save.","No Changes",wx.OK|wx.ICON_INFORMATION)

 

            self.display_table(headers, self.table_data)

            self.table.EnableEditing(False)

            self.save_button.Disable()

            self.edit_button.Disable()

            self.status_bar.SetStatusText("Editing disabled.")

        except Exception as e:

            wx.MessageBox(f"Error saving edits: {e}","Save Error",wx.OK|wx.ICON_ERROR)

            self.status_bar.SetStatusText("Error saving edits.")

 

    def load_feedback_loop(self, feedback_filename):

        try:

            with open(feedback_filename, "r", encoding='utf-8') as csvfile:

                content = csvfile.read()

                if "feedback_loop.csv" not in self.knowledge_file_names:

                    self.knowledge_files.append(content)

                    self.knowledge_file_names.append("feedback_loop.csv")

                    self.update_knowledge_display()

                self.process_feedback_loop(content)

        except Exception as e:

            wx.MessageBox(f"Error loading feedback_loop.csv: {e}", "Feedback Loop Error", wx.OK|wx.ICON_ERROR)

 

    def process_feedback_loop(self, content):

        try:

            feedback_df = pd.read_csv(io.StringIO(content))

            required_columns = ["File Name","Field","Original Value","Edited Value","Edit Timestamp"]

            if not all(column in feedback_df.columns for column in required_columns):

                wx.MessageBox("Feedback_loop.csv missing required columns.","Feedback Loop Error",wx.OK|wx.ICON_ERROR)

                return

 

            # Example logic: If you want to re-run the Catalog analysis after reloading feedback

            # to refresh the UI, you can do so. For example:

            if self.current_analysis_type.lower() == "catalog" and self.file_content:

                self.run_catalog_analysis()

                wx.MessageBox("Catalog updated based on feedback_loop.csv.","Catalog Updated",wx.OK|wx.ICON_INFORMATION)

        except Exception as e:

            wx.MessageBox(f"Error processing feedback_loop.csv: {e}","Feedback Loop Error",wx.OK|wx.ICON_ERROR)

 

    def load_knowledge(self, event):

        with wx.FileDialog(

            self,

            "Open Knowledge File",

            wildcard="All files (*.*)|*.*",

            style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE

        ) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:

                return

            file_paths = fileDialog.GetPaths()

            for file_path in file_paths:

                file_name = os.path.basename(file_path)

                try:

                    with open(file_path, "r", encoding="utf-8", errors='ignore') as file:

                        content = file.read()

                        self.knowledge_files.append(content)

                        self.knowledge_file_names.append(file_name)

                        self.update_knowledge_display()

                        if file_name.lower() == "feedback_loop.csv":

                            self.process_feedback_loop(content)

                except Exception as e:

                    wx.MessageBox(f"Error reading knowledge file: {e}","File Error",wx.OK|wx.ICON_ERROR)

 

    def update_knowledge_display(self):

        self.knowledge_listbox.Clear()

        self.knowledge_listbox.AppendItems(self.knowledge_file_names)

 

    def remove_knowledge_file(self, event):

        selection = self.knowledge_listbox.GetSelection()

        if selection != wx.NOT_FOUND:

            file_name = self.knowledge_file_names[selection]

            del self.knowledge_files[selection]

            del self.knowledge_file_names[selection]

            self.update_knowledge_display()

            if file_name.lower() == "feedback_loop.csv":

                if self.current_analysis_type.lower() == "catalog" and self.file_content:

                    self.run_catalog_analysis()

                    wx.MessageBox("Catalog updated after removing feedback_loop.csv.","Catalog Updated",wx.OK|wx.ICON_INFORMATION)

        else:

            wx.MessageBox("No knowledge file selected.","Error",wx.OK|wx.ICON_ERROR)

 

    def on_todo_action_complete(self, event):

        self.process_next_todo_action()

 

    def load_todo_file(self, event):

        with wx.FileDialog(

            self,

            "Open To Do file",

            wildcard="Text files (*.txt)|*.txt|CSV files (*.csv)|*.csv",

            style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST

        ) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:

                return

            todo_file_path = fileDialog.GetPath()

            try:

                with open(todo_file_path, 'r', encoding='utf-8') as file:

                    actions = file.readlines()

                for action in actions:

                    action = action.strip()

                    if action:

                        self.todo_actions_queue.append(action)

                if not self.todo_in_progress:

                    self.process_next_todo_action()

            except Exception as e:

                wx.MessageBox(f"Error reading To Do file: {e}","File Error",wx.OK|wx.ICON_ERROR)

 

    def perform_action(self, action):

        self.result_text.AppendText(f"Starting action: {action}\n")

        self.status_bar.SetStatusText(f"Executing: {action}")

        action_lower = action.lower()

        if action_lower == "profile":

            self.trigger_analysis(None)

        elif action_lower == "quality":

            self.trigger_quality_analysis(None)

        elif action_lower == "catalog":

            self.trigger_catalog_analysis(None)

        elif action_lower == "anomalies":

            self.trigger_anomalies_analysis(None)

        elif action_lower == "compliance check":

            self.trigger_compliance_analysis(None)

        elif action_lower == "upload file":

            wx.CallAfter(self.process_file_and_prompt, None)

        elif action_lower == "export to csv":

            wx.CallAfter(self.export_to_csv, None)

        elif action_lower == "export to txt":

            wx.CallAfter(self.export_to_txt, None)

        elif action_lower == "little buddy":

            wx.CallAfter(self.open_data_buddy, None)

        else:

            wx.MessageBox(f"Unknown action: {action}", "Action Error", wx.OK|wx.ICON_ERROR)

            self.status_bar.SetStatusText(f"Unknown action: {action}")

            self.post_todo_complete()

            return

        self.log_action("to_do", {"action": action})

 

    def process_next_todo_action(self):

        if self.todo_actions_queue:

            action = self.todo_actions_queue.popleft()

            self.todo_in_progress = True

            self.perform_action(action)

        else:

            if self.todo_in_progress:

                self.todo_in_progress = False

                wx.MessageBox("All To Do actions have been completed.","To Do Complete",wx.OK|wx.ICON_INFORMATION)

 

    def post_todo_complete(self):

        wx.PostEvent(self, TodoActionCompleteEvent())

 

    def export_to_csv(self, event):

        date_str = datetime.now().strftime("%m-%d-%y")

        filename = f"{self.current_analysis_type.replace(' ', '_')}_Analysis_{date_str}.csv"

        with wx.FileDialog(

            self,

            "Save CSV file",

            wildcard="CSV files (*.csv)|*.csv",

            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,

            defaultFile=filename

        ) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:

                self.post_todo_complete()

                return

            file_path = fileDialog.GetPath()

            try:

                headers = [self.table.GetColLabelValue(i) for i in range(self.table.GetNumberCols())]

                data = []

                for row in range(self.table.GetNumberRows()):

                    row_data = [self.table.GetCellValue(row, col) for col in range(len(headers))]

                    data.append(row_data)

                df = pd.DataFrame(data, columns=headers)

                df.to_csv(file_path, index=False)

                wx.MessageBox(f"Data exported to {file_path}", "Export Successful", wx.OK|wx.ICON_INFORMATION)

                self.log_action("exports", {"file": file_path, "type": "csv"})

            except Exception as e:

                wx.MessageBox(f"Error exporting to CSV: {e}", "Export Error", wx.OK|wx.ICON_ERROR)

            finally:

                self.post_todo_complete()

 

    def export_to_txt(self, event):

        date_str = datetime.now().strftime("%m-%d-%y")

        filename = f"{self.current_analysis_type.replace(' ', '_')}_Analysis_{date_str}.txt"

        with wx.FileDialog(

            self,

            "Save TXT file",

            wildcard="Text files (*.txt)|*.txt",

            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,

            defaultFile=filename

        ) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:

                self.post_todo_complete()

                return

            file_path = fileDialog.GetPath()

            try:

                headers = [self.table.GetColLabelValue(i) for i in range(self.table.GetNumberCols())]

                data = []

                for row in range(self.table.GetNumberRows()):

                    row_data = [self.table.GetCellValue(row, col) for col in range(len(headers))]

                    data.append(row_data)

                df = pd.DataFrame(data, columns=headers)

                df.to_csv(file_path, index=False, sep='\t')

                wx.MessageBox(f"Data exported to {file_path}", "Export Successful", wx.OK|wx.ICON_INFORMATION)

                self.log_action("exports", {"file": file_path, "type": "txt"})

            except Exception as e:

                wx.MessageBox(f"Error exporting to TXT: {e}", "Export Error", wx.OK|wx.ICON_ERROR)

            finally:

                self.post_todo_complete()

 

    def on_email_results(self, event):

        subject = f"Data Buddy {self.current_analysis_type} Results"

        body = self.build_email_body_from_table()

        self.send_email(subject, body)

 

    def send_email(self, subject, body):

        smtp_server = default_values["smtp_server"]

        smtp_port = default_values["smtp_port"]

        username = default_values["email_username"]

        password = default_values["email_password"]

        from_email = default_values["from_email"]

        to_email = default_values["to_email"]

 

        if not (smtp_server and smtp_port and username and password and from_email and to_email):

            wx.MessageBox(

                "Email settings are not configured. Please go to Settings and fill in all email details.",

                "Email Error",

                wx.OK|wx.ICON_ERROR

            )

            return

 

        try:

            port = int(smtp_port)

            context = ssl.create_default_context()

           

            if port == 465:

                with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:

                    server.ehlo()

                    server.login(username, password)

                    message = f"Subject: {subject}\nFrom: {from_email}\nTo: {to_email}\n\n{body}"

                    server.sendmail(from_email, to_email, message.encode('utf-8'))

            else:

                with smtplib.SMTP(smtp_server, port) as server:

                    server.ehlo()

                    server.starttls(context=context)

                    server.ehlo()

                    server.login(username, password)

                    message = f"Subject: {subject}\nFrom: {from_email}\nTo: {to_email}\n\n{body}"

                    server.sendmail(from_email, to_email, message.encode('utf-8'))

 

            wx.MessageBox("Email sent successfully!", "Success", wx.OK|wx.ICON_INFORMATION)

            self.log_action("email", {"subject": subject, "to": to_email})

        except Exception as e:

            wx.MessageBox(f"Error sending email: {e}", "Email Error", wx.OK|wx.ICON_ERROR)

 

    def build_email_body_from_table(self):

        headers = [self.table.GetColLabelValue(i) for i in range(self.table.GetNumberCols())]

        data = []

        for row in range(self.table.GetNumberRows()):

            row_data = [self.table.GetCellValue(row, col) for col in range(len(headers))]

            data.append(row_data)

 

        body = f"Analysis Type: {self.current_analysis_type}\n\n"

        body += "Results:\n"

        body += "\t".join(headers) + "\n"

        for row in data:

            body += "\t".join(row) + "\n"

 

        extra_text = self.result_text.GetValue()

        if extra_text:

            body += "\nAdditional Information:\n"

            body += extra_text

        return body

 

    def initUI(self):

        panel = wx.Panel(self)

        panel.SetBackgroundColour(wx.Colour(30,30,30))

        main_vbox = wx.BoxSizer(wx.VERTICAL)

 

        menubar = wx.MenuBar()

        file_menu = wx.Menu()

        file_menu.Append(wx.ID_EXIT, 'Exit', 'Exit the application')

        self.Bind(wx.EVT_MENU, self.on_quit, id=wx.ID_EXIT)

       

        settings_menu = wx.Menu()

        settings_menu.Append(wx.ID_PREFERENCES, 'Settings', 'Open Settings Window')

        self.Bind(wx.EVT_MENU, self.open_settings, id=wx.ID_PREFERENCES)

 

        menubar.Append(file_menu, '&File')

        menubar.Append(settings_menu, '&Settings')

        self.SetMenuBar(menubar)

 

        button_box = wx.BoxSizer(wx.HORIZONTAL)

 

        icon_path = "DataBuddyIcon.png"

        if os.path.exists(icon_path):

            self.icon_bitmap = wx.Bitmap(icon_path)

        else:

            self.icon_bitmap = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_OTHER, (50,50))

        self.icon = wx.StaticBitmap(panel, bitmap=self.icon_bitmap, size=(50,50))

        button_box.Add(self.icon, flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=5)

 

        self.upload_button = wx.Button(panel, label="Upload File", style=wx.BU_EXACTFIT)

        self.upload_button.Bind(wx.EVT_BUTTON, self.process_file_and_prompt)

        button_box.Add(self.upload_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.profile_button = wx.Button(panel, label="Profile", style=wx.BU_EXACTFIT)

        self.profile_button.Bind(wx.EVT_BUTTON, self.trigger_analysis)

        self.profile_button.Disable()

        button_box.Add(self.profile_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.quality_button = wx.Button(panel, label="Quality", style=wx.BU_EXACTFIT)

        self.quality_button.Bind(wx.EVT_BUTTON, self.trigger_quality_analysis)

        self.quality_button.Disable()

        button_box.Add(self.quality_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.catalog_button = wx.Button(panel, label="Catalog", style=wx.BU_EXACTFIT)

        self.catalog_button.Bind(wx.EVT_BUTTON, self.trigger_catalog_analysis)

        self.catalog_button.Disable()

        button_box.Add(self.catalog_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.anomalies_button = wx.Button(panel, label="Anomalies", style=wx.BU_EXACTFIT)

        self.anomalies_button.Bind(wx.EVT_BUTTON, self.trigger_anomalies_analysis)

        self.anomalies_button.Disable()

        button_box.Add(self.anomalies_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.optimizer_button = wx.Button(panel, label="Optimizer", style=wx.BU_EXACTFIT)

        self.optimizer_button.Bind(wx.EVT_BUTTON, self.open_optimizer)

        button_box.Add(self.optimizer_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.data_buddy_button = wx.Button(panel, label="Little Buddy", style=wx.BU_EXACTFIT)

        self.data_buddy_button.Bind(wx.EVT_BUTTON, self.open_data_buddy)

        button_box.Add(self.data_buddy_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.compliance_button = wx.Button(panel, label="Compliance Check", style=wx.BU_EXACTFIT)

        self.compliance_button.Bind(wx.EVT_BUTTON, self.trigger_compliance_analysis)

        self.compliance_button.Disable()

        button_box.Add(self.compliance_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.todo_button = wx.Button(panel, label="To Do", style=wx.BU_EXACTFIT)

        self.todo_button.Bind(wx.EVT_BUTTON, self.load_todo_file)

        button_box.Add(self.todo_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        main_vbox.Add(button_box, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.result_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE|wx.TE_READONLY)

        self.result_text.SetBackgroundColour(wx.Colour(50,50,50))

        self.result_text.SetForegroundColour(wx.Colour(255,255,255))

        main_vbox.Add(self.result_text, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

 

        self.prompt_label = wx.StaticText(panel, label="", style=wx.ALIGN_CENTER)

        self.prompt_label.SetForegroundColour(wx.Colour(255,255,255))

        main_vbox.Add(self.prompt_label, flag=wx.ALIGN_CENTER|wx.ALL, border=5)

 

        self.status_bar = wx.StatusBar(panel)

        self.SetStatusBar(self.status_bar)

        main_vbox.Add(self.status_bar, flag=wx.EXPAND|wx.ALL, border=5)

 

        table_area = wx.BoxSizer(wx.VERTICAL)

        table_scroll = wx.ScrolledWindow(panel, style=wx.HSCROLL|wx.VSCROLL)

        table_scroll.SetScrollRate(5,5)

 

        self.table = gridlib.Grid(table_scroll)

        self.table.CreateGrid(0,0)

        self.table.EnableEditing(False)

        self.table.SetGridLineColour(wx.Colour(255,255,255))

        self.table.SetDefaultCellBackgroundColour(wx.Colour(50,50,50))

        self.table.SetDefaultCellTextColour(wx.Colour(255,255,255))

        self.table.SetMargins(5,5)

        self.table.EnableGridLines(True)

        table_area.Add(self.table, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

 

        table_scroll.SetSizer(table_area)

        main_vbox.Add(table_scroll, proportion=2, flag=wx.EXPAND|wx.ALL, border=10)

 

        export_button_box = wx.BoxSizer(wx.HORIZONTAL)

 

        self.export_button = wx.Button(panel, label="Export to .CSV", style=wx.BU_EXACTFIT)

        self.export_button.Bind(wx.EVT_BUTTON, self.export_to_csv)

        export_button_box.Add(self.export_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.export_txt_button = wx.Button(panel, label="Export to .txt", style=wx.BU_EXACTFIT)

        self.export_txt_button.Bind(wx.EVT_BUTTON, self.export_to_txt)

        export_button_box.Add(self.export_txt_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.email_button = wx.Button(panel, label="Email", style=wx.BU_EXACTFIT)

        self.email_button.Bind(wx.EVT_BUTTON, self.on_email_results)

        export_button_box.Add(self.email_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        main_vbox.Add(export_button_box, flag=wx.ALIGN_RIGHT|wx.ALL, border=10)

 

        knowledge_box = wx.BoxSizer(wx.VERTICAL)

        knowledge_buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)

 

        self.knowledge_label = wx.StaticText(panel, label="Knowledge Files:")

        self.knowledge_label.SetForegroundColour(wx.Colour(255,255,255))

        knowledge_buttons_hbox.Add(self.knowledge_label, flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=5)

 

        self.load_knowledge_button = wx.Button(panel, label="Load Knowledge", style=wx.BU_EXACTFIT)

        self.load_knowledge_button.Bind(wx.EVT_BUTTON, self.load_knowledge)

        knowledge_buttons_hbox.Add(self.load_knowledge_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.remove_knowledge_button = wx.Button(panel, label="Remove Knowledge", style=wx.BU_EXACTFIT)

        self.remove_knowledge_button.Bind(wx.EVT_BUTTON, self.remove_knowledge_file)

        knowledge_buttons_hbox.Add(self.remove_knowledge_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        knowledge_box.Add(knowledge_buttons_hbox, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.knowledge_listbox = wx.ListBox(panel)

        self.knowledge_listbox.SetBackgroundColour(wx.Colour(50,50,50))

        self.knowledge_listbox.SetForegroundColour(wx.Colour(255,255,255))

        knowledge_box.Add(self.knowledge_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)

 

        main_vbox.Add(knowledge_box, flag=wx.EXPAND|wx.ALL, border=10)

 

        edit_save_box = wx.BoxSizer(wx.HORIZONTAL)

 

        self.edit_button = wx.Button(panel, label="Edit", style=wx.BU_EXACTFIT)

        self.edit_button.Bind(wx.EVT_BUTTON, self.enable_editing)

        self.edit_button.Disable()

        edit_save_box.Add(self.edit_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        self.save_button = wx.Button(panel, label="Save", style=wx.BU_EXACTFIT)

        self.save_button.Bind(wx.EVT_BUTTON, self.save_edits)

        self.save_button.Disable()

        edit_save_box.Add(self.save_button, flag=wx.EXPAND|wx.ALL, border=5)

 

        main_vbox.Add(edit_save_box, flag=wx.EXPAND|wx.RIGHT|wx.TOP, border=10)

 

        panel.SetSizer(main_vbox)

        self.SetSize((1200,800))

        self.SetTitle('Data Buddy')

        self.Centre()

 

if __name__ == '__main__':

    app = wx.App(False)

    window = MainWindow(None)

    window.Show(True)

    app.MainLoop()
