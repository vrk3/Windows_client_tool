"""Export formats (spec 7.3).

Pro's set is Printer, PDF, Excel, HTML, CSV, XML, SQLite, Text and Email.
Everything here respects the caller's rows, which already carry the current
filter, sort, mode and unit — an exporter that re-derived them would drift from
what the user is looking at.

`reportlab` (PDF) and `openpyxl` (Excel) are optional. A missing one is
reported as "not installed" rather than crashing the export menu, and
`available_formats()` lets the UI show only what can actually be produced.
Text, XML, SQLite, CSV and HTML need nothing beyond the standard library.
"""
import csv
import html
import json
import os
import sqlite3
import xml.sax.saxutils as saxutils


class ExportError(Exception):
    """The export could not be produced. The message is shown to the user."""


def _require(module: str, package: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise ExportError(
            f"{package} is not installed, so this format is unavailable. "
            f"Install it with: pip install {package}") from exc


def available_formats() -> dict:
    """Extension -> label, for the formats this machine can actually write."""
    formats = {
        "csv": "CSV (*.csv)",
        "html": "HTML (*.html)",
        "txt": "Text (*.txt)",
        "xml": "XML (*.xml)",
        "db": "SQLite (*.db)",
        "json": "JSON (*.json)",
    }
    try:
        __import__("openpyxl")
        formats["xlsx"] = "Excel (*.xlsx)"
    except ImportError:
        pass
    try:
        __import__("reportlab")
        formats["pdf"] = "PDF (*.pdf)"
    except ImportError:
        pass
    return formats


def export(path: str, rows, title: str = "TreeSize scan") -> str:
    """Write `rows` to `path`, picking the format from its extension.

    `rows` is a list of tuples with the header first, which is the shape every
    view already produces.
    """
    if len(rows) < 2:
        raise ExportError("There is nothing to export.")
    extension = os.path.splitext(path)[1].lower().lstrip(".")
    writer = _WRITERS.get(extension)
    if writer is None:
        raise ExportError(f"Unknown export format: .{extension}")
    try:
        writer(path, rows, title)
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError(str(exc)) from exc
    return path


def _fit(row, width: int) -> list:
    """A row padded or left long to `width` columns.

    No current producer emits ragged rows -- every view builds uniform
    tuples -- but three writers disagreeing about the same input is worse
    than any single rule. Short rows are PADDED, because the cells that are
    there are still data; long rows are left alone, because an extra cell is
    data too and truncating it loses more than a stray column costs.
    """
    cells = list(row)
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    return cells


# ---- writers ------------------------------------------------------------

def _write_csv(path, rows, _title):
    # utf-8-sig so Excel opens non-ASCII filenames as text rather than mojibake,
    # which is most of the reason anyone exports CSV in the first place.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(rows)


def _write_text(path, rows, title):
    columns = len(rows[0])
    rows = [_fit(row, columns) for row in rows]
    widths = [max(len(str(row[i])) for row in rows)
              for i in range(columns)]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(title + "\n" + "=" * len(title) + "\n\n")
        for index, row in enumerate(rows):
            handle.write("  ".join(str(cell).ljust(widths[i])
                                   for i, cell in enumerate(row)).rstrip() + "\n")
            if index == 0:
                handle.write("  ".join("-" * w for w in widths) + "\n")


def _write_html(path, rows, title):
    head, body = rows[0], rows[1:]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "<!doctype html><meta charset=utf-8>"
            f"<title>{html.escape(title)}</title>"
            "<style>body{font:13px/1.4 system-ui,sans-serif;margin:24px}"
            "table{border-collapse:collapse}"
            "th,td{border:1px solid #bbb;padding:3px 8px;text-align:left}"
            "th{background:#eee}tr:nth-child(even){background:#f7f7f7}</style>"
            f"<h1>{html.escape(title)}</h1><table><tr>"
            + "".join(f"<th>{html.escape(str(c))}</th>" for c in head)
            + "</tr>")
        for row in body:
            handle.write("<tr>" + "".join(
                f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>")
        handle.write("</table>")


def _write_xml(path, rows, title):
    head, body = rows[0], rows[1:]
    tags = [_tag(name) for name in head]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(f"<scan title={saxutils.quoteattr(title)}>\n")
        for row in body:
            handle.write("  <item>\n")
            for tag, cell in zip(tags, row):
                handle.write(f"    <{tag}>{saxutils.escape(str(cell))}</{tag}>\n")
            handle.write("  </item>\n")
        handle.write("</scan>\n")


def _tag(name: str) -> str:
    """A column heading as a legal XML tag.

    Headings are human text -- "% of Parent", "Size (bytes)" -- and neither is
    a valid tag name. A tag must not start with a digit either.
    """
    cleaned = "".join(c if c.isalnum() else "_" for c in name).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = "col_" + cleaned
    return cleaned.lower()


def _write_json(path, rows, title):
    head, body = rows[0], rows[1:]
    payload = {"title": title,
               "items": [dict(zip(head, row)) for row in body]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _write_sqlite(path, rows, title):
    """Spec note: Pro offers SQLite as an EXPORT format, not as the live store.

    An existing file is replaced rather than appended to, so an export is
    always exactly one scan and never a silent accumulation of several.
    """
    head, body = rows[0], rows[1:]
    columns = [_tag(name) for name in head]
    if os.path.exists(path):
        os.remove(path)
    connection = sqlite3.connect(path)
    try:
        columns_sql = ", ".join(f'"{c}" TEXT' for c in columns)
        connection.execute(f"CREATE TABLE scan ({columns_sql})")
        placeholders = ", ".join("?" for _ in columns)
        # The one place a long row IS truncated: the table has a fixed
        # column count, so an extra cell has nowhere to go and executemany
        # would fail the whole export over one row.
        connection.executemany(
            f"INSERT INTO scan VALUES ({placeholders})",
            [tuple(str(cell) for cell in _fit(row, len(columns))[:len(columns)])
             for row in body])
        connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        connection.execute("INSERT INTO meta VALUES (?, ?)", ("title", title))
        connection.commit()
    finally:
        connection.close()


#: Excel's hard ceiling on rows per worksheet. openpyxl does not enforce it
#: -- verified against 3.1.5: append() accepts rows past the end and save()
#: writes them, producing a file Excel will not open.
XLSX_MAX_ROWS = 1_048_576


def _write_xlsx(path, rows, title):
    openpyxl = _require("openpyxl", "openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Scan"

    # openpyxl does NOT enforce Excel's row ceiling: append() accepts rows
    # past the end without complaint and save() writes them into the sheet
    # XML, so the export "succeeds" and Excel then refuses to open the file
    # or repairs it by dropping content. Silent data loss, and reachable --
    # a million entries is an ordinary build server. Capped here, and the
    # cap is STATED in the sheet, exactly as the PDF export states its own.
    body = rows[1:]
    total = len(body)
    truncated = total > XLSX_MAX_ROWS - 1
    if truncated:
        body = body[:XLSX_MAX_ROWS - 2]     # header + the note row

    sheet.append(list(rows[0]))
    for row in body:
        sheet.append(list(row))
    if truncated:
        sheet.append([f"Showing the first {len(body):,} of {total:,} rows — "
                      f"a worksheet cannot hold more than "
                      f"{XLSX_MAX_ROWS:,}."])

    for cell in sheet[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    sheet.freeze_panes = "A2"

    # ONE pass for every column, not one pass per column. At 243k rows and
    # six columns the old form made 1.5M str() calls to answer six questions.
    # A short row is tolerated rather than indexing past the header, which is
    # what it used to do.
    widths = [len(str(value)) for value in rows[0]]
    for row in body:
        for index, value in enumerate(row):
            if index >= len(widths):
                break
            length = len(str(value))
            if length > widths[index]:
                widths[index] = length
    for index, longest in enumerate(widths, start=1):
        sheet.column_dimensions[
            openpyxl.utils.get_column_letter(index)].width = min(60, longest + 2)
    workbook.save(path)


def _write_pdf(path, rows, title):
    _require("reportlab", "reportlab")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    document = SimpleDocTemplate(path, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    # A five-million-row PDF is not a useful artifact; the spec says as much
    # about exports generally. The cap is stated in the document itself rather
    # than silently truncating.
    limit = 2000
    body = rows[1:limit + 1]
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    if len(rows) - 1 > limit:
        story.append(Paragraph(
            f"Showing the first {limit:,} of {len(rows) - 1:,} rows.",
            styles["Normal"]))
        story.append(Spacer(1, 8))
    table = Table([list(rows[0])] + [list(r) for r in body], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    document.build(story)


_WRITERS = {
    "csv": _write_csv,
    "txt": _write_text,
    "html": _write_html,
    "htm": _write_html,
    "xml": _write_xml,
    "json": _write_json,
    "db": _write_sqlite,
    "sqlite": _write_sqlite,
    "xlsx": _write_xlsx,
    "pdf": _write_pdf,
}
