# Direct CAD tool validation

The corrected assembly is open in a **Limo CAD Bevy desktop**. This review used the product's MCP tools directly, attached to that live document. The [raw native results](../cad-tool-validation.json) preserve its session identity, feature statuses, exact interference results, print warnings, hole-summary warnings and drawing references.

The [consistency audit](design-audit.md) records the intentionally failed alignment control, former incomplete flight envelope and additional datum-transfer allowance. The current files include its Ø33.6 entrance correction and rear cable passage; these nominal drawing sheets were re-exported from that source with revision PRINT-6. Broader tolerance and motion coverage remains separate evidence with explicit limitations.

Open [garden-auger-fit-inspection.limo](../garden-auger-fit-inspection.limo) for the current native inspection document, with **three associative drawing sheets** and a saved view showing the mating surfaces. It uses the current schema 10. The canonical schema-7 [print source](../garden-auger-direct-drive.nbcad) and housing print exports include the flat printable exterior; the auger, sleeve and adapter geometry is preserved. The native scene's mesh arrays match before and after adding the inspection sheets. The raised cover and servo are presentation offsets; mechanical placements are preserved.

![Mating surfaces captured from the live CAD window](../renders/cad-fit-mating-surfaces.png)

## What the CAD tool confirmed

Native project-open recomputed **71 features** with no failed feature status. The scene contains seven native bodies belonging to six components: five printed parts, including the two-body auger, and the purchased servo reference. All seven have appearances.

`assembly_interference_check` returned **exact: true** and **zero overlap volume in all 15 reported pairs** at the assembled mechanical poses. It measured **0.20 mm** nearest servo-to-housing clearance in each half, **0.30 mm** servo-case-to-adapter clearance, **0.80 mm** adapter-to-housing clearance and **0.20 mm** square-mate clearance. The housing seam touches at zero gap without volumetric interference. A 2 mm reporting threshold exposes near pairs; it is not a universal required fit gap.

The native drawing tools resolve retained topology references, then generate measured dimension text. No dimension value was entered as a label. [Sheet 1](../renders/cad-fit-dimensions.svg) measures **40.50 mm case plan length, 37.50 mm case height, 20.00 mm case width, 2.70 mm ear thickness, 24.70 mm ear underside-to-rear, 56.00 mm ear span, 41.30 mm pocket plan length, 40.00 mm cavity axial span and 3.10 mm ear pocket**. It also measures the lower half's **10.40 mm** pocket depth to the split face. The matching slot corners are **49.00 mm** apart; both reference slots have equal width, so their center separation is the same.

[Sheet 2](../renders/cad-fit-clearances.svg) measures **20.80 mm full clamshell pocket width**, **1.50 mm nominal rear case clearance** and **0.20 mm nominal front ear clearance** directly between the relevant bodies.

[Sheet 3](../renders/cad-thin-wall-dimensions.svg) measures the selected **10.20 mm servo floor, 3.80 mm left ear wall and 3.80 mm right ear wall** from current topology anchors. Every older housing anchor was rebound to a returned current edge endpoint before the sheets were re-exported. The engine recomputed identical meshes from the canonical source and inspection copy. [Exterior revision evidence](../thin-housing-verification.json) includes native sleeve capture checks, the unchanged other-body mesh arrays and actual native Bambu support/toolpath evidence.

![Current lower housing captured from the live CAD window](../renders/cad-thin-housing.png)

## Limits and warnings retained

- **Support and bridges:** both housing objects emit zero support toolpaths. A separate automatic-support lower-half probe also emits none. Upper screw-recess roofs remain short unsupported bridges; neither CAD preflight nor Bambu slice success certifies printed bridge quality. Check the test article. The native `support_used` metadata reflects globally enabled support and can remain true even when no support is extruded; emitted roles, feature times and actual material use are checked separately.
- **Wall thickness:** no automatic global minimum-wall validator is exposed. The new associative dimensions measure selected nominal planes. Bearing, ear and screw transitions retain extra stock; printed strength remains a physical test.
- **GD&T:** the available CAD interface has no automatic tolerance-stack validator. The previously reported tolerance bounds are separately derived inspection requirements. They are not a native CAD-certified GD&T result. These new sheets validate nominal geometry.
- **Motion:** the saved assembly has no joints or motion studies. This direct check is at its assembled poses; it does not provide a native swept-motion result. The earlier sampled checks are separate evidence.
- **Print preflight:** `ok: true` confirms timeline/appearance readiness, while its separate layout report warns about off-bed bodies and possible bounding-box overlap in the assembled pose. Its conservative mesh-bound warnings are distinct from the exact assembly interference result. The printer project has its own four-plate verification; the assembled CAD position is not a print layout.
- **Hole summary:** the tool reports 44 inferred holes with unknown depths and ten overlap warnings. Its adapter projection identifies open **R1 corner arcs**, while its summary counts those as four Ø2 holes. The inferred counterbore classification also includes outer cylindrical faces. This summary cannot certify bore depth or distinguish every bore from a fillet or outer surface. The raw warnings are preserved, rather than hidden or called a clean pass.
- **Absent hardware details:** the purchased envelope omits shaft teeth/the output-shaft solid, its internal threaded cavity and the cable boot. The tool cannot validate press-fit engagement, actual screw bottoming or boot fit for geometry that is absent. Physical print fit and loaded strength also remain outside this nominal CAD check.

The confirmed result is **a successfully recomputed nominal assembly with no reported volumetric collisions and native dimensions matching the corrected mating geometry**. No broader certification is claimed.


## Cable-envelope tooling experiment

The [separate native CAD experiment](../experiments/cable-routing-trial.limo) shows a cyan virtual Ø4 cable in the actual current housing. Production source and print files exclude that extra body. [Raw checks](../cable-route-verification.json) preserve the previous handle-blocked outlet, verify continuous native Ø4/Ø5 swept volumes, reject Ø6.2, and record sampled insertion, closure and offset trials. The nearest rear insert now has 3.07 mm sampled surrounding wall after allowance. Bundle size, boot and the trial R8 bend remain physical checks. [Tooling notes](cable-routing-experiment.md) distinguish this static native 3D volume check from Shapely's planar outlet check and from unimplemented flexible-wire mechanics.
