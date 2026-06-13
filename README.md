# Section DXF Standardizer

Agent-ready workflow and Python tooling for cleaning paired architectural section DXF exports into AutoCAD-compatible, editable, multi-layer technical drawings.

## What It Does

This project standardizes architectural section drawings exported as two DXF files per section:

- a cut-line file for heavy section geometry
- a visible-line file for projected/background geometry

The batch workflow scans numbered DXF pairs, detects coordinate offsets, aligns cut-line geometry to visible-line geometry, removes duplicate and noisy linework, reclassifies entities into architectural CAD layers, adds lightweight editable construction repair linework, and writes:

- standardized DXF files
- PNG previews
- per-section Markdown reports
- an all-sections summary report

## GitHub Repository Description

Use this as the GitHub "About" description:

```text
Agent-ready Python workflow for cleaning paired architectural section DXF files into AutoCAD-compatible, layered technical drawings.
```

Suggested GitHub topics:

```text
autocad dxf cad architecture architectural-drawing computational-design drafting-automation geometry-cleanup ezdxf python codex-skill
```

## Status

This is a practical drafting automation workflow, not a structural design engine. Generated repair geometry is editable drafting assistance and must be reviewed by an architect or structural engineer before professional use.

## Requirements

- Python 3.10+
- `ezdxf` for robust AutoCAD-compatible DXF writing

Install:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Input Convention

Place source DXF files in the repository root or current working directory.

For each numbered group:

- cut-line DXF: filename contains the group number and does not contain the visible-line keyword
- visible-line DXF: filename contains the group number and contains a visible-line keyword such as `看线`, `visible`, `projection`, `projected`, `viewline`, or `view-line`

Example:

```text
section1.dxf
section1_visible.dxf
section2.dxf
section2_visible.dxf
```

For Chinese exports, this pattern is also supported:

```text
剖面1.dxf
剖面1看线.dxf
剖面2.dxf
剖面2看线.dxf
```

Do not mix geometry between numbered groups.

## Usage

Run:

```bash
python tools/standardize_section_dxf_batch.py
```

Outputs are written to `out/`.

Expected outputs for groups 1 and 2:

```text
out/standardized_section_1.dxf
out/standardized_section_1_preview.png
out/standardized_section_1_report.md
out/standardized_section_2.dxf
out/standardized_section_2_preview.png
out/standardized_section_2_report.md
out/standardized_section_all_report.md
```

## Output Layers

Every standardized DXF contains these layers:

- `A-CUT-SECTION`
- `A-VISIBLE-PROJECTION`
- `A-STRUCTURE-FIX`
- `A-HATCH-MATERIAL`
- `A-CENTER-HIDDEN`
- `A-ANNO-NOTE`

Valid entities should not remain on layer `0`.

## AutoCAD Compatibility

AutoCAD is stricter than many DXF viewers. This project uses `ezdxf` for final DXF writing when available. The generated DXF should be audited and tested in AutoCAD before professional delivery.

If a DXF opens in a viewer but fails in AutoCAD, regenerate with `ezdxf` installed:

```bash
python -m pip install -r requirements.txt
python tools/standardize_section_dxf_batch.py
```

## Agent Skill

`SKILL.md` contains the reusable agent workflow. It describes how an AI coding/drafting agent should:

- scan inputs
- match groups
- align geometry
- classify layers
- add minimal construction repair linework
- validate outputs
- report limitations

`AGENTS.md` contains repository-level instructions for future agents and contributors.

## What Not To Commit

Do not commit private project drawings or generated outputs by default. Use anonymized or synthetic fixtures for public examples.

The included `.gitignore` blocks common CAD sources and generated output folders. If you intentionally add public sample fixtures, place them under `examples/`.

## License

Choose a license before publishing. MIT is simple and permissive; Apache-2.0 is also permissive and includes an explicit patent grant.
