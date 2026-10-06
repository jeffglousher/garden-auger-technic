# Cable routing: native volume checks and planar tooling

The current housing sends the servo lead to the **right side forward of the handle**. Its split-seam channel is 6 mm wide and 8 mm high. The existing sketch and cut supply the boot bay and two tangent R8 bends. A smooth side-routing spine contains the turn; the cut runs after all housing pad joins. Production feature count remains 71. Keep the JR connector outside and lay the lead into the open lower half before closure.

## Faults reproduced and corrected

The previous channel stopped at X50 while the handle continues to X100. The native tool reports 314.159 mm³ overlap in each half for a Ø4 straight cable extended to the actual exterior. A later rear-pad join also filled part of the intended boot bay. The revised cut is reordered after those joins instead of adding another relief operation.

The source diagram shows the cable emerging from the servo's right side near its rear. It does **not** dimension the boot, cable bundle, entry across the seam or permissible bend radius. Existing boot-bay coordinates and the new envelopes are **design trials**, not dimensions measured from that photograph or published by INJORA.

## Working integration

[check_cable_route.py](../scripts/check_cable_route.py) uses the installed CAD engine's `solid_sweep` with a circular section and continuous native line/arc spine. `assembly_interference_check` measures exact retained-solid clearance for this complete static envelope; the curve is not reduced to isolated test points. Temporary probes are discarded from production CAD. The [raw results](../cable-route-verification.json) bind the checks to the current source hash and preserve failed controls.

- Ø4 trial bundle: 1.00 mm minimum housing clearance.
- Ø5 trial bundle: fits with 0.50 mm nominal minimum clearance.
- Ø6.2 oversized bundle: rejected by native overlap in both halves.
- Six Ø4 placement trials: ±0.4 mm in Y/Z, including two diagonal samples, pass.
- Five lower insertion and five upper closure samples: pass at the recorded heights. These are sampled positions, not continuous motion certification.
- Boot trial: 5.45 ×9.60 ×7.00 mm rectangular envelope outside the case passes. This is a trial box, not the actual molded boot.

The native [experiment project](../experiments/cable-routing-trial.limo) adds a visible cyan Ø4 cable. It is **not a print part**. Canonical source and all print exports exclude it. The [top](../renders/cad-cable-route-top.png) and [isometric](../renders/cad-cable-route-isometric.png) images are captured from the CAD viewport. Their [provenance](../renders/cable-route-provenance.json) identifies the geometry and capture hashes.

Run from the repository:

```powershell
uv run --no-project --python 3.14 --with shapely==2.1.2 python scripts/check_cable_route.py --inspection-project C:/Users/jeffg/dev/garden-auger-technic/experiments/cable-routing-trial.limo
```

The reusable experiment also integrates **Shapely/GEOS** for planar outlet checks. It measures the final outbound Ø4 segment against the actual native handle-front datum: 8.00 mm clear. It does not make that claim for the attached boot near the handle root. Shapely uses XY and ignores Z; curved buffers are polygonal approximations. The native analytic 3D sweep remains the clearance authority. See the [official Shapely manual](https://shapely.readthedocs.io/en/stable/manual.html) for those planar and curve limitations.

## Remaining limits

The 8 mm centerline radius, Ø4/Ø5 bundle and boot box need an actual cable-fit check. A geometric clearance pass does not simulate elasticity, bend strain, friction, insulation wear, fatigue, water sealing or tug loads. The factory boot remains the only strain relief; this channel clears the lead without clamping it. There is no qualified pull-retention feature and no additional hardware.

Both housing halves slice with zero support toolpaths at the saved settings. The lower half separately passes with automatic supports enabled. The upper screw-recess roofs retain short bridges whose printed quality needs checking. The nearest rear insert retains 3.07 mm sampled wall after the stated allowance; other insert pilots, screw seats and mating datums are unchanged. The CAD tool still exposes no global minimum-wall or GD&T certification.
