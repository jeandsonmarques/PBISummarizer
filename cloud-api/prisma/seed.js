import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcryptjs';

const prisma = new PrismaClient();

async function main() {
  const email = process.env.ADMIN_EMAIL || 'admin@local';
  const plain = process.env.ADMIN_PASSWORD || 'admin123!';
  const role  = 'ADMIN';

  const hash = bcrypt.hashSync(plain, 10);

  // ===== Ajuste aqui se o nome da tabela/colunas forem diferentes =====
  // O model Prisma "User" mapeia a tabela "users" (colunas: email, password_hash, role).
  // Se seu model tiver outro nome, troque prisma.user; se o campo for "password_hash" ou similar, ajuste os atributos do create/update.
  const upserted = await prisma.user.upsert({
    where: { email },
    update: { passwordHash: hash, role },
    create: { email, passwordHash: hash, role }
  });
  // ===================================================================

  console.log('Admin OK:', { id: upserted.id, email: upserted.email, role: upserted.role });
}

main()
  .catch((e) => {
    console.error('Seed error:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
