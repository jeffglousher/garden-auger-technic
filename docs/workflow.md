# Limo CAD to a locally reinforced print

## Demonstration

Open `garden-auger.limo` in [Limo CAD](https://github.com/limo-cad/Limo-CAD), then recall **Complete assembly**. Its 84 named features describe the servo reference, housing envelope, D grips, cavities, fasteners, drive, matched locators, rotating shield and engravings. Suppressed historical alternatives and unused sketches were removed after exact native mesh comparison. Repository images render that same geometry; they are not screenshots claiming a particular application UI state.

The `.limo` model owns fitted solid geometry. `print/garden-auger.3mf` contains the saved printer, materials, support settings, two-plate placement and local reinforcement volumes. STLs preserve only the five part meshes.

## Current external adjustment example

`print/reinforcement.json` names all nine cylindrical regions and records their dimensions in CAD body-definition coordinates. Four lower zones surround the insert anchors; four upper zones follow the opposing screw load paths; one zone reinforces the adapter hub and screw seat. They request five walls and 100% zig-zag infill. Global remains three walls and 15% grid.

`scripts/build_print.py` rebuilds those named Bambu `modifier_part` volumes without altering the original normal-part meshes. It translates each CAD-frame region into the centered manufacturing mesh frame. Existing component/plate transforms position the region with its parent. Modifier volumes do not add mechanical geometry or extra printed parts.

Open the 3MF in Bambu Studio and expand the housings or adapter in the Objects list to inspect named modifier regions and their local wall/infill settings. Global edits affect the baseline; explicit local regions retain their overrides. To change this scripted example reproducibly, edit `reinforcement.json`, run `python scripts/build_print.py`, then slice again. Building without `--slicer` invalidates cached slice statistics/previews and makes no new print-time claim.

With `--slicer`, the script uses a temporary copy, verifies both plates and modifier readback, checks actual object order and the PLA bed-temperature wait, refreshes previews/statistics and retains evidence under ignored `.build/print`. It never contacts a printer. The published 3MF contains no G-code. Native inspection previously confirmed increased extrusion inside all nine regions against the unreinforced baseline. Physical strength remains a separate question.

## Existing Limo capabilities and remaining qualification

The installed engine's focused MCP operations include `print_intent_get`, `print_modifier_create`, `print_modifier_update`, `print_modifier_remove`, `print_modifier_copy`, `print_modifier_reset` and `print_modifier_effective`. They also appear in `cad_interface` under `document/print-intent`. Tool focus can hide them from the initial `tools/list`; that does not mean they are missing. Read operations were exercised in this session. Mutations require a current `expected_model_json` snapshot and stable body attachment.

Closed [modifier feature request #314](https://github.com/limo-cad/Limo-CAD/issues/314) covers primitive zones, shared engine/MCP behavior and Bevy controls. Open [handoff acceptance #316](https://github.com/limo-cad/Limo-CAD/issues/316) owns remaining visible/native qualification. This repository implements no CAD application feature and claims no completion of that application acceptance. The saved auger `.limo` intentionally has empty print intent, accurately demonstrating the verified external workflow.

The existing typed operations are callable through MCP/stdio, including from an external script. This repository's Python script is the verified manufacturing path. Native Limo command-script parity and a UI create/edit/save/reopen/export walkthrough using this exact example are requested qualification; neither was exercised here.

Use this public case to qualify discoverable UI controls and named overlays, MCP/script parity, saved local intent and export of all nine zones through both print-by-object layouts. Compare actual Bambu toolpaths and distinguish CAD intent, exported metadata, native slicing and physical results. Preserve PETG-to-PLA thermal order; no built-in slicer or printer connection is required.
