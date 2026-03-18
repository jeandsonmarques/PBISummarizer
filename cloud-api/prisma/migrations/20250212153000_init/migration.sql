-- Enable bcrypt helpers if seed.sql is executed directly
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS "users" (
    "id" SERIAL PRIMARY KEY,
    "email" VARCHAR(255) NOT NULL UNIQUE,
    "password_hash" TEXT NOT NULL,
    "role" VARCHAR(50) NOT NULL DEFAULT 'admin',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "layers" (
    "id" SERIAL PRIMARY KEY,
    "name" VARCHAR(255) NOT NULL,
    "provider" VARCHAR(50) NOT NULL DEFAULT 'postgis',
    "uri" TEXT,
    "description" TEXT,
    "schema" VARCHAR(255) DEFAULT 'public',
    "srid" INTEGER,
    "epsg" INTEGER,
    "geom_type" VARCHAR(50),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "created_by_user_id" INTEGER REFERENCES "users"("id"),
    CONSTRAINT "uq_layers_name_provider_user" UNIQUE ("name", "provider", "created_by_user_id")
);
