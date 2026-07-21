# Document Naming Conventions

> These conventions apply to all project-level markdown files in this workspace.
> Where useful (e.g. translated `.lXX` PDFs, downsampled image PDFs) the same
> qualifier system extends to non-markdown documents — see §3b for resolution.

---

## 1. Full filename anatomy

```
YYMMDD_HHMM__base_name[.4h][.lXX][.rNNNDPI].md
         ^^
         double underscore separates timestamp from base name
```

| Part | Required | Description |
|---|---|---|
| `YYMMDD` or `YYMMDD_HHMM` | Recommended | Timestamp prefix — date or date+time (see §5) |
| `__` | Required if timestamped | **Double underscore** separates timestamp from base name |
| `base_name` | Required | Short descriptive name, lowercase, single underscores |
| `.4h` | Optional | Audience extension: "for humans" (see §2) |
| `.lXX` | Optional | Language extension (see §3) |
| `.rNNNDPI` | Optional | Resolution qualifier for downsampled binary docs (see §3b) |
| `.md` / `.pdf` / … | Required | Always last |

**Examples:**

```
260309_1100__property_context.md              ← ground truth, agent-facing
260309_1100__property_context.4h.lFR.md      ← human-readable, French
260309_1100__property_context.4h.lHU.md      ← human-readable, Hungarian
260309__daily_notes.md                        ← date only, no time
```

**Why double underscore?** Splitting on `__` unambiguously separates the timestamp from the base name, regardless of whether the time component is present:

```python
timestamp, rest = filename.split('__', 1)
# '260309_1100', 'property_context.4h.lHU.md'
# '260309',      'daily_notes.md'
```

---

## 2. Audience extension — `.4h`

| Extension | Meaning |
|---|---|
| *(none)* | Default — ground truth, agent-facing, language-neutral (usually English) |
| `.4h` | "For humans" — styled, translated, may contain tone/context notes |

Rules:
- A file without `.4h` is the authoritative source. Agents read this.
- `.4h` files are derived from the ground truth. All facts must match.
- `.4h` files may include human-oriented sections (tone guidance, message templates, cultural notes) not present in the ground truth.
- `.4h` always appears **before** `.lXX`.

---

## 3. Language extension — `.lXX`

Language is always the **last qualifier** before `.md`. The `l` prefix makes it unambiguous.

| Extension | Language |
|---|---|
| *(none)* | English (or language-neutral) |
| `.lFR` | French |
| `.lHU` | Hungarian |
| `.lDE` | German |
| `.lES` | Spanish |

Rules:
- Language extensions only appear on `.4h` files (translated files are always "for humans").
- Strip `.lXX` to find the source file: `name.4h.lHU.md` → source is `name.md`.
- Strip `.4h.lXX` to find the ground truth: always `name.md`.

---

## 3b. Resolution extension — `.rNNNDPI`

For derived binary documents (mainly PDFs of image-heavy slide decks/scans) that have been **downsampled to reduce file size**, append a resolution qualifier just before the extension. `NNN` is the target DPI as an integer; `DPI` is uppercase and literal.

| Extension | Meaning |
|---|---|
| *(none)* | Original / non-downsampled |
| `.r150DPI` | Downsampled to 150 DPI (default — Ghostscript `/ebook` quality) |
| `.r300DPI` | Downsampled to 300 DPI (high-quality print) |
| `.r96DPI`  | Downsampled to 96 DPI (screen — only when print is irrelevant) |

Rules:
- Applies to `.pdf` (and other raster-bearing binary formats), not `.md`.
- Sits **after** `.lXX` and **before** the extension.
- The original (un-suffixed) file is the source of truth — derived `.rNNNDPI` files may be deleted and regenerated at any time.
- **Default to 150 DPI** when shrinking image-heavy PDFs. Do not go below 150 DPI without an explicit reason — lower settings produce visibly mushy text.

**Example:**
```
260312__fec_conf_diapos.lFR.pdf            ← original (44 MB)
260312__fec_conf_diapos.lFR.r150DPI.pdf    ← compressed (3.6 MB)
```

The `pdf-compress` skill (`~/.claude/skills/pdf-compress/`) automates this.

---

## 4. Combination rules

```
name.md                   = ground truth (no audience, no language qualifier)
name.4h.md                = human-readable, same language as ground truth (rare)
name.4h.lXX.md            = human-readable, translated to language XX
name.lXX.pdf              = exported/translated PDF (binary)
name.lXX.r150DPI.pdf      = downsampled PDF derived from name.lXX.pdf
```

**Order is fixed:** timestamp + `__` → base name → `.4h` → `.lXX` → `.rNNNDPI` → extension

Never: `name.lHU.4h.md` ✗ — language always last among text qualifiers.
Never: `name.r150DPI.lFR.pdf` ✗ — resolution always last before extension.

---

## 5. Timestamp prefix format

Time is optional. Use `__` (double underscore) after the timestamp in both cases:

```
YYMMDD__base_name.md          ← date only
YYMMDD_HHMM__base_name.md     ← date + time (when precision matters)
YYMMDD_HHMMSS__base_name.md     ← date + time (when more precision matters: programitically created docs of parallel processes or other where seconds are worth to be noted)
```

- `YY` = 2-digit year (26 = 2026)
- `MM` = 2-digit month
- `DD` = 2-digit day
- `HHMM` = 24h time, no colon (optional)
- `_` within the timestamp, `__` after it — do **not** use `-`, `:`, or `|`

Both variants sort chronologically when listed alphabetically. Use the creation or publication time of the document, not the last edit time. Omit time when only the date is meaningful (e.g. daily summaries, dated reports).

---

## 6. Ordering prefix — `dd_` or `dddd_`

Some files use a **numeric ordering prefix** that is **not a date**. This is common for Jupyter notebooks and structured tutorial sequences where execution or reading order matters.

```
00_intro.ipynb
01_preprocessing.ipynb
02_feature_engineering.ipynb
10_model_training.ipynb
```

Or with 4 digits for large collections:
```
0010_setup.ipynb
0020_data_loading.ipynb
0100_experiments.ipynb
```

Rules:
- Ordering prefixes use only digits + `_` (single underscore).
- They are **not timestamps** — do not interpret them as dates.
- To distinguish: timestamps are always 6 digits (`YYMMDD`) or 11 (`YYMMDD_HHMM`). Ordering prefixes are 2 or 4 digits.
- Ordering prefixes do **not** use `__` — the double underscore is reserved for the timestamp/base separator.
- Mixing ordering prefixes and timestamp prefixes in the same directory is discouraged.

---

## 7. Directory-level files

- `README.md` — no timestamp prefix (always current, auto-updated)
- `MEMORY.md` — no timestamp (persistent auto-memory, not versioned)
- `config.md` — no timestamp (parameter file, mutable)
- `AGENTS.md` — no timestamp (agent instruction file)

Timestamped files are **immutable by convention** once pushed — create a new file rather than editing an old one if the content changes significantly.
