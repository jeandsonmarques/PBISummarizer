-- Atualizacao incremental da tabela layers para alinhar com app/models.py
-- O script e idempotente e pode ser executado quantas vezes for necessario.
BEGIN;

-- Novas colunas usadas pela API
ALTER TABLE layers ADD COLUMN IF NOT EXISTS provider VARCHAR(50);
ALTER TABLE layers ALTER COLUMN provider SET DEFAULT 'postgis';
UPDATE layers SET provider = 'postgis' WHERE provider IS NULL;
ALTER TABLE layers ALTER COLUMN provider SET NOT NULL;

ALTER TABLE layers ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE layers ADD COLUMN IF NOT EXISTS uri VARCHAR(1024);
ALTER TABLE layers ADD COLUMN IF NOT EXISTS epsg INT;
ALTER TABLE layers ADD COLUMN IF NOT EXISTS created_by_user_id INT;

-- Remover qualquer unique baseado apenas em name
DO $$
DECLARE
    constraint_record record;
BEGIN
    FOR constraint_record IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'layers'::regclass
          AND contype = 'u'
          AND conkey = ARRAY[
              (SELECT attnum FROM pg_attribute WHERE attrelid = 'layers'::regclass AND attname = 'name')
          ]
    LOOP
        EXECUTE format('ALTER TABLE layers DROP CONSTRAINT %I', constraint_record.conname);
    END LOOP;
END $$;

-- Unique novo: (name, provider, created_by_user_id)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'layers'::regclass
          AND conname = 'uq_layers_name_provider_user'
    ) THEN
        ALTER TABLE layers
            ADD CONSTRAINT uq_layers_name_provider_user
            UNIQUE (name, provider, created_by_user_id);
    END IF;
END $$;

-- FK opcional para o criador
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'layers' AND column_name = 'created_by_user_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'layers'::regclass
          AND contype = 'f'
          AND conname = 'fk_layers_created_by_user_id'
    ) THEN
        ALTER TABLE layers
            ADD CONSTRAINT fk_layers_created_by_user_id
            FOREIGN KEY (created_by_user_id) REFERENCES users(id)
            ON DELETE SET NULL;
    END IF;
END $$;

COMMIT;
