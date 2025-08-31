# Sidecar Application: Data Governance  
**Created by:** Salah Aldin Mokhayesh (Aldin AI LLC)  
**Version:** 1.0  
**Last Updated:** 2025-08-31

## 1) What is the Sidecar?
The Sidecar is a companion app that **attaches to an existing data platform** (data lake, warehouse, or any HTTP/S3 source). It **pulls data on demand**, runs governance and quality actions, and **pushes the results back** via the same connection (S3/URI) or exports to local files.

Think of it as a non-invasive “sidecar” next to your platform—no pipelines to rewrite, no schemas to migrate.

---

## 2) High-Level Flow

```
[ Data Lake / Warehouse / HTTP ]  <-- S3/URI -->
                │
                ▼
         Sidecar Application
      ┌──────────────────────────┐
      │  Load ▶ Analyze ▶ Export │
      └──────────────────────────┘
                │
                ▼
[ Result Artifacts (CSV/TXT/S3 objects) ]
```

**Key actions:**
- **Load File** (CSV/TXT) or **Load from URI/S3**
- **Profile** (structure & stats)
- **Quality** (completeness, validity, uniqueness + rules)
- **Catalog** (friendly names & business descriptions; AI-assisted)
- **Compliance** (SLA/status summary)
- **Detect Anomalies** (AI/stats explanations + remediation tips)
- **Generate Synthetic Data** (choose fields + record count)
- **Export CSV/TXT** and **Upload to S3**
- **Little Buddy** (chat assistant; can reference “Knowledge Files” you load)

---

## 3) Supported Inputs/Outputs

**Inputs**
- CSV / Tab-delimited TXT (auto delimiter detection)
- Remote HTTP/HTTPS text via URL
- S3 objects via `s3://bucket/key`
- **Knowledge Files** (images, `.csv`, `.json`, `.txt`, `.md`) used by Little Buddy

**Outputs**
- CSV/TXT exports
- S3 uploads to **Profile/Quality/Catalog/Compliance** buckets (configurable)
- On-screen interactive grid

---

## 4) UI Buttons & What They Do

- **Load Knowledge Files**: Attach one or more reference files that Little Buddy can cite.
- **Load File**: Open a local CSV/TXT and display in the grid.
- **Load from URI/S3**: Pull text from `https://...` or `s3://bucket/key`.
- **Generate Synthetic Data**: Choose count + fields; Sidecar synthesizes realistic values (emails, phones, amounts, dates, addresses, etc.).
- **Quality Rule Assignment**: Map column(s) to regex patterns from a JSON rule set; stored in memory for the session.
- **Profile**: Per-column stats (nulls/blanks/unique/min/max/median/std or length metrics).
- **Quality**: Scores per column (completeness, uniqueness, validity, overall quality).
- **Catalog**: Friendly names + business descriptions; AI-assists based on column tokens.
- **Compliance**: Simple rolled-up SLA/met/not-met view.
- **Detect Anomalies**: Finds outliers/oddities; provides **reason** and **remediation** suggestions.
- **Little Buddy**: Ask questions, request summaries, or generate images (if enabled).
- **Export CSV/TXT** / **Upload to S3**: Save results to local disk or configured buckets.

---

## 5) Configuration (defaults.json)

The app reads `defaults.json` on startup and lets you modify values in **Settings**.

Key fields to know:

```json
{
  "provider": "openai | gemini | azure-openai",
  "openai_api_key": "",
  "openai_base_url": "https://api.openai.com/v1",
  "openai_chat_model_fast": "gpt-4o-mini",
  "openai_chat_model_best": "gpt-4o",
  "openai_image_model": "gpt-image-1",

  "gemini_api_key": "",
  "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta",
  "gemini_chat_model_fast": "gemini-1.5-flash",
  "gemini_chat_model_best": "gemini-1.5-pro",

  "azure_tts_key": "",
  "azure_tts_region": "",

  "aws_access_key_id": "",
  "aws_secret_access_key": "",
  "aws_session_token": "",
  "aws_s3_region": "us-east-1",

  "aws_profile_bucket": "",
  "aws_quality_bucket": "",
  "aws_catalog_bucket": "",
  "aws_compliance_bucket": "",

  "filepath": "C:\\Users\\<you>",
  "max_tokens": "1200",
  "temperature": "0.4"
}
```

> **Security:** Do not commit secrets to source control. Use env vars or a secrets store where possible.

---

## 6) Quality Rules (Regex)

- Load a JSON rules file and assign patterns per field.
- Example rules JSON:

```json
{
  "email": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
  "phone": "^\\d{3}-\\d{3}-\\d{4}$",
  "zip": "^\\d{5}(-\\d{4})?$",
  "amount": "^[0-9]+(\\.[0-9]{2})?$",
  "date": "^\\d{4}-\\d{2}-\\d{2}$"
}
```

- Sidecar computes **Validity %** using either the assigned rule or a smart default for numeric/date/email-like fields.

---

## 7) Catalog (AI-Assisted)

- Generates a **Friendly Name**, **Business Description**, **Type**, **Nullable**, and **Example** for each column.
- Logic:
  1) Tokenize column name (`email_address` → “Email Address”)
  2) Rule-of-thumb descriptions (e.g., id, email, phone, amount, date)
  3) Optional AI enhancement to refine wording for business users

---

## 8) Detect Anomalies (AI + Stats)

**What it flags**
- Unusual value distributions (e.g., z-score > N)
- Suspicious patterns (invalid emails/phones)
- Out-of-range amounts/dates
- Duplicate keys / extreme cardinality shifts

**What it returns**
- **Field** / **Anomaly** / **Reason** / **Recommendation**
  - _Example_:  
    - **Field**: `Loan Amount`  
    - **Anomaly**: Extreme high outliers (top 0.1%)  
    - **Reason**: Tail values beyond 5σ from median  
    - **Recommendation**: Cap at P99.5 or review upstream rules; add range validation

---

## 9) Little Buddy (Assistant)

**Purpose:** Q&A, explanations, code snippets, quick analysis summaries, and optional image generation (if configured).

**Knows about:**
- The loaded dataset (headers + sample)
- Any **Knowledge Files** you attach (e.g., `governance_policies.md`, `naming_standards.txt`, images, JSON docs)

**Useful Prompts**
- “Explain the quality score and how to improve it.”
- “Generate a regex for phone numbers with country code.”
- “Draft a business description for `orig_bal_amt` in plain language.”
- “Find anomalies in this dataset and propose one fix per anomaly.”
- “Create a synthetic dataset with 2,000 rows for fields A, B, and C.”

---

## 10) Synthetic Data Generator

- Choose number of records and any subset of columns.
- Smart generators:
  - **Names**: realistic first/last names; middle initial
  - **Emails**: `{first}.{last}{n}@domain`
  - **Phones**: `AAA-BBB-CCCC`
  - **Addresses**: street, city, state, ZIP
  - **Amounts**: `float` in realistic ranges
  - **Dates**: YYYY-MM-DD spanning recent years
- Great for demos, sandboxes, and unit tests.

---

## 11) Buckets & Result Artifacts

- **Profile** → `aws_profile_bucket`
- **Quality** → `aws_quality_bucket`
- **Catalog** → `aws_catalog_bucket`
- **Compliance** → `aws_compliance_bucket`

Each export writes a timestamped CSV, e.g.:  
`Profile_20250115_153045.csv`

---

## 12) Troubleshooting

- **401 Unauthorized (OpenAI/Gemini)**  
  Ensure the correct provider is selected in **Settings** and the matching API key is populated. Some providers also require a “base URL”.
- **S3 Access Denied**  
  Verify IAM policy allows `s3:GetObject` for reading and `s3:PutObject` for writing to the target buckets.
- **Large Files**  
  Start with a small sample to profile/quality-check; then scale up.
- **GIF/MP4 Branding**  
  Use `assets/sidecar-01-black.png` (static) for compatibility across all platforms. Animated headers depend on local codecs.

---

## 13) Governance Checklist (Quick Win)

- [ ] Business-friendly catalog for all shared tables  
- [ ] Column-level quality rules (regex/format/range)  
- [ ] Minimum viable anomaly monitoring (daily)  
- [ ] SLA dashboard (Compliance) exported to S3  
- [ ] Synthetic data for dev/test mirroring real distributions  
- [ ] Documented escalation runbook for broken quality gates

---

## 14) Glossary

- **Completeness** – % of non-null and non-blank records  
- **Uniqueness** – % of unique values (when a field should be unique)  
- **Validity** – % of values that match a rule/schema  
- **Quality Score** – Average of completeness & validity (configurable)  
- **Catalog** – Human-readable names and business descriptions for fields  
- **Anomaly** – Outlier or unexpected pattern detected in the data

---

## 15) Example Usage Recipe

1. **Load from URI/S3**: `s3://my-bucket/raw/customers.csv`
2. Click **Profile** → review completeness and ranges  
3. Click **Quality Rule Assignment** → apply patterns to `email`, `phone`, `zip`  
4. Click **Quality** → check scores; export CSV  
5. Click **Detect Anomalies** → review reasons & recommendations  
6. Click **Catalog** → AI-assist friendly names & descriptions  
7. **Upload to S3** results → share with your team  
8. Open **Little Buddy** → ask for a summary deck outline

---

## 16) Change Log (v1.0)
- Initial knowledge file
- Captures architecture, flows, features, and operations
- Includes prompts, troubleshooting, and glossary

---

**End of knowledge file** ✅
