# Zero-clearance, separated locators

Current candidate: `experiments/garden-auger-locator-fit.limo` and `garden-auger-locator-fit-assembly.3mf`. Use the relocated-locator housing pair. The lower half from PR22 is unchanged and compatible; only the upper sockets change in this zero-clearance revision. The previous simple-print assembly remains available as historical evidence.

The four lower-owned pins and upper straight sockets are both 5.00 mm diameter: **0.00 mm nominal radial and diametral clearance**. This replaces the preceding 5.20 mm sockets at the owner's request for a very tight friction fit. Equal CAD diameters describe line-to-line contact; actual friction/interference and insertion force depend on the printed dimensions, not a simulated material deformation. Pin projection remains 2.8 mm, socket depth 3.2 mm, with chamfered entries. The 0.4 mm axial tip room is deliberate; only the straight locating surfaces have zero clearance. Pin cross-sectional area increases 56.25%; this is geometry, not a measured strength gain.

Locator centers move to (-21,132), (21,132), (-36,183), (16,175) mm. Minimum center spacing to the nearest insert/screw axis increases from 6.5 to 13.8 mm. The lower pin-root to insert-pilot edge separation is at least 9.3 mm; upper socket entry to screw-head recess separation is at least 8.0 mm. The insert pilot dimensions, thread hardware, screw seats and four M3 x18 screw stacks remain unchanged. More widely separated features do not certify insert pullout strength.

The first trial placed a front socket too close to the outer wall and a rear socket into the cable passage. Those positions were rejected. Revised native sections show at least 2.6 mm of side stock at Z1 across all four socket centers. These are selected sections, not a global minimum-wall certification.

The servo nest, bearing/bushing interfaces, adapter, auger, 38 mm shield, cable route, flat bed lands and D grips remain. Native mesh comparison confirms the servo and all three other printed parts are unchanged.

Reproduce from the repository root with the existing offline numpy/trimesh/manifold3d/pillow Python environment:

1. `python scripts/build_locator_fit.py`
2. `python scripts/check_locator_stock.py`
3. `python scripts/check_outer_walls.py --locator-fit`
4. `python scripts/check_d_grips.py --locator-fit --build-root .build/clamshell-detail/current-assembly/locator-zero`
5. `python scripts/package_refined_assembly.py --locator-fit --build-root .build/clamshell-detail/current-assembly/locator-zero`

Owned native proof uses the existing D project lane, with a 90 MiB ceiling. Retain compressed slicing/source/section evidence while current or needed to reproduce; release verified duplicate G-code after settlement. Physical tight-fit assembly and strength remain to be checked; no printer command is authorized or sent by these scripts.

Native Bambu slicing passed both print-by-object plates with no warnings: approximately 8 h 36 min /228.9 g total, excluding bed cooling. Both new halves are on plate 1; unchanged auger, adapter and bushing are on plate 2. The editable project contains no embedded G-code.

[Zero-clearance comparison](../locator-zero-review.json), [Geometry evidence](../locator-fit-geometry-review.json), [functional checks](../locator-fit-validation.json), [wall checks](../locator-fit-wall-review.json), [native print verification](../locator-fit-verification.json).

![New lower pins](../renders/locator-fit/lower-print-face.png)

![New upper sockets](../renders/locator-fit/upper-print-face.png)
