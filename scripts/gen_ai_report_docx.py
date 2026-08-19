# -*- coding: utf-8 -*-
"""将 AI 领域进展技术报告 Markdown 源稿转换为格式化的 Word (.docx)。

用法: python gen_ai_report_docx.py <md路径> <docx输出路径>
"""
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

SRC = "/home/lcz/XA202612-2/AI领域进展技术报告_20260802-0809.md"
OUT = "/home/lcz/XA202612-2/AI领域进展技术报告_2026-08-09.docx"

BODY_FONT = "宋体"
HEADING_FONT = "黑体"


def set_run_font(run, name=BODY_FONT, size=12, bold=False, color=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color


def add_para(doc, text, size=12, bold=False, font=BODY_FONT,
             align=None, indent_first=True, space_after=6):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.line_spacing = 1.5
    if indent_first and text:
        pf.first_line_indent = Pt(size * 2)
    if align is not None:
        pf.alignment = align
    # 处理粗体片段 **...**
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = p.add_run(part[2:-2])
            set_run_font(run, font, size, bold=True)
        else:
            run = p.add_run(part)
            set_run_font(run, font, size, bold=bold)
    return p


def main():
    src = SRC if len(sys.argv) < 2 else sys.argv[1]
    out = OUT if len(sys.argv) < 3 else sys.argv[2]
    with open(src, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]

    doc = Document()
    # 页边距
    for sec in doc.sections:
        sec.left_margin = Pt(72)
        sec.right_margin = Pt(72)
        sec.top_margin = Pt(72)
        sec.bottom_margin = Pt(72)

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s == "---":
            continue
        if s.startswith("# "):  # 文档主标题
            p = doc.add_paragraph()
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(12)
            run = p.add_run(s[2:].strip())
            set_run_font(run, HEADING_FONT, 18, bold=True, color=RGBColor(0x1F, 0x30, 0x5A))
            continue
        if s.startswith("## "):  # 一级标题
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(8)
            run = p.add_run(s[3:].strip())
            set_run_font(run, HEADING_FONT, 15, bold=True, color=RGBColor(0x1F, 0x30, 0x5A))
            continue
        if s.startswith("### "):  # 二级标题
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(s[4:].strip())
            set_run_font(run, HEADING_FONT, 13, bold=True)
            continue
        if s.startswith("*") and s.endswith("*") and not s.startswith("**"):  # 页脚斜体
            p = doc.add_paragraph()
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(s.strip("*"))
            set_run_font(run, BODY_FONT, 9, color=RGBColor(0x80, 0x80, 0x80))
            continue
        # 列表项（无序/有序）去掉标记
        m = re.match(r"^[-*] ", s)
        if m:
            text = s[2:]
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent = Pt(24)
            pf.space_after = Pt(4)
            pf.line_spacing = 1.5
            bullet = p.add_run("• ")
            set_run_font(bullet, BODY_FONT, 12)
            parts = re.split(r"(\*\*.*?\*\*)", text)
            for part in parts:
                if not part:
                    continue
                if part.startswith("**") and part.endswith("**"):
                    run = p.add_run(part[2:-2])
                    set_run_font(run, BODY_FONT, 12, bold=True)
                else:
                    run = p.add_run(part)
                    set_run_font(run, BODY_FONT, 12)
            continue
        m = re.match(r"^\d+\. ", s)
        if m:
            text = s
            p = add_para(doc, text, size=12, indent_first=False)
            p.paragraph_format.left_indent = Pt(24)
            p.paragraph_format.space_after = Pt(4)
            continue
        # 普通正文
        add_para(doc, s, size=12)

    doc.save(out)
    print(f"已生成: {out}")


if __name__ == "__main__":
    main()
