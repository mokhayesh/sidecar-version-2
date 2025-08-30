import re
import csv
import pandas as pd
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# Helpers shared across analyses
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
# Profile
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


# ──────────────────────────────────────────────────────────────────────────────
# Quality
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Catalog
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Compliance (placeholder sample)
# ──────────────────────────────────────────────────────────────────────────────

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
# Detect Anomalies (new)
# ──────────────────────────────────────────────────────────────────────────────

_POSITIVE_HINTS = {"amount","total","price","cost","balance","qty","quantity","count","number","age"}

def detect_anomalies(df: pd.DataFrame):
    """
    Heuristic anomaly detection with reason and remediation suggestion.
    Returns (headers, rows) where rows = [row#, field, value, reason, recommendation].
    """
    rows = []
    n = len(df)
    if n == 0 or df.empty:
        return ["Row #","Field","Value","Reason","Recommendation"], rows

    for col in df.columns:
        s = df[col]
        col_l = str(col).lower()

        # Missing/blanks
        blank_mask = s.isnull() | (s.astype(str).str.strip() == "")
        for i in s[blank_mask].index:
            rows.append([int(i)+1, col, "", "Missing/blank value",
                         "Populate or impute; add NOT NULL constraint if appropriate."])

        # Numeric anomalies
        s_num = pd.to_numeric(s, errors="coerce")
        num_mask = s_num.notna()
        if num_mask.any():
            vals = s_num[num_mask]
            q1 = float(vals.quantile(0.25))
            q3 = float(vals.quantile(0.75))
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outlier_idx = vals[(vals < lower) | (vals > upper)].index
            for i in outlier_idx:
                rows.append([int(i)+1, col, str(s.iloc[i]),
                             f"Numeric outlier outside IQR [{lower:.2f}, {upper:.2f}]",
                             "Verify source; correct data entry or cap/winsorize outliers."])
            # Expect non-negative?
            if any(h in col_l for h in _POSITIVE_HINTS):
                neg_idx = vals[vals < 0].index
                for i in neg_idx:
                    rows.append([int(i)+1, col, str(s.iloc[i]),
                                 "Negative value where non-negative expected",
                                 "Check business rule; fix sign or treat refunds separately."])

        # Date/time anomalies
        if ("date" in col_l or "time" in col_l) or pd.api.types.is_datetime64_any_dtype(s):
            dt = pd.to_datetime(s, errors="coerce")
            bad_idx = dt[dt.isna() & (~blank_mask)].index
            for i in bad_idx:
                rows.append([int(i)+1, col, str(s.iloc[i]),
                             "Unparseable date/time",
                             "Normalize to ISO-8601 (YYYY-MM-DD) or correct format."])
            now = pd.Timestamp.now()
            future_idx = dt[dt > now + pd.Timedelta(days=365)].index
            for i in future_idx:
                rows.append([int(i)+1, col, str(s.iloc[i]),
                             "Suspicious future date (> 1 year ahead)",
                             "Confirm timezone/year; correct if mis-keyed."])
            old_idx = dt[dt < pd.Timestamp(1970, 1, 1)].index
            for i in old_idx:
                rows.append([int(i)+1, col, str(s.iloc[i]),
                             "Suspicious historic date (< 1970)",
                             "Check default 1900/1970 bug; replace with null if unknown."])

        # Email format
        if "email" in col_l:
            invalid = ~s.astype(str).str.match(_EMAIL_RE, na=False) & ~blank_mask
            for i in s[invalid].index:
                rows.append([int(i)+1, col, str(s.iloc[i]),
                             "Invalid email format",
                             "Fix typos; validate with regex on input; consider domain allow-list."])

        # ID duplicates
        if col_l.endswith("id") or col_l.startswith("id"):
            dup = s.duplicated(keep=False) & s.notna() & ~blank_mask
            for i in s[dup].index:
                rows.append([int(i)+1, col, str(s.iloc[i]),
                             "Duplicate identifier",
                             "Deduplicate records; enforce UNIQUE constraint."])

        # Long free-text spikes (very long strings)
        if s.dtype == object and not pd.api.types.is_numeric_dtype(s):
            lens = s.dropna().astype(str).str.len()
            if not lens.empty:
                long_th = lens.quantile(0.99)
                long_idx = lens[lens > long_th].index
                for i in long_idx:
                    rows.append([int(i)+1, col, str(s.iloc[i])[:120] + ("…" if len(str(s.iloc[i])) > 120 else ""),
                                 f"Unusually long text (> p99 ≈ {int(long_th)} chars)",
                                 "Trim noise; split into structured fields; cap input length."])

    hdr = ["Row #", "Field", "Value", "Reason", "Recommendation"]
    return hdr, rows
