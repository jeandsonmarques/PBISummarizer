# Summarizer

Summarizer is a QGIS plugin for turning spatial layers and attribute tables into clear, report-ready analytical outputs.

It is designed for teams that need summaries, dashboard-style views, and structured exports without leaving QGIS.

## What it does

- Summarizes layers and table data
- Produces report-oriented analytical outputs
- Provides dashboard-style views inside QGIS
- Supports local-first workflows for day-to-day use
- Can connect to optional cloud or AI-assisted services when configured

## Requirements

- QGIS 3.34 or later
- Standard QGIS Python environment

Core plugin workflows run locally inside QGIS. Optional cloud workflows require a separately deployed backend service, network access, and the credentials or tokens configured by the deployment owner. Optional AI-assisted workflows may also depend on additional local or remote services.

## Installation

### From ZIP

1. Open **Plugins > Manage and Install Plugins...** in QGIS
2. Select **Install from ZIP**
3. Choose the plugin package archive

### From source

The release package is assembled as a single `Summarizer/` folder.

For QGIS publication, the final ZIP must contain only `Summarizer/` at the root.

## Package contents

- `Summarizer/metadata.txt` - QGIS plugin metadata
- `Summarizer/README.md` - package-level release notes
- `Summarizer/CHANGELOG.md` - release history
- `Summarizer/LICENSE` - GPL license text
- `Summarizer/resources/icon.svg` - main plugin icon

## Support

- Repository: https://github.com/jeandsonmarques/Summarizer
- Issues: https://github.com/jeandsonmarques/Summarizer/issues

## License

This project is distributed under `GPL-3.0-or-later`.
