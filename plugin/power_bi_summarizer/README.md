# Summarizer Package

This folder contains the distributable QGIS plugin package used for publication.

## Package scope

The package is client-side only. It includes the plugin code, metadata, and resources required for QGIS to load and run the extension.

## Distribution rules

- Ship only the `Summarizer/` folder at the root of the ZIP archive.
- Exclude development-only files, temporary artifacts, cached bytecode, and build outputs.
- Keep backend services and other deployment-specific components outside the release ZIP.

## Included surface area

- plugin entry point
- plugin metadata
- UI and reporting components
- local resources and icons
- optional integrations used by the QGIS client

## Release checklist

- confirm version, description, and compatibility in `metadata.txt`
- confirm repository, homepage, and issue tracker URLs
- verify that the archive root is `Summarizer/`
- verify that no generated files or hidden directories are present
