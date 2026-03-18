"""Script para criar tabelas e semear dados basicos."""
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .auth import hash_password
from .db import Base, SessionLocal, engine
from .models import Layer, User

ADMIN_EMAIL = "admin@demo.dev"
ADMIN_PASSWORD = "demo123"

LAYER_SEEDS = [
    {
        "name": "redes_esgoto",
        "provider": "postgis",
        "description": "Camada de rede de esgoto",
        "schema": "public",
        "srid": 31984,
        "epsg": 31984,
        "geom_type": "LINESTRING",
    },
    {
        "name": "pocos_bombeamento",
        "provider": "postgis",
        "description": "Camada de pocos",
        "schema": "public",
        "srid": 31984,
        "epsg": 31984,
        "geom_type": "POINT",
    },
    {
        "name": "bairros",
        "provider": "postgis",
        "description": "Camada de bairros",
        "schema": "public",
        "srid": 31984,
        "epsg": 31984,
        "geom_type": "MULTIPOLYGON",
    },
]


def _ensure_admin(session: Session) -> Tuple[User, bool]:
    admin = session.query(User).filter(User.email == ADMIN_EMAIL).first()
    if admin:
        return admin, False

    admin = User(
        email=ADMIN_EMAIL,
        password_hash=hash_password(ADMIN_PASSWORD),
        role="admin",
    )
    session.add(admin)
    session.flush()  # ensure admin.id is available
    return admin, True


def _seed_layers(session: Session, creator_id: Optional[int]) -> int:
    seed_names = [layer["name"] for layer in LAYER_SEEDS]
    existing = {
        row[0]
        for row in session.query(Layer.name)
        .filter(Layer.name.in_(seed_names))
        .all()
    }

    created = 0
    for payload in LAYER_SEEDS:
        if payload["name"] in existing:
            continue
        session.add(
            Layer(
                **payload,
                created_by_user_id=creator_id,
            )
        )
        created += 1
    return created


def main() -> None:
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    admin = None
    admin_created = False
    layers_created = 0

    try:
        admin, admin_created = _ensure_admin(session)
        admin_id = admin.id if admin else None
        layers_created = _seed_layers(session, creator_id=admin_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if admin_created:
        print(f"Usuario admin criado: {ADMIN_EMAIL}")
    else:
        print(f"Usuario admin ja existia: {ADMIN_EMAIL}")

    if layers_created:
        print(f"{layers_created} camadas de exemplo criadas.")
    else:
        print("Camadas de exemplo ja existiam ou nao foram criadas.")


if __name__ == "__main__":
    main()
