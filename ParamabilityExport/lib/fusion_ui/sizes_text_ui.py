"""Fallback for the sizes table: one multi line text box with CSV text, used when the table cannot be shown."""
from ..export_plan.dialog_rows import escape, text_rows
from ..export_plan.sizes_text import others_line, prefill_sizes_text, settable_parameters

SIZES_ID = "pm_sizes_text"
OTHERS_ID = "pm_sizes_others"
NOTICE_ID = "pm_sizes_notice"
HELP_ID = "pm_sizes_help"

NOTICE = "The table could not be shown in this Fusion version, so sizes are typed as text."
HELP = "First line: name, then the parameters that change. Each next line is one size."


def build(inputs, params):
    inputs.addTextBoxCommandInput(NOTICE_ID, "", escape(NOTICE), text_rows([NOTICE]), True)
    inputs.addTextBoxCommandInput(HELP_ID, "", escape(HELP), text_rows([HELP]), True)
    inputs.addTextBoxCommandInput(SIZES_ID, "Sizes", prefill_sizes_text(params), 8, False)
    columns = [p["name"] for p in settable_parameters(params)]
    others = others_line(params, columns)
    inputs.addTextBoxCommandInput(OTHERS_ID, "", escape(others), text_rows([others]), True)


def read_text(inputs):
    return inputs.itemById(SIZES_ID).text
