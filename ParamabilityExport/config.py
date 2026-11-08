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
EXPORT_COMMAND_TOOLTIP = "Save this design as a .paramability file with size choices."

PACKAGE_EXTENSION = ".paramability"
