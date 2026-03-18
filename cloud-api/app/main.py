import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.admin import admin_router
from app.config import UPLOAD_DIR
from . import auth, db, models, schemas

API_BASEPATH = os.getenv("API_BASEPATH", "/api/v1")
ALLOWED_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")

app = FastAPI(
    title="Power BI Summarizer Cloud API",
    version="1.0.0",
    docs_url=f"{API_BASEPATH}/docs",
    redoc_url=f"{API_BASEPATH}/redoc",
    openapi_url=f"{API_BASEPATH}/openapi.json",
)

origins = [origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter()


@app.on_event("startup")
def _ensure_upload_dir() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@api_router.get("/health", tags=["health"])  # Simple readiness probe
def readiness_check():
    return {"status": "ok"}


@api_router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db_session: Session = Depends(db.get_db)):
    user = auth.authenticate_user(db_session, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = auth.create_access_token(subject=str(user.id))
    return schemas.TokenResponse(access_token=token, expires_in=auth.JWT_EXPIRES)


@api_router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@api_router.get("/layers", response_model=List[schemas.LayerOut])
def list_layers(
    current_user: models.User = Depends(auth.get_current_user),
    db_session: Session = Depends(db.get_db),
):
    layers = db_session.query(models.Layer).order_by(models.Layer.name.asc()).all()
    return layers


def _resolve_user_from_request(
    request: Request,
    db_session: Session,
    token_query: Optional[str] = None,
) -> models.User:
    """
    Resolve o usuario autenticado a partir do header Authorization ou do
    parametro de query "token" (usado pelo plugin ao baixar GPKG).
    """
    auth_header = request.headers.get("Authorization") or ""
    token_value = (token_query or "").strip()
    if not token_value and auth_header.lower().startswith("bearer "):
        token_value = auth_header.split(" ", 1)[1].strip()

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token_value:
        raise credentials_exception

    try:
        payload = jwt.decode(token_value, auth.JWT_SECRET, algorithms=[auth.JWT_ALGORITHM])
        subject: Optional[str] = payload.get("sub")
        if subject is None:
            raise credentials_exception
    except JWTError as exc:  # pragma: no cover - jose libera detalhes
        raise credentials_exception from exc

    user = db_session.query(models.User).filter(models.User.id == int(subject)).first()
    if user is None:
        raise credentials_exception
    return user


@api_router.get("/layers/{layer_id}/download-gpkg")
def download_layer_gpkg(
    layer_id: int,
    request: Request,
    token: Optional[str] = None,
    db_session: Session = Depends(db.get_db),
):
    """
    Faz download do GPKG salvo em UPLOAD_DIR para camadas com provider='gpkg'.
    Protegido por autenticacao (Bearer header ou query param ?token=...).
    """
    _resolve_user_from_request(request, db_session, token_query=token)

    layer = db_session.query(models.Layer).filter(models.Layer.id == layer_id).first()
    if layer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camada nao encontrada")
    if (layer.provider or "").lower() != "gpkg":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Download disponivel apenas para camadas GPKG.",
        )
    if not layer.uri:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Caminho do GPKG nao registrado para esta camada.",
        )

    base_dir = UPLOAD_DIR.resolve()
    try:
        relative_path = Path(layer.uri)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Caminho do arquivo invalido.",
        )
    target_path = (base_dir / relative_path).resolve()
    try:
        target_path.relative_to(base_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Caminho do arquivo invalido.",
        )

    print(f"[DOWNLOAD GPKG] UPLOAD_DIR={base_dir}")
    print(f"[DOWNLOAD GPKG] uri do layer={layer.uri}")
    print(f"[DOWNLOAD GPKG] caminho completo={target_path}")
    print(f"[DOWNLOAD GPKG] existe? {target_path.is_file()}")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arquivo GPKG nao encontrado: {target_path}",
        )

    filename = Path(layer.uri).name or f"layer_{layer_id}.gpkg"

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Accept-Ranges": "bytes",
    }
    return FileResponse(
        path=target_path,
        filename=filename,
        media_type="application/geopackage+sqlite3",
        headers=headers,
    )


@api_router.delete("/layers/{layer_id}")
def delete_layer(
    layer_id: int,
    request: Request,
    token: Optional[str] = None,
    db_session: Session = Depends(db.get_db),
):
    """
    Remove um registro de camada e seu arquivo GPKG associado (quando aplicável).
    Disponível apenas para administradores autenticados.
    """
    user = _resolve_user_from_request(request, db_session, token_query=token)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admins podem excluir camadas.",
        )

    layer = db_session.query(models.Layer).filter(models.Layer.id == layer_id).first()
    if layer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camada nao encontrada.")

    provider = (layer.provider or "").lower()
    if provider == "gpkg" and layer.uri:
        base_dir = UPLOAD_DIR.resolve()
        try:
            relative_path = Path(layer.uri)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caminho do arquivo invalido.",
            )
        target_path = (base_dir / relative_path).resolve()
        try:
            target_path.relative_to(base_dir)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caminho do arquivo invalido.",
            )
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Falha ao remover arquivo GPKG: {exc}",
                )

    db_session.delete(layer)
    db_session.commit()
    return {"status": "ok"}


app.include_router(api_router, prefix=API_BASEPATH)
app.include_router(
    admin_router,
    prefix=API_BASEPATH,
)
