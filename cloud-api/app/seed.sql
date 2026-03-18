-- Enable pgcrypto so we can hash passwords using bcrypt (bf)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS layers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'postgis',
    uri TEXT,
    description TEXT,
    schema TEXT DEFAULT 'public',
    srid INT,
    epsg INT,
    geom_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id INT REFERENCES users(id),
    CONSTRAINT uq_layers_name_provider_user UNIQUE (name, provider, created_by_user_id)
);

INSERT INTO users (email, password_hash, role)
VALUES ('admin@demo.dev', crypt('demo123', gen_salt('bf')), 'admin')
ON CONFLICT (email) DO NOTHING;

INSERT INTO layers (name, provider, uri, description, schema, srid, epsg, geom_type, created_by_user_id)
VALUES
    ('redes_esgoto', 'postgis', NULL, 'Camada de rede de esgoto', 'public', 31984, 31984, 'LINESTRING', 1),
    ('pocos_bombeamento', 'postgis', NULL, 'Camada de pocos', 'public', 31984, 31984, 'POINT', 1),
    ('bairros', 'postgis', NULL, 'Camada de bairros', 'public', 31984, 31984, 'MULTIPOLYGON', 1)
ON CONFLICT (name, provider, created_by_user_id) DO NOTHING;
