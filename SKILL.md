---
name: standardize-section-dxf
description: Clean and standardize architectural section CAD/DXF drawings from paired cut-line and visible-line files. Use when asked to scan DXF files, match numbered section groups, align cut geometry to visible geometry, remove duplicate/short/noise lines, classify entities into architectural layers, add lightweight construction details, and generate editable DXF, PNG previews, and Markdown validation reports.
---

# Standardize Section DXF

Use this skill to turn raw architectural section DXF exports into editable, layered technical section drawings. The expected input is one or more groups of DXF files where each group has:

- a cut-line file: section geometry that is cut through and should become heavy section linework
- a visible-line file: projected/background geometry that should become fine visible linework

For numbered groups, match files by group number and by the visible-line keyword. Do not mix geometry across groups.

## Use This Skill For

- paired architectural section DXF cleanup
- cut-line and visible-line section exports that need alignment
- AutoCAD-readable layered output drawings
- geometry deduplication and short-line/noise removal
- editable technical section drafting from raw projection exports
- agent-assisted drafting workflows that need visual inspection plus code validation

Do not use this skill for DWG conversion, structural calculation, BIM model authoring, raster-to-vector tracing, or construction certification.

## Default Workflow

1. Scan the working directory for DXF files.
2. Match each numbered group:
   - cut-line file: filename contains the group number and does not contain the visible-line keyword such as `看线`
   - visible-line file: filename contains the group number and contains the visible-line keyword
3. Parse DXF entities with code, not only by visual inspection. Prefer structured DXF parsing when available; otherwise parse ASCII DXF group codes for `LINE` entities.
4. Render source overlays or previews and inspect them visually.
5. Compute bounding boxes for each file.
6. Detect coordinate offset between the cut-line file and the visible-line file.
7. Use the visible-line file as the coordinate baseline and translate cut-line geometry only. Do not scale, rotate, mirror, or reshape the original building.
8. Merge the aligned cut geometry and visible geometry.
9. Clean geometry:
   - remove zero-length entities
   - remove extremely short fragments
   - remove duplicate or reversed duplicate linework
   - remove isolated noise that is not connected to the section drawing
   - preserve the main architectural outline and dimensions
10. Reclassify all valid geometry into the required output layers.
11. Add minimal editable construction repair geometry only where needed.
12. Write output DXF, PNG preview, per-group report, and all-groups report.
13. Re-open the output DXF and validate layers, entity counts, and absence of valid entities on layer `0`.
14. If validation fails, patch the script and rerun until it passes.

## Input Assumptions

- Source DXF files should contain editable model-space linework.
- The current script is optimized for `LINE`-heavy section exports.
- Other entity types such as `LWPOLYLINE`, `ARC`, `CIRCLE`, `SPLINE`, `INSERT`, `HATCH`, and dimensions may require parser extension before they are preserved.
- The visible-line file is the coordinate baseline.
- The cut-line file may have a consistent translation offset relative to the visible-line file.
- Group matching must be deterministic and reported.

## Required Output Layers

Every output DXF must contain these layers. No valid geometry should remain on the default `0` layer.

- `A-CUT-SECTION`: heavy section linework for walls, slabs, platforms, roof, beams, columns, foundations, and other cut elements. Prefer entities from the cut-line file.
- `A-VISIBLE-PROJECTION`: fine visible linework for projected/background elements, openings, furniture, railings, distant members, and visible contours. Prefer entities from the visible-line file.
- `A-STRUCTURE-FIX`: added or repaired lightweight structure such as steel beams, purlins, joists, braces, node plates, piles, and support corrections.
- `A-HATCH-MATERIAL`: sparse material indication for timber decking, roof panels, acoustic wall buildup, glass, metal, and ground. Keep hatches sparse to avoid blackened drawings.
- `A-CENTER-HIDDEN`: centerlines, axes, hidden lines, and construction reference lines. Use dashed or center linetype.
- `A-ANNO-NOTE`: necessary labels, levels, layer notes, and construction notes. Keep text clear of the main section.

## Alignment Heuristics

Use more than one test before applying a translation.

- Compare cut and visible bounding boxes.
- Match long line segments by length, angle, and midpoint.
- Score candidate translations by sampling cut-line points and checking their proximity to visible-line geometry.
- Refine the best candidate with exact or near-exact endpoint matches when possible.
- Treat large consistent translations as coordinate offsets. Record `dx` and `dy` in the report.
- Keep each group independent; never use geometry from another group to improve a match.

## Architectural Repair Rules

Repair only as editable linework and keep the original section readable. The goal is a technical cleanup, not a redesign.

Check and repair these conditions when visible:

- floating members
- beam-column misalignment
- roof disconnected from supports
- missing platform thickness
- railing or wall intersections that read incorrectly
- missing roof purlins, secondary members, or node plates
- missing light steel platform beams below decking
- insufficient foundation support expression
- land-side acoustic wall lacking build-up layers
- river-side railing or open interface not clearly expressed

Use this lightweight material language for added construction:

- platform: treated timber or bamboo-composite boards over light steel frame
- foundation: micro steel piles or screw piles with steel platform beams
- roof: light metal or polycarbonate sheet with aluminum/light steel purlins
- land-side wall: perforated panel, polyester acoustic fiber, and air cavity
- river-side interface: glass guardrail or translucent polycarbonate panel

Avoid introducing heavy concrete expression unless the source drawing already clearly requires it.

## Script Guidance

If a repository already contains `tools/standardize_section_dxf_batch.py`, use it first:

```bash
python3 tools/standardize_section_dxf_batch.py
```

The script should support:

- automatic DXF scanning
- group matching
- DXF entity reading
- bbox analysis
- coordinate alignment
- duplicate and short-line cleanup
- architectural layer classification
- supplemental editable construction linework
- DXF writing
- PNG preview generation
- Markdown report generation
- output validation

Prefer `ezdxf` for final AutoCAD-facing DXF output. A dependency-light fallback is useful for portability, but AutoCAD is stricter than many DXF readers and may reject or crash on hand-written files with inconsistent version/entity structures. If writing DXF manually, keep the declared DXF version consistent with the emitted entity structure. For newer fields such as `370` lineweight, emit full subclass records and handles, or avoid those fields.

## AutoCAD Compatibility Rules

- Prefer writing final DXF through `ezdxf` or another mature DXF writer.
- Audit generated DXF files when possible.
- Avoid mixing a newer `$ACADVER` with old-style entities.
- Do not rely on generic DXF viewers as proof that AutoCAD can open the file.
- If AutoCAD prompts for recovery, crashes, or closes after pressing Enter, regenerate with a clean writer rather than patching random group codes.
- Keep output entities simple and editable: `LINE` and `TEXT` are the safest baseline.

Recommended open-source setup:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python tools/standardize_section_dxf_batch.py
```

## Validation Checklist

The job is complete only when all checks pass:

- every expected group has one cut-line DXF and one visible-line DXF
- output DXF exists for every group
- output PNG preview exists for every group
- per-group Markdown report exists for every group
- all-groups Markdown report exists
- every output DXF contains all six required layers
- valid entities are not left on layer `0`
- cut-line and visible-line geometry are aligned
- no geometry from different groups is mixed
- main building outline, scale relationship, and section direction are preserved
- generated construction details remain lightweight and editable

## Reporting

Each group report should include:

- input filenames
- source entity counts
- cut and visible bounding boxes
- whether coordinate offset was detected
- applied translation `dx`, `dy`
- alignment score or evidence
- cleanup counts
- output layer entity counts
- `0` layer validation result
- generated artifact status
- manual review notes

The all-groups report should summarize the same fields across every processed group.

## Failure Recovery

If AutoCAD cannot open the generated DXF:

1. Check whether `ezdxf` was installed and used for final output.
2. Run an audit with `ezdxf` if available.
3. Confirm `$ACADVER`, subclass records, handles, and lineweight fields are consistent.
4. Regenerate the DXF from clean entities instead of copying unknown `OBJECTS` or proxy records from source files.
5. If the file opens in a lightweight viewer but not AutoCAD, treat AutoCAD as the compatibility target.

If alignment is wrong:

1. Render source overlays before cleanup.
2. Compare bbox translation against long-line matching translation.
3. Prefer the translation with better sampled geometry overlap.
4. Keep each numbered group isolated.

If generated repair geometry overextends:

1. Limit supplemental roof/platform/wall features to detected architectural extents.
2. Re-render previews.
3. Keep repair geometry on `A-STRUCTURE-FIX` or `A-HATCH-MATERIAL` so it remains easy to delete manually.

## Quality Boundaries

Do not claim structural correctness from automated linework alone. State that added support, material, and annotation details need architectural or structural review before construction use.

Do not destructively modify source DXF files. Write standardized outputs to an output directory such as `out/`.

## Open-Source Packaging Notes

- Keep private project drawings out of the repository unless explicitly licensed as examples.
- Provide synthetic or anonymized fixtures for tests.
- Include `requirements.txt` when relying on `ezdxf`.
- Include a clear license such as MIT or Apache-2.0.
- Document that the tool automates drafting cleanup and does not replace architectural or structural review.
