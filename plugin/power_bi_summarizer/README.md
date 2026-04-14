# Power BI Summarizer

Power BI Summarizer is a QGIS plugin for summarizing QGIS layers, preparing reporting-ready tables, and supporting Power BI-oriented analysis workflows from inside QGIS.

## Overview

The plugin combines local QGIS data exploration, report-style summaries, dashboard helpers, export utilities, and optional cloud connectivity in a single client package. The QGIS plugin is installable on its own, while the backend service used by cloud workflows is deployed separately and is not bundled in the plugin ZIP.

## Features

- Summarize vector layer content into tables and metrics ready for reporting.
- Build dashboard-oriented views and chart widgets inside QGIS.
- Export datasets and derived outputs for downstream Power BI workflows.
- Connect to optional cloud catalogs and remote layer delivery endpoints.
- Support optional AI-assisted interpretation for report generation.

## Installation

### Install from a ZIP package

1. Build or obtain a ZIP that contains only the `power_bi_summarizer/` folder.
2. In QGIS, open `Plugins > Manage and Install Plugins...`.
3. Use `Install from ZIP` and select the generated package.

### Build the ZIP from this repository

Package the `plugin/power_bi_summarizer/` folder into a ZIP so that the archive contains only the `power_bi_summarizer/` directory at its root.

If you prefer an automated build step, restore or create a packaging script before generating the release ZIP.

## Basic usage

1. Enable the plugin in QGIS.
2. Open `Power BI Summarizer` from the Plugins menu.
3. Select project layers or imported datasets.
4. Generate summaries, pivoted views, charts, or exportable outputs.
5. Configure cloud settings only if you need remote catalog workflows.

## What works locally

These workflows are available with the plugin alone:

- summarize local QGIS layers
- build pivoted or report-style views
- export local results to supported output formats
- use browser integration with local or saved database connections
- use the sample mock catalog for non-production cloud UI testing

## Cloud features

Cloud functionality is optional and is not required for the plugin to load or for local summarization workflows to work.

The plugin includes:

- a cloud client UI
- session management
- endpoint configuration
- optional browser integration with remote layers

The plugin does not include:

- the `cloud-api/` backend
- hosted storage
- user provisioning outside the backend API
- account recovery, hosting, or infrastructure operations

Real cloud workflows require all of the following:

- a separately deployed backend service
- a reachable HTTP or HTTPS base URL
- valid user credentials for that deployment
- any required backend storage or database configuration

If no backend is configured, the plugin still works for local summarization and can fall back to the sample mock catalog for non-production cloud screens.

## External dependencies

### Required runtime environment

- QGIS 3.34 to 3.99
- Standard QGIS Python environment

### Optional Python or service dependencies

- `pandas` for table-oriented processing used by several UI and reporting flows
- the QGIS network stack for cloud HTTP communication inside QGIS
- `langchain-openai` plus an OpenAI API key for optional LangChain-based interpretation
- a local Ollama service for optional local fallback interpretation

Optional dependencies are not required for the core plugin UI to load, but related features remain unavailable until configured.

## Limitations

- The plugin is currently scoped to QGIS 3 and is not yet declared ready for QGIS 4 or Qt6.
- Cloud features depend on an external backend that must be deployed and operated separately.
- Remote GPKG access currently relies on a tokenized download URL for GDAL `/vsicurl/` access. This should be reviewed again before public publication.
- Saved database connection passwords should be reviewed carefully before public publication. Prefer QGIS authentication storage when possible.
- Optional AI features depend on services that may introduce cost, latency, network, or policy requirements.

## Support and issues

- Project page: `<README_OR_PROJECT_PAGE_URL>`
- Source repository: `<PUBLIC_REPOSITORY_URL>`
- Issue tracker: `<ISSUES_URL>`

Replace the placeholders above before publishing the repository or uploading a release to the official QGIS plugin repository.
