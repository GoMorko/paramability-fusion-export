"""What can be read from a capture for any destination: facts about the design (what a step uses, where it sits, which
sizes may move it) and doubts (sizes that move something whose motion is not known). Both translators (`translator`
for the recipe, `orca_translate` for the Orca Design tab) and the probe plan read it. No Fusion imports, and no
destination words: it never refuses a step, it records what is known through a `recorder.Recorder`."""
