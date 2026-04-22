PowerBISummarizer i18n
======================

This folder stores language packs for the plugin.

Current setup:
- Runtime translation pack (PT/EN/ES) in `utils/i18n_runtime.py`.
- Global language selection persisted in `QSettings` key `PowerBISummarizer/uiLocale`.
- Reports page texts are translated immediately when language is changed.

Optional Qt Linguist workflow (future):
1. Generate/update `.ts` files with `pylupdate5`.
2. Compile `.ts` to `.qm` with `lrelease`.
3. Keep `.qm` files in this folder:
   - `PowerBISummarizer_en.qm`
   - `PowerBISummarizer_es.qm`
4. Plugin loader will pick `.qm` automatically when available.
