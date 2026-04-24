# Summarizer Package

This directory contains the distributable QGIS plugin package.

## Package scope

The package is intentionally client-side only. It includes the plugin code, resources, and metadata needed for QGIS to load the extension.

## Distribution rules

- Ship only the `Summarizer/` folder at the root of the ZIP archive.
- Keep development-only assets, test fixtures, and backend components out of the release package.
- Make sure `metadata.txt` is updated before publishing.

## Included surface area

- plugin entry point
- plugin metadata
- UI and report components
- local resources and icons
- optional integrations used by the QGIS client

## Release checklist

- confirm version and compatibility in `metadata.txt`
- confirm repository and issue tracker URLs
- verify the archive structure before release, with `Summarizer/` at the ZIP root
- remove temporary files and build artifacts
