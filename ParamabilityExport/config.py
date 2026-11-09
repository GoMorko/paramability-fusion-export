"""Names and ids shared by the add-in."""
import os

ADDIN_NAME = os.path.basename(os.path.dirname(__file__))
COMPANY_NAME = "Paramability"

WORKSPACE_ID = "FusionSolidEnvironment"
TAB_ID = "ToolsTab"
PANEL_ID = "ParamabilityPanel"
PANEL_NAME = "Paramability"

EXPORT_COMMAND_ID = "ParamabilityExportCommand"
EXPORT_COMMAND_NAME = "Export for Paramability"
EXPORT_COMMAND_TOOLTIP = "Save a body as a .paramability file. Your user parameters become sizes you can change in Paramability."

ROWS_COMMAND_ID = "ParamabilityExportRowsCommand"
ROWS_COMMAND_NAME = "Export size choices"
ROWS_COMMAND_TOOLTIP = "Save a body in several ready-made sizes, as a dropdown in Paramability."

PACKAGE_EXTENSION = ".paramability"
