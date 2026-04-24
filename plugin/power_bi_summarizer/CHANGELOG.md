# Changelog

## [0.1.0] - 2026-04-06

- Reorganized the repository so the QGIS plugin packages from a release root named `Summarizer/`.
- Separated the plugin package from the `cloud-api/` backend.
- Added publication-oriented metadata, README, changelog and license files.
- Added a packaging script that builds a ZIP containing only the `Summarizer/` folder.
- Moved development smoke tests out of the plugin package boundary.
- Migrated plugin HTTP requests toward the QGIS network stack when available.
- Removed debug `print()` calls from the main plugin client paths.
- Removed the implicit mock admin demo account and clarified cloud versus mock behavior.
