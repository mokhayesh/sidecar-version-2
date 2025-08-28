import wx
import os
import json

# Load defaults from disk or use fallback
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
    "aws_access_key_id": "",
    "aws_secret_access_key": "",
    "aws_session_token": "",
    "aws_s3_region": "us-east-1",
    "aws_profile_bucket": "",
    "aws_quality_bucket": "",
    "aws_catalog_bucket": "",
    "aws_compliance_bucket": "",
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
        print(f"Warning loading defaults: {e}")

def save_defaults():
    with open(DEFAULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(defaults, f, indent=2)
    wx.MessageBox("Settings saved.", "Settings", wx.OK | wx.ICON_INFORMATION)


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
            ("From Email", "from_email"), ("To Email", "to_email")
        ]

        row = 0
        for label, key in fields:
            sizer.Add(wx.StaticText(panel, label=label + ":"), (row, 0), flag=wx.ALIGN_RIGHT | wx.TOP, border=5)
            style = wx.TE_PASSWORD if "password" in key or "secret" in key else 0
            ctrl = wx.TextCtrl(panel, value=str(defaults.get(key, "")), size=(320, -1), style=style)
            setattr(self, f"{key}_ctrl", ctrl)
            sizer.Add(ctrl, (row, 1), flag=wx.EXPAND | wx.TOP, border=5)
            row += 1

        save_btn = wx.Button(panel, label="Save")
        save_btn.Bind(wx.EVT_BUTTON, self.on_save)
        sizer.Add(save_btn, (row, 0), span=(1, 2), flag=wx.ALIGN_CENTER | wx.TOP, border=10)

        panel.SetSizerAndFit(sizer)

    def on_save(self, _):
        for attr in dir(self):
            if attr.endswith("_ctrl"):
                key = attr[:-5]
                defaults[key] = getattr(self, attr).GetValue()
        save_defaults()
        self.Close()
