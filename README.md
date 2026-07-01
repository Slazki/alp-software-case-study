# ALP Software Case Study

This repository is my submission for the ALP Software Case Study. The case study asks for a Supabase-backed HOA "DataHub" that turns messy spreadsheet exports into a normalized, queryable database, then uses that database to generate a one-page HOA profile with an AI-assisted summary.

The work here is designed to be repeatable: the raw CSVs stay in the repo, the cleaning rules are implemented in code, the Supabase SQL can be rerun from scratch, and the generated one-pager can be recreated from either Supabase or local cleaned data.

## Reviewer Quick Start

The Supabase database has been loaded successfully when this verification query returns:

| associations | board_members | vendors | vendor_links |
|---:|---:|---:|---:|
| 12 | 52 | 10 | 13 |

Verification SQL:

```sql
select
  (select count(*) from public.associations) as associations,
  (select count(*) from public.board_members) as board_members,
  (select count(*) from public.vendors) as vendors,
  (select count(*) from public.association_vendors) as vendor_links;
```

The generated example one-pager is:

- `submissions/examples/SR-04_one_pager.html`
- `submissions/examples/SR-04_one_pager.md`

The written deliverables are:

- `submissions/schema_and_cleaning_rationale.docx`
- `submissions/automation_proposal.docx`

## What I Built

I built a small, repeatable data pipeline and reporting workflow around the three provided exports:

- `hoas_export.csv`
- `board_members.csv`
- `vendors_intake.csv`

The project includes:

- A normalized Postgres schema for Supabase.
- A deterministic data-cleaning script that parses messy values and deduplicates vendors.
- A generated SQL reset/seed file that creates and loads the database.
- Cleaned CSV/JSON outputs for review.
- A one-pager generator that reads from Supabase when configured.
- A local fallback mode so the generator can still be tested without credentials.
- Two Word deliverables for the written portions of the assignment.

## Repository Structure

```text
.
|-- hoas_export.csv
|-- board_members.csv
|-- vendors_intake.csv
|-- supabase/
|   |-- schema.sql
|   `-- reset_and_seed.sql
|-- scripts/
|   |-- clean_and_seed.py
|   |-- load_to_supabase.py
|   `-- build_word_docs.py
|-- one_pager/
|   `-- generate_one_pager.py
|-- submissions/
|   |-- schema_and_cleaning_rationale.docx
|   |-- automation_proposal.docx
|   |-- cleaned/
|   `-- examples/
|-- requirements.txt
`-- .env.example
```

## Schema Design Summary

The schema models the domain with normalized tables:

- `associations`: one row per HOA, keyed by `hoa_code`, with typed fields for dues, reserves, dates, unit counts, state, and reserve-study status.
- `board_members`: board roster rows linked to `associations` with a foreign key.
- `vendors`: one canonical row per real vendor after deduplication.
- `association_vendors`: many-to-many bridge table between associations and vendors.
- `vendor_aliases`: source-name variants preserved after vendor deduplication.
- `data_quality_flags`: review log for missing, partial, conflicting, or inferred values.

I modeled vendors with a bridge table because a vendor can serve many associations, an association can use many vendors, and some vendors are prospects that serve no association yet.

## Data Cleaning Summary

Cleaning is performed by `scripts/clean_and_seed.py`.

Important cleaning decisions:

- State values like `CA`, `ca`, `Calif.`, and `California` are normalized to `CA`.
- Currency values are parsed into numeric values instead of stored as text.
- `N/A`, blanks, and `TBD` are converted to `null` when the value cannot be trusted.
- Month/year reserve-study dates are stored as the first day of that month and marked with `last_reserve_study_precision = 'month'`.
- The duplicate board-member row is removed.
- Vendor names are deduplicated using normalized email first, then phone/trade, then normalized name/trade.
- Vendor aliases such as `Bright Path Landscaping LLC` are preserved in `vendor_aliases`.
- Prospect vendors are retained in `vendors` even when they have no association link.
- Questionable values are stored in `data_quality_flags` instead of being silently hidden.

## Supabase Setup

The simplest review path is to run the generated SQL directly in Supabase:

1. Create a Supabase project.
2. Open the Supabase SQL Editor.
3. Paste and run `supabase/reset_and_seed.sql`.
4. Run the verification query from the Reviewer Quick Start section.

Optional scripted load:

```powershell
Copy-Item .env.example .env
# edit .env and set SUPABASE_DB_URL
python -m pip install -r requirements.txt
python scripts/load_to_supabase.py
```

`SUPABASE_DB_URL` should be the Supabase Postgres connection string.

## One-Pager Generator

The one-pager generator is in:

```text
one_pager/generate_one_pager.py
```

Generate from Supabase:

```powershell
python one_pager/generate_one_pager.py SR-04 --source supabase --summary-mode openai
```

Generate from local cleaned data:

```powershell
python one_pager/generate_one_pager.py SR-04 --source local --summary-mode fallback
```

The generator outputs both HTML and Markdown into `submissions/examples/`.

The example included in this repo was generated for `SR-04`, The Beacon Pointe Association. It pulls together identity, financials, reserve-study status, board roster, vendors, and a short "Summary / Areas to Watch" section.

## AI-Assisted Summary

The one-pager supports two summary modes:

- `openai`: calls the OpenAI Responses API when `OPENAI_API_KEY` is set.
- `fallback`: uses deterministic Python logic so the report can still be generated without an API key.

The OpenAI model can be configured with:

```text
OPENAI_MODEL
```

If no model is provided, the script uses the default in `.env.example`.

## Regenerating Outputs

Regenerate cleaned data and Supabase SQL:

```powershell
python scripts/clean_and_seed.py
```

Regenerate the local example one-pager:

```powershell
python one_pager/generate_one_pager.py SR-04 --source local --summary-mode fallback
```

Regenerate the Word deliverables:

```powershell
python scripts/build_word_docs.py
```

## Deliverables

Task 1 and Task 2:

- `supabase/schema.sql`
- `supabase/reset_and_seed.sql`
- `submissions/schema_and_cleaning_rationale.docx`
- `submissions/cleaned/`

Task 3:

- `one_pager/generate_one_pager.py`
- `submissions/examples/SR-04_one_pager.html`
- `submissions/examples/SR-04_one_pager.md`

Task 4:

- `submissions/automation_proposal.docx`

## AI-Use Transparency

I used AI tools to help plan the schema, draft the cleaning rationale, scaffold the Python scripts, improve the one-pager layout, and draft the hypothetical automation proposal. I reviewed and corrected the outputs, including fixing SQL generation issues, verifying the Supabase row counts, and checking the generated HTML one-pager visually.

The actual data transformations are deterministic and inspectable in `scripts/clean_and_seed.py`. The generated SQL is inspectable in `supabase/reset_and_seed.sql`. Ambiguous or incomplete data is preserved in `data_quality_flags` rather than being overwritten without explanation.

## Security Notes

No secrets are committed to this repository. `.env.example` shows the expected environment variables, but real `.env` files are ignored by Git.

Do not commit:

- Supabase database passwords
- Supabase service-role keys
- OpenAI API keys
- A real `.env` file
