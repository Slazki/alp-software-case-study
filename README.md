# ALP Software Case Study

This folder contains a complete, repeatable submission package for the HOA DataHub case study.

## What is included

- `supabase/schema.sql` - normalized Postgres schema.
- `supabase/reset_and_seed.sql` - generated schema reset plus cleaned inserts for all CSVs.
- `scripts/clean_and_seed.py` - reads the raw CSVs, cleans/deduplicates them, and regenerates the SQL plus cleaned outputs.
- `scripts/load_to_supabase.py` - optional loader that runs `reset_and_seed.sql` against a Supabase Postgres connection string.
- `one_pager/generate_one_pager.py` - generator for the HOA one-pager. It reads from Supabase when configured, and has a local cleaned-data mode for development.
- `submissions/schema_and_cleaning_rationale.docx` - Task 1/2 rationale document.
- `submissions/automation_proposal.docx` - Task 4 one-page proposal.
- `submissions/examples/SR-04_one_pager.html` - generated example one-pager.

## Supabase setup

1. Create a Supabase project.
2. In Supabase, open SQL Editor.
3. Paste and run `supabase/reset_and_seed.sql`.
4. Optional scripted load:

```powershell
Copy-Item .env.example .env
# edit .env and set SUPABASE_DB_URL
python -m pip install -r requirements.txt
python scripts/load_to_supabase.py
```

For the connection string, use Supabase project settings -> Database -> Connection string -> URI.

## Generate a one-pager

From Supabase:

```powershell
python one_pager/generate_one_pager.py SR-04 --source supabase --summary-mode openai
```

Local development fallback:

```powershell
python one_pager/generate_one_pager.py SR-04 --source local --summary-mode fallback
```

The hosted LLM summary uses the OpenAI Responses API when `OPENAI_API_KEY` is set. The default model can be changed with `OPENAI_MODEL`.

## Regenerate everything local

```powershell
python scripts/clean_and_seed.py
python one_pager/generate_one_pager.py SR-04 --source local --summary-mode fallback
python scripts/build_word_docs.py
```

## AI-use transparency

AI assistance was used to structure the schema, draft cleaning rationale, write the generator scaffolding, and draft the hypothetical automation proposal. The actual cleaning rules are deterministic code, the generated SQL is inspectable, and questionable source values are preserved in `data_quality_flags`
