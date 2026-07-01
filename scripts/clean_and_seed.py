from __future__ import annotations

import csv
import json
import re
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ROOT / "submissions"
CLEANED_DIR = SUBMISSIONS / "cleaned"
SUPABASE_DIR = ROOT / "supabase"

NULL_MARKERS = {"", "n/a", "na", "none", "null", "tbd"}
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
ROLE_ORDER = {
    "president": 1,
    "vice president": 2,
    "treasurer": 3,
    "secretary": 4,
    "member at large": 5,
}


def is_nullish(value: Any) -> bool:
    return value is None or str(value).strip().lower() in NULL_MARKERS


def as_text(value: Any) -> str | None:
    if is_nullish(value):
        return None
    return str(value).strip()


def add_flag(
    flags: list[dict[str, str | None]],
    entity_type: str,
    entity_key: str,
    field_name: str,
    raw_value: Any,
    cleaned_value: Any,
    issue: str,
    severity: str = "review",
) -> None:
    flags.append(
        {
            "entity_type": entity_type,
            "entity_key": entity_key,
            "field_name": field_name,
            "raw_value": None if raw_value is None else str(raw_value),
            "cleaned_value": None if cleaned_value is None else str(cleaned_value),
            "issue": issue,
            "severity": severity,
        }
    )


def parse_int(value: Any, *, flags: list[dict[str, str | None]], entity_key: str, field: str) -> int | None:
    raw = "" if value is None else str(value).strip()
    if is_nullish(raw):
        add_flag(flags, "association", entity_key, field, raw, None, "Missing numeric value left null.")
        return None
    try:
        return int(raw.replace(",", ""))
    except ValueError:
        add_flag(flags, "association", entity_key, field, raw, None, "Could not parse integer.", "warning")
        return None


def parse_money(
    value: Any,
    *,
    flags: list[dict[str, str | None]],
    entity_type: str,
    entity_key: str,
    field: str,
) -> Decimal | None:
    raw = "" if value is None else str(value).strip()
    if is_nullish(raw):
        add_flag(flags, entity_type, entity_key, field, raw, None, "Missing or placeholder money value left null.")
        return None
    cleaned = re.sub(r"[$,\s]", "", raw)
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        add_flag(flags, entity_type, entity_key, field, raw, None, "Could not parse money value.", "warning")
        return None
    if amount == 0:
        add_flag(flags, entity_type, entity_key, field, raw, amount, "Zero value retained but should be reviewed.")
    return amount


def parse_bool(value: Any) -> bool | None:
    raw = "" if value is None else str(value).strip().lower()
    if raw in {"yes", "y", "true", "1"}:
        return True
    if raw in {"no", "n", "false", "0"}:
        return False
    return None


def parse_month(
    value: Any,
    *,
    flags: list[dict[str, str | None]],
    entity_key: str,
) -> int | None:
    raw = "" if value is None else str(value).strip()
    if is_nullish(raw):
        add_flag(flags, "association", entity_key, "fiscal_year_end", raw, None, "Missing fiscal year end left null.")
        return None
    if raw.isdigit():
        month = int(raw)
        if 1 <= month <= 12:
            return month
    month = MONTHS.get(raw.lower())
    if month:
        return month
    add_flag(flags, "association", entity_key, "fiscal_year_end", raw, None, "Could not parse fiscal year end.", "warning")
    return None


def parse_state(value: Any, *, flags: list[dict[str, str | None]], entity_key: str) -> str:
    raw = "" if value is None else str(value).strip()
    normalized = {
        "ca": "CA",
        "calif.": "CA",
        "california": "CA",
    }.get(raw.lower())
    if normalized:
        if raw != normalized:
            add_flag(flags, "association", entity_key, "state", raw, normalized, "State normalized to postal code.", "info")
        return normalized
    cleaned = raw.upper()[:2] if raw else "CA"
    add_flag(flags, "association", entity_key, "state", raw, cleaned, "Unexpected state value normalized.", "review")
    return cleaned


def parse_date_flexible(
    value: Any,
    *,
    flags: list[dict[str, str | None]],
    entity_type: str,
    entity_key: str,
    field: str,
    flag_missing: bool = True,
) -> tuple[date | None, str]:
    raw = "" if value is None else str(value).strip()
    if is_nullish(raw):
        if flag_missing:
            add_flag(flags, entity_type, entity_key, field, raw, None, "Missing date left null.")
        return None, "unknown"

    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date(), "day"
        except ValueError:
            pass

    match = re.fullmatch(r"(\d{1,2})/(\d{4})", raw)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        if 1 <= month <= 12:
            parsed = date(year, month, 1)
            add_flag(
                flags,
                entity_type,
                entity_key,
                field,
                raw,
                parsed.isoformat(),
                "Month/year date stored as first day of month with month precision.",
                "info",
            )
            return parsed, "month"

    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", raw)
    if match:
        month = MONTHS.get(match.group(1).lower())
        year = int(match.group(2))
        if month:
            parsed = date(year, month, 1)
            add_flag(
                flags,
                entity_type,
                entity_key,
                field,
                raw,
                parsed.isoformat(),
                "Month/year date stored as first day of month with month precision.",
                "info",
            )
            return parsed, "month"

    add_flag(flags, entity_type, entity_key, field, raw, None, "Could not parse date.", "warning")
    return None, "unknown"


def normalize_email(value: Any) -> str | None:
    text = as_text(value)
    return text.lower() if text else None


def phone_parts(value: Any) -> tuple[str | None, str | None]:
    raw = as_text(value)
    if not raw:
        return None, None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        display = f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
        return f"+1{digits}", display
    return digits or None, raw


def normalize_trade(value: Any) -> str:
    trade = as_text(value) or "Unknown"
    return re.sub(r"\s+", " ", trade).strip()


def company_key(name: str) -> str:
    lowered = name.lower()
    lowered = re.sub(r"\b(llc|incorporated|inc|co|company)\b\.?", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def display_company_name(name: str) -> str:
    cleaned = re.sub(r"\b(LLC|Inc\.?|Incorporated|Co\.?|Company)\b\.?$", "", name, flags=re.I).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or name


def split_service_area(value: Any) -> list[str]:
    text = as_text(value)
    if not text:
        return []
    return sorted({part.strip() for part in text.split(",") if part.strip()})


def split_hoa_codes(value: Any) -> list[str]:
    text = as_text(value)
    if not text:
        return []
    return [part.strip().upper() for part in re.split(r"[;,]", text) if part.strip()]


def clean_associations(flags: list[dict[str, str | None]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with (ROOT / "hoas_export.csv").open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            hoa_code = raw["hoa_code"].strip()
            study_date, precision = parse_date_flexible(
                raw["last_reserve_study"],
                flags=flags,
                entity_type="association",
                entity_key=hoa_code,
                field="last_reserve_study",
            )
            has_reserve_study = parse_bool(raw["has_reserve_study"])
            if has_reserve_study is None:
                add_flag(
                    flags,
                    "association",
                    hoa_code,
                    "has_reserve_study",
                    raw["has_reserve_study"],
                    False,
                    "Could not parse reserve-study flag; defaulted to false.",
                    "warning",
                )
                has_reserve_study = False

            rows.append(
                {
                    "hoa_code": hoa_code,
                    "association_name": raw["association_name"].strip(),
                    "city": raw["city"].strip(),
                    "state_code": parse_state(raw["state"], flags=flags, entity_key=hoa_code),
                    "unit_count": parse_int(raw["unit_count"], flags=flags, entity_key=hoa_code, field="unit_count"),
                    "monthly_dues": parse_money(
                        raw["monthly_dues"],
                        flags=flags,
                        entity_type="association",
                        entity_key=hoa_code,
                        field="monthly_dues",
                    ),
                    "fiscal_year_end_month": parse_month(raw["fiscal_year_end"], flags=flags, entity_key=hoa_code),
                    "reserve_balance": parse_money(
                        raw["reserve_balance"],
                        flags=flags,
                        entity_type="association",
                        entity_key=hoa_code,
                        field="reserve_balance",
                    ),
                    "last_reserve_study": study_date,
                    "last_reserve_study_precision": precision,
                    "has_reserve_study": has_reserve_study,
                    "board_email": normalize_email(raw["board_email"]),
                }
            )
    return rows


def clean_board_members(
    flags: list[dict[str, str | None]],
    valid_hoa_codes: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    with (ROOT / "board_members.csv").open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            hoa_code = raw["hoa_code"].strip().upper()
            if hoa_code not in valid_hoa_codes:
                add_flag(flags, "board_member", hoa_code, "hoa_code", hoa_code, None, "Unknown association code.", "warning")
                continue

            term_start, _ = parse_date_flexible(
                raw["term_start"],
                flags=flags,
                entity_type="board_member",
                entity_key=f"{hoa_code}:{raw['full_name']}:{raw['role']}",
                field="term_start",
            )
            term_end, _ = parse_date_flexible(
                raw["term_end"],
                flags=flags,
                entity_type="board_member",
                entity_key=f"{hoa_code}:{raw['full_name']}:{raw['role']}",
                field="term_end",
            )
            email = normalize_email(raw["email"])
            if not email:
                add_flag(
                    flags,
                    "board_member",
                    f"{hoa_code}:{raw['full_name']}:{raw['role']}",
                    "email",
                    raw["email"],
                    None,
                    "Board member email missing.",
                )

            key = (
                hoa_code,
                raw["full_name"].strip().lower(),
                raw["role"].strip().lower(),
                email,
                term_start.isoformat() if term_start else None,
                term_end.isoformat() if term_end else None,
            )
            if key in seen:
                add_flag(
                    flags,
                    "board_member",
                    f"{hoa_code}:{raw['full_name']}:{raw['role']}",
                    "row",
                    str(raw),
                    "deduplicated",
                    "Exact duplicate board member row removed.",
                    "info",
                )
                continue
            seen.add(key)
            rows.append(
                {
                    "hoa_code": hoa_code,
                    "full_name": raw["full_name"].strip(),
                    "role": raw["role"].strip(),
                    "email": email,
                    "term_start": term_start,
                    "term_end": term_end,
                }
            )

    rows.sort(key=lambda row: (row["hoa_code"], ROLE_ORDER.get(row["role"].lower(), 99), row["full_name"]))
    return rows


def clean_vendors(
    flags: list[dict[str, str | None]],
    valid_hoa_codes: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    duplicate_relationships: set[tuple[str, str]] = set()

    with (ROOT / "vendors_intake.csv").open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            source_name = raw["vendor_name"].strip()
            trade = normalize_trade(raw["trade"])
            email = normalize_email(raw["email"])
            phone_e164, phone_display = phone_parts(raw["phone"])
            key = (
                f"email:{email}"
                if email
                else f"phone:{phone_e164}:{trade.lower()}"
                if phone_e164
                else f"name:{company_key(source_name)}:{trade.lower()}"
            )
            group = groups.setdefault(
                key,
                {
                    "canonical_key": key,
                    "source_names": [],
                    "trade": trade,
                    "phone_e164": phone_e164,
                    "phone_display": phone_display,
                    "email": email,
                    "coi_values": [],
                    "service_area": set(),
                    "served_codes": set(),
                },
            )

            if trade != group["trade"]:
                add_flag(flags, "vendor", key, "trade", f"{group['trade']} / {trade}", group["trade"], "Conflicting trade retained from first matching vendor.", "review")
            if source_name not in group["source_names"]:
                group["source_names"].append(source_name)
            if phone_e164 and not group["phone_e164"]:
                group["phone_e164"] = phone_e164
                group["phone_display"] = phone_display
            if email and not group["email"]:
                group["email"] = email

            coi = parse_bool(raw["coi_on_file"])
            group["coi_values"].append(coi)
            if coi is None:
                add_flag(flags, "vendor", key, "coi_on_file", raw["coi_on_file"], None, "COI value missing or unparseable.")

            group["service_area"].update(split_service_area(raw["service_area"]))
            codes = split_hoa_codes(raw["serves_hoa_codes"])
            if not codes:
                add_flag(flags, "vendor", key, "serves_hoa_codes", raw["serves_hoa_codes"], None, "Intake row has no linked HOA; vendor retained as prospect if no other row links it.", "info")
            for code in codes:
                if code not in valid_hoa_codes:
                    add_flag(flags, "vendor", key, "serves_hoa_codes", code, None, "Unknown HOA code ignored.", "warning")
                    continue
                rel_key = (key, code)
                if rel_key in duplicate_relationships:
                    add_flag(flags, "vendor", key, "serves_hoa_codes", code, code, "Duplicate vendor-HOA relationship removed.", "info")
                duplicate_relationships.add(rel_key)
                group["served_codes"].add(code)

    vendors: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []

    for key, group in groups.items():
        source_names = group["source_names"]
        candidate_names = [display_company_name(name) for name in source_names]
        canonical_name = sorted(candidate_names, key=lambda name: (len(name), name.lower()))[0]
        coi_values = group["coi_values"]
        coi_on_file = True if any(value is True for value in coi_values) else False if any(value is False for value in coi_values) else None
        if any(value is True for value in coi_values) and any(value is False for value in coi_values):
            add_flag(flags, "vendor", key, "coi_on_file", str(coi_values), coi_on_file, "Conflicting COI values; true retained because one source says file exists.", "review")
        if len(source_names) > 1 or any(display_company_name(name) != canonical_name for name in source_names):
            add_flag(
                flags,
                "vendor",
                key,
                "vendor_name",
                "; ".join(source_names),
                canonical_name,
                "Vendor aliases merged because rows shared email or phone/trade.",
                "info",
            )

        vendors.append(
            {
                "canonical_key": key,
                "canonical_name": canonical_name,
                "trade": group["trade"],
                "phone_e164": group["phone_e164"],
                "phone_display": group["phone_display"],
                "email": group["email"],
                "coi_on_file": coi_on_file,
                "service_area": sorted(group["service_area"]),
            }
        )
        for alias in sorted(set(source_names), key=str.lower):
            aliases.append({"canonical_key": key, "alias_name": alias})
        for code in sorted(group["served_codes"]):
            relationships.append({"hoa_code": code, "canonical_key": key})
        if not group["served_codes"]:
            add_flag(flags, "vendor", key, "relationship_status", None, "prospect", "Vendor has no HOA relationship and is retained as a prospect.", "info")

    vendors.sort(key=lambda row: (row["trade"], row["canonical_name"]))
    aliases.sort(key=lambda row: (row["canonical_key"], row["alias_name"]))
    relationships.sort(key=lambda row: (row["hoa_code"], row["canonical_key"]))
    return vendors, aliases, relationships


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return value


def csv_ready(value: Any) -> Any:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return json_ready(value)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_ready(row.get(field)) for field in fieldnames})


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, date):
        return "'" + value.isoformat() + "'"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def sql_text_array(values: list[str]) -> str:
    if not values:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(sql_literal(value) for value in values) + "]::text[]"


def tuple_lines(rows: list[str], suffix: str = "") -> str:
    return ",\n".join(rows) + suffix + ";\n"


def build_seed_sql(
    associations: list[dict[str, Any]],
    board_members: list[dict[str, Any]],
    vendors: list[dict[str, Any]],
    aliases: list[dict[str, Any]],
    relationships: list[dict[str, str]],
    flags: list[dict[str, str | None]],
) -> str:
    schema = (SUPABASE_DIR / "schema.sql").read_text(encoding="utf-8")
    lines = [
        "-- Generated by scripts/clean_and_seed.py. Re-run that script after editing raw CSVs.",
        "drop view if exists public.association_vendor_counts;",
        "drop table if exists public.data_quality_flags, public.association_vendors, public.vendor_aliases, public.vendors, public.board_members, public.associations cascade;",
        "",
        schema,
        "",
        "truncate table public.data_quality_flags, public.association_vendors, public.vendor_aliases, public.vendors, public.board_members, public.associations restart identity cascade;",
        "",
    ]

    assoc_values = []
    for row in associations:
        assoc_values.append(
            "("
            + ", ".join(
                [
                    sql_literal(row["hoa_code"]),
                    sql_literal(row["association_name"]),
                    sql_literal(row["city"]),
                    sql_literal(row["state_code"]),
                    sql_literal(row["unit_count"]),
                    sql_literal(row["monthly_dues"]),
                    sql_literal(row["fiscal_year_end_month"]),
                    sql_literal(row["reserve_balance"]),
                    sql_literal(row["last_reserve_study"]),
                    sql_literal(row["last_reserve_study_precision"]),
                    sql_literal(row["has_reserve_study"]),
                    sql_literal(row["board_email"]),
                ]
            )
            + ")"
        )
    lines.append(
        "insert into public.associations (hoa_code, association_name, city, state_code, unit_count, monthly_dues, fiscal_year_end_month, reserve_balance, last_reserve_study, last_reserve_study_precision, has_reserve_study, board_email) values\n"
        + tuple_lines(assoc_values)
    )

    board_values = []
    for row in board_members:
        board_values.append(
            "("
            + ", ".join(
                [
                    f"(select id from public.associations where hoa_code = {sql_literal(row['hoa_code'])})",
                    sql_literal(row["full_name"]),
                    sql_literal(row["role"]),
                    sql_literal(row["email"]),
                    sql_literal(row["term_start"]),
                    sql_literal(row["term_end"]),
                ]
            )
            + ")"
        )
    lines.append(
        "insert into public.board_members (association_id, full_name, role, email, term_start, term_end) values\n"
        + tuple_lines(board_values, "\non conflict do nothing")
    )

    vendor_values = []
    for row in vendors:
        vendor_values.append(
            "("
            + ", ".join(
                [
                    sql_literal(row["canonical_key"]),
                    sql_literal(row["canonical_name"]),
                    sql_literal(row["trade"]),
                    sql_literal(row["phone_e164"]),
                    sql_literal(row["phone_display"]),
                    sql_literal(row["email"]),
                    sql_literal(row["coi_on_file"]),
                    sql_text_array(row["service_area"]),
                ]
            )
            + ")"
        )
    lines.append(
        "insert into public.vendors (canonical_key, canonical_name, trade, phone_e164, phone_display, email, coi_on_file, service_area) values\n"
        + tuple_lines(vendor_values)
    )

    alias_values = []
    for row in aliases:
        alias_values.append(
            "("
            + ", ".join(
                [
                    f"(select id from public.vendors where canonical_key = {sql_literal(row['canonical_key'])})",
                    sql_literal(row["alias_name"]),
                ]
            )
            + ")"
        )
    lines.append(
        "insert into public.vendor_aliases (vendor_id, alias_name) values\n"
        + tuple_lines(alias_values, "\non conflict do nothing")
    )

    relationship_values = []
    for row in relationships:
        relationship_values.append(
            "("
            + ", ".join(
                [
                    f"(select id from public.associations where hoa_code = {sql_literal(row['hoa_code'])})",
                    f"(select id from public.vendors where canonical_key = {sql_literal(row['canonical_key'])})",
                    sql_literal("active"),
                ]
            )
            + ")"
        )
    lines.append(
        "insert into public.association_vendors (association_id, vendor_id, relationship_status) values\n"
        + tuple_lines(relationship_values, "\non conflict do nothing")
    )

    flag_values = []
    for row in flags:
        flag_values.append(
            "("
            + ", ".join(
                [
                    sql_literal(row["entity_type"]),
                    sql_literal(row["entity_key"]),
                    sql_literal(row["field_name"]),
                    sql_literal(row["raw_value"]),
                    sql_literal(row["cleaned_value"]),
                    sql_literal(row["issue"]),
                    sql_literal(row["severity"]),
                ]
            )
            + ")"
        )
    lines.append(
        "insert into public.data_quality_flags (entity_type, entity_key, field_name, raw_value, cleaned_value, issue, severity) values\n"
        + tuple_lines(flag_values)
    )
    return "\n".join(lines)


def main() -> None:
    SUBMISSIONS.mkdir(exist_ok=True)
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)

    flags: list[dict[str, str | None]] = []
    associations = clean_associations(flags)
    valid_hoa_codes = {row["hoa_code"] for row in associations}
    board_members = clean_board_members(flags, valid_hoa_codes)
    vendors, aliases, relationships = clean_vendors(flags, valid_hoa_codes)

    data = {
        "associations": associations,
        "board_members": board_members,
        "vendors": vendors,
        "vendor_aliases": aliases,
        "association_vendors": relationships,
        "data_quality_flags": flags,
    }
    (CLEANED_DIR / "cleaned_data.json").write_text(
        json.dumps(data, indent=2, default=json_ready),
        encoding="utf-8",
    )

    write_csv(
        CLEANED_DIR / "associations_clean.csv",
        associations,
        [
            "hoa_code",
            "association_name",
            "city",
            "state_code",
            "unit_count",
            "monthly_dues",
            "fiscal_year_end_month",
            "reserve_balance",
            "last_reserve_study",
            "last_reserve_study_precision",
            "has_reserve_study",
            "board_email",
        ],
    )
    write_csv(
        CLEANED_DIR / "board_members_clean.csv",
        board_members,
        ["hoa_code", "full_name", "role", "email", "term_start", "term_end"],
    )
    write_csv(
        CLEANED_DIR / "vendors_clean.csv",
        vendors,
        ["canonical_key", "canonical_name", "trade", "phone_e164", "phone_display", "email", "coi_on_file", "service_area"],
    )
    write_csv(CLEANED_DIR / "vendor_aliases_clean.csv", aliases, ["canonical_key", "alias_name"])
    write_csv(CLEANED_DIR / "association_vendors_clean.csv", relationships, ["hoa_code", "canonical_key"])
    write_csv(
        CLEANED_DIR / "data_quality_flags.csv",
        flags,
        ["entity_type", "entity_key", "field_name", "raw_value", "cleaned_value", "issue", "severity"],
    )

    seed_sql = build_seed_sql(associations, board_members, vendors, aliases, relationships, flags)
    (SUPABASE_DIR / "reset_and_seed.sql").write_text(seed_sql, encoding="utf-8")

    print(f"Cleaned {len(associations)} associations, {len(board_members)} board rows, {len(vendors)} vendors.")
    print(f"Wrote {len(flags)} data-quality flags.")
    print(f"Wrote {SUPABASE_DIR / 'reset_and_seed.sql'}")


if __name__ == "__main__":
    main()
