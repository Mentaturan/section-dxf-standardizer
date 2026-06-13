# Agent Instructions

This repository contains an open-source workflow for cleaning and standardizing architectural section DXF drawings from paired cut-line and visible-line exports.

## Working Style

- Be direct and factual.
- Prefer editing files and running validation over giving abstract advice.
- Do not overwrite source DXF files.
- Keep outputs reproducible from the script.
- Keep private local paths, project-specific names, and machine-specific assumptions out of reusable documentation.

## Repository Layout

- `SKILL.md`: reusable agent workflow for DXF section standardization.
- `tools/standardize_section_dxf_batch.py`: batch DXF cleaning and standardization script.
- `requirements.txt`: Python dependency list. Install it for AutoCAD-compatible DXF writing.
- `README.md`: public GitHub project overview and usage guide.
- `out/`: generated DXF, PNG preview, and Markdown reports.

Source DXF files are expected in the working directory. Generated files should go under `out/`.

## Standard Command

Run the batch workflow from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python3 tools/standardize_section_dxf_batch.py
```

The script should print recognized input pairs, process each group independently, generate outputs, and fail with a non-zero exit code when validation fails.

## Input Matching Convention

For each numbered group:

- cut-line DXF: filename contains the group number and does not contain the visible-line keyword, for example `看线`
- visible-line DXF: filename contains the group number and contains the visible-line keyword

Never mix geometry between groups.

## Required Output Layers

Every standardized DXF must contain these layers:

- `A-CUT-SECTION`
- `A-VISIBLE-PROJECTION`
- `A-STRUCTURE-FIX`
- `A-HATCH-MATERIAL`
- `A-CENTER-HIDDEN`
- `A-ANNO-NOTE`

Valid drawing entities must not remain on layer `0`.

## Implementation Rules

- Parse DXF geometry programmatically and inspect previews visually.
- Use visible-line coordinates as the baseline.
- Translate cut-line geometry to align; do not scale, rotate, mirror, or redraw the building.
- Keep numbered groups isolated. Never borrow geometry from another group.
- Remove zero-length, extremely short, duplicate, reversed duplicate, and isolated noise linework.
- Preserve the original architectural outline, section direction, and scale relationship.
- Add only minimal editable construction repair geometry.
- Keep material hatch or texture linework sparse.
- Write reports with actual entity counts and validation results.
- Prefer `ezdxf` for final DXF writing. When writing DXF manually, keep the DXF version and entity structure consistent and avoid newer-only fields unless full newer-version subclass records are emitted.
- Keep source files read-only. Generated outputs belong in `out/`.

## Validation Before Finishing

After any script change, run:

```bash
python3 tools/standardize_section_dxf_batch.py
```

Then independently check:

- all requested DXF outputs exist
- all requested PNG previews exist
- all requested Markdown reports exist
- all six required layers are present in every DXF
- valid entities on layer `0` equals `0`
- per-layer entity counts are reported
- previews show aligned cut and visible geometry

If a preview shows overextended generated linework or unclear construction repair, adjust the script and rerun.

## Open-Source Maintenance Notes

- Keep the core script portable. Avoid mandatory proprietary CAD software dependencies.
- If third-party Python packages are introduced, document them and keep outputs reproducible.
- Do not commit large private source drawings unless they are intentionally licensed sample fixtures.
- Add small synthetic DXF fixtures for tests when possible.
- Automated architectural repair is drafting assistance, not structural certification. Keep that limitation visible in reports and documentation.
- Keep `.gitignore` conservative enough to block private DXF/DWG files and generated outputs.
- Prefer issues and pull requests that include small reproducible fixtures, screenshots, expected layer counts, and AutoCAD version details.
- If changing DXF writing logic, test with AutoCAD or at least `ezdxf` audit before claiming compatibility.
