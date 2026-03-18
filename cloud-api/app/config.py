import os
from pathlib import Path

# Base directory where uploaded GPKG files will be stored.
_UPLOAD_DIR_ENV = os.environ.get("UPLOAD_DIR")
if _UPLOAD_DIR_ENV:
    UPLOAD_DIR = Path(_UPLOAD_DIR_ENV)
else:
    UPLOAD_DIR = Path("/data/gpkg")
