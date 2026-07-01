from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLEANED_JSON = ROOT / "submissions" / "cleaned" / "cleaned_data.json"
EXAMPLE_DIR = ROOT / "submissions" / "examples"

ROLE_ORDER = {
    "president": 1,
    "vice president": 2,
    "treasurer": 3,
    "secretary": 4,
    "member at large": 5,
}


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def money(value: Any, *, cents: bool = False) -> str:
    amount = as_decimal(value)
    if amount is None:
        return "Not on file"
    if cents:
        return f"${amount:,.2f}"
    return f"${amount:,.0f}"


def plain(value: Any, fallback: str = "Not on file") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def month_name(value: Any) -> str:
    if value is None or value == "":
        return "Not on file"
    try:
        month = int(value)
    except (TypeError, ValueError):
        return "Not on file"
    if 1 <= month <= 12:
        return calendar.month_name[month]
    return "Not on file"


def format_date(value: Any, precision: str | None = None) -> str:
    if not value:
        return "Not on file"
    text = str(value)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return text
    if precision == "month":
        return parsed.strftime("%B %Y")
    return parsed.strftime("%b %-d, %Y") if os.name != "nt" else parsed.strftime("%b %#d, %Y")


def reserve_study_label(association: dict[str, Any]) -> str:
    if not association.get("has_reserve_study"):
        return "Reserve study: not on file"
    study_date = format_date(
        association.get("last_reserve_study"),
        association.get("last_reserve_study_precision"),
    )
    if study_date == "Not on file":
        return "Reserve study: marked on file, date not available"
    return f"Reserve study: {study_date}"


def fetch_from_local(identifier: str) -> dict[str, Any]:
    data = json.loads(CLEANED_JSON.read_text(encoding="utf-8"))
    association = next(
        (row for row in data["associations"] if row["hoa_code"].lower() == identifier.lower()),
        None,
    )
    if not association:
        raise SystemExit(f"No local association found for {identifier}. Use an HOA code such as SR-04.")

    hoa_code = association["hoa_code"]
    vendor_by_key = {row["canonical_key"]: row for row in data["vendors"]}
    relationship_keys = [
        row["canonical_key"]
        for row in data["association_vendors"]
        if row["hoa_code"] == hoa_code
    ]
    return {
        "association": association,
        "board_members": [
            row for row in data["board_members"] if row["hoa_code"] == hoa_code
        ],
        "vendors": [vendor_by_key[key] for key in relationship_keys if key in vendor_by_key],
        "flags": [
            row
            for row in data["data_quality_flags"]
            if row["entity_key"] == hoa_code or row["entity_key"].startswith(f"{hoa_code}:")
        ],
    }


def fetch_from_supabase(identifier: str) -> dict[str, Any]:
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL is required when --source supabase is used.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit("Missing dependency: run `python -m pip install -r requirements.txt`.") from exc

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        association = conn.execute(
            """
            select *
            from public.associations
            where lower(hoa_code) = lower(%s) or id::text = %s
            limit 1
            """,
            (identifier, identifier),
        ).fetchone()
        if not association:
            raise SystemExit(f"No association found for {identifier}.")

        board_members = conn.execute(
            """
            select full_name, role, email, term_start, term_end
            from public.board_members
            where association_id = %s
            order by
              case lower(role)
                when 'president' then 1
                when 'vice president' then 2
                when 'treasurer' then 3
                when 'secretary' then 4
                when 'member at large' then 5
                else 99
              end,
              full_name
            """,
            (association["id"],),
        ).fetchall()
        vendors = conn.execute(
            """
            select v.canonical_name, v.trade, v.phone_display, v.email, v.coi_on_file, v.service_area
            from public.association_vendors av
            join public.vendors v on v.id = av.vendor_id
            where av.association_id = %s
            order by v.trade, v.canonical_name
            """,
            (association["id"],),
        ).fetchall()
        flags = conn.execute(
            """
            select entity_type, entity_key, field_name, raw_value, cleaned_value, issue, severity
            from public.data_quality_flags
            where entity_key = %s or entity_key like %s
            order by severity desc, field_name
            """,
            (association["hoa_code"], f"{association['hoa_code']}:%"),
        ).fetchall()

    return {
        "association": dict(association),
        "board_members": [dict(row) for row in board_members],
        "vendors": [dict(row) for row in vendors],
        "flags": [dict(row) for row in flags],
    }


def fallback_summary(profile: dict[str, Any]) -> str:
    association = profile["association"]
    board_members = profile["board_members"]
    vendors = profile["vendors"]
    issues: list[str] = []

    reserve = as_decimal(association.get("reserve_balance"))
    units = association.get("unit_count")
    if not association.get("has_reserve_study"):
        issues.append("a reserve study is not on file")
    if reserve is None:
        issues.append("reserve balance is missing")
    elif units:
        reserve_per_unit = reserve / Decimal(str(units))
        if reserve_per_unit < Decimal("1000"):
            issues.append(f"reserve funding is relatively light at about ${reserve_per_unit:,.0f} per unit")
    if not units:
        issues.append("unit count needs confirmation")

    roles = {member["role"].lower() for member in board_members}
    for required_role in ("president", "treasurer"):
        if required_role not in roles:
            issues.append(f"no {required_role} is listed")
    missing_emails = sum(1 for member in board_members if not member.get("email"))
    if missing_emails:
        issues.append(f"{missing_emails} board email record(s) are missing")
    if not vendors:
        issues.append("no active vendors are linked")
    coi_gaps = [vendor["canonical_name"] for vendor in vendors if vendor.get("coi_on_file") is False]
    if coi_gaps:
        issues.append("COI follow-up is needed for " + ", ".join(coi_gaps))

    if issues:
        watch = "; ".join(issues[:4])
        return (
            f"{association['association_name']} has a usable core profile, with board and vendor records tied back to the "
            f"association code. Areas to watch: {watch}. The next operating step is to confirm the flagged values, then use "
            "the profile as the standing source for board packets and internal account reviews."
        )
    return (
        f"{association['association_name']} has a complete operational profile across identity, finances, governance, and vendors. "
        "No major data gaps stand out from the loaded fields, so routine monitoring should focus on keeping board terms, vendor COIs, "
        "and reserve-study dates current as new documents arrive."
    )


def openai_summary(profile: dict[str, Any]) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
    prompt = {
        "association": profile["association"],
        "board_members": profile["board_members"],
        "vendors": profile["vendors"],
        "quality_flags": profile["flags"][:10],
    }
    payload = {
        "model": model,
        "instructions": (
            "Write a concise HOA management one-pager section called Summary / Areas to Watch. "
            "Use only the supplied structured fields. Flag missing reserve studies, low reserve funding relative to units, "
            "missing board emails or roles, and vendor compliance gaps. Do not invent facts."
        ),
        "input": json.dumps(prompt, default=str),
        "max_output_tokens": 180,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI request failed: {exc.code} {detail}") from exc

    if body.get("output_text"):
        return body["output_text"].strip()
    parts: list[str] = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                parts.append(text)
    if parts:
        return "\n".join(parts).strip()
    raise RuntimeError("OpenAI response did not include output text.")


def make_summary(profile: dict[str, Any], mode: str) -> tuple[str, str]:
    if mode == "fallback":
        return fallback_summary(profile), "fallback"
    if mode in {"auto", "openai"}:
        try:
            return openai_summary(profile), "openai"
        except Exception:
            if mode == "openai":
                raise
            return fallback_summary(profile), "fallback"
    raise ValueError(f"Unknown summary mode: {mode}")


def enrich_profile(profile: dict[str, Any], summary: str, summary_source: str) -> dict[str, Any]:
    board_members = sorted(
        profile["board_members"],
        key=lambda row: (ROLE_ORDER.get(row["role"].lower(), 99), row["full_name"]),
    )
    vendors = sorted(profile["vendors"], key=lambda row: (row["trade"], row["canonical_name"]))
    vendor_counts = Counter(vendor["trade"] for vendor in vendors)
    profile = dict(profile)
    profile["board_members"] = board_members
    profile["vendors"] = vendors
    profile["vendor_counts"] = dict(sorted(vendor_counts.items()))
    profile["summary"] = summary
    profile["summary_source"] = summary_source
    profile["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return profile


def render_html(profile: dict[str, Any]) -> str:
    association = profile["association"]
    board_members = profile["board_members"]
    vendors = profile["vendors"]
    vendor_counts = profile["vendor_counts"]
    reserve = as_decimal(association.get("reserve_balance"))
    units = association.get("unit_count")
    reserve_per_unit = money(reserve / Decimal(str(units))) if reserve is not None and units else "Not available"

    board_rows = "\n".join(
        f"<tr><td>{escape(member['role'])}</td><td>{escape(member['full_name'])}</td><td>{escape(plain(member.get('email'), 'Missing'))}</td><td>{escape(format_date(member.get('term_end')))}</td></tr>"
        for member in board_members
    ) or "<tr><td colspan='4'>No board members linked.</td></tr>"
    vendor_rows = "\n".join(
        f"<tr><td>{escape(vendor['trade'])}</td><td>{escape(vendor['canonical_name'])}</td><td>{escape('Yes' if vendor.get('coi_on_file') else 'No' if vendor.get('coi_on_file') is False else 'Unknown')}</td></tr>"
        for vendor in vendors
    ) or "<tr><td colspan='3'>No vendors linked.</td></tr>"
    vendor_count_text = ", ".join(f"{trade}: {count}" for trade, count in vendor_counts.items()) or "No linked vendors"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(association['hoa_code'])} One-Pager</title>
  <style>
    @page {{ size: Letter; margin: 0.55in; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: #172033;
      font: 13px/1.35 Arial, Helvetica, sans-serif;
      background: #ffffff;
    }}
    main {{ max-width: 7.4in; margin: 0 auto; padding: 0.18in 0; }}
    header {{ border-bottom: 2px solid #255f85; padding-bottom: 10px; margin-bottom: 12px; }}
    .eyebrow {{ color: #5f6b7a; font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; }}
    h1 {{ margin: 2px 0 4px; font-size: 25px; line-height: 1.05; color: #123047; }}
    h2 {{ margin: 13px 0 6px; font-size: 14px; color: #255f85; }}
    p {{ margin: 0 0 7px; }}
    .topline {{ color: #425066; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .facts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-top: 8px; }}
    .fact {{ border: 1px solid #d8dee8; border-left: 4px solid #69a36f; padding: 7px 8px; min-height: 42px; }}
    .label {{ display: block; color: #667085; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .value {{ display: block; color: #172033; font-size: 14px; font-weight: 700; margin-top: 2px; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ border: 1px solid #d8dee8; padding: 5px 6px; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ background: #f1f5f8; color: #23384f; text-align: left; font-size: 11px; }}
    td {{ font-size: 12px; }}
    .summary {{ border: 1px solid #d8dee8; border-left: 4px solid #c78a29; padding: 8px 9px; background: #fffaf2; }}
    .footer {{ margin-top: 10px; color: #667085; font-size: 10px; border-top: 1px solid #d8dee8; padding-top: 6px; }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Summit Ridge DataHub profile - {escape(association['hoa_code'])}</div>
    <h1>{escape(association['association_name'])}</h1>
    <div class="topline">{escape(association['city'])}, {escape(association['state_code'])} | {plain(association.get('unit_count'))} units | Board email: {escape(plain(association.get('board_email')))}</div>
  </header>

  <section class="facts">
    <div class="fact"><span class="label">Monthly dues</span><span class="value">{money(association.get('monthly_dues'), cents=True)}</span></div>
    <div class="fact"><span class="label">Fiscal year end</span><span class="value">{month_name(association.get('fiscal_year_end_month'))}</span></div>
    <div class="fact"><span class="label">Reserve balance</span><span class="value">{money(association.get('reserve_balance'))}</span></div>
    <div class="fact"><span class="label">Reserve per unit</span><span class="value">{reserve_per_unit}</span></div>
  </section>

  <div class="grid">
    <section>
      <h2>Financial Snapshot</h2>
      <p>{escape(reserve_study_label(association))}</p>
      <p>Vendor mix: {escape(vendor_count_text)}</p>
    </section>

    <section>
      <h2>Vendors</h2>
      <table>
        <thead><tr><th style="width: 34%;">Trade</th><th>Vendor</th><th style="width: 20%;">COI</th></tr></thead>
        <tbody>{vendor_rows}</tbody>
      </table>
    </section>
  </div>

  <section>
    <h2>Governance</h2>
    <table>
      <thead><tr><th style="width: 18%;">Role</th><th style="width: 24%;">Name</th><th>Email</th><th style="width: 18%;">Term End</th></tr></thead>
      <tbody>{board_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Summary / Areas To Watch</h2>
    <div class="summary">{escape(profile['summary'])}</div>
  </section>

  <div class="footer">Generated {escape(profile['generated_at'])} from {escape(profile['summary_source'])} summary mode. Regenerate with the same script after database changes.</div>
</main>
</body>
</html>
"""


def render_markdown(profile: dict[str, Any]) -> str:
    association = profile["association"]
    vendors = profile["vendors"]
    board_members = profile["board_members"]
    vendor_counts = ", ".join(f"{trade}: {count}" for trade, count in profile["vendor_counts"].items()) or "No linked vendors"
    lines = [
        f"# {association['association_name']} ({association['hoa_code']})",
        "",
        f"**Location:** {association['city']}, {association['state_code']}  ",
        f"**Units:** {plain(association.get('unit_count'))}  ",
        f"**Board email:** {plain(association.get('board_email'))}",
        "",
        "## Financial Snapshot",
        "",
        f"- Monthly dues: {money(association.get('monthly_dues'), cents=True)}",
        f"- Fiscal year end: {month_name(association.get('fiscal_year_end_month'))}",
        f"- Reserve balance: {money(association.get('reserve_balance'))}",
        f"- {reserve_study_label(association)}",
        "",
        "## Governance",
        "",
    ]
    if board_members:
        for member in board_members:
            lines.append(f"- {member['role']}: {member['full_name']} ({plain(member.get('email'), 'email missing')})")
    else:
        lines.append("- No board members linked.")
    lines.extend(["", "## Vendors", "", f"Vendor mix: {vendor_counts}", ""])
    if vendors:
        for vendor in vendors:
            coi = "yes" if vendor.get("coi_on_file") else "no" if vendor.get("coi_on_file") is False else "unknown"
            lines.append(f"- {vendor['trade']}: {vendor['canonical_name']} (COI: {coi})")
    else:
        lines.append("- No vendors linked.")
    lines.extend(["", "## Summary / Areas To Watch", "", profile["summary"], ""])
    return "\n".join(lines)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Generate an HOA one-pager from Supabase or cleaned local data.")
    parser.add_argument("identifier", help="HOA code such as SR-04, or Supabase association id.")
    parser.add_argument("--source", choices=["auto", "supabase", "local"], default="auto")
    parser.add_argument("--summary-mode", choices=["auto", "openai", "fallback"], default="auto")
    parser.add_argument("--out-dir", default=str(EXAMPLE_DIR))
    args = parser.parse_args()

    if args.source == "auto":
        source = "supabase" if os.environ.get("SUPABASE_DB_URL") else "local"
    else:
        source = args.source

    profile = fetch_from_supabase(args.identifier) if source == "supabase" else fetch_from_local(args.identifier)
    summary, summary_source = make_summary(profile, args.summary_mode)
    profile = enrich_profile(profile, summary, summary_source)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    code = profile["association"]["hoa_code"]
    html_path = out_dir / f"{code}_one_pager.html"
    md_path = out_dir / f"{code}_one_pager.md"
    html_path.write_text(render_html(profile), encoding="utf-8")
    md_path.write_text(render_markdown(profile), encoding="utf-8")
    print(f"Wrote {html_path}")
    print(f"Wrote {md_path}")
    if source == "local":
        print("Used local cleaned data. Use --source supabase after loading the hosted project.")
    if summary_source == "fallback":
        print("Used deterministic fallback summary. Set OPENAI_API_KEY and use --summary-mode openai for hosted LLM output.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
