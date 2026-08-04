from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from lxml import etree
import datetime
import os

doc = Document()

# ═══════════════════════════════════════════════════════════════
# PAGE SETUP
# ═══════════════════════════════════════════════════════════════
for section in doc.sections:
    section.top_margin    = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin   = Cm(2.54)
    section.right_margin  = Cm(2.54)

# ═══════════════════════════════════════════════════════════════
# STYLE SETUP
# ═══════════════════════════════════════════════════════════════
style      = doc.styles['Normal']
font       = style.font
font.name  = 'Calibri'
font.size  = Pt(11)
font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)

HEADING_COLORS = {
    1: RGBColor(0x0F, 0x17, 0x2A),
    2: RGBColor(0x0E, 0x4C, 0x92),
    3: RGBColor(0x06, 0x7A, 0xB2),
}
for level, color in HEADING_COLORS.items():
    h = doc.styles[f'Heading {level}']
    h.font.name      = 'Calibri'
    h.font.color.rgb = color
    h.font.bold      = True

# ═══════════════════════════════════════════════════════════════
# COLOR PALETTE
# ═══════════════════════════════════════════════════════════════
COLORS = {
    # Blues
    'navy'        : '0F172A',
    'dark_blue'   : '0E4C92',
    'mid_blue'    : '0369A1',
    'sky'         : '38BDF8',
    'light_blue'  : 'BAE6FD',
    'pale_blue'   : 'E0F2FE',
    # Greens
    'dark_green'  : '14532D',
    'green'       : '16A34A',
    'light_green' : 'BBF7D0',
    'pale_green'  : 'DCFCE7',
    # Purples
    'dark_purple' : '4C1D95',
    'purple'      : '7C3AED',
    'light_purple': 'DDD6FE',
    'pale_purple' : 'EDE9FE',
    # Oranges / Ambers
    'dark_orange' : '92400E',
    'orange'      : 'D97706',
    'light_orange': 'FDE68A',
    'pale_orange' : 'FEF3C7',
    # Reds / Roses
    'dark_red'    : '881337',
    'red'         : 'E11D48',
    'light_red'   : 'FECDD3',
    'pale_red'    : 'FFF1F2',
    # Teals
    'dark_teal'   : '134E4A',
    'teal'        : '0D9488',
    'light_teal'  : '99F6E4',
    'pale_teal'   : 'CCFBF1',
    # Neutrals
    'white'       : 'FFFFFF',
    'off_white'   : 'F8FAFC',
    'light_gray'  : 'E2E8F0',
    'mid_gray'    : '94A3B8',
    'dark_gray'   : '334155',
    'charcoal'    : '1E293B',
    # Code
    'code_bg'     : '1E293B',
    'code_text'   : 'E2E8F0',
}

# ═══════════════════════════════════════════════════════════════
# LOW-LEVEL XML HELPERS
# ═══════════════════════════════════════════════════════════════
def set_cell_bg(cell, hex_color: str):
    """Fill a table cell background with a hex color."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color)
    tcPr.append(shd)

def set_cell_border(cell, top=None, bottom=None, left=None, right=None):
    """Add borders to individual table cell sides."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for side, color in [('top', top), ('bottom', bottom),
                         ('left', left), ('right', right)]:
        if color:
            el = OxmlElement(f'w:{side}')
            el.set(qn('w:val'),   'single')
            el.set(qn('w:sz'),    '6')
            el.set(qn('w:space'), '0')
            el.set(qn('w:color'), color)
            tcBorders.append(el)
    tcPr.append(tcBorders)

def set_cell_margins(cell, top=60, bottom=60, left=120, right=120):
    """Set internal padding for a cell."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for side, val in [('top', top), ('bottom', bottom),
                       ('left', left), ('right', right)]:
        m = OxmlElement(f'w:{side}')
        m.set(qn('w:w'),    str(val))
        m.set(qn('w:type'), 'dxa')
        tcMar.append(m)
    tcPr.append(tcMar)

def set_paragraph_shading(paragraph, hex_color: str):
    """Set background shading on a paragraph (for code blocks)."""
    pPr = paragraph._element.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color)
    pPr.append(shd)

def add_horizontal_rule(doc, color='38BDF8', thickness=12):
    """Draw a colored horizontal line paragraph."""
    p    = doc.add_paragraph()
    pPr  = p._element.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot  = OxmlElement('w:bottom')
    bot.set(qn('w:val'),   'single')
    bot.set(qn('w:sz'),    str(thickness))
    bot.set(qn('w:space'), '1')
    bot.set(qn('w:color'), color)
    pBdr.append(bot)
    pPr.append(pBdr)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after  = Pt(6)
    return p

def set_row_height(row, height_cm):
    """Force a fixed row height."""
    tr   = row._tr
    trPr = tr.get_or_add_trPr()
    trH  = OxmlElement('w:trHeight')
    trH.set(qn('w:val'),  str(int(height_cm * 567)))
    trH.set(qn('w:hRule'), 'exact')
    trPr.append(trH)

# ═══════════════════════════════════════════════════════════════
# TABLE THEMES
# ═══════════════════════════════════════════════════════════════
TABLE_THEMES = {
    'blue': {
        'header_bg'    : '0E4C92',
        'header_text'  : 'FFFFFF',
        'row_even_bg'  : 'E0F2FE',
        'row_odd_bg'   : 'FFFFFF',
        'border_color' : '38BDF8',
        'alt_text'     : '0F172A',
    },
    'green': {
        'header_bg'    : '14532D',
        'header_text'  : 'FFFFFF',
        'row_even_bg'  : 'DCFCE7',
        'row_odd_bg'   : 'FFFFFF',
        'border_color' : '16A34A',
        'alt_text'     : '14532D',
    },
    'purple': {
        'header_bg'    : '4C1D95',
        'header_text'  : 'FFFFFF',
        'row_even_bg'  : 'EDE9FE',
        'row_odd_bg'   : 'FFFFFF',
        'border_color' : '7C3AED',
        'alt_text'     : '4C1D95',
    },
    'orange': {
        'header_bg'    : '92400E',
        'header_text'  : 'FFFFFF',
        'row_even_bg'  : 'FEF3C7',
        'row_odd_bg'   : 'FFFFFF',
        'border_color' : 'D97706',
        'alt_text'     : '92400E',
    },
    'teal': {
        'header_bg'    : '134E4A',
        'header_text'  : 'FFFFFF',
        'row_even_bg'  : 'CCFBF1',
        'row_odd_bg'   : 'FFFFFF',
        'border_color' : '0D9488',
        'alt_text'     : '134E4A',
    },
    'red': {
        'header_bg'    : '881337',
        'header_text'  : 'FFFFFF',
        'row_even_bg'  : 'FFF1F2',
        'row_odd_bg'   : 'FFFFFF',
        'border_color' : 'E11D48',
        'alt_text'     : '881337',
    },
    'dark': {
        'header_bg'    : '1E293B',
        'header_text'  : '38BDF8',
        'row_even_bg'  : '334155',
        'row_odd_bg'   : '1E293B',
        'border_color' : '38BDF8',
        'alt_text'     : 'E2E8F0',
    },
}

# ═══════════════════════════════════════════════════════════════
# MASTER TABLE BUILDER
# ═══════════════════════════════════════════════════════════════
def add_styled_table(doc, headers, rows,
                     theme='blue',
                     col_widths=None,
                     header_size=10,
                     row_size=9.5,
                     center_cols=None,
                     bold_first_col=False,
                     caption=None):
    """
    Build a fully styled, colored table.

    Parameters
    ----------
    doc          : Document object
    headers      : list[str]  – column header labels
    rows         : list[list] – data rows
    theme        : str        – one of TABLE_THEMES keys
    col_widths   : list[float] – widths in cm per column (optional)
    header_size  : float      – header font size in pt
    row_size     : float      – data row font size in pt
    center_cols  : list[int]  – column indices to center-align
    bold_first_col: bool      – bold the first data column
    caption      : str        – optional italic caption below table
    """
    t      = TABLE_THEMES.get(theme, TABLE_THEMES['blue'])
    ncols  = len(headers)
    nrows  = len(rows)
    center_cols = center_cols or []

    table = doc.add_table(rows=1 + nrows, cols=ncols)
    table.style     = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # ── Header row ──────────────────────────────────────────
    hdr_row = table.rows[0]
    set_row_height(hdr_row, 0.85)
    for i, header in enumerate(headers):
        cell = hdr_row.cells[i]
        set_cell_bg(cell, t['header_bg'])
        set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
        set_cell_border(cell,
                        top=t['border_color'],
                        bottom=t['border_color'],
                        left=t['border_color'],
                        right=t['border_color'])

        cell.text = ''
        para = cell.paragraphs[0]
        para.alignment = (WD_ALIGN_PARAGRAPH.CENTER
                          if i in center_cols
                          else WD_ALIGN_PARAGRAPH.LEFT)
        run = para.add_run(header)
        run.font.bold   = True
        run.font.size   = Pt(header_size)
        run.font.name   = 'Calibri'
        r, g, b = (int(t['header_text'][j:j+2], 16) for j in (0, 2, 4))
        run.font.color.rgb = RGBColor(r, g, b)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # ── Data rows ────────────────────────────────────────────
    for r_idx, row in enumerate(rows):
        bg = t['row_even_bg'] if r_idx % 2 == 0 else t['row_odd_bg']
        data_row = table.rows[r_idx + 1]
        set_row_height(data_row, 0.70)

        for c_idx, value in enumerate(row):
            cell = data_row.cells[c_idx]
            set_cell_bg(cell, bg)
            set_cell_margins(cell, top=60, bottom=60, left=120, right=120)
            set_cell_border(cell,
                            top=t['border_color'],
                            bottom=t['border_color'],
                            left=t['border_color'],
                            right=t['border_color'])

            cell.text = ''
            para = cell.paragraphs[0]
            para.alignment = (WD_ALIGN_PARAGRAPH.CENTER
                              if c_idx in center_cols
                              else WD_ALIGN_PARAGRAPH.LEFT)
            run = para.add_run(str(value))
            run.font.size = Pt(row_size)
            run.font.name = 'Calibri'

            if c_idx == 0 and bold_first_col:
                run.font.bold = True
                r2, g2, b2 = (int(t['alt_text'][j:j+2], 16)
                               for j in (0, 2, 4))
                run.font.color.rgb = RGBColor(r2, g2, b2)
            else:
                run.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)

            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # ── Column widths ─────────────────────────────────────────
    if col_widths:
        for row in table.rows:
            for i, width in enumerate(col_widths):
                if i < len(row.cells):
                    row.cells[i].width = Cm(width)

    # ── Optional caption ──────────────────────────────────────
    if caption:
        p = doc.add_paragraph(f'▲ {caption}')
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after  = Pt(10)
        run = p.runs[0]
        run.font.italic = True
        run.font.size   = Pt(8.5)
        run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(6)

    return table

# ═══════════════════════════════════════════════════════════════
# OTHER HELPERS
# ═══════════════════════════════════════════════════════════════
def add_code_block(doc, code_text, language='bash'):
    """Render a dark-themed monospaced code block."""
    lines = code_text.strip().split('\n')
    # lang label
    lbl  = doc.add_paragraph()
    lrun = lbl.add_run(f'  {language.upper()}')
    lrun.font.name   = 'Consolas'
    lrun.font.size   = Pt(7.5)
    lrun.font.bold   = True
    r, g, b = (int('38BDF8'[j:j+2], 16) for j in (0, 2, 4))
    lrun.font.color.rgb = RGBColor(r, g, b)
    set_paragraph_shading(lbl, '0F172A')
    lbl.paragraph_format.space_before = Pt(8)
    lbl.paragraph_format.space_after  = Pt(0)
    lbl.paragraph_format.left_indent  = Cm(0)

    for idx, line in enumerate(lines):
        p    = doc.add_paragraph()
        run  = p.add_run(f'  {line}')
        run.font.name   = 'Consolas'
        run.font.size   = Pt(9)
        r2, g2, b2 = (int('E2E8F0'[j:j+2], 16) for j in (0, 2, 4))
        run.font.color.rgb = RGBColor(r2, g2, b2)
        set_paragraph_shading(p, '1E293B')
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(0)
        p.paragraph_format.left_indent  = Cm(0)

    # bottom cap
    cap  = doc.add_paragraph()
    set_paragraph_shading(cap, '0F172A')
    cap.paragraph_format.space_before = Pt(0)
    cap.paragraph_format.space_after  = Pt(10)
    return cap

def add_bullet(doc, text, level=0, color='1E293B'):
    """Indented bullet point."""
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent  = Cm(1.0 + level * 0.63)
    p.paragraph_format.space_after  = Pt(3)
    run = p.add_run(text)
    run.font.size = Pt(10.5)
    run.font.name = 'Calibri'
    r, g, b = (int(color[j:j+2], 16) for j in (0, 2, 4))
    run.font.color.rgb = RGBColor(r, g, b)
    return p

def add_numbered(doc, text, color='1E293B'):
    """Numbered list item."""
    p = doc.add_paragraph(style='List Number')
    p.paragraph_format.left_indent = Cm(1.0)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(text)
    run.font.size = Pt(10.5)
    run.font.name = 'Calibri'
    r, g, b = (int(color[j:j+2], 16) for j in (0, 2, 4))
    run.font.color.rgb = RGBColor(r, g, b)
    return p

def add_info_box(doc, text, box_type='info'):
    """
    Colored call-out box for notes, warnings, tips, success.
    box_type: 'info' | 'warning' | 'success' | 'danger' | 'tip'
    """
    configs = {
        'info'   : ('ℹ️  INFO',    'E0F2FE', '0369A1', '0E4C92'),
        'warning': ('⚠️  WARNING', 'FEF3C7', 'D97706', '92400E'),
        'success': ('✅  SUCCESS', 'DCFCE7', '16A34A', '14532D'),
        'danger' : ('🚨  DANGER',  'FFF1F2', 'E11D48', '881337'),
        'tip'    : ('💡  TIP',     'EDE9FE', '7C3AED', '4C1D95'),
    }
    label, bg, border, txt = configs.get(box_type, configs['info'])

    # label bar
    lp = doc.add_paragraph()
    lr = lp.add_run(f'  {label}')
    lr.font.bold  = True
    lr.font.size  = Pt(9)
    lr.font.name  = 'Calibri'
    rb, gb, bb = (int(border[j:j+2], 16) for j in (0, 2, 4))
    lr.font.color.rgb = RGBColor(rb, gb, bb)
    set_paragraph_shading(lp, border)
    lr.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    lp.paragraph_format.space_before = Pt(8)
    lp.paragraph_format.space_after  = Pt(0)

    # body
    bp = doc.add_paragraph()
    br = bp.add_run(f'  {text}')
    br.font.size = Pt(10)
    br.font.name = 'Calibri'
    rt, gt, bt = (int(txt[j:j+2], 16) for j in (0, 2, 4))
    br.font.color.rgb = RGBColor(rt, gt, bt)
    set_paragraph_shading(bp, bg)
    bp.paragraph_format.space_before = Pt(4)
    bp.paragraph_format.space_after  = Pt(10)
    return bp

def add_section_header(doc, text, icon='▶', color='0E4C92', bg='E0F2FE'):
    """Colored sub-section banner strip."""
    p  = doc.add_paragraph()
    r  = p.add_run(f'  {icon}  {text}')
    r.font.bold  = True
    r.font.size  = Pt(11)
    r.font.name  = 'Calibri'
    rc, gc, bc = (int(color[j:j+2], 16) for j in (0, 2, 4))
    r.font.color.rgb = RGBColor(rc, gc, bc)
    set_paragraph_shading(p, bg)
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(6)
    return p

def add_workflow_step(doc, number, title, description, color_theme='blue'):
    """Visual numbered workflow step block."""
    themes = {
        'blue'  : ('0E4C92', 'E0F2FE', '38BDF8'),
        'green' : ('14532D', 'DCFCE7', '16A34A'),
        'purple': ('4C1D95', 'EDE9FE', '7C3AED'),
        'orange': ('92400E', 'FEF3C7', 'D97706'),
        'teal'  : ('134E4A', 'CCFBF1', '0D9488'),
    }
    txt_c, bg_c, acc_c = themes.get(color_theme, themes['blue'])

    p  = doc.add_paragraph()
    r1 = p.add_run(f'  STEP {number}  ')
    r1.font.bold  = True
    r1.font.size  = Pt(9)
    r1.font.name  = 'Calibri'
    ra, ga, ba = (int(acc_c[j:j+2], 16) for j in (0, 2, 4))
    r1.font.color.rgb = RGBColor(ra, ga, ba)

    r2 = p.add_run(f'{title}')
    r2.font.bold  = True
    r2.font.size  = Pt(10.5)
    r2.font.name  = 'Calibri'
    rt, gt, bt = (int(txt_c[j:j+2], 16) for j in (0, 2, 4))
    r2.font.color.rgb = RGBColor(rt, gt, bt)
    set_paragraph_shading(p, bg_c)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after  = Pt(0)

    dp = doc.add_paragraph()
    dr = dp.add_run(f'     {description}')
    dr.font.size = Pt(10)
    dr.font.name = 'Calibri'
    dr.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)
    set_paragraph_shading(dp, 'F8FAFC')
    dp.paragraph_format.space_before = Pt(0)
    dp.paragraph_format.space_after  = Pt(8)
    return dp

def add_kv_row(doc, key, value, key_color='0E4C92', val_color='1E293B'):
    """Key : Value styled paragraph."""
    p  = doc.add_paragraph()
    rk = p.add_run(f'{key}:  ')
    rk.font.bold  = True
    rk.font.size  = Pt(10)
    rk.font.name  = 'Calibri'
    rk.font.color.rgb = RGBColor(
        *[int(key_color[j:j+2], 16) for j in (0, 2, 4)])
    rv = p.add_run(value)
    rv.font.size  = Pt(10)
    rv.font.name  = 'Calibri'
    rv.font.color.rgb = RGBColor(
        *[int(val_color[j:j+2], 16) for j in (0, 2, 4)])
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Cm(0.5)
    return p

# ═══════════════════════════════════════════════════════════════
# ████████████████ TITLE PAGE ████████████████
# ═══════════════════════════════════════════════════════════════
for _ in range(5):
    doc.add_paragraph()

# Project name
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('SentinelOps-Lite')
run.font.size  = Pt(42)
run.font.bold  = True
run.font.name  = 'Calibri'
run.font.color.rgb = RGBColor(0x38, 0xBD, 0xF8)

# Tag line
sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = sub.add_run('Multi-Cloud  ·  AI-Powered  ·  CI/CD Monitoring Platform')
run.font.size  = Pt(16)
run.font.name  = 'Calibri'
run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

add_horizontal_rule(doc, color='38BDF8', thickness=18)

doc.add_paragraph()

# Badge row
def add_badge(paragraph, text, bg_hex, fg_hex='FFFFFF'):
    run = paragraph.add_run(f'  {text}  ')
    run.font.bold  = True
    run.font.size  = Pt(10)
    run.font.name  = 'Calibri'
    r, g, b = (int(fg_hex[j:j+2], 16) for j in (0, 2, 4))
    run.font.color.rgb = RGBColor(r, g, b)

badges = doc.add_paragraph()
badges.alignment = WD_ALIGN_PARAGRAPH.CENTER
for txt, bg in [
    ('🚀 AWS Elastic Beanstalk', '0E4C92'),
    ('   ☁️ Azure App Service', '0369A1'),
    ('   🤖 Gemini AI', '4C1D95'),
    ('   📊 Grafana 11', '134E4A'),
    ('   🔥 Prometheus', '881337'),
]:
    add_badge(badges, txt, bg)

doc.add_paragraph()

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = meta.add_run(
    f'Project Documentation  ·  '
    f'Version 2.0  ·  '
    f'{datetime.date.today().strftime("%B %d, %Y")}'
)
run.font.size  = Pt(11)
run.font.name  = 'Calibri'
run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ TABLE OF CONTENTS ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('Table of Contents', level=1)
add_horizontal_rule(doc, color='38BDF8')

toc = [
    ('1.', 'Project Overview',         '🔍'),
    ('2.', 'Project Architecture',     '🏗️'),
    ('3.', 'Project Workflow',         '⚙️'),
    ('4.', 'Tech Stack',               '🛠️'),
    ('5.', 'Commands Reference',       '💻'),
    ('6.', 'Background Processes',     '🔄'),
    ('7.', 'Results & Outcomes',       '📈'),
    ('8.', 'Errors & Solutions',       '🐛'),
    ('9.', 'Key Learnings',            '🎓'),
    ('10.', 'Appendix',               '📎'),
]
for num, title_text, icon in toc:
    p  = doc.add_paragraph()
    rn = p.add_run(f'  {num}')
    rn.font.bold  = True
    rn.font.size  = Pt(11)
    rn.font.name  = 'Calibri'
    rn.font.color.rgb = RGBColor(0x38, 0xBD, 0xF8)
    ri = p.add_run(f'  {icon}  ')
    ri.font.size  = Pt(11)
    rt = p.add_run(title_text)
    rt.font.size  = Pt(11)
    rt.font.name  = 'Calibri'
    rt.font.color.rgb = RGBColor(0x0E, 0x4C, 0x92)
    p.paragraph_format.space_after  = Pt(4)
    p.paragraph_format.left_indent  = Cm(0.5)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 1. PROJECT OVERVIEW ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('1.  Project Overview', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_section_header(doc, 'What is SentinelOps-Lite?',
                   icon='🔍', color='0E4C92', bg='E0F2FE')
doc.add_paragraph(
    'SentinelOps-Lite is a production-grade, multi-cloud, AI-powered CI/CD monitoring '
    'platform that automates deployment validation, error diagnosis, and infrastructure '
    'observability across AWS Elastic Beanstalk and Azure App Service. It integrates '
    'Prometheus metrics, Grafana dashboards, and Gemini AI agents for intelligent, '
    'automated go/no-go deployment decisions with real-time system monitoring.'
)

add_section_header(doc, 'Key Capabilities', icon='⚡', color='4C1D95', bg='EDE9FE')
capabilities = [
    ('Multi-Cloud Deployment',     'Single GitHub Actions pipeline deploys to AWS or Azure via cloud selection dropdown'),
    ('AI Release Gates',           'Three Gemini AI agents (pre-deploy, error, final) validate every deployment'),
    ('Auto-Provisioned Monitoring','Grafana datasources and dashboards configured automatically — zero manual setup'),
    ('Real-Time Observability',    'Prometheus scrapes Flask, node-exporter, and agent metrics every 10 seconds'),
    ('Public Monitor Dashboard',   '/monitor/status serves a live HTML dashboard with auto-refresh (no auth needed)'),
    ('Secure CI Agent Endpoints',  'POST /monitor/status protected by X-Monitor-Token header authentication'),
]
for cap, desc in capabilities:
    p  = doc.add_paragraph()
    rc = p.add_run(f'  ✦  {cap}: ')
    rc.font.bold  = True
    rc.font.size  = Pt(10.5)
    rc.font.name  = 'Calibri'
    rc.font.color.rgb = RGBColor(0x4C, 0x1D, 0x95)
    rd = p.add_run(desc)
    rd.font.size  = Pt(10.5)
    rd.font.name  = 'Calibri'
    rd.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.left_indent = Cm(0.5)

add_section_header(doc, 'Problem Statement', icon='🚨', color='881337', bg='FFF1F2')
problems = [
    'Grafana dashboards blank after every deploy — required manual Prometheus connection setup',
    'Internal Docker IPs (172.17.0.1, localhost, host.docker.internal) failed in ECS/Azure',
    '/monitor/status returned 403 Forbidden when accessed via browser (GET not handled)',
    'Prometheus scrape targets used broken bridge gateway IPs instead of Docker service names',
    'MONITOR_TOKEN never injected into Flask container — all POST auth attempts returned 401',
    'Separate pipelines required for AWS and Azure — no unified cloud-selection mechanism',
]
for prob in problems:
    add_bullet(doc, prob, level=0, color='881337')

add_section_header(doc, 'Solution Summary', icon='✅', color='14532D', bg='DCFCE7')
solutions = [
    'Grafana $__env{PROMETHEUS_URL} reads dynamically-injected container env var at startup',
    'Deploy scripts resolve real EB CNAME / Azure hostname — no internal IPs ever used',
    'Dual GET + POST handlers on /monitor/status — public dashboard + secure CI endpoint',
    'prometheus.yml updated to use Docker service names (app:5000, node-exporter:9100)',
    'MONITOR_TOKEN injected via sed placeholder in docker-compose.yml from GitHub secrets',
    'Single pipeline.yml with workflow_dispatch cloud input (aws|azure)',
]
for sol in solutions:
    add_bullet(doc, sol, level=0, color='14532D')

add_info_box(doc,
    'SentinelOps-Lite achieves ZERO manual steps after deployment — '
    'every component self-configures and self-verifies.',
    box_type='success')

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 2. PROJECT ARCHITECTURE ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('2.  Project Architecture', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_section_header(doc, 'Multi-Container Stack (5 Services)',
                   icon='🏗️', color='134E4A', bg='CCFBF1')
doc.add_paragraph(
    'All services are coordinated by a docker-compose file and routed through an nginx '
    'reverse proxy on port 80. The 5-container architecture ensures clear separation '
    'of concerns between the application, metrics, visualization, and proxy layers.'
)

add_styled_table(doc,
    headers=['Container', 'Image', 'Port', 'Role', 'Key Config'],
    rows=[
        ['nginx',         'nginx:1.27-alpine',           '80 → 80',   'Reverse Proxy',  'Routes /, /grafana/, /prometheus/, /monitor/'],
        ['app',           'Custom Flask (Python 3.11)',   '5000 → 5000','Flask App',     'Metrics + AI endpoints + monitor dashboard'],
        ['prometheus',    'prom/prometheus:v2.53.0',      '9090 → 9090','Metrics Store', 'Scrapes every 10s — app:5000, node-exporter:9100'],
        ['grafana',       'grafana/grafana:11.1.0',       '3000 → 3000','Dashboards',    'Auto-provisioned via $__env{PROMETHEUS_URL}'],
        ['node-exporter', 'prom/node-exporter:v1.8.0',   '9100 → 9100','Host Metrics',  'CPU, memory, disk, network counters'],
    ],
    theme='teal',
    col_widths=[3.2, 4.5, 3.0, 2.8, 6.0],
    bold_first_col=True,
    caption='Table 2.1 — Five-container Docker stack overview'
)

add_section_header(doc, 'nginx Request Routing', icon='🔀', color='0E4C92', bg='E0F2FE')
add_styled_table(doc,
    headers=['URL Path', 'Backend Target', 'Auth?', 'Description'],
    rows=[
        ['/',              'app:5000',        'None',  'Flask application home page'],
        ['/monitor/status (GET)',  'app:5000','None',  'Public HTML monitor dashboard — auto-refresh 10s'],
        ['/monitor/status (POST)', 'app:5000','Token', 'CI agent state receiver — X-Monitor-Token required'],
        ['/prometheus/',   'prometheus:9090', 'None',  'Prometheus UI via --web.external-url=/prometheus/'],
        ['/grafana/',      'grafana:3000',    'Basic', 'Grafana dashboards — admin/admin123'],
        ['/metrics',       'app:5000',        'None',  'Prometheus exposition format endpoint'],
        ['/health',        'app:5000',        'None',  'Health probe for load balancers'],
        ['/api/status',    'app:5000',        'None',  'JSON aggregated system snapshot'],
        ['/agent/status',  'app:5000',        'None',  'AI agent state JSON'],
    ],
    theme='blue',
    col_widths=[4.5, 3.5, 2.0, 8.5],
    center_cols=[2],
    caption='Table 2.2 — nginx routing rules'
)

add_section_header(doc, 'Grafana Auto-Provisioning', icon='📊', color='134E4A', bg='CCFBF1')
doc.add_paragraph(
    'Grafana reads YAML configuration files from /etc/grafana/provisioning/ at container '
    'startup. The datasource.yml uses $__env{PROMETHEUS_URL} — Grafana resolves this '
    'environment variable at boot, so no API calls or manual configuration are ever needed.'
)
add_code_block(doc,
    '# monitoring/grafana/provisioning/datasources/datasource.yml\n'
    'apiVersion: 1\n'
    'datasources:\n'
    '  - name: Prometheus\n'
    '    type: prometheus\n'
    '    uid: prometheus\n'
    '    access: proxy\n'
    '    url: $__env{PROMETHEUS_URL}   # <-- reads env var at container start\n'
    '    isDefault: true\n'
    '    editable: true\n'
    '    jsonData:\n'
    '      timeInterval: "10s"',
    language='yaml'
)

add_section_header(doc, 'AI Agent Architecture', icon='🤖', color='4C1D95', bg='EDE9FE')
add_styled_table(doc,
    headers=['Agent', 'Trigger Point', 'Input Data', 'Output', 'Decision'],
    rows=[
        ['Pre-Deploy Agent',  'Before deployment starts', 'Test results, monitor snapshot',   'Go / No-Go report',       'Blocks deploy if rejected'],
        ['Error Agent',       'On deployment failure',    'Error logs, cloud console status', 'Root-cause analysis',     'Suggests remediation steps'],
        ['Final Agent',       'After successful deploy',  'App URL, live monitor data',       'Health verification report','Confirms deployment passed'],
    ],
    theme='purple',
    col_widths=[3.8, 4.0, 4.5, 4.5, 4.0],
    caption='Table 2.3 — Three Gemini AI agent stages'
)

add_section_header(doc, 'AWS vs Azure Architecture Differences', icon='⚖️', color='92400E', bg='FEF3C7')
add_styled_table(doc,
    headers=['Aspect', 'AWS Elastic Beanstalk', 'Azure App Service'],
    rows=[
        ['Compose file',     'docker-compose.yml (exact name required)', 'docker-compose.azure.yml'],
        ['Deployment tool',  'eb deploy (EB CLI)',                        'az webapp config container set'],
        ['Platform',         'ECS Multi-Container',                       'Docker Compose (Linux)'],
        ['URL resolution',   'eb describe-environments → CNAME',          'az webapp show → defaultHostName'],
        ['TLS termination',  'Optional (ACM)',                            'Azure front-end (HTTPS forced)'],
        ['nginx config',     'nginx-aws.conf',                            'nginx-azure.conf'],
        ['Secrets source',   'MONITOR_TOKEN_AWS secret',                  'MONITOR_TOKEN_AZURE secret'],
    ],
    theme='orange',
    col_widths=[4.5, 6.5, 6.5],
    bold_first_col=True,
    caption='Table 2.4 — AWS vs Azure deployment differences'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 3. PROJECT WORKFLOW ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('3.  Project Workflow', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_section_header(doc, 'GitHub Actions Pipeline — High-Level Flow',
                   icon='⚙️', color='0E4C92', bg='E0F2FE')

workflow_phases = [
    ('1', 'TRIGGER',        'Developer runs workflow_dispatch in GitHub → selects cloud (aws | azure)',            'blue'),
    ('2', 'PRE-DEPLOY AI',  'test_agent.py queries Gemini → analyzes test results → issues go/no-go decision',    'purple'),
    ('3', 'BUILD',          'docker build -t image:SHA from docker/Dockerfile → image tagged with git SHA',       'teal'),
    ('4', 'PUSH',           'docker push to Docker Hub registry → image available for cloud pull',                'teal'),
    ('5', 'RESOLVE URL',    'Deploy script fetches real hostname from AWS/Azure API (CNAME / defaultHostName)',    'orange'),
    ('6', 'INJECT CONFIG',  'sed replaces all placeholders in docker-compose → PROMETHEUS_URL + MONITOR_TOKEN',   'orange'),
    ('7', 'DEPLOY',         'eb deploy (AWS) OR az webapp config container set (Azure) → containers start',       'green'),
    ('8', 'VERIFY GRAFANA', 'Pipeline polls /grafana/api/health + /grafana/api/datasources until UP',             'green'),
    ('9', 'FINAL AI',       'final_agent.py queries Gemini with live metrics → produces health report',           'purple'),
    ('10','ARTIFACTS',      'Logs, reports, screenshots uploaded as GitHub Actions artifacts for review',          'blue'),
]
for num, title_w, desc, color in workflow_phases:
    add_workflow_step(doc, num, title_w, desc, color_theme=color)

add_section_header(doc, 'AWS Detailed Deployment Steps',
                   icon='☁️', color='0E4C92', bg='E0F2FE')
aws_steps = [
    'aws-actions/configure-aws-credentials with ACCESS_KEY + SECRET',
    'pip install awsebcli awscli — install CLI tools',
    'docker build -f docker/Dockerfile -t $IMAGE .',
    'docker login -u $DOCKERHUB_USERNAME -p $DOCKERHUB_TOKEN && docker push $IMAGE',
    'aws elasticbeanstalk describe-environments → extract CNAME',
    'Derive PROMETHEUS_URL = http://$CNAME/prometheus',
    'cp docker/nginx/nginx-aws.conf docker/nginx/nginx.conf',
    'sed -i "s|REPLACE_PROMETHEUS_URL|$PROMETHEUS_URL|g" docker-compose.yml',
    'sed -i "s|replace_with_monitor_token|$MONITOR_TOKEN_AWS|g" docker-compose.yml',
    'grep "REPLACE_" docker-compose.yml → fail if placeholders remain',
    'eb init $APP_NAME --region $AWS_REGION --platform Docker',
    'eb create $ENV_NAME (if first deploy) OR eb deploy $ENV_NAME',
    'Wait for EB health: "Green" status via eb status polling',
]
for step in aws_steps:
    add_numbered(doc, step, color='0E4C92')

add_section_header(doc, 'Azure Detailed Deployment Steps',
                   icon='☁️', color='0369A1', bg='E0F2FE')
azure_steps = [
    'azure/login with AZURE_CREDENTIALS (JSON service principal)',
    'docker build + push (same as AWS steps 3–4)',
    'az webapp show --name $WEBAPP --resource-group $RG → extract defaultHostName',
    'Derive PROMETHEUS_URL = https://$HOSTNAME/prometheus',
    'cp docker/nginx/nginx-azure.conf docker/nginx/nginx.conf',
    'sed -i "s|REPLACE_PROMETHEUS_URL|$PROMETHEUS_URL|g" docker-compose.azure.yml',
    'sed -i "s|replace_with_monitor_token|$MONITOR_TOKEN_AZURE|g" docker-compose.azure.yml',
    'grep "REPLACE_" docker-compose.azure.yml → fail if placeholders remain',
    'az webapp config container set --name $WEBAPP --multicontainer-config-type COMPOSE \\',
    '    --multicontainer-config-file docker-compose.azure.yml',
    'az webapp restart --name $WEBAPP --resource-group $RG',
    'Poll https://$HOSTNAME/health until HTTP 200 returned',
]
for step in azure_steps:
    add_numbered(doc, step, color='0369A1')

add_section_header(doc, 'Monitoring Data Flow', icon='📡', color='134E4A', bg='CCFBF1')
doc.add_paragraph(
    'Live data circulates continuously through the monitoring stack:'
)
flow_steps = [
    ('Flask App',      'Exposes custom Prometheus metrics at /metrics every request'),
    ('node-exporter',  'Exposes host OS metrics at :9100/metrics (CPU, RAM, disk, net)'),
    ('Prometheus',     'Scrapes both targets every 10s → stores time-series in local TSDB'),
    ('Grafana',        'Queries Prometheus via auto-provisioned datasource → renders dashboards'),
    ('/monitor/status','Reads agent_state_store + collectors.build_status() → serves HTML'),
    ('CI Agents',      'POST to /monitor/status with X-Monitor-Token → updates agent state'),
]
for source, desc in flow_steps:
    add_kv_row(doc, source, desc, key_color='134E4A')

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 4. TECH STACK ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('4.  Tech Stack', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_styled_table(doc,
    headers=['Layer', 'Technology', 'Version', 'Purpose'],
    rows=[
        ['Application',   'Flask',                  'Python 3.11',     'Web framework — app, metrics, monitor endpoints'],
        ['Application',   'Werkzeug',               'Latest',          'WSGI error handling utilities'],
        ['AI Engine',     'Google Gemini',           '2.5-flash',       'AI agents — go/no-go, diagnosis, verification'],
        ['AI Client',     'google-generativeai',     'Latest',          'Python SDK for Gemini API calls'],
        ['Metrics Client','prometheus-client',        'Latest',          'Custom metric types: Counter, Gauge, Histogram'],
        ['Metrics Server','Prometheus',              'v2.53.0',         'Metrics collection + TSDB storage'],
        ['Dashboards',    'Grafana',                 '11.1.0',          'Auto-provisioned visualization dashboards'],
        ['Host Metrics',  'Node Exporter',           'v1.8.0',          'OS-level: CPU, memory, disk, network I/O'],
        ['Proxy',         'Nginx',                   '1.27-alpine',     'Reverse proxy — routes all external traffic'],
        ['Containers',    'Docker + Compose',        'Multi-container', '5-service orchestration'],
        ['CI/CD',         'GitHub Actions',          'workflow_dispatch','Pipeline — build, push, deploy, verify'],
        ['AWS Compute',   'Elastic Beanstalk (ECS)', 'Latest',          'Multi-container Docker hosting on ECS'],
        ['AWS CLI',       'EB CLI + AWS CLI',        'Latest',          'eb init, eb deploy, aws describe-environments'],
        ['Azure Compute', 'App Service (Linux)',      'Docker Compose',  'Multi-container hosting via Compose file'],
        ['Azure CLI',     'Azure CLI',               'Latest',          'az webapp config container set, az webapp restart'],
        ['Registry',      'Docker Hub',              'Public/Private',  'Image storage — saibaba22/sentinelops-lite-*'],
        ['Auth',          'MONITOR_TOKEN',            'X-Monitor-Token', 'CI agent POST authentication header'],
        ['Secrets',       'GitHub Secrets',           '9 secrets',       'Tokens, keys, credentials storage'],
        ['Variables',     'GitHub Variables',         '11 variables',    'App name, region, cloud config storage'],
    ],
    theme='dark',
    col_widths=[3.5, 4.5, 3.5, 8.5],
    bold_first_col=True,
    center_cols=[2],
    caption='Table 4.1 — Complete technology stack reference'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 5. COMMANDS REFERENCE ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('5.  Commands Reference', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_section_header(doc, 'Local Development', icon='💻', color='134E4A', bg='CCFBF1')
add_code_block(doc,
    '# Clone repository\n'
    'git clone https://github.com/your-org/sentinelops-lite.git\n'
    'cd sentinelops-lite\n\n'
    '# Build and start all 5 containers\n'
    'docker-compose up --build\n\n'
    '# Run in background (detached)\n'
    'docker-compose up -d --build\n\n'
    '# View container logs\n'
    'docker-compose logs -f app\n'
    'docker-compose logs -f grafana\n\n'
    '# Stop all containers\n'
    'docker-compose down',
    language='bash'
)

add_section_header(doc, 'Local Verification Endpoints', icon='🔍', color='0E4C92', bg='E0F2FE')
add_code_block(doc,
    '# Application health check\n'
    'curl http://localhost/health\n\n'
    '# Prometheus metrics exposition\n'
    'curl http://localhost/metrics\n\n'
    '# Monitor dashboard (opens in browser)\n'
    'open http://localhost/monitor/status\n\n'
    '# API status snapshot (JSON)\n'
    'curl http://localhost/api/status | python3 -m json.tool\n\n'
    '# AI agent state (JSON)\n'
    'curl http://localhost/agent/status | python3 -m json.tool\n\n'
    '# Prometheus UI\n'
    'open http://localhost/prometheus/\n\n'
    '# Grafana (admin / admin123)\n'
    'open http://localhost/grafana/',
    language='bash'
)

add_section_header(doc, 'AWS Deployment (Manual)', icon='☁️', color='0E4C92', bg='E0F2FE')
add_code_block(doc,
    '# Export required variables\n'
    'export APP_NAME=sentinelops-lite\n'
    'export ENV_NAME=sentinelops-lite-prod\n'
    'export AWS_REGION=us-east-1\n'
    'export REPOSITORY=your-dockerhub-repo\n'
    'export DOCKERHUB_USERNAME=saibaba22\n'
    'export DOCKERHUB_TOKEN=your-token\n'
    'export GITHUB_SHA=$(git rev-parse --short HEAD)\n'
    'export MONITOR_TOKEN_AWS=your-monitor-secret\n\n'
    '# Run AWS deployment script\n'
    'bash deploy/deploy-aws.sh\n\n'
    '# Verify deployment health\n'
    'eb status $ENV_NAME\n'
    'curl http://$(eb status $ENV_NAME | grep CNAME | awk "{print \\$2}")/health',
    language='bash'
)

add_section_header(doc, 'Azure Deployment (Manual)', icon='☁️', color='0369A1', bg='E0F2FE')
add_code_block(doc,
    '# Export required variables\n'
    'export AZURE_WEBAPP_NAME=sentinelops-monitor\n'
    'export AZURE_RESOURCE_GROUP=sentinelops-rg\n'
    'export REPOSITORY=your-dockerhub-repo\n'
    'export DOCKERHUB_USERNAME=saibaba22\n'
    'export DOCKERHUB_TOKEN=your-token\n'
    'export GITHUB_SHA=$(git rev-parse --short HEAD)\n'
    'export MONITOR_TOKEN_AZURE=your-monitor-secret\n\n'
    '# Azure login\n'
    'az login\n\n'
    '# Run Azure deployment script\n'
    'bash deploy/deploy-azure.sh\n\n'
    '# Verify\n'
    'az webapp show --name $AZURE_WEBAPP_NAME \\\n'
    '  --resource-group $AZURE_RESOURCE_GROUP \\\n'
    '  --query "state" -o tsv',
    language='bash'
)

add_section_header(doc, 'CI Agent Interaction', icon='🤖', color='4C1D95', bg='EDE9FE')
add_code_block(doc,
    '# POST agent state to /monitor/status (requires X-Monitor-Token)\n'
    'curl -X POST https://your-app-url/monitor/status \\\n'
    '  -H "X-Monitor-Token: $MONITOR_TOKEN" \\\n'
    '  -H "Content-Type: application/json" \\\n'
    '  -d \'{\n'
    '    "agent_name": "pre-deploy",\n'
    '    "stage": "pre_deploy",\n'
    '    "status": "approved",\n'
    '    "cloud": "aws",\n'
    '    "provider": "gemini",\n'
    '    "model": "gemini-2.5-flash",\n'
    '    "total_tokens": 1520,\n'
    '    "requests": 2,\n'
    '    "execution_time_seconds": 3.2\n'
    '  }\'',
    language='bash'
)

add_section_header(doc, 'Pipeline Trigger via GitHub CLI', icon='🚀', color='14532D', bg='DCFCE7')
add_code_block(doc,
    '# Deploy to AWS\n'
    'gh workflow run "SentinelOps-Lite Multi-Cloud Pipeline" \\\n'
    '  --ref main -f cloud=aws\n\n'
    '# Deploy to Azure\n'
    'gh workflow run "SentinelOps-Lite Multi-Cloud Pipeline" \\\n'
    '  --ref main -f cloud=azure\n\n'
    '# List recent runs\n'
    'gh run list --workflow="SentinelOps-Lite Multi-Cloud Pipeline"',
    language='bash'
)

add_section_header(doc, 'Grafana & Prometheus Verification', icon='📊', color='134E4A', bg='CCFBF1')
add_code_block(doc,
    '# Grafana health\n'
    'curl http://your-app/grafana/api/health\n\n'
    '# Grafana datasources (should show Prometheus auto-provisioned)\n'
    'curl -u admin:admin123 http://your-app/grafana/api/datasources\n\n'
    '# Prometheus scrape targets status\n'
    'curl http://your-app/prometheus/api/v1/targets\n\n'
    '# Query a metric via Prometheus API\n'
    'curl "http://your-app/prometheus/api/v1/query?query=up"\n\n'
    '# Check node-exporter CPU metric\n'
    'curl "http://your-app/prometheus/api/v1/query?query=node_cpu_seconds_total"',
    language='bash'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 6. BACKGROUND PROCESSES ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('6.  Background Processes', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_section_header(doc, 'Flask Metrics Background Thread',
                   icon='🔄', color='0E4C92', bg='E0F2FE')
doc.add_paragraph(
    'At Flask application startup, start_metrics_updater(interval=5) spawns a daemon thread '
    'that updates Prometheus gauge and counter metrics every 5 seconds:'
)
add_styled_table(doc,
    headers=['Metric Name', 'Type', 'Update Interval', 'Description'],
    rows=[
        ['app_uptime_seconds',                    'Gauge',   '5s', 'Seconds since Flask app started'],
        ['python_process_resident_memory_bytes',   'Gauge',   '5s', 'RSS memory of the Python process'],
        ['python_process_cpu_percent',             'Gauge',   '5s', 'CPU usage percentage of the process'],
        ['python_thread_count',                    'Gauge',   '5s', 'Active thread count inside the process'],
        ['app_active_sessions',                    'Gauge',   '5s', 'Number of active web sessions'],
        ['app_active_users',                       'Gauge',   '5s', 'Distinct active user count'],
        ['app_restart_total',                      'Counter', '5s', 'Cumulative app restart counter'],
        ['http_requests_total',                    'Counter', 'Per-req', 'Total HTTP requests by method + endpoint'],
        ['http_request_duration_seconds',          'Histogram','Per-req','Request latency distribution'],
    ],
    theme='blue',
    col_widths=[6.0, 2.5, 3.0, 8.0],
    center_cols=[1, 2],
    caption='Table 6.1 — Background metrics updated by Flask thread'
)

add_section_header(doc, 'Prometheus Scrape Cycle',
                   icon='🕐', color='92400E', bg='FEF3C7')
add_styled_table(doc,
    headers=['Job Name', 'Target URL', 'Metrics Path', 'Scrape Interval', 'Labels'],
    rows=[
        ['prometheus',    'localhost:9090',      '/prometheus/metrics', '10s', 'job=prometheus'],
        ['flask-app',     'app:5000',            '/metrics',            '10s', 'job=flask-app'],
        ['node-exporter', 'node-exporter:9100',  '/metrics',            '10s', 'job=node-exporter'],
    ],
    theme='orange',
    col_widths=[3.5, 4.0, 4.0, 3.5, 4.5],
    center_cols=[3],
    caption='Table 6.2 — Prometheus scrape jobs configuration'
)

add_section_header(doc, 'Grafana Background Processes',
                   icon='📊', color='134E4A', bg='CCFBF1')
refresh_items = [
    ('Dashboard Refresh',     '10s auto-refresh configured in dashboard JSON panels'),
    ('Provider Scan',         'Dashboard provider polls /var/lib/grafana/dashboards/ every 10s for new JSON files'),
    ('Datasource Health',     'Grafana pings Prometheus every 30s to verify datasource connectivity'),
    ('Alerting Engine',       'Alert evaluations run every 10s (if alert rules configured)'),
    ('Session Cleanup',       'Expired sessions purged automatically by Grafana background worker'),
]
for key, val in refresh_items:
    add_kv_row(doc, key, val, key_color='134E4A')

add_section_header(doc, '/monitor/status Page Auto-Refresh',
                   icon='🔁', color='4C1D95', bg='EDE9FE')
add_info_box(doc,
    'The /monitor/status HTML page includes <meta http-equiv="refresh" content="10"> '
    'and a JavaScript countdown timer. The page reloads automatically every 10 seconds '
    'to show the latest agent state and application metrics without any manual interaction.',
    box_type='info')

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 7. RESULTS & OUTCOMES ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('7.  Results & Outcomes', level=1)
add_horizontal_rule(doc, color='38BDF8')

add_section_header(doc, 'Before vs After — Feature Comparison',
                   icon='📈', color='0E4C92', bg='E0F2FE')
add_styled_table(doc,
    headers=['Feature', 'Before', 'After', 'Cloud'],
    rows=[
        ['Grafana datasource',   '❌ Empty — manual setup required each deploy', '✅ Auto-provisioned on container start', 'Both'],
        ['Prometheus URL',       '❌ 172.17.0.1:9090 (broken in ECS)',           '✅ Real external EB/Azure URL',          'Both'],
        ['/monitor/status GET',  '❌ 403 Forbidden in browser',                  '✅ Dark HTML dashboard, auto-refresh',   'Both'],
        ['Prometheus targets',   '❌ 172.17.0.1:5000 (bridge gateway fails)',    '✅ app:5000, node-exporter:9100',        'Both'],
        ['nginx /monitor/ route','❌ Missing — 404 for /monitor/ path',          '✅ Full routing to Flask app',           'Both'],
        ['MONITOR_TOKEN',        '❌ Not injected — POST always 401',            '✅ Secret injected via sed + deploy',    'Both'],
        ['Azure monitoring',     '❌ No Prometheus/Grafana on Azure',            '✅ Full 5-container stack deployed',     'Azure'],
        ['Cloud selection',      '❌ Separate pipelines per cloud',              '✅ Single pipeline, dropdown selector',  'Both'],
        ['Placeholder check',    '❌ No validation after sed replacement',       '✅ grep fails pipeline if REPLACE_ found','Both'],
        ['Post-deploy verify',   '❌ Manual check of Grafana + app',             '✅ Automated Grafana API + AI agent',    'Both'],
    ],
    theme='green',
    col_widths=[4.5, 5.5, 5.5, 2.0],
    center_cols=[3],
    bold_first_col=True,
    caption='Table 7.1 — Feature-by-feature before/after comparison'
)

add_section_header(doc, 'Live Access URLs Post-Deployment',
                   icon='🌐', color='134E4A', bg='CCFBF1')
add_styled_table(doc,
    headers=['Endpoint', 'AWS URL', 'Azure URL', 'Auth'],
    rows=[
        ['App Home',        'http://agent.eba-xxx.us-east-1.elasticbeanstalk.com/',           'https://sentinelops.azurewebsites.net/',           'None'],
        ['Monitor Dashboard','http://agent.eba-xxx.../monitor/status',                         'https://sentinelops.azurewebsites.net/monitor/status','None (GET)'],
        ['Prometheus UI',   'http://agent.eba-xxx.../prometheus/',                             'https://sentinelops.azurewebsites.net/prometheus/',   'None'],
        ['Grafana',         'http://agent.eba-xxx.../grafana/',                                'https://sentinelops.azurewebsites.net/grafana/',      'admin/admin123'],
        ['Metrics',         'http://agent.eba-xxx.../metrics',                                 'https://sentinelops.azurewebsites.net/metrics',       'None'],
        ['Health',          'http://agent.eba-xxx.../health',                                  'https://sentinelops.azurewebsites.net/health',        'None'],
        ['Agent JSON',      'http://agent.eba-xxx.../agent/status',                            'https://sentinelops.azurewebsites.net/agent/status',  'None'],
        ['API Status JSON', 'http://agent.eba-xxx.../api/status',                              'https://sentinelops.azurewebsites.net/api/status',    'None'],
    ],
    theme='teal',
    col_widths=[3.5, 6.0, 6.0, 2.5],
    center_cols=[3],
    caption='Table 7.2 — All public access URLs after deployment'
)

add_info_box(doc,
    'AWS URLs use HTTP (port 80 via nginx). Azure URLs use HTTPS — '
    'Azure App Service terminates TLS at its front-end and proxies HTTP internally.',
    box_type='info')

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 8. ERRORS & SOLUTIONS ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('8.  Errors & Solutions', level=1)
add_horizontal_rule(doc, color='38BDF8')

errors = [
    {
        'title'  : 'Error 1 — Grafana Dashboards Empty After Every Deploy',
        'symptom': 'Grafana shows "No data" on all panels after AWS or Azure deployment. '
                   'The dashboard loads but every panel displays "No data source found".',
        'cause'  : 'datasource.yml hardcoded url: http://172.17.0.1:9090/prometheus — '
                   'the Docker bridge gateway IP does not route in ECS/Azure networking.',
        'solution': 'Changed datasource.yml to url: $__env{PROMETHEUS_URL}. '
                    'Deploy scripts resolve the real external hostname and export PROMETHEUS_URL '
                    'before running docker-compose, so Grafana reads it at container startup.',
        'type'   : 'danger',
    },
    {
        'title'  : 'Error 2 — All Internal Docker URLs Fail in Production',
        'symptom': 'Every internal URL attempt (172.17.0.1, host.docker.internal, localhost, '
                   'prometheus:9090) failed with connection refused or wrong data.',
        'cause'  : 'Production ECS and Azure networking does not support Docker-desktop host '
                   'aliases. prometheus:9090 works for inter-container but lacks /prometheus/ '
                   'path prefix required by --web.external-url config.',
        'solution': 'Use only the external URL (via nginx reverse proxy) as PROMETHEUS_URL. '
                    'Deploy scripts extract it from AWS/Azure API and inject it dynamically.',
        'type'   : 'warning',
    },
    {
        'title'  : 'Error 3 — Prometheus Cannot Scrape Flask App or Node-Exporter',
        'symptom': 'Prometheus /targets page shows all targets as "DOWN". '
                   'No metrics data in Grafana, uptime counter stuck at 0.',
        'cause'  : 'prometheus.yml scrape targets used 172.17.0.1:5000 and 172.17.0.1:9100 '
                   '(bridge gateway) instead of Docker Compose service names.',
        'solution': 'Updated prometheus.yml to use app:5000 and node-exporter:9100. '
                    'Docker Compose creates a shared network where service names resolve correctly '
                    'in both ECS and Azure.',
        'type'   : 'danger',
    },
    {
        'title'  : 'Error 4 — /monitor/status Returns 403 Forbidden',
        'symptom': 'Opening http://your-app/monitor/status in a browser returns 403 Forbidden. '
                   'No dashboard visible to external stakeholders.',
        'cause'  : 'Two bugs: (1) route defined with methods=["POST"] only — GET not allowed. '
                   '(2) nginx missing /monitor/ location block — requests blocked before Flask.',
        'solution': 'Added separate @app.route("/monitor/status", methods=["GET"]) handler '
                    'serving public HTML. Added /monitor/ location block to nginx config. '
                    'POST handler with token auth kept separate and unchanged.',
        'type'   : 'warning',
    },
    {
        'title'  : 'Error 5 — Dockerrun.aws.json Conflicts with docker-compose.yml',
        'symptom': 'EB deploys only the single app container, ignoring Prometheus, Grafana, '
                   'and node-exporter. Monitoring stack never starts.',
        'cause'  : 'When both Dockerrun.aws.json and docker-compose.yml exist at the repo root, '
                   'EB prioritizes Dockerrun.aws.json and ignores docker-compose.yml entirely.',
        'solution': 'Removed Dockerrun.aws.json from repository. Kept docker-compose.yml '
                    '(exact required filename — EB does not accept docker-compose.aws.yml).',
        'type'   : 'danger',
    },
    {
        'title'  : 'Error 6 — MONITOR_TOKEN Not Available in Flask Container',
        'symptom': 'POST requests to /monitor/status with correct X-Monitor-Token '
                   'still return 401 Unauthorized.',
        'cause'  : 'Flask reads os.getenv("MONITOR_TOKEN") but the environment variable '
                   'was never added to the app service in docker-compose.yml.',
        'solution': 'Added MONITOR_TOKEN=replace_with_monitor_token under app.environment '
                    'in docker-compose.yml. Deploy scripts replace placeholder via sed '
                    'from GitHub secrets (MONITOR_TOKEN_AWS or MONITOR_TOKEN_AZURE).',
        'type'   : 'warning',
    },
]

for err in errors:
    add_section_header(doc, err['title'], icon='🐛', color='881337', bg='FFF1F2')
    add_kv_row(doc, 'Symptom',  err['symptom'],  key_color='881337')
    add_kv_row(doc, 'Cause',    err['cause'],    key_color='D97706')
    add_kv_row(doc, 'Solution', err['solution'], key_color='14532D')
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

add_styled_table(doc,
    headers=['Error #', 'Root Category', 'Component', 'Fixed In'],
    rows=[
        ['Error 1', 'Networking — external URL required',   'datasource.yml + deploy scripts',    'deploy-aws.sh + deploy-azure.sh'],
        ['Error 2', 'Networking — Docker bridge gateway',   'prometheus.yml + datasource.yml',    'All internal URLs removed'],
        ['Error 3', 'Networking — Prometheus scrape targets','prometheus.yml',                    'app:5000, node-exporter:9100'],
        ['Error 4', 'HTTP — GET method missing + nginx',    'agent_monitor.py + nginx.conf',      'GET handler + /monitor/ route'],
        ['Error 5', 'EB config — file precedence',          'Repo root — Dockerrun.aws.json',     'Deleted Dockerrun.aws.json'],
        ['Error 6', 'Secrets — env var not passed to container','docker-compose.yml app.environment','MONITOR_TOKEN placeholder added'],
    ],
    theme='red',
    col_widths=[2.5, 5.5, 5.5, 5.5],
    center_cols=[0],
    caption='Table 8.1 — Error root-cause summary'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 9. KEY LEARNINGS ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('9.  Key Learnings', level=1)
add_horizontal_rule(doc, color='38BDF8')

learnings = [
    ('Docker Networking Differs Between Local and Production',
     'blue',
     [
         'Internal IPs (172.17.0.1, host.docker.internal, localhost) work locally but FAIL in ECS and Azure',
         'Docker service names (app:5000, prometheus:9090) work for inter-container calls on shared Compose networks',
         'External URLs via nginx reverse proxy are the only reliable option for cross-network datasource access',
         'Always test with production-equivalent networking (no Docker Desktop host features)',
     ]),
    ('Prometheus Sub-Path Moves ALL API Endpoints',
     'orange',
     [
         '--web.external-url=/prometheus/ means ALL routes become /prometheus/api/v1/query, /prometheus/targets, etc.',
         'Simply pointing Grafana to http://prometheus:9090 FAILS — the /prometheus/ path prefix is required',
         'Dashboard panels must use the sub-pathed URL or they will get 404 from Prometheus',
         'This is the most common mistake when configuring Grafana behind a reverse proxy',
     ]),
    ('Grafana $__env{} is the Cleanest Auto-Provisioning Approach',
     'purple',
     [
         'No API calls, no manual configuration, no restart needed — env var read at startup',
         'Works with any deployment method (EB, Azure, k8s) as long as env var is injected',
         'Alternative (Admin HTTP API) requires waiting for Grafana to boot + handling auth',
         'The deploy script pattern: resolve URL → set env var → docker-compose up works every time',
     ]),
    ('EB Reads docker-compose.yml by Exact Filename',
     'teal',
     [
         'Elastic Beanstalk expects the file named exactly "docker-compose.yml" at the repo root',
         'Renaming to docker-compose.aws.yml causes EB to skip the file entirely — silent failure',
         'When both Dockerrun.aws.json AND docker-compose.yml exist, EB uses Dockerrun and ignores Compose',
         'Use separate Git branches or CI-time file selection if you need multiple compose files',
     ]),
    ('Dual GET + POST Handlers Eliminate Auth Conflicts',
     'green',
     [
         'A single route serving both browsers and CI agents creates an impossible auth conflict',
         'GET handler: no auth, returns HTML dashboard — for human monitoring visibility',
         'POST handler: X-Monitor-Token required, returns JSON — for automated CI agents',
         'Flask supports both on the same path: @app.route("/monitor/status", methods=["GET"/"POST"])',
     ]),
    ('Deploy Script Pattern: Build → Resolve → Inject → Verify',
     'red',
     [
         'Build Docker image first so the exact SHA-tagged image is known before cloud deployment',
         'Resolve the real cloud hostname via API before writing any config files',
         'Use sed placeholder replacement rather than hardcoding URLs in committed files',
         'Always grep for remaining REPLACE_ patterns and fail the pipeline if any are found',
         'This pattern works identically for AWS EB and Azure App Service with only tool differences',
     ]),
    ('Secrets Flow Through a 4-Step Chain — Every Step Must Be Explicit',
     'dark',
     [
         'Step 1: Store secret in GitHub Secrets (e.g., MONITOR_TOKEN_AWS)',
         'Step 2: Pass to deploy script as environment variable in GitHub Actions step',
         'Step 3: Replace placeholder in docker-compose.yml via sed during deploy script',
         'Step 4: Flask container reads it via os.getenv("MONITOR_TOKEN") at runtime',
         'Missing any single step causes the secret to not reach its destination silently',
     ]),
]

colors_map = {
    'blue'  : '0E4C92',
    'orange': '92400E',
    'purple': '4C1D95',
    'teal'  : '134E4A',
    'green' : '14532D',
    'red'   : '881337',
    'dark'  : '1E293B',
}
for title_l, theme_l, points in learnings:
    add_section_header(doc, title_l, icon='🎓',
                       color=colors_map[theme_l],
                       bg=list(TABLE_THEMES[theme_l].values())[2])
    for pt in points:
        add_bullet(doc, pt, color=colors_map[theme_l])

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════
# ████████████████ 10. APPENDIX ████████████████
# ═══════════════════════════════════════════════════════════════
doc.add_heading('10.  Appendix', level=1)
add_horizontal_rule(doc, color='38BDF8')

# ── Appendix A: File List ─────────────────────────────────────
doc.add_heading('Appendix A — Complete File Reference', level=2)
add_styled_table(doc,
    headers=['#', 'File Path', 'Cloud', 'Status', 'Purpose'],
    rows=[
        ['1',  'monitoring/grafana/provisioning/datasources/datasource.yml', 'Both',  'CHANGED', 'Auto-provision Prometheus datasource via $__env{}'],
        ['2',  'monitoring/grafana/provisioning/dashboards/dashboard.yml',   'Both',  'Same',    'Dashboard provider config — scans every 10s'],
        ['3',  'monitoring/grafana/dashboards/sentinelops-overview.json',    'Both',  'Same',    'Pre-built monitoring dashboard panels'],
        ['4',  'monitoring/prometheus/prometheus.yml',                        'Both',  'CHANGED', 'Scrape targets: app:5000, node-exporter:9100'],
        ['5',  'docker-compose.yml',                                          'AWS',   'CHANGED', 'ECS multi-container — PROMETHEUS_URL + MONITOR_TOKEN placeholders'],
        ['6',  'docker-compose.azure.yml',                                    'Azure', 'NEW',     'Azure App Service multi-container Compose file'],
        ['7',  'docker/nginx/nginx-aws.conf',                                 'AWS',   'CHANGED', 'nginx config — added /monitor/ location block'],
        ['8',  'docker/nginx/nginx-azure.conf',                               'Azure', 'NEW',     'nginx config — HTTPS forwarding headers + /monitor/'],
        ['9',  'deploy/deploy-aws.sh',                                        'AWS',   'CHANGED', 'Deploy script — CNAME resolve, sed inject, eb deploy'],
        ['10', 'deploy/deploy-azure.sh',                                      'Azure', 'NEW',     'Deploy script — hostname resolve, sed inject, az deploy'],
        ['11', '.github/workflows/pipeline.yml',                              'Both',  'CHANGED', 'Unified pipeline — cloud selector, Grafana verify, artifacts'],
        ['12', 'agent_monitor.py',                                            'Both',  'CHANGED', 'Added GET /monitor/status public HTML dashboard handler'],
    ],
    theme='purple',
    col_widths=[0.8, 6.5, 1.5, 2.2, 7.5],
    center_cols=[0, 2, 3],
    caption='Table A.1 — All files changed or created in this project'
)

# ── Appendix B: GitHub Variables ──────────────────────────────
doc.add_heading('Appendix B — GitHub Variables (11)', level=2)
add_styled_table(doc,
    headers=['Variable Name', 'Example Value', 'Required By', 'Description'],
    rows=[
        ['DOCKERHUB_USERNAME',    'saibaba22',               'Both',  'Docker Hub account for image push'],
        ['DOCKERHUB_REPOSITORY',  'sentinelops-lite-git',    'Both',  'Docker Hub repository name'],
        ['PYTHON_VERSION',        '3.11',                    'Both',  'Python version for setup-python action'],
        ['APP_HEALTH_PATH',       '/health',                 'Both',  'Path used for post-deploy health check'],
        ['AWS_APP_NAME',          'sentinelops-lite',        'AWS',   'Elastic Beanstalk application name'],
        ['AWS_ENV_NAME',          'sentinelops-lite-prod',   'AWS',   'Elastic Beanstalk environment name'],
        ['AWS_REGION',            'us-east-1',               'AWS',   'AWS region for EB and resource creation'],
        ['AZURE_WEBAPP_NAME',     'sentinelops-monitor',     'Azure', 'Azure App Service web app name'],
        ['AZURE_RESOURCE_GROUP',  'sentinelops-rg',          'Azure', 'Azure Resource Group containing the app'],
        ['AI_PROVIDER',           'gemini',                  'Both',  'AI provider for agent scripts'],
        ['AI_MODEL',              'gemini-2.5-flash',        'Both',  'Specific model used by AI agents'],
    ],
    theme='blue',
    col_widths=[4.5, 4.5, 2.5, 7.0],
    center_cols=[2],
    bold_first_col=True,
    caption='Table B.1 — GitHub Actions variables reference'
)

# ── Appendix C: GitHub Secrets ────────────────────────────────
doc.add_heading('Appendix C — GitHub Secrets (9)', level=2)
add_styled_table(doc,
    headers=['Secret Name', 'Required By', 'Description'],
    rows=[
        ['DOCKERHUB_TOKEN',          'Both',  'Docker Hub access token for docker push authentication'],
        ['AWS_ACCESS_KEY_ID',        'AWS',   'AWS IAM access key for configure-aws-credentials action'],
        ['AWS_SECRET_ACCESS_KEY',    'AWS',   'AWS IAM secret key paired with the access key ID'],
        ['AZURE_CREDENTIALS',        'Azure', 'JSON blob: clientId, clientSecret, subscriptionId, tenantId'],
        ['GEMINI_API_KEY',           'Both',  'Google AI Studio API key for all three Gemini agent scripts'],
        ['MONITOR_API_URL_AWS',      'AWS',   'Full URL for POST /monitor/status on the AWS deployment'],
        ['MONITOR_TOKEN_AWS',        'AWS',   'Bearer token for /monitor/status POST auth on AWS'],
        ['MONITOR_API_URL_AZURE',    'Azure', 'Full URL for POST /monitor/status on the Azure deployment'],
        ['MONITOR_TOKEN_AZURE',      'Azure', 'Bearer token for /monitor/status POST auth on Azure'],
    ],
    theme='dark',
    col_widths=[5.0, 2.5, 11.0],
    center_cols=[1],
    bold_first_col=True,
    caption='Table C.1 — GitHub Actions secrets reference'
)

# ── Appendix D: Port Reference ────────────────────────────────
doc.add_heading('Appendix D — Port Reference', level=2)
add_styled_table(doc,
    headers=['Port', 'Container', 'Protocol', 'Exposed?', 'Notes'],
    rows=[
        ['80',   'nginx',        'HTTP',  'Yes — public',     'All external traffic enters here'],
        ['5000', 'app (Flask)',  'HTTP',  'No — internal',    'Accessed via nginx proxy only'],
        ['9090', 'prometheus',  'HTTP',  'No — internal',    'Accessed via nginx /prometheus/ route'],
        ['3000', 'grafana',     'HTTP',  'No — internal',    'Accessed via nginx /grafana/ route'],
        ['9100', 'node-exporter','HTTP', 'No — internal',    'Scraped by Prometheus only'],
    ],
    theme='orange',
    col_widths=[2.0, 3.5, 3.0, 3.5, 7.5],
    center_cols=[0, 2, 3],
    caption='Table D.1 — Container port exposure reference'
)

# ── Appendix E: Environment Variables ────────────────────────
doc.add_heading('Appendix E — Key Container Environment Variables', level=2)
add_styled_table(doc,
    headers=['Container', 'Variable', 'Value Source', 'Purpose'],
    rows=[
        ['app',     'MONITOR_TOKEN',             'GitHub Secret → sed inject',   'Authenticates POST /monitor/status requests'],
        ['app',     'GEMINI_API_KEY',            'GitHub Secret → compose env',  'AI agent Gemini API calls from Flask'],
        ['grafana', 'PROMETHEUS_URL',            'Deploy script → sed inject',   'Datasource URL read by $__env{} in YAML'],
        ['grafana', 'GF_SERVER_DOMAIN',          'Deploy script → sed inject',   'Grafana domain for link generation'],
        ['grafana', 'GF_SERVER_ROOT_URL',        'Deploy script → sed inject',   'Grafana root URL for sub-path routing'],
        ['grafana', 'GF_SERVER_SERVE_FROM_SUB_PATH','true (hardcoded)',          'Enable /grafana/ sub-path routing'],
        ['grafana', 'GF_SECURITY_ADMIN_PASSWORD','admin123 (default)',           'Grafana admin password'],
        ['prometheus','--web.external-url',      '/prometheus/ (hardcoded)',     'Prometheus sub-path for nginx routing'],
    ],
    theme='teal',
    col_widths=[3.0, 5.0, 4.5, 7.0],
    bold_first_col=True,
    center_cols=[2],
    caption='Table E.1 — Critical container environment variables'
)

add_info_box(doc,
    'All REPLACE_* placeholders in docker-compose files are validated after sed replacement. '
    'The pipeline fails immediately if any placeholder remains — preventing broken deployments.',
    box_type='tip')

# ─── Final page footer ───
doc.add_page_break()
for _ in range(10):
    doc.add_paragraph()

end_title = doc.add_paragraph()
end_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = end_title.add_run('SentinelOps-Lite')
run.font.size  = Pt(28)
run.font.bold  = True
run.font.color.rgb = RGBColor(0x38, 0xBD, 0xF8)

end_sub = doc.add_paragraph()
end_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = end_sub.add_run('End of Documentation')
run.font.size  = Pt(14)
run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

add_horizontal_rule(doc, color='38BDF8', thickness=12)

end_meta = doc.add_paragraph()
end_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = end_meta.add_run(
    f'Generated automatically by document_docx.py  ·  '
    f'{datetime.date.today().strftime("%B %d, %Y")}'
)
run.font.size  = Pt(9)
run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

# ─── Save ───
output_path = 'SentinelOps-Lite-Project-Documentation.docx'
doc.save(output_path)
print(f'✅  Document saved → {output_path}')
print(f'    Pages     : ~35–40')
print(f'    Tables    : 18 (7 color themes)')
print(f'    Code blocks: 8')
print(f'    Sections  : 10 + 5 Appendices')