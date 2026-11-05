# Garden auger

A servo-driven garden auger designed with **[Limo CAD](https://github.com/limo-cad/Limo-CAD)**. The editable model includes matching clamshell halves, flat-bottom D grips, a rotating dirt shield, a square drive adapter and a captured wear bushing.

![Current assembly](docs/images/assembly.png)

## Open or print

- **[garden-auger.limo](garden-auger.limo)**: editable source with 84 descriptive features and a complete-assembly view.
- **[print/garden-auger.3mf](print/garden-auger.3mf)**: current Bambu project, five parts on two plates, print by object.
- **[Individual STLs](print/parts/)**: geometry only.
- **[Assembly notes](docs/assembly.md)** and **[CAD/export walkthrough](docs/workflow.md)**.

The saved Bambu X2D /0.4 mm project uses 0.24 mm layers, three global walls and 15% grid infill. Nine named local zones use five walls and 100% infill around insert anchors, opposing screw load paths and the adapter hub. Native slicing passes without warnings: about **5 h 58 min /160.5 g**, plus cooling and plate handling. Plate 2 completes PETG parts before the PLA bushing and waits for a 55 C bed.

Housing: yellow PETG. Auger: orange PETG. Adapter: gray PETG. Bushing: teal PLA. Four M3 x18 screws and four ruthex RX-M3x5.7 inserts close the clamshell. The servo-to-adapter connection is owner-confirmed proven and complete.

## Design, export, adjust

1. Model geometry and check assembly interference in Limo CAD.
2. Export manufacturing geometry into the saved Bambu project.
3. Apply localized adjustments using **[reinforcement.json](print/reinforcement.json)** and **[build_print.py](scripts/build_print.py)**, or edit those modifier regions in Bambu Studio.
4. Slice locally and verify imported settings, object order and the thermal transition.

The nine regions in this example currently live in the manufacturing project, not in the `.limo` model. Limo already exposes print-modifier engine/MCP operations; visible UI and end-to-end handoff acceptance are tracked in **[Limo CAD #316](https://github.com/limo-cad/Limo-CAD/issues/316)**, following the implemented modifier scope in [#314](https://github.com/limo-cad/Limo-CAD/issues/314). This public model is a reproducible case for that work. No CAD application implementation is included here.

Rebuild external adjustments using Python 3.10+ (standard library only):

```sh
python scripts/build_print.py
```

Optionally regenerate native slice evidence without sending a print:

```sh
python scripts/build_print.py --slicer "C:/Program Files/Bambu Studio/bambu-studio.exe"
```

With Limo CAD installed, `python scripts/verify_model.py` checks names, bounds and exact nominal interference. Pass `--executable /path/to/Limo-CAD` for a different installation.

## Validation and remaining work

[Validation record](docs/validation.json): cleanup preserves all seven native CAD body meshes and all five print meshes. Two auger CAD bodies export as one printed part. Materials and the validated two-plate layout remain. Locators retain diameter5 mm matched pins/sockets and zero nominal diametral clearance.

Remaining physical checks: revised assembly closure/free rotation, clamped housing/insert durability and hand comfort, and the first soil/ingress trial. See [assembly acceptance #5](https://github.com/jeffglousher/garden-auger-technic/issues/5) and [soil trial #3](https://github.com/jeffglousher/garden-auger-technic/issues/3). Geometry checks and slicer estimates do not establish a numerical strength rating.

Earlier experiments and candidates remain in Git history through `43a04a9`; the current tree keeps one clear model and print project.
