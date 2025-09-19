import os
import json
import wx

# ──────────────────────────────────────────────────────────────────────────────
# Defaults & persistence
# ──────────────────────────────────────────────────────────────────────────────

DEFAULTS_FILE = "defaults.json"

defaults = {
    # Provider & API keys
    "provider": "auto",                  # auto | openai | gemini | custom
    "api_key": "",                      # OpenAI key
    "openai_org": "",                   # optional OpenAI organization
    "gemini_api_key": "",               # Google Gemini key

    # Chat models / settings
    "default_model": "gpt-4o",
    "fast_model": "gpt-4o-mini",
    "max_tokens": "800",
    "temperature": "0.6",
    "top_p": "1.0",
    "frequency_penalty": "0.0",
    "presence_penalty": "0.0",

    # Chat endpoints
    "url": "https://api.openai.com/v1/chat/completions",
    "gemini_text_url": "https://generativelanguage.googleapis.com/v1beta/models",

    # Image generation
    "image_provider": "auto",           # auto | openai | gemini | stability | none
    "image_model": "gpt-image-1",
    "image_generation_url": "https://api.openai.com/v1/images/generations",
    "stability_api_key": "",

    # (Optional) TTS (Azure)
    "azure_tts_key": "",
    "azure_tts_region": "",

    # AWS & S3
    "aws_access_key_id": "",
    "aws_secret_access_key": "",
    "aws_session_token": "",
    "aws_s3_region": "us-east-1",
    "aws_profile_bucket": "",
    "aws_quality_bucket": "",
    "aws_catalog_bucket": "",
    "aws_compliance_bucket": "",
    # NEW: requested buckets
    "aws_anomalies_bucket": "",
    "aws_synthetic_bucket": "",

    # Email
    "smtp_server": "",
    "smtp_port": "",
    "email_username": "",
    "email_password": "",
    "from_email": "",
    "to_email": "",

    # Misc
    "filepath": os.path.expanduser("~"),
}

if os.path.exists(DEFAULTS_FILE):
    try:
        defaults.update(json.load(open(DEFAULTS_FILE, "r", encoding="utf-8")))
    except Exception:
        pass


def save_defaults() -> None:
    json.dump(defaults, open(DEFAULTS_FILE, "w", encoding="utf-8"), indent=2)
    wx.MessageBox("Settings saved.", "Settings", wx.OK | wx.ICON_INFORMATION)


# ──────────────────────────────────────────────────────────────────────────────
# Settings window with provider & model dropdowns
# ──────────────────────────────────────────────────────────────────────────────

OPENAI_MAIN = ["gpt-4o", "o4-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"]
OPENAI_FAST = ["gpt-4o-mini", "gpt-4.1-mini", "o4-mini"]
OPENAI_IMAGE = ["gpt-image-1"]

GEMINI_MAIN = ["gemini-1.5-pro", "gemini-1.5-flash"]
GEMINI_FAST = ["gemini-1.5-flash", "gemini-1.5-flash-8b"]
GEMINI_IMAGE = ["gemini-1.5-flash", "gemini-1.5-pro"]  # used for image output

STABILITY_IMAGE = ["sdxl", "sd3-medium"]

PROVIDERS = ["auto", "openai", "gemini", "custom"]
IMAGE_PROVIDERS = ["auto", "openai", "gemini", "stability", "none"]


class SettingsWindow(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title="Settings", size=(560, 820))
        panel = wx.Panel(self)
        s = wx.GridBagSizer(6, 6)

        row = 0

        # Provider
        s.Add(wx.StaticText(panel, label="Provider:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.provider = wx.Choice(panel, choices=PROVIDERS)
        self.provider.SetSelection(max(PROVIDERS.index(defaults.get("provider", "auto")), 0))
        self.provider.Bind(wx.EVT_CHOICE, self._on_provider_change)
        s.Add(self.provider, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        # OpenAI key / org
        s.Add(wx.StaticText(panel, label="OpenAI API Key:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.api_key = wx.TextCtrl(panel, value=defaults.get("api_key", ""))
        s.Add(self.api_key, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="OpenAI Org (optional):"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.org = wx.TextCtrl(panel, value=defaults.get("openai_org", ""))
        s.Add(self.org, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        # Gemini key
        s.Add(wx.StaticText(panel, label="Gemini API Key:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.gemini_key = wx.TextCtrl(panel, value=defaults.get("gemini_api_key", ""))
        s.Add(self.gemini_key, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        # Chat URLs
        s.Add(wx.StaticText(panel, label="Chat URL:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.chat_url = wx.TextCtrl(panel, value=defaults.get("url", "https://api.openai.com/v1/chat/completions"))
        s.Add(self.chat_url, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Gemini Base URL:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.gemini_url = wx.TextCtrl(panel, value=defaults.get("gemini_text_url", "https://generativelanguage.googleapis.com/v1beta/models"))
        s.Add(self.gemini_url, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        # Model dropdowns
        s.Add(wx.StaticText(panel, label="Default Model:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.default_model = wx.Choice(panel)
        s.Add(self.default_model, (row, 1), span=(1, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Fast Model:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.fast_model = wx.Choice(panel)
        s.Add(self.fast_model, (row, 3), span=(1, 1), flag=wx.EXPAND)
        row += 1

        # Gen settings
        s.Add(wx.StaticText(panel, label="Max Tokens:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.max_tokens = wx.TextCtrl(panel, value=str(defaults.get("max_tokens", "800")))
        s.Add(self.max_tokens, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Temperature:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.temperature = wx.TextCtrl(panel, value=str(defaults.get("temperature", "0.6")))
        s.Add(self.temperature, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Top P:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.top_p = wx.TextCtrl(panel, value=str(defaults.get("top_p", "1.0")))
        s.Add(self.top_p, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Frequency Penalty:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.freq_pen = wx.TextCtrl(panel, value=str(defaults.get("frequency_penalty", "0.0")))
        s.Add(self.freq_pen, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Presence Penalty:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.pres_pen = wx.TextCtrl(panel, value=str(defaults.get("presence_penalty", "0.0")))
        s.Add(self.pres_pen, (row, 1), flag=wx.EXPAND)
        row += 1

        # Image provider + model
        s.Add(wx.StaticText(panel, label="Image Provider:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.image_provider = wx.Choice(panel, choices=IMAGE_PROVIDERS)
        self.image_provider.SetSelection(max(IMAGE_PROVIDERS.index(defaults.get("image_provider", "auto")), 0))
        self.image_provider.Bind(wx.EVT_CHOICE, self._on_image_provider_change)
        s.Add(self.image_provider, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Image Model:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.image_model = wx.Choice(panel)
        s.Add(self.image_model, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Image URL (OpenAI):"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.image_url = wx.TextCtrl(panel, value=defaults.get("image_generation_url", "https://api.openai.com/v1/images/generations"))
        s.Add(self.image_url, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Stability API Key:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.stability = wx.TextCtrl(panel, value=defaults.get("stability_api_key", ""))
        s.Add(self.stability, (row, 1), span=(1, 2), flag=wx.EXPAND)
        row += 1

        # TTS
        s.Add(wx.StaticText(panel, label="Azure TTS Key:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.azure_key = wx.TextCtrl(panel, value=defaults.get("azure_tts_key", ""))
        s.Add(self.azure_key, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Azure TTS Region:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.azure_region = wx.TextCtrl(panel, value=defaults.get("azure_tts_region", ""))
        s.Add(self.azure_region, (row, 3), flag=wx.EXPAND)
        row += 1

        # AWS keys/region
        s.Add(wx.StaticText(panel, label="AWS Access Key:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.aws_key = wx.TextCtrl(panel, value=defaults.get("aws_access_key_id", ""))
        s.Add(self.aws_key, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="AWS Secret Key:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.aws_secret = wx.TextCtrl(panel, value=defaults.get("aws_secret_access_key", ""))
        s.Add(self.aws_secret, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="AWS Session Token:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.aws_token = wx.TextCtrl(panel, value=defaults.get("aws_session_token", ""))
        s.Add(self.aws_token, (row, 1), span=(1, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="AWS Region:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.aws_region = wx.TextCtrl(panel, value=defaults.get("aws_s3_region", "us-east-1"))
        s.Add(self.aws_region, (row, 1), flag=wx.EXPAND)
        row += 1

        # Buckets (including the two new ones)
        s.Add(wx.StaticText(panel, label="Profile Bucket:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.bucket_profile = wx.TextCtrl(panel, value=defaults.get("aws_profile_bucket", ""))
        s.Add(self.bucket_profile, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Quality Bucket:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.bucket_quality = wx.TextCtrl(panel, value=defaults.get("aws_quality_bucket", ""))
        s.Add(self.bucket_quality, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Catalog Bucket:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.bucket_catalog = wx.TextCtrl(panel, value=defaults.get("aws_catalog_bucket", ""))
        s.Add(self.bucket_catalog, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Compliance Bucket:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.bucket_compliance = wx.TextCtrl(panel, value=defaults.get("aws_compliance_bucket", ""))
        s.Add(self.bucket_compliance, (row, 3), flag=wx.EXPAND)
        row += 1

        # NEW ROW
        s.Add(wx.StaticText(panel, label="Anomalies Bucket:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.bucket_anomalies = wx.TextCtrl(panel, value=defaults.get("aws_anomalies_bucket", ""))
        s.Add(self.bucket_anomalies, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Synthetic Data Bucket:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.bucket_synth = wx.TextCtrl(panel, value=defaults.get("aws_synthetic_bucket", ""))
        s.Add(self.bucket_synth, (row, 3), flag=wx.EXPAND)
        row += 1

        # Email
        s.Add(wx.StaticText(panel, label="SMTP Server:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.smtp_server = wx.TextCtrl(panel, value=defaults.get("smtp_server", ""))
        s.Add(self.smtp_server, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="SMTP Port:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.smtp_port = wx.TextCtrl(panel, value=defaults.get("smtp_port", ""))
        s.Add(self.smtp_port, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="Email Username:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.email_user = wx.TextCtrl(panel, value=defaults.get("email_username", ""))
        s.Add(self.email_user, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="Email Password:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.email_pass = wx.TextCtrl(panel, value=defaults.get("email_password", ""))
        s.Add(self.email_pass, (row, 3), flag=wx.EXPAND)
        row += 1

        s.Add(wx.StaticText(panel, label="From Email:"), (row, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.from_email = wx.TextCtrl(panel, value=defaults.get("from_email", ""))
        s.Add(self.from_email, (row, 1), flag=wx.EXPAND)

        s.Add(wx.StaticText(panel, label="To Email:"), (row, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        self.to_email = wx.TextCtrl(panel, value=defaults.get("to_email", ""))
        s.Add(self.to_email, (row, 3), flag=wx.EXPAND)
        row += 1

        hint = wx.StaticText(
            panel,
            label=("Recommendations: Fast chat → gpt-4o-mini / gemini-1.5-flash. "
                   "Higher quality → gpt-4o / gemini-1.5-pro. "
                   "Images → gpt-image-1 (OpenAI) / gemini-1.5-flash (Gemini) / SDXL (Stability).")
        )
        hint.Wrap(520)
        s.Add(hint, (row, 0), span=(1, 4), flag=wx.ALL | wx.EXPAND, border=6)
        row += 1

        save_btn = wx.Button(panel, label="Save")
        save_btn.Bind(wx.EVT_BUTTON, self.on_save)
        s.Add(save_btn, (row, 0), span=(1, 4), flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizerAndFit(s)

        self._refresh_model_choices()
        self._refresh_image_models()
        self._select_choice(self.default_model, defaults.get("default_model"))
        self._select_choice(self.fast_model, defaults.get("fast_model"))
        self._select_choice(self.image_model, defaults.get("image_model"))

    # utils
    def _select_choice(self, choice_ctrl: wx.Choice, value: str | None):
        if not value:
            return
        items = [choice_ctrl.GetString(i) for i in range(choice_ctrl.GetCount())]
        if value in items:
            choice_ctrl.SetSelection(items.index(value))

    def _on_provider_change(self, _):
        self._refresh_model_choices()

    def _on_image_provider_change(self, _):
        self._refresh_image_models()

    def _refresh_model_choices(self):
        provider = ["auto", "openai", "gemini", "custom"][self.provider.GetSelection()]
        self.default_model.Clear()
        self.fast_model.Clear()

        if provider in ("auto", "openai", "custom"):
            for m in OPENAI_MAIN:
                self.default_model.Append(m)
            for m in OPENAI_FAST:
                self.fast_model.Append(m)
        elif provider == "gemini":
            for m in GEMINI_MAIN:
                self.default_model.Append(m)
            for m in GEMINI_FAST:
                self.fast_model.Append(m)

        if self.default_model.GetCount() == 0:
            self.default_model.Append(defaults.get("default_model", "gpt-4o-mini"))
        if self.fast_model.GetCount() == 0:
            self.fast_model.Append(defaults.get("fast_model", "gpt-4o-mini"))

        self._select_choice(self.default_model, defaults.get("default_model"))
        self._select_choice(self.fast_model, defaults.get("fast_model"))

    def _refresh_image_models(self):
        prov = IMAGE_PROVIDERS[self.image_provider.GetSelection()]
        self.image_model.Clear()
        if prov in ("auto", "openai"):
            for m in OPENAI_IMAGE:
                self.image_model.Append(m)
        elif prov == "gemini":
            for m in GEMINI_IMAGE:
                self.image_model.Append(m)
        elif prov == "stability":
            for m in STABILITY_IMAGE:
                self.image_model.Append(m)
        else:
            self.image_model.Append(defaults.get("image_model", "gpt-image-1"))

        self._select_choice(self.image_model, defaults.get("image_model"))

    def on_save(self, _):
        defaults["provider"] = ["auto", "openai", "gemini", "custom"][self.provider.GetSelection()]
        defaults["api_key"] = self.api_key.GetValue().strip()
        defaults["openai_org"] = self.org.GetValue().strip()
        defaults["gemini_api_key"] = self.gemini_key.GetValue().strip()

        defaults["url"] = self.chat_url.GetValue().strip()
        defaults["gemini_text_url"] = self.gemini_url.GetValue().strip()
        defaults["default_model"] = self.default_model.GetStringSelection() or self.default_model.GetString(0)
        defaults["fast_model"] = self.fast_model.GetStringSelection() or self.fast_model.GetString(0)
        defaults["max_tokens"] = self.max_tokens.GetValue().strip()
        defaults["temperature"] = self.temperature.GetValue().strip()
        defaults["top_p"] = self.top_p.GetValue().strip()
        defaults["frequency_penalty"] = self.freq_pen.GetValue().strip()
        defaults["presence_penalty"] = self.pres_pen.GetValue().strip()

        defaults["image_provider"] = IMAGE_PROVIDERS[self.image_provider.GetSelection()]
        defaults["image_model"] = self.image_model.GetStringSelection() or self.image_model.GetString(0)
        defaults["image_generation_url"] = self.image_url.GetValue().strip()
        defaults["stability_api_key"] = self.stability.GetValue().strip()

        defaults["azure_tts_key"] = self.azure_key.GetValue().strip()
        defaults["azure_tts_region"] = self.azure_region.GetValue().strip()

        defaults["aws_access_key_id"] = self.aws_key.GetValue().strip()
        defaults["aws_secret_access_key"] = self.aws_secret.GetValue().strip()
        defaults["aws_session_token"] = self.aws_token.GetValue().strip()
        defaults["aws_s3_region"] = self.aws_region.GetValue().strip()
        defaults["aws_profile_bucket"] = self.bucket_profile.GetValue().strip()
        defaults["aws_quality_bucket"] = self.bucket_quality.GetValue().strip()
        defaults["aws_catalog_bucket"] = self.bucket_catalog.GetValue().strip()
        defaults["aws_compliance_bucket"] = self.bucket_compliance.GetValue().strip()
        # Save new buckets
        defaults["aws_anomalies_bucket"] = self.bucket_anomalies.GetValue().strip()
        defaults["aws_synthetic_bucket"] = self.bucket_synth.GetValue().strip()

        defaults["smtp_server"] = self.smtp_server.GetValue().strip()
        defaults["smtp_port"] = self.smtp_port.GetValue().strip()
        defaults["email_username"] = self.email_user.GetValue().strip()
        defaults["email_password"] = self.email_pass.GetValue().strip()
        defaults["from_email"] = self.from_email.GetValue().strip()
        defaults["to_email"] = self.to_email.GetValue().strip()

        save_defaults()
        self.Close()
