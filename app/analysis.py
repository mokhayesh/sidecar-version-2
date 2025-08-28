import pandas as pd
import re
import csv
from datetime import datetime

# ──────────────────────────────────────────────────────────────
#  Utility Functions
# ──────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────
#  Profile Analysis
# ──────────────────────────────────────────────────────────────
def profile_analysis(df: pd.DataFrame):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(df)
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

    hdr = ["Field", "Total", "Unique", "Completeness (%)", "Nulls", "Blanks",
           "Min", "Max", "Median", "Std", "Analysis Date"]
    return hdr, rows

# ──────────────────────────────────────────────────────────────
#  Quality Analysis
# ──────────────────────────────────────────────────────────────
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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(df)
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

    hdr = ["Field", "Total", "Completeness (%)", "Uniqueness (%)", "Validity (%)",
           "Quality Score (%)", "Analysis Date"]
    return hdr, rows

# ──────────────────────────────────────────────────────────────
#  Catalog Analysis
# ──────────────────────────────────────────────────────────────
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
    if {"amount", "total", "price", "cost", "balance"} & set(tokens):
        return f"Monetary amount representing the {noun}."
    if {"qty", "quantity", "count", "number"} & set(tokens):
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
        dtype = "Numeric" if pd.api.types.is_numeric_dtype(s) else "Date" if "date" in descr else "Text"
        nullable = "Yes" if s.isnull().any() else "No"
        example = str(s.dropna().iloc[0]) if not s.dropna().empty else ""

        rows.append([col, friendly, descr, dtype, nullable, example, now])

    hdr = ["Field", "Friendly Name", "Description", "Data Type",
           "Nullable", "Example", "Analysis Date"]
    return hdr, rows

# ──────────────────────────────────────────────────────────────
#  Compliance Analysis (Static Example)
# ──────────────────────────────────────────────────────────────
def compliance_analysis(_df: pd.DataFrame):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        ["Quality", "MyApp", "DataLake", "Table", "85%", "80%", "✔", "Meets SLA", now],
        ["Completeness", "MyApp", "DataLake", "Table", "85%", "80%", "✔", "Meets SLA", now],
        ["Validity", "MyApp", "DataLake", "Table", "85%", "80%", "✔", "Meets SLA", now],
        ["GLBA", "MyApp", "DataLake", "Table", "85%", "80%", "✔", "Meets SLA", now],
        ["CCPA", "MyApp", "DataLake", "Table", "70%", "80%", "✘", "Below SLA", now]
    ]
    hdr = ["Aspect", "Application", "Layer", "Table", "Score", "SLA",
           "Compliant", "Notes", "Analysis Date"]
    return hdr, rows
