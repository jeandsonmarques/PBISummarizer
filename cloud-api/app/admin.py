import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user, get_password_hash
from app.config import UPLOAD_DIR
from app.db import get_db

admin_router = APIRouter(prefix="/admin", tags=["admin"])
_INVALID_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
logger = logging.getLogger(__name__)


@dataclass
class GpkgMetadata:
    table_name: str
    geometry_column: str
    geometry_type: str
    srid: Optional[int]
    identifier: Optional[str] = None
    extent: Optional[Tuple[float, float, float, float]] = None


@admin_router.post(
    "/create-user",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: schemas.CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admins podem criar usuarios.",
        )

    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="E-mail ja cadastrado"
        )

    hashed_pw = get_password_hash(payload.password)

    user = models.User(
        email=payload.email,
        password_hash=hashed_pw,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def _require_admin(current_user: models.User) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admins podem executar esta acao.",
        )


def _sanitize_filename(name: str) -> str:
    sanitized = _INVALID_FILENAME_CHARS.sub("_", name)
    sanitized = sanitized.strip("._") or "layer"
    return sanitized


def _cleanup_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        # Best effort cleanup; ignore failures so API can still return an error
        pass


def _extract_gpkg_metadata(path: Path) -> GpkgMetadata:
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo GPKG nao encontrado apos upload.",
        )
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as exc:  # pragma: no cover - SQLite failure
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel abrir o arquivo GPKG enviado.",
        ) from exc

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                g.table_name,
                g.column_name,
                g.geometry_type_name,
                s.organization,
                s.organization_coordsys_id,
                g.srs_id
            FROM gpkg_geometry_columns g
            LEFT JOIN gpkg_spatial_ref_sys s ON g.srs_id = s.srs_id
            ORDER BY g.table_name
            """
        )
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O arquivo GPKG nao possui colunas de geometria.",
            )
        table_name, geom_column, geom_type, org, org_srid, fallback_srid = rows[0]
        srid: Optional[int] = None
        if org and org.upper() == "EPSG" and org_srid is not None:
            srid = int(org_srid)
        elif fallback_srid is not None:
            srid = int(fallback_srid)
        cursor.execute(
            """
            SELECT
                identifier,
                min_x,
                min_y,
                max_x,
                max_y
            FROM gpkg_contents
            WHERE table_name = ?
            """,
            (table_name,),
        )
        contents = cursor.fetchone()
        identifier = table_name
        extent: Optional[Tuple[float, float, float, float]] = None
        if contents:
            identifier = contents[0] or table_name
            bounds = contents[1:]
            if all(value is not None for value in bounds):
                extent = tuple(float(value) for value in bounds)  # type: ignore[arg-type]
    except sqlite3.Error as exc:  # pragma: no cover - SQLite failure
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel ler os metadados do GPKG.",
        ) from exc
    finally:
        conn.close()

    geom_type_name = (geom_type or "").upper().strip()
    if not geom_type_name or not geom_column:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel identificar o tipo de geometria do arquivo GPKG.",
        )
    return GpkgMetadata(
        table_name=table_name,
        geometry_column=geom_column,
        geometry_type=geom_type_name,
        srid=srid,
        identifier=identifier,
        extent=extent,
    )


@admin_router.post(
    "/upload-layer-gpkg",
    response_model=schemas.LayerOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_layer_gpkg(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    description: str | None = Form(None),
    epsg: int | None = Form(None),
    group_name: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_admin(current_user)

    filename = file.filename or ""
    if not filename.lower().endswith(".gpkg"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envie um arquivo com extensao .gpkg",
        )

    base_name = Path(filename).stem
    safe_stem = _sanitize_filename(base_name)
    safe_display_name = name.strip() if name and name.strip() else safe_stem

    now = datetime.utcnow()
    dated_path = Path(str(now.year), f"{now.month:02}", f"{now.day:02}")
    generated_filename = f"{uuid4().hex}_{safe_stem}.gpkg"
    base_upload_dir = UPLOAD_DIR.resolve()
    # Evita duplicar subpasta gpkg se UPLOAD_DIR ja termina com gpkg
    relative_prefix = Path("" if base_upload_dir.name.lower() == "gpkg" else "gpkg")
    relative_uri = (relative_prefix / dated_path / generated_filename).as_posix()
    target_dir = base_upload_dir / relative_prefix / dated_path
    target_path = target_dir / generated_filename

    target_dir.mkdir(parents=True, exist_ok=True)

    existing = (
        db.query(models.Layer)
        .filter(
            models.Layer.name == safe_display_name,
            models.Layer.provider == "gpkg",
            models.Layer.created_by_user_id == current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ja existe uma camada com este nome para este usuario.",
        )

    try:
        with target_path.open("wb") as out_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)
        print(f"[UPLOAD GPKG] UPLOAD_DIR={base_upload_dir}")
        print(f"[UPLOAD GPKG] uri salvada no banco={relative_uri}")
        print(f"[UPLOAD GPKG] caminho completo={target_path}")

        metadata = _extract_gpkg_metadata(target_path)
        detected_srid = metadata.srid
        logger.info(f"[UPLOAD GPKG] epsg_form={epsg}, srid_from_gpkg={detected_srid}")
        if detected_srid is None and epsg is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nao foi possivel determinar o SRID do arquivo GPKG. Informe um EPSG valido.",
            )
        if detected_srid is not None:
            final_srid = int(detected_srid)
            if epsg is not None and int(epsg) != final_srid:
                logger.warning(
                    "[UPLOAD GPKG] EPSG informado %s difere do SRID %s. Usando SRID do arquivo.",
                    epsg,
                    detected_srid,
                )
        else:
            final_srid = int(epsg) if epsg is not None else None

        normalized_group = (group_name or "").strip() or None

        layer = models.Layer(
            name=safe_display_name,
            provider="gpkg",
            uri=relative_uri,
            description=description,
            group_name=normalized_group,
            epsg=final_srid,
            srid=final_srid,
            schema=None,
            geom_type=metadata.geometry_type,
            created_by_user_id=current_user.id,
        )
        db.add(layer)
        db.commit()
        db.refresh(layer)
    except IntegrityError as exc:
        db.rollback()
        _cleanup_file(target_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ja existe uma camada com este nome.",
        ) from exc
    except HTTPException:
        db.rollback()
        _cleanup_file(target_path)
        raise
    except Exception:
        db.rollback()
        _cleanup_file(target_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao salvar camada GPKG",
        )
    finally:
        await file.close()

    return layer
