# Fit and lettering coupons

Open [the coupon print project](../print/garden-auger-coupons.3mf) for a small test before another housing print. The [editable model](../experiments/garden-auger-coupons.limo) is built in Limo CAD from the current housing profiles.

The plate holds three pins, one common socket and two lettering plaques. Count the notches along each pin's front edge:

- One notch: 4.90 mm pin, 0.05 mm clearance per side.
- Two notches: 4.80 mm pin, 0.10 mm per side.
- Three notches: 4.70 mm pin, 0.15 mm per side — the owner's selected fit, now applied to all four housing pins.

All three use the 5.00 mm socket. They copy the housing's lead chamfers, 1.8 mm pin height and 2.2 mm socket depth. The flat bases are 18 × 14 × 3.80 mm. Let them cool, then choose the tightest pin that seats fully by hand and comes apart without damage. Report its notch count and any wobble. A coupon checks local fit; it does not prove that both complete housing halves close.

The 40 × 27.2 × 2.72 mm plaques copy the lower housing's actual lettering at its current size and 0.72 mm region depth. The left plaque uses the base color with a concentric surface pattern inside the letters; the right uses a contrasting PETG color. Both surfaces stay solid and nominally flat. The first coupon's plain same-color mask merged away in slicing. The revised texture preserves the letter-shaped toolpaths; its physical readability still needs checking.

Use orange PETG for the bases and blue PETG for contrast. In the current printer, those are main AMS A1 and A2 respectively. The project's logical filaments are 1 and 3; map them explicitly in Studio. Loaded slots can change. Keep both colors PETG.

The coupon tops match the housing's phase within the 0.24 mm layer grid. Settings retain three walls, 15% grid infill, four top layers and three bottom layers. This small plate prints by layer, with no support, brim, skirt, raft or prime tower. The full assembly remains separate.

The first print's Studio estimate with both loaded colors on the main AMS was **40 minutes, 13.78 g and about $0.25** at $17.99/kg. The revised texture changes its toolpaths; slice again for your actual mapping and estimate. The saved plate uses Convenience Mode to match the printer's loaded materials. The owner accepted the three-notch local fit; complete housing closure and the revised texture's readability remain physical checks.

Rebuild and check locally:

```powershell
cargo xtask coupons --slicer "C:/Program Files/Bambu Studio/bambu-studio.exe"
```

The command validates all six native body bounds, pin/socket profile rings, closed mesh boundaries, both color assignments and the sliced process. It never connects to a printer. Evidence stays in `.build/coupon-review`.
