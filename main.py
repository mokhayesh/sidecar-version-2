# main.py
# Application launcher for the Data Buddy UI.
# Robust to missing optional dependencies; keeps your defaults handling.

import os
import json
import wx
import urllib3

# Required UI modules
from main_window import MainWindow

# Optional/utility modules (imported defensively so UI can still launch)
try:
    import wx.grid as gridlib  # noqa: F401
except Exception:
    gridlib = None

try:
    import wx.richtext as rt  # noqa: F401
except Exception:
    rt = None

try:
    import pandas as pd  # noqa: F401
except Exception:
    pd = None

# Nice-to-have libs; don't block UI if missing
def _try_import(name):
    try:
        module = __import__(name)
        return module
    except Exception:
        return None

re = _try_import("re")
csv = _try_import("csv")
io = _try_import("io")
requests = _try_import("requests")
boto3 = _try_import("boto3")
urllib3 = _try_import("urllib3") or urllib3  # keep built-in ref if local import fails

# botocore bits are optional
try:
    from botocore import UNSIGNED  # noqa: F401
    from botocore.config import Config  # noqa: F401
except Exception:
    UNSIGNED = None
    Config = None

# Speech / TTS / audio (optional)
sr = _try_import("speech_recognition")
edge_tts = _try_import("edge_tts")
pygame = _try_import("pygame")

from datetime import datetime  # noqa: F401

# Disable SSL warnings
if urllib3:
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

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

def _load_defaults():
    if os.path.exists(DEFAULTS_FILE):
        try:
            with open(DEFAULTS_FILE, encoding="utf-8") as f:
                defaults.update(json.load(f))
        except Exception as e:
            print(f"Warning: Could not load defaults from {DEFAULTS_FILE} — {e}")

def save_defaults():
    try:
        with open(DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(defaults, f, indent=2)
        wx.MessageBox("Settings saved.", "Settings", wx.OK | wx.ICON_INFORMATION)
    except Exception as e:
        wx.MessageBox(f"Failed to save settings:\n{e}", "Settings", wx.OK | wx.ICON_ERROR)

# Load defaults on import
_load_defaults()

# ╔═════════════════════════════════════════════════════════════════════════╗
# ║                             UI Entry Point                             ║
# ╚═════════════════════════════════════════════════════════════════════════╝
def main():
    # Initialize pygame audio lazily (ignore if not installed)
    if pygame:
        try:
            pygame.mixer.init()
        except Exception:
            pass

    app = wx.App(False)
    win = MainWindow()
    win.Show()
    app.MainLoop()

if __name__ == "__main__":
    main()
