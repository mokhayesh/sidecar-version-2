import csv
import io
import json
import re
from datetime import datetime

import numpy as np
import pandas as pd
import requests

# ──────────────────────────────────────────────────────────────────────────────
# CSV/Parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Profile / Quality / Catalog / Compliance (original logic)
# ──────────────────────────────────────────────────────────────────────────────

def profile_analysis(df: pd.DataFrame):
    now, total = datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(df)
    rows = []
    for col in df.columns:
        s = df[col]
        nulls = int(s.isnull().sum())
        blanks = int((s.astype(str).str.strip() == "").sum())
        uniq = int(s.nunique(dropna=True))
        comp = round(100 * (total - nulls - blanks) / total, 2) if total else 0

        # Treat numeric-looking strings as numeric (strip thousands separators)
        s_num = pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")
        if s_num.notna().sum() > 0:
            vals = s_num.dropna()
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


_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_DATE_PARSE = lambda x: pd.to_datetime(x, errors="coerce")

def _default_valid_count(s: pd.Series) -> int:
    name = (s.name or "").lower()
    # Semantic checks first
    if "email" in name:
        return s.astype(str).str.match(_EMAIL_RE).sum()
    if "date" in name or pd.api.types.is_datetime64_any_dtype(s):
        return _DATE_PARSE(s).notna().sum()
    # Numeric-looking strings (strip commas)
    nums = pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")
    if nums.notna().sum() >= max(1, int(0.5 * len(s))):
        return int(nums.notna().sum())
    # Fallback: non-empty strings
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


# ──────────────────────────────────────────────────────────────────────────────
# Baseline rule-based anomaly detector (fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _rule_based_anomalies(df: pd.DataFrame):
    findings = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for col in df.columns:
        s = df[col].astype(str).str.strip()
        blanks = int((s == "").sum())
        nulls = int((s.str.lower() == "nan").sum())

        # Numeric with commas supported
        numeric = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")
        if numeric.notna().any():
            neg = int((numeric < 0).sum())
            std = float(numeric.std(skipna=True) or 0)
            huge = int((numeric > numeric.mean(skipna=True) + 6 * std).sum()) if std else 0
        else:
            neg = huge = 0

        bad_email = 0
        if "email" in col.lower():
            mask_valid = s.str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", regex=True, na=False)
            bad_email = int((~mask_valid).sum())

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
    return hdr, findings


# ──────────────────────────────────────────────────────────────────────────────
# Heuristic anomalies used by the UI (adds duplicates & z-score outliers)
# ──────────────────────────────────────────────────────────────────────────────

def anomalies_analysis(df: pd.DataFrame):
    """Return (headers, rows) of anomalies suitable for the grid.

    Rules:
      • Missing / blank cells
      • Duplicate full rows
      • Numeric outliers (|z| > 3)
      • Email format checks for columns with 'email' in the name

    Side effect:
      • Writes per-row flags: __anomaly__ (0/1) and __anomaly_mark__ ('⚠'/'')
    """
    findings = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Row-wise flags we will write back (aligned by index)
    row_flags = pd.Series(False, index=df.index)

    # 0) Duplicate rows (ignore any existing anomaly columns when checking)
    dups = df.drop(columns=["__anomaly__", "__anomaly_mark__"], errors="ignore").duplicated(keep="first")
    for idx in dups[dups].index.tolist():
        findings.append(["(row)", "Duplicate row", "Deduplicate or add a key", now])
    row_flags |= dups

    # 1) Missing / blank
    for col in df.columns:
        s = df[col]
        blanks_mask = s.astype(str).str.strip().eq("") | s.isna()
        n_blanks = int(blanks_mask.sum())
        if n_blanks:
            findings.append([col, f"{n_blanks} missing/blank", "Impute, drop or enforce NOT NULL", now])
        row_flags |= blanks_mask

    # 2) Numeric outliers via z-score > 3 (handles commas)
    for col in df.columns:
        s_num = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")
        if s_num.notna().sum() == 0:
            continue
        mu = s_num.mean()
        sigma = s_num.std(ddof=0)
        if sigma and np.isfinite(sigma) and sigma > 0:
            z = (s_num - mu).abs() / sigma
            out_mask = (z > 3)
            n_out = int(out_mask.sum())
            if n_out:
                findings.append([col, f"{n_out} outlier(s) (|z|>3)", "Winsorize, robust scale, or verify source", now])
            row_flags |= out_mask.fillna(False)

    # 3) Email format check (vectorized)
    email_cols = [c for c in df.columns if "email" in c.lower()]
    if email_cols:
        for col in email_cols:
            bad_mask = ~df[col].astype(str).str.match(_EMAIL_RE, na=False)
            bad_count = int(bad_mask.sum())
            if bad_count:
                findings.append([col, f"{bad_count} invalid email(s)", "Validate with regex & cleanse source", now])
            row_flags |= bad_mask

    # Write back flags for the KPI/grid
    df["__anomaly__"] = row_flags.astype(int)
    # Optional visible marker (useful if your grid renders 0 as blank)
    df["__anomaly_mark__"] = np.where(df["__anomaly__"].eq(1), "⚠", "")

    if not findings:
        findings = [["(none)", "No anomalies found", "", now]]

    hdr = ["Field", "Reason", "Recommendation", "Detected At"]
    return hdr, findings

# Backwards/compat alias for older wiring
def detect_anomalies(df: pd.DataFrame):
    return anomalies_analysis(df)


# ──────────────────────────────────────────────────────────────────────────────
# LLM plumbing
# ──────────────────────────────────────────────────────────────────────────────

def _provider_from_defaults(defaults: dict) -> str:
    # Expected: "openai" or "gemini" (case-insensitive). Anything else -> no-op.
    prov = (defaults.get("provider") or "").strip().lower()
    if "gemini" in prov:
        return "gemini"
    if "openai" in prov:
        return "openai"
    return ""

def _openai_json(defaults: dict, prompt: str, model: str | None = None, timeout=60):
    api_key = (defaults.get("openai_api_key") or "").strip()
    base = (defaults.get("openai_base_url") or "https://api.openai.com").rstrip("/")
    mdl = model or defaults.get("default_model") or "gpt-4o-mini"
    if not api_key:
        raise RuntimeError("OpenAI API key not configured")

    url = f"{base}/v1/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": mdl,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a precise data analyst. Respond ONLY with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(defaults.get("temperature", 0.3)),
            "max_tokens": int(defaults.get("max_tokens", 1200)),
        },
        timeout=timeout,
        verify=False,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

def _gemini_json(defaults: dict, prompt: str, model: str | None = None, timeout=60):
    api_key = (defaults.get("gemini_api_key") or "").strip()
    base = (defaults.get("gemini_base_url") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    mdl = model or defaults.get("default_model") or "gemini-1.5-flash"
    if not api_key:
        raise RuntimeError("Gemini API key not configured")

    url = f"{base}/models/{mdl}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": float(defaults.get("temperature", 0.3))},
    }
    resp = requests.post(url, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # best effort to parse JSON content from Gemini response
    txt = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(txt)

def run_llm_json(defaults: dict, prompt: str, *, model: str | None = None, provider: str | None = None) -> dict:
    provider = (provider or _provider_from_defaults(defaults) or "openai").lower()
    if provider == "gemini":
        return _gemini_json(defaults, prompt, model=model)
    return _openai_json(defaults, prompt, model=model)


# ──────────────────────────────────────────────────────────────────────────────
# AI-assisted catalog/anomaly (optional)
# ──────────────────────────────────────────────────────────────────────────────

def ai_catalog(df: pd.DataFrame, defaults: dict):
    """LLM-backed catalog; falls back to simple catalog on error."""
    try:
        preview_rows = min(30, len(df))
        sample = df.head(preview_rows).astype(str).to_dict(orient="records")
        cols = list(df.columns)

        prompt = (
            "Create a column catalog for the dataset. Return STRICT JSON ONLY:\n"
            "{ \"rows\": [ {\"field\": str, \"friendly\": str, \"description\": str, \"dtype\": str, \"nullable\": bool, \"example\": str} ] }\n"
            "Use friendly names (Title Case), concise descriptions (<= 12 words), and infer dtype from values.\n\n"
            f"Columns: {json.dumps(cols, ensure_ascii=False)}\n"
            f"Preview: {json.dumps(sample, ensure_ascii=False)}"
        )
        out = run_llm_json(defaults, prompt)
        rows = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in out.get("rows", []):
            rows.append([
                r.get("field",""),
                r.get("friendly",""),
                r.get("description",""),
                r.get("dtype",""),
                "Yes" if r.get("nullable", True) else "No",
                r.get("example",""),
                now
            ])
        if not rows:
            raise RuntimeError("Empty AI catalog")
        hdr = ["Field", "Friendly Name", "Description", "Data Type", "Nullable", "Example", "Analysis Date"]
        return hdr, rows

    except Exception:
        return catalog_analysis(df)


def ai_detect_anomalies(df: pd.DataFrame, defaults: dict):
    """LLM-backed anomaly detection; falls back to rule-based if the call fails."""
    try:
        preview_rows = min(30, len(df))
        sample = df.head(preview_rows).astype(str).to_dict(orient="records")
        quick = {}
        for c in df.columns:
            s = df[c]
            quick[c] = {
                "nulls": int(s.isna().sum()),
                "blanks": int((s.astype(str).str.strip() == "").sum()),
                "unique": int(s.nunique(dropna=True)),
                "dtype": str(s.dtype),
            }

        prompt = (
            "You are a data quality expert. Find likely anomalies in this dataset.\n"
            "Return STRICT JSON ONLY in this format:\n"
            "{ \"items\": [ {\"field\": str, \"reason\": str, \"recommendation\": str} ] }\n"
            "Reasons should be specific (e.g., 'outliers > 6 sigma', 'invalid email format', 'suspicious zero balance').\n"
            "Recommendations should be actionable (e.g., 'validate format with regex', 'clip to 3σ', 'backfill from source').\n\n"
            f"Quick stats per column: {json.dumps(quick, ensure_ascii=False)}\n\n"
            f"Sample rows: {json.dumps(sample, ensure_ascii=False)}"
        )

        out = run_llm_json(defaults, prompt)
        items = out.get("items", [])
        rows = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for it in items:
            rows.append([
                it.get("field",""),
                it.get("reason",""),
                it.get("recommendation",""),
                now
            ])
        if not rows:
            raise RuntimeError("Empty AI anomalies")
        hdr = ["Field", "Reason", "Recommendation", "Detected At"]
        return hdr, rows

    except Exception:
        return _rule_based_anomalies(df)
