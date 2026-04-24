Summarizer i18n
======================

This folder stores language packs for the plugin.

Current setup:
- Runtime translation pack (PT/EN/ES) in `utils/i18n_runtime.py`.
- Global language selection persisted in `QSettings` key `Summarizer/uiLocale`.
- Reports page texts are translated immediately when language is changed.

Optional Qt Linguist workflow:
1. Generate or update `.ts` files with `pylupdate5`.
2. Compile `.ts` to `.qm` with `lrelease`.
3. Keep `.qm` files in this folder:
   - `Summarizer_en.qm`
   - `Summarizer_es.qm`
4. The plugin loader will pick `.qm` files automatically when available.
