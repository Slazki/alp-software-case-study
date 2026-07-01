from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ROOT / "submissions"


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCustom",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#123047"),
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCustom",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=14,
        ),
        "heading": ParagraphStyle(
            "HeadingCustom",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#255F85"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "BodyCustom",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#172033"),
            spaceAfter=7,
        ),
        "label": ParagraphStyle(
            "LabelCustom",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#172033"),
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "SmallCustom",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=4,
        ),
    }


def clean(text: str) -> str:
    replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(clean(text), style)


def section(story: list, heading: str, body: list[str], s: dict[str, ParagraphStyle]) -> None:
    story.append(paragraph(heading, s["heading"]))
    for text in body:
        story.append(paragraph(text, s["body"]))


def labeled(story: list, label: str, text: str, s: dict[str, ParagraphStyle]) -> None:
    story.append(paragraph(label, s["label"]))
    story.append(paragraph(text, s["body"]))


def build_pdf(path: Path, story: list, *, top: float = 0.72, bottom: float = 0.72) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=top * inch,
        bottomMargin=bottom * inch,
        title=path.stem.replace("_", " ").title(),
        author="Fahad Majidi",
    )
    doc.build(story)


def schema_and_cleaning_pdf() -> Path:
    s = styles()
    story: list = [
        paragraph("Schema Design and Data Cleaning Rationale", s["title"]),
        paragraph("ALP Software Case Study, Summit Ridge DataHub", s["subtitle"]),
    ]

    section(
        story,
        "Purpose",
        [
            "For this case study I treated the files like a first client export. My goal was to turn three messy spreadsheets into a clean Supabase database that a team could query and maintain. I kept the raw files, wrote repeatable cleaning code, loaded the cleaned records, and generated a one page HOA profile from the cleaned data.",
            "I did not try to hide messy values. When a value was missing, partial, duplicated, or uncertain, I either normalized it with a clear rule or stored a review note in the data quality flags table.",
        ],
        s,
    )

    section(
        story,
        "Schema Choices",
        [
            "The associations table is the central HOA record. It stores the HOA code, name, city, state, unit count, monthly dues, fiscal year end, reserve balance, reserve study status, and board email with proper data types.",
            "The board members table belongs to associations through a foreign key. I kept board service scoped to an association because the file does not prove that repeated names across different HOAs are the same person.",
            "The vendors table stores one cleaned company row per real vendor. The association vendors table is the bridge between HOAs and vendors, which supports vendors serving several associations and associations using several vendors.",
            "The vendor aliases table keeps source names that were merged during cleanup. The data quality flags table records the values I normalized, retained for review, or left blank because inventing an answer would be worse than showing the gap.",
        ],
        s,
    )

    section(
        story,
        "Cleaning Decisions",
        [
            "I normalized state values such as CA, ca, Calif., and California to CA. I parsed monthly dues and reserve balances into numeric values. Blanks, N A, and TBD became null when there was no trustworthy value.",
            "Reserve study dates with only month and year were stored as the first day of that month, and I kept a precision field so the database still shows that the original source was not exact.",
            "I removed the exact duplicate board row for Alex Tanaka. Missing board emails and open term dates were kept blank and flagged for review.",
            "For vendors, I deduplicated by email first, then by phone and trade, then by normalized name and trade. That merged Bright Path Landscaping with Bright Path Landscaping LLC, Coastline Plumbing duplicate rows, and Reliable Electric with Reliable Electrical Services.",
            "Vendors with no HOA relationship were not deleted. I kept them as prospects because that is useful operational data for a management company.",
        ],
        s,
    )

    story.append(PageBreak())

    section(
        story,
        "What I Did",
        [
            "I created the normalized schema, wrote the cleaning and seed script, generated the Supabase reset file, loaded the data into Supabase, and verified the final counts. The loaded database has 12 associations, 52 board member rows, 10 vendors, and 13 vendor links.",
            "I also built the one page generator and generated an example profile for SR 04, The Beacon Pointe Association. I checked the output visually and fixed the layout so long emails did not overlap other fields.",
        ],
        s,
    )

    section(
        story,
        "My Judgment and Review",
        [
            "The vendor cleanup required the most judgment. I did not merge companies only because their names looked similar. I used matching email and phone values as stronger evidence, then preserved every source name as an alias so the original intake history was still visible.",
            "I also chose not to replace unusual values just because they looked wrong. For example, I kept the zero monthly dues value and flagged it for review. I left unknown reserve balances and missing unit counts blank because a reviewer should be able to tell the difference between a confirmed zero and an unknown value.",
            "After the load, I checked the database directly in Supabase. I verified the row counts, opened the tables, and confirmed that the relationships matched the cleaned files. I also generated the SR 04 profile and inspected the visual result before treating the work as complete.",
            "If this were moving into production, my next step would be to add a simple review screen for the data quality flags so staff could confirm or correct uncertain records without editing SQL.",
        ],
        s,
    )

    section(
        story,
        "AI Use",
        [
            "I used AI as a working assistant while building the project. It helped me plan the schema, draft scripts, improve wording, and shape the one page generator.",
            "I reviewed the work myself, corrected generated SQL after Supabase showed an error, reran the load, checked the row counts, inspected the HTML output, and made the final decisions about what to normalize and what to flag.",
        ],
        s,
    )

    path = SUBMISSIONS / "schema_and_cleaning_rationale.pdf"
    build_pdf(path, story)
    return path


def automation_pdf() -> Path:
    s = styles()
    story: list = [
        paragraph("AI Automation Proposal", s["title"]),
        paragraph("Maintenance Intake Triage Assistant for Summit Ridge DataHub", s["subtitle"]),
    ]

    labeled(
        story,
        "Assumptions",
        "I assumed Summit Ridge earns recurring management fees and spends a lot of staff time turning owner messages, board requests, and vendor updates into tracked work. I also assumed the DataHub is meant to become the trusted source for HOA context, board contacts, vendor relationships, and compliance notes.",
        s,
    )
    labeled(
        story,
        "Problem",
        "Maintenance intake is repetitive and easy to route incorrectly. A coordinator has to identify the HOA, understand the issue, decide the trade, check vendor fit, notice missing information, and write a response. SQL is useful after the facts are known, but it does not read messy emails or photos well.",
        s,
    )
    labeled(
        story,
        "What I would build",
        "I would build an intake assistant that reads incoming owner emails, web form entries, and vendor notes. It would produce a draft ticket with the association, issue type, urgency, missing details, suggested vendor choices, COI warnings, and a short draft reply for staff to approve.",
        s,
    )
    labeled(
        story,
        "How I would build it",
        "The AI part would classify and summarize the messy message. The normal code and database queries would handle the reliable checks, such as which vendors serve the association, whether a COI is on file, and which fields are missing. Every draft would be stored with the source message, model output, confidence, and human approval status.",
        s,
    )
    labeled(
        story,
        "Guardrails",
        "A human would approve anything sent to owners, boards, or vendors. Low confidence matches, emergency language, legal topics, and missing HOA matches would go to a review queue. Vendor suggestions would show why they were selected and would clearly warn when COI information is missing or not on file.",
        s,
    )
    labeled(
        story,
        "Why this is worth doing",
        "This would save time on a task that happens every day, while still keeping people in control. It uses AI where AI is useful, reading messy language and drafting a clear summary, and uses deterministic database checks where accuracy matters.",
        s,
    )
    labeled(
        story,
        "AI use on this proposal",
        "I used AI to help draft and tighten this proposal, then I edited it to match the case study, my schema, and the kind of workflow I would actually build next.",
        s,
    )

    path = SUBMISSIONS / "automation_proposal.pdf"
    build_pdf(path, story, top=0.62, bottom=0.62)
    return path


def main() -> None:
    SUBMISSIONS.mkdir(exist_ok=True)
    schema_path = schema_and_cleaning_pdf()
    automation_path = automation_pdf()
    print(f"Wrote {schema_path}")
    print(f"Wrote {automation_path}")


if __name__ == "__main__":
    main()
