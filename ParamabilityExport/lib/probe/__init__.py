"""Sketch values that follow sizes, measured in Fusion at other size values and fitted. Pure, no Fusion.

`plan` lists what to read and which extra size settings to try, `match` turns a read sketch state into the numbers the
translator writes, `fit` finds exact affine formulas over parameter columns, and `build` makes the motion file
(`sketch_values.motion`) that the translator reads. `state` holds the record of one probe state (`ProbeState`) and its
`report.json` form; `plan` and `build` take either. `derived` is the other way to the same values: it solves the
sketch's dimensions and constraints (`sketch_solve`) and compares the result with what was measured; the export only
records that comparison.
"""
