---
name: claude-doc-style
description: "Create, edit, or work with .docx files using the docx-js library and XML editing workflows. Use when asked to create a new Word document, edit an existing .docx file, add tracked changes or comments, format tables, embed images, add headers/footers, or perform any .docx generation or manipulation task. Covers full workflow: new document creation with docx-js (JavaScript), editing existing docs via XML unpack/repack, tracked changes, comments, styles, tables, images, lists, page layouts, and table of contents."
---

# Claude Doc Style — DOCX Skill

Full reference for creating and editing `.docx` files. Read `references/docx-reference.md` for detailed syntax, examples, and critical rules.

## Workflow Overview

| Task | Approach |
|---|---|
| Create new document | Use `docx-js` (JavaScript) |
| Edit existing document | Unpack XML → edit → repack |
| Read/analyze content | `pandoc` or unpack for raw XML |

## Creating New Documents

Install: `npm install -g docx`

```bash
node create-doc.js        # Run script
python scripts/office/validate.py doc.docx   # Validate after creation
```

Key steps:
1. Write JavaScript using `docx` package imports — see reference for full import list
2. Set page size explicitly (docx-js defaults A4; use US Letter: 12240×15840 DXA for US docs)
3. Use `Packer.toBuffer(doc).then(buffer => fs.writeFileSync("doc.docx", buffer))`
4. Validate after creation

## Editing Existing Documents

```bash
python scripts/office/unpack.py document.docx unpacked/   # Step 1: Unpack
# Edit XML in unpacked/word/ using Edit tool directly
python scripts/office/pack.py unpacked/ output.docx --original document.docx  # Step 3: Repack
```

Use **"Claude"** as author for all tracked changes and comments unless instructed otherwise.

## Critical Rules (Quick Reference)

- **Page size**: always set explicitly; US Letter = 12240×15840 DXA
- **Landscape**: pass portrait dimensions, set `orientation: PageOrientation.LANDSCAPE` — docx-js swaps internally
- **No `\n`**: use separate `Paragraph` elements
- **No unicode bullets**: use `LevelFormat.BULLET` with numbering config
- **PageBreak**: must be inside a `Paragraph`
- **ImageRun**: always set `type` (png/jpg/etc)
- **Tables**: always `WidthType.DXA` (never PERCENTAGE); set dual widths (`columnWidths` + per-cell `width`); `columnWidths` must sum to table width; use `ShadingType.CLEAR`
- **TOC**: headings must use `HeadingLevel` only; include `outlineLevel` on heading styles
- **Style IDs**: use exact IDs (`"Heading1"`, `"Heading2"`, etc.) to override built-in styles

## Reference

See `references/docx-reference.md` for:
- Full import list and document setup
- Styles, lists, tables, images, hyperlinks, footnotes
- Headers/footers, tab stops, multi-column layouts, TOC
- XML tracked changes and comments syntax
- Schema compliance rules
- All critical rules with examples
