"""Document parsers for PDF, DOCX, and XLSX files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
import pandas as pd
import pdfplumber
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.exceptions import IngestionError, UnsupportedFileTypeError
from app.ingestion.normalizer import clean_text, normalize_table_rows


@dataclass(slots=True)
class ParsedElement:
    """Normalized raw element extracted from a document."""

    text: str
    page_number: int | None
    section: str
    element_type: str


class DocumentParser:
    """Parse supported files and return normalized elements."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx"}

    def parse(self, file_path: Path) -> list[ParsedElement]:
        """Dispatch parser by extension."""
        extension = file_path.suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise UnsupportedFileTypeError(f"Unsupported file type: {extension}")

        if extension == ".pdf":
            return self._parse_pdf(file_path)
        if extension == ".docx":
            return self._parse_docx(file_path)
        return self._parse_xlsx(file_path)

    def _parse_pdf(self, file_path: Path) -> list[ParsedElement]:
        elements: list[ParsedElement] = []
        try:
            pdf_doc = fitz.open(file_path)
            for page_index, page in enumerate(pdf_doc, start=1):
                text = clean_text(page.get_text("text"))
                if text:
                    elements.append(
                        ParsedElement(
                            text=text,
                            page_number=page_index,
                            section=f"page_{page_index}",
                            element_type="text",
                        )
                    )

            with pdfplumber.open(file_path) as plumber_pdf:
                for page_index, page in enumerate(plumber_pdf.pages, start=1):
                    for table in page.extract_tables() or []:
                        table_text = normalize_table_rows(table)
                        if table_text:
                            elements.append(
                                ParsedElement(
                                    text=table_text,
                                    page_number=page_index,
                                    section=f"table_page_{page_index}",
                                    element_type="table",
                                )
                            )
        except Exception as exc:  # noqa: BLE001
            raise IngestionError(f"Failed to parse PDF {file_path.name}") from exc
        finally:
            if "pdf_doc" in locals():
                pdf_doc.close()

        return elements

    def _parse_docx(self, file_path: Path) -> list[ParsedElement]:
        elements: list[ParsedElement] = []
        try:
            doc = Document(file_path)
            section_name = "document"
            current_page = 1
            table_index = 0

            for block in _iter_docx_blocks(doc):
                if isinstance(block, Paragraph):
                    paragraph_text = clean_text(block.text)
                    style_name = block.style.name if block.style else ""

                    if paragraph_text and style_name.startswith("Heading"):
                        section_name = paragraph_text
                    elif paragraph_text:
                        elements.append(
                            ParsedElement(
                                text=paragraph_text,
                                page_number=current_page,
                                section=section_name,
                                element_type="text",
                            )
                        )

                    if _paragraph_has_page_break(block):
                        current_page += 1
                    continue

                if isinstance(block, Table):
                    table_index += 1
                    table_rows = [
                        [clean_text(cell.text) for cell in row.cells] for row in block.rows
                    ]
                    table_text = normalize_table_rows(table_rows)
                    if table_text:
                        elements.append(
                            ParsedElement(
                                text=table_text,
                                page_number=current_page,
                                section=f"{section_name} / table_{table_index}",
                                element_type="table",
                            )
                        )
        except Exception as exc:  # noqa: BLE001
            raise IngestionError(f"Failed to parse DOCX {file_path.name}") from exc

        return elements

    def _parse_xlsx(self, file_path: Path) -> list[ParsedElement]:
        elements: list[ParsedElement] = []
        try:
            workbook = pd.read_excel(file_path, sheet_name=None)
            for sheet_name, frame in workbook.items():
                if frame.empty:
                    continue
                frame = frame.fillna("")
                header = [clean_text(str(column)) for column in frame.columns]
                row_lines: list[str] = []
                for _, row in frame.iterrows():
                    pairs: list[str] = []
                    for idx, value in enumerate(row.tolist()):
                        column = header[idx] if idx < len(header) else f"column_{idx}"
                        pairs.append(f"{column}: {clean_text(str(value))}")
                    row_line = "; ".join(pairs).strip("; ").strip()
                    if row_line:
                        row_lines.append(row_line)

                text = "\n".join(row_lines).strip()
                if text:
                    elements.append(
                        ParsedElement(
                            text=text,
                            page_number=None,
                            section=f"sheet_{sheet_name}",
                            element_type="table",
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            raise IngestionError(f"Failed to parse XLSX {file_path.name}") from exc

        return elements


def _iter_docx_blocks(doc: DocxDocument):
    parent = doc.element.body
    for child in parent.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def _paragraph_has_page_break(paragraph: Paragraph) -> bool:
    paragraph_xml = paragraph._element.xml  # noqa: SLF001
    return "w:type=\"page\"" in paragraph_xml or "w:lastRenderedPageBreak" in paragraph_xml
