# Current design decisions

Use these decisions when rebuilding or reviewing the current release. Historical alternatives in Git and supplier reference files do not select a different design.

- The user-confirmed [INJORA dimensioned diagram](../source/references/injora-injs035-360-dimensions.jpg) controls the 40 ×20 mm case, 2.7 mm mounting ears and 4.0 mm nominal tip-to-case stack. Do not substitute the contradictory summary dimensions or request these dimensions again. [Source provenance](../source/references/provenance.json) records what is shown and what remains unshown.
- One PETG adapter seats directly on the servo's metal shaft, retained by its compatible center screw. Its round pilot has no printed spline teeth. There is no separate metal horn or M4 mounting pattern.
- The pilot is provisionally Ø5.70 ×3.70 mm. Select the diameter from the four physical fit coupons. The [Hitec H25T depth reference](../source/references/hitec-horn-spline-2026.pdf), printed page 75, supplies the 3.70 mm design depth; it is not a universal servo standard.
- Keep the 14 mm rounded square peg, 14.4 mm socket, Ø24 adapter boss, Ø28 ×5 mm flange and full loose PLA sleeve. The clamshell alone captures the collar and sleeve. No ring lock or clip is needed.
- Use the current housing with its shared entrance taper and restored 3.10 mm ear pocket. Preserve the locating features, screw seats and four Ø4.00 ×6.70 mm insert pilots for ruthex RX-M3×5.7 inserts.
- CAD design colors and saved slicer spool colors have distinct purposes; both remain explicit in [README](../README.md). The Bambu project contains current object overrides. Portable 3MF exports carry geometry and material metadata; STLs carry only geometry.

Print feedback is pending. Remaining checks are printed fit and seating, usable internal screw depth and factory screw compatibility, cable boot fit, free rotation, alignment, loaded torque, creep and wear. CAD checks do not establish a measured strength rating. These checks do not reopen the confirmed nominal hardware dimensions.

The separate CAD application team owns the 3MF feature work tracked in [Limo-CAD issues #312–#316](https://github.com/jackControls/Limo-CAD/issues/312). This repository continues to use its existing export and Bambu preparation scripts until those capabilities are implemented and verified.
