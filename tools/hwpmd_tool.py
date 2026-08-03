#!/usr/bin/env python3
"""Export HWP5 XML to a self-contained, round-trip-oriented Markdown file.

The exporter intentionally keeps three layers in one .md file:

1. Human-editable HTML/Markdown content.
2. A canonical JSON manifest containing HWP structure and style references.
3. The original HWP bytes and canonical pyhwp XML as verified payloads.

The original HWP payload permits byte-identical recovery when the document has
not been edited. Edited text can later be overlaid onto the embedded HWP
template by an HWP-aware importer without guessing the original formatting.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SCHEMA = "hwpmd/1.0"
HWP_BEGIN = "<!--@hwp-template-begin"
HWP_END = "<!--@hwp-template-end-->"
XML_BEGIN = "<!--@hwp-xml-begin"
XML_END = "<!--@hwp-xml-end-->"
MANIFEST_BEGIN = "<!--@hwp-manifest-begin"
MANIFEST_END = "<!--@hwp-manifest-end-->"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def b64_lines(data: bytes, width: int = 76) -> str:
    value = base64.b64encode(data).decode("ascii")
    return "\n".join(value[i : i + width] for i in range(0, len(value), width))


def xml_obj(element: ET.Element) -> dict[str, Any]:
    """Losslessly model parsed XML order, attributes, text, and children."""
    result: dict[str, Any] = {
        "tag": element.tag,
        "attrs": dict(element.attrib),
    }
    if element.text not in (None, ""):
        result["text"] = element.text
    children = [xml_obj(child) for child in list(element)]
    if children:
        result["children"] = children
    return result


def utf16_hash(text: str) -> str:
    return sha256(text.encode("utf-16le"))


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def heading_level(text: str, style_id: int, in_cell: bool) -> int | None:
    if in_cell:
        return None
    stripped = " ".join(text.split())
    if stripped == "연구개발계획서":
        return 1
    if stripped.replace(" ", "") == "목차":
        return 2
    if style_id == 170 or re.match(r"^\[별첨\s*\d+\]", stripped):
        return 2
    if re.match(r"^\d+\.\s+\S", stripped):
        return 2
    if re.match(r"^\d+-\d+\.\s+\S", stripped):
        return 3
    if re.match(r"^[가-힣]\.\s+\S", stripped):
        return 4
    if re.match(r"^\(\d+\)\s+\S", stripped):
        return 5
    return None


class HwpMdExporter:
    def __init__(self, source: Path, xml_path: Path) -> None:
        self.source = source
        self.xml_path = xml_path
        self.source_bytes = source.read_bytes()
        self.xml_bytes = xml_path.read_bytes()
        self.root = ET.fromstring(self.xml_bytes)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.counts = Counter(element.tag for element in self.root.iter())
        self.section_summaries: list[dict[str, Any]] = []
        self.table_counter = 0
        self.image_counter = 0

        docinfo = self.root.find("DocInfo")
        if docinfo is None:
            raise ValueError("DocInfo not found in pyhwp XML")
        idmappings = docinfo.find("IdMappings")
        self.styles = idmappings.findall("Style") if idmappings is not None else []

    def style_name(self, style_id: int) -> str:
        if 0 <= style_id < len(self.styles):
            return self.styles[style_id].attrib.get("local-name", "")
        return ""

    def make_manifest(self) -> dict[str, Any]:
        summary = self.root.find("HwpSummaryInfo")
        docinfo = self.root.find("DocInfo")
        assert docinfo is not None
        return {
            "schema": SCHEMA,
            "source": {
                "name": self.source.name,
                "size": len(self.source_bytes),
                "sha256": sha256(self.source_bytes),
                "hwp_version": self.root.attrib.get("version", ""),
            },
            "canonical_xml": {
                "size": len(self.xml_bytes),
                "sha256": sha256(self.xml_bytes),
                "compression": "gzip",
                "payload_anchor": "hwp-xml",
            },
            "preservation": {
                "mode": "template-overlay",
                "unmodified_recovery": "byte-identical",
                "edited_recovery": (
                    "overlay edited anchored nodes onto the embedded HWP template "
                    "using an HWP-aware writer; do not infer formatting from Markdown headings"
                ),
                "unit": "HWPUNIT (1/7200 inch)",
                "line_segments": (
                    "layout snapshot only; an HWP layout engine must repaginate edited text"
                ),
            },
            "counts": dict(sorted(self.counts.items())),
            "summary_info": xml_obj(summary) if summary is not None else None,
            "doc_info": xml_obj(docinfo),
            "sections": self.section_summaries,
            "nodes": self.nodes,
        }

    def paragraph_text(self, paragraph: ET.Element) -> str:
        output: list[str] = []
        for lineseg in paragraph.findall("LineSeg"):
            for child in list(lineseg):
                if child.tag == "Text":
                    output.append(child.text or "")
                elif child.tag == "ControlChar":
                    name = child.attrib.get("name", "")
                    if name == "TAB":
                        output.append("\t")
                    elif name == "LINE_BREAK":
                        output.append("\n")
                    elif name in {"FIXWIDTH_SPACE", "NONBREAK_SPACE"}:
                        output.append(" ")
        return "".join(output)

    def control_snapshot(self, child: ET.Element, reference: str | None = None) -> dict[str, Any]:
        item: dict[str, Any] = {
            "kind": child.tag,
            "attrs": dict(child.attrib),
        }
        if child.text not in (None, ""):
            item["text"] = child.text
        if reference is not None:
            item["reference"] = reference
        elif list(child):
            item["xml"] = xml_obj(child)
        return item

    def render_text_run(self, element: ET.Element) -> str:
        text = html.escape(element.text or "", quote=False)
        charshape = element.attrib.get("charshape-id", "")
        language = element.attrib.get("lang", "")
        attrs = []
        if charshape:
            attrs.append(f'data-hwp-cs="{html.escape(charshape)}"')
        if language:
            attrs.append(f'lang="{html.escape(language)}"')
        return f"<span {' '.join(attrs)}>{text}</span>"

    def render_control_char(self, element: ET.Element) -> str:
        name = element.attrib.get("name", "UNKNOWN")
        escaped = html.escape(name, quote=True)
        if name == "PARAGRAPH_BREAK":
            return ""
        if name == "TAB":
            return f'<span data-hwp-ctl="{escaped}">&#9;</span>'
        if name == "LINE_BREAK":
            return f'<br data-hwp-ctl="{escaped}">'
        if name in {"FIXWIDTH_SPACE", "NONBREAK_SPACE"}:
            return f'<span data-hwp-ctl="{escaped}"> </span>'
        return f'<span data-hwp-ctl="{escaped}"></span>'

    def render_complex_control(self, element: ET.Element, path: str) -> str:
        if element.tag == "FieldFormula":
            command = element.attrib.get("command", "")
            return (
                f'<span data-hwp-control="FieldFormula" '
                f'data-hwp-node="{html.escape(path)}">'
                f'{html.escape(command, quote=False)}</span>'
            )
        if element.tag == "GShapeObjectControl":
            self.image_counter += 1
            bindata = element.find(".//PictureInfo")
            bindata_id = ""
            if bindata is not None:
                bindata_id = (
                    bindata.attrib.get("bindata-id", "")
                    or bindata.attrib.get("bin-data-id", "")
                    or bindata.attrib.get("storage-id", "")
                )
            label = f"그림 {self.image_counter}"
            if bindata_id:
                label += f": {bindata_id}"
            return (
                f'<span class="hwp-object" data-hwp-control="GShapeObjectControl" '
                f'data-hwp-node="{html.escape(path)}">[{html.escape(label)}]</span>'
            )
        return (
            f'<span class="hwp-control" data-hwp-control="{html.escape(element.tag)}" '
            f'data-hwp-node="{html.escape(path)}"></span>'
        )

    def paragraph_parts(
        self, paragraph: ET.Element, path: str
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        rendered: list[str] = []
        lines: list[dict[str, Any]] = []
        table_paths: list[str] = []
        table_index = 0
        control_index = 0

        for lineseg in paragraph.findall("LineSeg"):
            snapshot: dict[str, Any] = {
                "attrs": dict(lineseg.attrib),
                "items": [],
            }
            for child in list(lineseg):
                if child.tag == "Text":
                    rendered.append(self.render_text_run(child))
                    snapshot["items"].append(
                        {
                            "kind": "Text",
                            "attrs": dict(child.attrib),
                            "text": child.text or "",
                        }
                    )
                elif child.tag == "ControlChar":
                    rendered.append(self.render_control_char(child))
                    snapshot["items"].append(self.control_snapshot(child))
                elif child.tag == "TableControl":
                    table_path = f"{path}.T{table_index:02d}"
                    table_index += 1
                    table_paths.append(table_path)
                    rendered.append(self.render_table(child, table_path))
                    snapshot["items"].append(
                        self.control_snapshot(child, reference=table_path)
                    )
                else:
                    control_path = f"{path}.C{control_index:02d}"
                    control_index += 1
                    rendered.append(self.render_complex_control(child, control_path))
                    snapshot["items"].append(self.control_snapshot(child))
            lines.append(snapshot)
        return rendered, lines, table_paths

    def render_paragraph(
        self, paragraph: ET.Element, path: str, in_cell: bool = False
    ) -> str:
        attrs = dict(paragraph.attrib)
        style_id = int(attrs.get("style-id", "0"))
        plain_text = self.paragraph_text(paragraph)
        rendered, lines, table_paths = self.paragraph_parts(paragraph, path)
        self.nodes[path] = {
            "kind": "paragraph",
            "attrs": attrs,
            "style_name": self.style_name(style_id),
            "original_text": plain_text,
            "original_text_sha256_utf16le": utf16_hash(plain_text),
            "line_segments": lines,
            "tables": table_paths,
        }

        marker = (
            f"<!--@hwp node={path} pid={attrs.get('paragraph-id', '')} "
            f"style={attrs.get('style-id', '')} para={attrs.get('parashape-id', '')}-->"
        )
        content = "".join(rendered)
        if not content:
            content = '<br data-hwp-blank="true">'

        tag = "p"
        level = heading_level(plain_text, style_id, in_cell)
        if level is not None:
            tag = f"h{level}"
        class_name = "hwp-note" if plain_text.lstrip().startswith("※") else "hwp-paragraph"
        html_block = (
            f'<{tag} class="{class_name}" data-hwp-node="{html.escape(path)}" '
            f'data-hwp-style="{attrs.get("style-id", "")}" '
            f'data-hwp-parashape="{attrs.get("parashape-id", "")}">'
            f"{content}</{tag}>"
        )
        return f"{marker}\n{html_block}"

    def render_cell(self, cell: ET.Element, table_path: str, cell_index: int) -> str:
        attrs = dict(cell.attrib)
        row = attrs.get("row", "0")
        col = attrs.get("col", "0")
        cell_path = f"{table_path}.R{int(row):02d}C{int(col):02d}"
        self.nodes[cell_path] = {
            "kind": "table-cell",
            "attrs": attrs,
            "cell_index": cell_index,
            "paragraphs": [],
        }
        cell_paragraphs: list[str] = []
        paragraph_index = 0
        column_index = 0
        for child in list(cell):
            if child.tag == "Paragraph":
                paragraph_path = f"{cell_path}.P{paragraph_index:02d}"
                paragraph_index += 1
                self.nodes[cell_path]["paragraphs"].append(paragraph_path)
                cell_paragraphs.append(
                    self.render_paragraph(paragraph=child, path=paragraph_path, in_cell=True)
                )
            elif child.tag == "ColumnSet":
                column_path = f"{cell_path}.COL{column_index:02d}"
                column_index += 1
                self.nodes[column_path] = {
                    "kind": "column-set",
                    "attrs": dict(child.attrib),
                    "paragraphs": [],
                }
                for nested_index, paragraph in enumerate(child.findall("Paragraph")):
                    paragraph_path = f"{column_path}.P{nested_index:02d}"
                    self.nodes[column_path]["paragraphs"].append(paragraph_path)
                    self.nodes[cell_path]["paragraphs"].append(paragraph_path)
                    cell_paragraphs.append(
                        self.render_paragraph(
                            paragraph=paragraph, path=paragraph_path, in_cell=True
                        )
                    )

        colspan = attrs.get("colspan", "1")
        rowspan = attrs.get("rowspan", "1")
        td_attrs = [
            f'data-hwp-cell="{html.escape(cell_path)}"',
            f'data-hwp-col="{html.escape(col)}"',
            f'data-hwp-row="{html.escape(row)}"',
            f'data-hwp-width="{html.escape(attrs.get("width", ""))}"',
            f'data-hwp-height="{html.escape(attrs.get("height", ""))}"',
            f'data-hwp-borderfill="{html.escape(attrs.get("borderfill-id", ""))}"',
        ]
        if colspan != "1":
            td_attrs.append(f'colspan="{html.escape(colspan)}"')
        if rowspan != "1":
            td_attrs.append(f'rowspan="{html.escape(rowspan)}"')
        return f"<td {' '.join(td_attrs)}>\n" + "\n".join(cell_paragraphs) + "\n</td>"

    def render_table(self, table: ET.Element, path: str) -> str:
        self.table_counter += 1
        body = table.find("TableBody")
        if body is None:
            body = table
        rows = body.findall("TableRow")
        self.nodes[path] = {
            "kind": "table",
            "attrs": dict(table.attrib),
            "body_attrs": dict(body.attrib),
            "rows": [],
        }
        table_attrs = [
            f'data-hwp-node="{html.escape(path)}"',
            f'data-hwp-table-id="{html.escape(table.attrib.get("instance-id", ""))}"',
            f'data-hwp-rows="{html.escape(body.attrib.get("rows", str(len(rows))))}"',
            f'data-hwp-cols="{html.escape(body.attrib.get("cols", ""))}"',
        ]
        result = [
            f"<!--@hwp table={path}-->",
            f"<table {' '.join(table_attrs)}>",
            "<tbody>",
        ]
        cell_index = 0
        for row_index, row in enumerate(rows):
            row_path = f"{path}.ROW{row_index:02d}"
            cells = row.findall("TableCell")
            self.nodes[path]["rows"].append(
                {
                    "path": row_path,
                    "attrs": dict(row.attrib),
                    "cells": [
                        f"{path}.R{int(cell.attrib.get('row', '0')):02d}"
                        f"C{int(cell.attrib.get('col', '0')):02d}"
                        for cell in cells
                    ],
                }
            )
            result.append(f'<tr data-hwp-row="{html.escape(row_path)}">')
            for cell in cells:
                result.append(self.render_cell(cell, path, cell_index))
                cell_index += 1
            result.append("</tr>")
        result.extend(["</tbody>", "</table>"])
        return "\n".join(result)

    def render_sections(self) -> str:
        body = self.root.find("BodyText")
        if body is None:
            raise ValueError("BodyText not found in pyhwp XML")
        output: list[str] = []
        labels = {
            0: "표지 및 과제개요",
            1: "요약문",
            2: "본문 및 별첨",
        }
        for section_index, section in enumerate(body.findall("SectionDef")):
            section_path = f"S{section_index}"
            column_set = section.find("ColumnSet")
            paragraphs = (
                column_set.findall("Paragraph") if column_set is not None else []
            )
            layout_children = [
                xml_obj(child)
                for child in list(section)
                if child.tag != "ColumnSet"
            ]
            self.section_summaries.append(
                {
                    "path": section_path,
                    "attrs": dict(section.attrib),
                    "layout": layout_children,
                    "column_set_attrs": dict(column_set.attrib) if column_set is not None else {},
                    "paragraphs": [
                        f"{section_path}.P{index:04d}"
                        for index in range(len(paragraphs))
                    ],
                }
            )
            output.extend(
                [
                    "",
                    f"## Section {section_index}: {labels.get(section_index, '')}",
                    "",
                    f"<!--@hwp section={section_path}-->",
                ]
            )
            for paragraph_index, paragraph in enumerate(paragraphs):
                path = f"{section_path}.P{paragraph_index:04d}"
                if paragraph.attrib.get("new-page") == "1" and paragraph_index > 0:
                    output.append(
                        f'<!--@hwp page-break before={path} explicit="true"-->'
                    )
                output.append(self.render_paragraph(paragraph, path))
                output.append("")
        return "\n".join(output)

    def document_markdown(self) -> str:
        body_markdown = self.render_sections()
        manifest = self.make_manifest()
        manifest_json = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_hash = sha256(manifest_json)
        compressed_xml = gzip.compress(self.xml_bytes, compresslevel=9, mtime=0)
        generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        frontmatter = [
            "---",
            f'hwpmd: "{SCHEMA}"',
            "source:",
            f"  name: {yaml_quote(self.source.name)}",
            f"  size: {len(self.source_bytes)}",
            f"  sha256: {sha256(self.source_bytes)}",
            f"  hwp_version: {yaml_quote(self.root.attrib.get('version', ''))}",
            "serialization:",
            '  preservation: "template-overlay"',
            '  encoding: "UTF-8"',
            '  source_text_encoding: "UTF-16LE"',
            '  unit: "HWPUNIT (1/7200 inch)"',
            f"  generated_utc: {yaml_quote(generated)}",
            "counts:",
            f"  sections: {self.counts.get('SectionDef', 0)}",
            f"  paragraphs: {self.counts.get('Paragraph', 0)}",
            f"  tables: {self.counts.get('TableControl', 0)}",
            f"  table_cells: {self.counts.get('TableCell', 0)}",
            f"  styles: {self.counts.get('Style', 0)}",
            f"  paragraph_shapes: {self.counts.get('ParaShape', 0)}",
            f"  character_shapes: {self.counts.get('CharShape', 0)}",
            f"  border_fills: {self.counts.get('BorderFill', 0)}",
            "payloads:",
            f"  manifest_sha256: {manifest_hash}",
            f"  canonical_xml_sha256: {sha256(self.xml_bytes)}",
            f"  canonical_xml_gzip_size: {len(compressed_xml)}",
            "---",
        ]

        introduction = """
# 연구개발계획서 — HWP-MD 보존본

이 파일은 일반 Markdown 변환본이 아니라 HWP 형식 복원을 고려한 자체 완결형 보존본이다.

- **편집 권위층:** 아래 `문서 본문`의 앵커가 붙은 HTML/Markdown 텍스트
- **서식 권위층:** 문서 하단의 canonical JSON manifest
- **무손실 권위층:** 원본 HWP 전체 base64 payload
- **검증 권위층:** pyhwp canonical XML gzip payload

## 편집 규칙

1. `<!--@hwp ...-->`, `data-hwp-*` 속성, 표의 `rowspan`/`colspan`은 삭제하거나 바꾸지 않는다.
2. 본문 문구는 해당 앵커 바로 다음의 텍스트만 수정한다.
3. 문단을 새로 만들 때는 `clone-from="기존 노드 경로"`를 명시해야 기존 서식을 재사용할 수 있다.
4. 삭제는 앵커 제거가 아니라 manifest/importer에서 명시적 `delete` 작업으로 처리한다.
5. Markdown 제목(`#`)이나 GFM 파이프 표를 서식의 근거로 사용하지 않는다. 실제 서식은 style/shape ID가 우선한다.
6. 편집 후 HWP 저장 시 한글 엔진이 줄 배치와 미리보기를 재생성하므로 모양은 유지할 수 있지만 파일 바이트 동일성은 목표가 아니다.

## 문서 본문

<!--@hwp-document-begin-->
""".strip()

        payloads = f"""
<!--@hwp-document-end-->

## HWP 구조 매니페스트

아래 블록은 자동 처리용이다. 직접 편집하지 않는다.

{MANIFEST_BEGIN} bytes={len(manifest_json)} sha256={manifest_hash} encoding=utf-8-->
```hwp-manifest-json
{manifest_json.decode("utf-8")}
```
{MANIFEST_END}

## Canonical HWP XML

아래 블록은 pyhwp XML을 gzip으로 압축한 검증·복원 보조 payload다.

{XML_BEGIN} bytes={len(self.xml_bytes)} compressed-bytes={len(compressed_xml)} sha256={sha256(self.xml_bytes)} encoding=gzip+base64-->
```hwp-xml-gzip-base64
{b64_lines(compressed_xml)}
```
{XML_END}

## 원본 HWP 템플릿

아래 블록은 원본 HWP 전체를 담는다. 본문이 수정되지 않은 경우 byte-identical 복구에 사용한다.

{HWP_BEGIN} bytes={len(self.source_bytes)} sha256={sha256(self.source_bytes)} encoding=base64-->
```hwp-template-base64
{b64_lines(self.source_bytes)}
```
{HWP_END}
""".strip()

        return (
            "\n".join(frontmatter)
            + "\n\n"
            + introduction
            + "\n"
            + body_markdown
            + "\n"
            + payloads
            + "\n"
        )


def extract_fenced_payload(
    text: str, begin_marker: str, end_marker: str, fence_name: str
) -> tuple[dict[str, str], str]:
    begin = text.find(begin_marker)
    if begin < 0:
        raise ValueError(f"begin marker not found: {begin_marker}")
    header_end = text.find("-->", begin)
    if header_end < 0:
        raise ValueError(f"unterminated marker: {begin_marker}")
    end = text.find(end_marker, header_end)
    if end < 0:
        raise ValueError(f"end marker not found: {end_marker}")
    header = text[begin + len(begin_marker) : header_end]
    attrs = dict(re.findall(r"([A-Za-z0-9_-]+)=([^\s>]+)", header))
    fence_start = text.find(f"```{fence_name}", header_end, end)
    if fence_start < 0:
        raise ValueError(f"fence not found: {fence_name}")
    data_start = text.find("\n", fence_start, end)
    fence_end = text.find("\n```", data_start, end)
    if data_start < 0 or fence_end < 0:
        raise ValueError(f"invalid fenced payload: {fence_name}")
    return attrs, text[data_start + 1 : fence_end]


def validate_markdown(path: Path, source: Path | None = None) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    hwp_attrs, hwp_b64 = extract_fenced_payload(
        text, HWP_BEGIN, HWP_END, "hwp-template-base64"
    )
    hwp_data = base64.b64decode("".join(hwp_b64.split()), validate=True)
    if len(hwp_data) != int(hwp_attrs["bytes"]):
        raise ValueError("embedded HWP size mismatch")
    if sha256(hwp_data) != hwp_attrs["sha256"].upper():
        raise ValueError("embedded HWP SHA-256 mismatch")
    if source is not None and hwp_data != source.read_bytes():
        raise ValueError("embedded HWP payload is not byte-identical to source")

    xml_attrs, xml_b64 = extract_fenced_payload(
        text, XML_BEGIN, XML_END, "hwp-xml-gzip-base64"
    )
    xml_data = gzip.decompress(
        base64.b64decode("".join(xml_b64.split()), validate=True)
    )
    if len(xml_data) != int(xml_attrs["bytes"]):
        raise ValueError("embedded XML size mismatch")
    if sha256(xml_data) != xml_attrs["sha256"].upper():
        raise ValueError("embedded XML SHA-256 mismatch")
    ET.fromstring(xml_data)

    manifest_attrs, manifest_text = extract_fenced_payload(
        text, MANIFEST_BEGIN, MANIFEST_END, "hwp-manifest-json"
    )
    manifest_data = manifest_text.encode("utf-8")
    if len(manifest_data) != int(manifest_attrs["bytes"]):
        raise ValueError("manifest size mismatch")
    if sha256(manifest_data) != manifest_attrs["sha256"].upper():
        raise ValueError("manifest SHA-256 mismatch")
    manifest = json.loads(manifest_text)

    marker_counts = {
        "paragraph_markers": len(re.findall(r"<!--@hwp node=[^ >]+ pid=", text)),
        "table_markers": len(re.findall(r"<!--@hwp table=", text)),
        "cell_elements": len(re.findall(r"<td data-hwp-cell=", text)),
        "section_markers": len(re.findall(r"<!--@hwp section=", text)),
    }
    expected = {
        "paragraph_markers": manifest["counts"].get("Paragraph", 0),
        "table_markers": manifest["counts"].get("TableControl", 0),
        "cell_elements": manifest["counts"].get("TableCell", 0),
        "section_markers": manifest["counts"].get("SectionDef", 0),
    }
    if marker_counts != expected:
        raise ValueError(
            f"visible structure count mismatch: {marker_counts} != {expected}"
        )
    return {
        "schema": manifest["schema"],
        "source_sha256": sha256(hwp_data),
        "xml_sha256": sha256(xml_data),
        "manifest_sha256": sha256(manifest_data),
        **marker_counts,
        "nodes": len(manifest["nodes"]),
    }


def restore_original(markdown: Path, output: Path) -> None:
    text = markdown.read_text(encoding="utf-8")
    attrs, payload = extract_fenced_payload(
        text, HWP_BEGIN, HWP_END, "hwp-template-base64"
    )
    data = base64.b64decode("".join(payload.split()), validate=True)
    if len(data) != int(attrs["bytes"]) or sha256(data) != attrs["sha256"].upper():
        raise ValueError("embedded HWP payload failed integrity validation")
    output.write_bytes(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="create a self-contained HWP-MD file")
    export.add_argument("--source", type=Path, required=True)
    export.add_argument("--xml", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)

    validate = sub.add_parser("validate", help="validate all embedded payloads")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--source", type=Path)

    restore = sub.add_parser(
        "restore-original", help="restore the embedded original HWP byte-for-byte"
    )
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        exporter = HwpMdExporter(args.source.resolve(), args.xml.resolve())
        markdown = exporter.document_markdown()
        args.output.write_text(markdown, encoding="utf-8", newline="\n")
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "bytes": args.output.stat().st_size,
                    "sha256": sha256(args.output.read_bytes()),
                    "tables_rendered": exporter.table_counter,
                    "images_seen": exporter.image_counter,
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "validate":
        result = validate_markdown(args.input, args.source)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "restore-original":
        restore_original(args.input, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "bytes": args.output.stat().st_size,
                    "sha256": sha256(args.output.read_bytes()),
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
