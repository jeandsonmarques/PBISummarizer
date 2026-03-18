# Power BI Summarizer Cloud API

API em FastAPI com autenticacao JWT e PostgreSQL para expor login, dados do usuario autenticado e catalogo de camadas georreferenciadas. Pensada para deploy no Railway com o comando `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## Estrutura
```
cloud-api/
|-- app/
|   |-- auth.py        # utilitarios de JWT/bcrypt e dependencias de auth
|   |-- db.py          # conexao SQLAlchemy com PostgreSQL
|   |-- main.py        # FastAPI + rotas /api/v1
|   |-- models.py      # ORM (users, layers)
|   |-- schemas.py     # Pydantic (login/token/user/layer)
|   `-- seed.sql       # criacao e carga inicial (admin + 3 camadas)
|-- Dockerfile
`-- requirements.txt
```

## Variaveis de ambiente
Defina no Railway (ou `.env` local) os valores fornecidos:

| Variavel | Descricao |
| --- | --- |
| `DATABASE_URL` | URL completa do Postgres (ex.: `postgresql://...`) |
| `URL_DO_BANCO_DE_DADOS` | Fallback legacy usado enquanto o Railway ainda injeta esta variavel |
| `JWT_SECRET` | Segredo para assinar tokens JWT |
| `JWT_EXPIRES` | Expiracao em segundos (ex.: `3600`) |
| `API_BASEPATH` | Prefixo dos endpoints (padrao `/api/v1`) |
| `CORS_ALLOW_ORIGINS` | Lista separada por virgula de origens permitidas (opcional) |

Essenciais no Railway: defina `DATABASE_URL`, `JWT_SECRET`, `JWT_EXPIRES=3600` e `API_BASEPATH=/api/v1` antes do deploy.

> Em producao (Railway) usamos `psycopg2-binary`. Se preferir `psycopg2` normal, sera preciso instalar `libpq-dev` e compiladores no container.

## Execucao local
```bash
cd cloud-api
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
A documentacao interativa ficara em `http://localhost:8000/api/v1/docs`.

## Inicializar banco no Railway (local)
1. Crie um arquivo `.env` na pasta `cloud-api` apontando para o Postgres do Railway (ou para o seu Postgres local):
   ```bash
   echo DATABASE_URL="postgresql://postgres:SENHA@trolley.proxy.rlwy.net:18067/ferrovia" > .env
   ```
   > A aplicacao primeiro tenta `DATABASE_URL`. Se estiver vazia, cai automaticamente para `URL_DO_BANCO_DE_DADOS`, mantendo compatibilidade com variaveis antigas.
2. Instale as dependencias Python (uma vez):
   ```bash
   pip install -r requirements.txt
   ```
3. Rode o script de inicializacao/semente sempre que quiser garantir as tabelas/usuarios/camadas:
   ```bash
   python -m app.db_init
   ```
   O script executa `Base.metadata.create_all`, cria/atualiza o usuario `admin@demo.dev` (senha `demo123`) e insere as tres camadas de exemplo (`redes_esgoto`, `pocos_bombeamento`, `bairros`) apenas se ainda nao existirem. Depois disso o login via `/api/v1/login` funcionara usando:
   ```
   email: admin@demo.dev
   senha: demo123
   ```

## Prisma (migracoes e seed)
Os comandos do Prisma garantem que o schema do Postgres esteja atualizado e que os dados base sejam criados. Rode uma vez após clonar ou sempre que subir o serviço:

```bash
cd cloud-api
npm install
npm run prisma:deploy   # equivalente a npx prisma migrate deploy
npm run prisma:seed     # equivalente a npx prisma db seed
```

O arquivo `prisma/seed.js` popula o usuário `admin@demo.dev`/`demo123` e as três camadas padrão (`redes_esgoto`, `pocos_bombeamento`, `bairros`). O SQL legacy (`app/seed.sql`) continua disponível para quem preferir aplicar via `psql`.

## Docker / Railway
1. Faca push do diretorio `cloud-api` para o repositorio https://github.com/jeandsonmarques/cloud.git.
2. No Railway, crie um novo servico a partir do repositorio, selecione `cloud-api` como *Root Directory* (sem incluir o nome do repositorio no caminho) e mantenha o comando padrao do Dockerfile.
3. Configure as variaveis em *Settings -> Variables* com: `DATABASE_URL`, `JWT_SECRET`, `JWT_EXPIRES=3600` e `API_BASEPATH=/api/v1` (adicione as demais conforme necessidade).
4. Logo apos o deploy, rode `npx prisma migrate deploy` e `npx prisma db seed` (ou `npm run prisma:deploy` / `npm run prisma:seed`) apontando `DATABASE_URL` para o Postgres do Railway. Isso cria as tabelas `users/layers` e garante o usuario `admin@demo.dev`.
5. Railway fornecera a URL final (`https://<app>.up.railway.app`). Os endpoints ficarao disponiveis em `https://<app>.up.railway.app/api/v1/*`.

## Seed do banco
### Via Prisma (recomendado)
Depois de definir `DATABASE_URL`, rode:
```bash
npm run prisma:deploy
npm run prisma:seed
```
O script `prisma/seed.js` usa Prisma Client + bcrypt para garantir o usuário `admin@demo.dev`/`demo123` e as três camadas padrão.

### Via SQL direto
O arquivo `app/seed.sql` continua disponivel e cria tudo via `psql`:
```bash
psql "$DATABASE_URL" -f app/seed.sql
```
> O script habilita `pgcrypto` automaticamente para usar `crypt('demo123', gen_salt('bf'))`.

## Testes rapidos com curl
Autenticar:
```bash
curl -X POST "$BASE_URL/api/v1/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.dev","password":"demo123"}'
```
Resposta esperada:
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```
Usar o token:
```bash
curl "$BASE_URL/api/v1/me" -H "Authorization: Bearer <jwt>"
curl "$BASE_URL/api/v1/layers" -H "Authorization: Bearer <jwt>"
```
Retorno de `/layers`:
```json
[
  {"id":1,"name":"redes_esgoto","schema":"public","srid":31984,"geom_type":"LINESTRING"},
  {"id":2,"name":"pocos_bombeamento","schema":"public","srid":31984,"geom_type":"POINT"},
  {"id":3,"name":"bairros","schema":"public","srid":31984,"geom_type":"MULTIPOLYGON"}
]
```

## Atualizar banco existente (Railway)
Caso o Postgres ja exista e a tabela `layers` ainda esteja no schema antigo (sem `provider/description/uri/epsg/created_by_user_id` ou com unique apenas em `name`), aplique a migracao incremental `app/migrate_layers.sql`. Ela e idempotente e pode ser rodada mais de uma vez.

1. Pegue a `DATABASE_URL` do Postgres no Railway (Settings -> Variables).
2. Execute o script contra esse banco:
   ```bash
   cd cloud-api
   psql "$DATABASE_URL" -f app/migrate_layers.sql
   ```
   Se preferir GUI, copie o conteudo do arquivo e rode conectado ao Postgres do Railway.
3. Depois de aplicar a migracao, faca um redeploy do servico no Railway para a API usar o schema atualizado.

O script adiciona as colunas novas, garante `provider` como NOT NULL com default `postgis`, remove a unique antiga so em `name` (ignorando se ela nao existir) e cria a unique `uq_layers_name_provider_user` em `(name, provider, created_by_user_id)`.

## Proximos passos sugeridos
- Ajustar politicas de CORS (`CORS_ALLOW_ORIGINS`).
- Adicionar mais camadas/tabelas conforme necessidade do Power BI.
- Criar testes automatizados (pytest) se desejar evoluir a API.
