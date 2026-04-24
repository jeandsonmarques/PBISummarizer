# Summarizer

**Summarizer** is a QGIS plugin designed to transform spatial data into clear, report-ready analytical outputs.

It helps analysts and technical teams move from raw layers and attribute tables to structured summaries, dashboard-style views, and decision-oriented outputs without leaving QGIS.

---

## Overview

Many QGIS workflows stop at map exploration. Summarizer extends that workflow by helping users organize spatial and tabular information into formats that are easier to review, present, export, and reuse in reporting pipelines.

The plugin is built with a practical approach:

- core workflows run locally inside QGIS
- reporting-oriented outputs are prioritized
- optional advanced integrations can be enabled when needed
- the package remains focused on usability rather than infrastructure complexity

---

## Key Features

- Layer and attribute table summarization
- Report-ready tabular outputs
- Dashboard-style analytical views inside QGIS
- Local-first core workflows
- Optional cloud-connected and AI-assisted extensions
- Structured export for downstream reporting processes

---

## Main Use Cases

Summarizer is intended for workflows such as:

- project layer summaries
- reporting-oriented spatial analysis
- analytical review of infrastructure or operational datasets
- dashboard-style visualization in QGIS
- preparation of structured outputs for business reporting

---

## Current Status

Summarizer is under active development.

The repository already contains the plugin package structure, publication metadata, and the main application framework for QGIS distribution. Some areas are still being refined, especially around usability, visual consistency, packaging maturity, and release hardening.

---

## Compatibility

- QGIS 3.34 or later
- Standard QGIS Python environment

This project is not currently positioned as QGIS 4 or Qt6 ready.

---

## Installation

### From ZIP

1. Open **Plugins > Manage and Install Plugins...** in QGIS
2. Select **Install from ZIP**
3. Choose the plugin package ZIP file

### From Source

The release package is assembled into a single `Summarizer/` folder for distribution.

For QGIS packaging, the final distributable archive must contain only the `Summarizer/` folder at the root of the ZIP file.

---

## Project Structure

- `Summarizer/` - distributable QGIS plugin package
- `Summarizer/metadata.txt` - QGIS plugin metadata
- `Summarizer/__init__.py` - plugin entry point
- `Summarizer/README.md` - package-level technical notes

---

## Core and Optional Features

### Core Local Features

These workflows are intended to run directly inside QGIS:

- layer summarization
- table-oriented analytical workflows
- report-ready outputs
- dashboard-style visual components

### Optional External Features

Some advanced capabilities may depend on additional configuration, such as:

- cloud-connected workflows
- deployed backend services
- external APIs
- AI-assisted interpretation features
- optional local or remote services

These are not required for the core plugin concept.

---

## Packaging Notes

Before publishing an official plugin package, make sure that:

- metadata links point to the final public repository
- the release ZIP contains only the `Summarizer/` folder at its root
- cache, build, and temporary files are excluded
- the declared version matches the release version
- the package installs correctly through **Install from ZIP** in QGIS

---

## Roadmap

Current priorities include:

- improving usability and visual consistency
- refining dashboard-style workflows
- stabilizing packaging and release flow
- expanding user documentation
- preparing the plugin for broader public distribution

---

## Support

- Repository: https://github.com/jeandsonmarques/Summarizer
- Issues: https://github.com/jeandsonmarques/Summarizer/issues

---

## License

This project is distributed under **GPL-3.0-or-later**.
