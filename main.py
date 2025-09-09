import wx
from main_window import MainWindow
import wx.grid as gridlib
import wx.richtext as rt
import pandas as pd
import re, csv, io, os, json, threading, requests, boto3, urllib3
from datetime import datetime
from botocore import UNSIGNED
from botocore.config import Config
import speech_recognition as sr
import edge_tts
import pygame


# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ╔═════════════════════════════════════════════════════════════════════════╗
# ║                             Global Defaults                            ║
# ╚═════════════════════════════════════════════════════════════════════════╝
DEFAULTS_FILE = "defaults.json"

defaults = {
    "api_key": "",
    "filepath": os.path.expanduser("~"),
    "default_model": "gpt-4",
    "max_tokens": "800",
    "temperature": "0.6",
    "top_p": "1.0",
    "frequency_penalty": "0.0",
    "presence_penalty": "0.0",
    "url": "https://api.openai.com/v1/chat/completions",
    "image_generation_url": "https://api.openai.com/v1/images/generations",

    # AWS
    "aws_access_key_id": "",
    "aws_secret_access_key": "",
    "aws_session_token": "",
    "aws_s3_region": "us-east-1",
    "aws_profile_bucket": "",
    "aws_quality_bucket": "",
    "aws_catalog_bucket": "",
    "aws_compliance_bucket": "",

    # Email
    "smtp_server": "",
    "smtp_port": "",
    "email_username": "",
    "email_password": "",
    "from_email": "",
    "to_email": ""
}

if os.path.exists(DEFAULTS_FILE):
    try:
        with open(DEFAULTS_FILE, encoding="utf-8") as f:
            defaults.update(json.load(f))
    except Exception as e:
        print(f"Warning: Could not load defaults from {DEFAULTS_FILE} — {e}")

def save_defaults():
    with open(DEFAULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(defaults, f, indent=2)
    wx.MessageBox("Settings saved.", "Settings", wx.OK | wx.ICON_INFORMATION)


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║                             UI Entry Point                             ║
# ╚═════════════════════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    app = wx.App(False)          # create wx application object
    win = MainWindow()           # create our main frame
    win.Show()                   # show the window
    app.MainLoop()               # start the UI event loop


