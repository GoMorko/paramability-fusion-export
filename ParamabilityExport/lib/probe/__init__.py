"""Sketch values that follow sizes, measured in Fusion at other size values and fitted. Pure, no Fusion.

`plan` lists what to read and which extra size settings to try, `match` turns a read sketch state into the numbers the
translator writes, `fit` finds exact affine formulas over parameter columns, `motion` holds the result the translator
reads (`build` makes it). The translator imports only `probe.motion`.
"""
