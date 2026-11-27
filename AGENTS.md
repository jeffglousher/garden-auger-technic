# Working on the garden auger

Use `garden-auger.limo` as the source for the assembly. When a solid changes, update its STL and the corresponding mesh in every affected Bambu project. The [workflow](docs/workflow.md) explains how to do that.

- **CAD.** Name features for the part and purpose. The main assembly contains the drive, housing and print flats. The editable [flight model](cad/auger-flight.limo) drives the helical geometry.
- **Printing.** Keep the auger lengthwise, underside down. Use PETG for the structural parts and support bodies, PLA Basic for the bushing, and Bambu Support for PLA/PETG for the contact layers. Keep local reinforcement inside the part.
- **Validation.** Run `cargo test --workspace --locked` for tooling, `cargo xtask verify-model` for CAD, and a native Bambu slice of each affected plate. Check supports, first-layer footprints, materials and clearances. Record what still needs a physical print.
- **Publishing.** Keep temporary exports, G-code and logs under ignored build output. Refresh affected plate images and estimates from the new slice. Keep the README focused on the part, assembly and print files.
