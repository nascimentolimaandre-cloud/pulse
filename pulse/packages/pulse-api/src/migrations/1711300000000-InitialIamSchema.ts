import { MigrationInterface, QueryRunner } from 'typeorm';

export class InitialIamSchema1711300000000 implements MigrationInterface {
  name = 'InitialIamSchema1711300000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    // ── iam_organizations ──────────────────────────────────────────
    await queryRunner.query(`
      CREATE TABLE "iam_organizations" (
        "id"         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
        "tenant_id"  uuid         NOT NULL,
        "name"       varchar(255) NOT NULL,
        "slug"       varchar(100) NOT NULL UNIQUE,
        "created_at" timestamp    NOT NULL DEFAULT now(),
        "updated_at" timestamp    NOT NULL DEFAULT now()
      );
    `);

    await queryRunner.query(
      `CREATE INDEX "IDX_iam_organizations_tenant_id" ON "iam_organizations" ("tenant_id")`,
    );

    await queryRunner.query(
      `ALTER TABLE "iam_organizations" ENABLE ROW LEVEL SECURITY`,
    );

    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_select" ON "iam_organizations"
        FOR SELECT USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_insert" ON "iam_organizations"
        FOR INSERT WITH CHECK ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_update" ON "iam_organizations"
        FOR UPDATE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_delete" ON "iam_organizations"
        FOR DELETE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);

    // ── iam_users ──────────────────────────────────────────────────
    await queryRunner.query(`
      CREATE TABLE "iam_users" (
        "id"         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
        "tenant_id"  uuid         NOT NULL,
        "email"      varchar(255) NOT NULL,
        "name"       varchar(255) NOT NULL,
        "avatar_url" varchar(500),
        "org_id"     uuid         REFERENCES "iam_organizations"("id"),
        "role"       varchar(50)  NOT NULL DEFAULT 'member',
        "created_at" timestamp    NOT NULL DEFAULT now()
      );
    `);

    await queryRunner.query(
      `CREATE INDEX "IDX_iam_users_tenant_id" ON "iam_users" ("tenant_id")`,
    );

    await queryRunner.query(
      `ALTER TABLE "iam_users" ENABLE ROW LEVEL SECURITY`,
    );

    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_select" ON "iam_users"
        FOR SELECT USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_insert" ON "iam_users"
        FOR INSERT WITH CHECK ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_update" ON "iam_users"
        FOR UPDATE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_delete" ON "iam_users"
        FOR DELETE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);

    // ── iam_teams ──────────────────────────────────────────────────
    await queryRunner.query(`
      CREATE TABLE "iam_teams" (
        "id"           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
        "tenant_id"    uuid         NOT NULL,
        "name"         varchar(255) NOT NULL,
        "org_id"       uuid         REFERENCES "iam_organizations"("id"),
        "repo_ids"     jsonb        NOT NULL DEFAULT '[]',
        "board_config" jsonb        NOT NULL DEFAULT '{}',
        "created_at"   timestamp    NOT NULL DEFAULT now()
      );
    `);

    await queryRunner.query(
      `CREATE INDEX "IDX_iam_teams_tenant_id" ON "iam_teams" ("tenant_id")`,
    );

    await queryRunner.query(
      `ALTER TABLE "iam_teams" ENABLE ROW LEVEL SECURITY`,
    );

    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_select" ON "iam_teams"
        FOR SELECT USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_insert" ON "iam_teams"
        FOR INSERT WITH CHECK ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_update" ON "iam_teams"
        FOR UPDATE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_delete" ON "iam_teams"
        FOR DELETE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);

    // ── iam_memberships ────────────────────────────────────────────
    await queryRunner.query(`
      CREATE TABLE "iam_memberships" (
        "id"         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
        "tenant_id"  uuid        NOT NULL,
        "user_id"    uuid        REFERENCES "iam_users"("id"),
        "team_id"    uuid        REFERENCES "iam_teams"("id"),
        "role"       varchar(50) NOT NULL DEFAULT 'member',
        "created_at" timestamp   NOT NULL DEFAULT now()
      );
    `);

    await queryRunner.query(
      `CREATE INDEX "IDX_iam_memberships_tenant_id" ON "iam_memberships" ("tenant_id")`,
    );

    await queryRunner.query(
      `ALTER TABLE "iam_memberships" ENABLE ROW LEVEL SECURITY`,
    );

    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_select" ON "iam_memberships"
        FOR SELECT USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_insert" ON "iam_memberships"
        FOR INSERT WITH CHECK ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_update" ON "iam_memberships"
        FOR UPDATE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
    await queryRunner.query(`
      CREATE POLICY "tenant_isolation_delete" ON "iam_memberships"
        FOR DELETE USING ("tenant_id" = current_setting('app.current_tenant')::uuid);
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    // Drop in reverse order to respect foreign key constraints

    // ── iam_memberships ────────────────────────────────────────────
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_delete" ON "iam_memberships"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_update" ON "iam_memberships"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_insert" ON "iam_memberships"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_select" ON "iam_memberships"`,
    );
    await queryRunner.query(
      `DROP INDEX IF EXISTS "IDX_iam_memberships_tenant_id"`,
    );
    await queryRunner.query(`DROP TABLE IF EXISTS "iam_memberships"`);

    // ── iam_teams ──────────────────────────────────────────────────
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_delete" ON "iam_teams"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_update" ON "iam_teams"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_insert" ON "iam_teams"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_select" ON "iam_teams"`,
    );
    await queryRunner.query(`DROP INDEX IF EXISTS "IDX_iam_teams_tenant_id"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "iam_teams"`);

    // ── iam_users ──────────────────────────────────────────────────
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_delete" ON "iam_users"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_update" ON "iam_users"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_insert" ON "iam_users"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_select" ON "iam_users"`,
    );
    await queryRunner.query(`DROP INDEX IF EXISTS "IDX_iam_users_tenant_id"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "iam_users"`);

    // ── iam_organizations ──────────────────────────────────────────
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_delete" ON "iam_organizations"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_update" ON "iam_organizations"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_insert" ON "iam_organizations"`,
    );
    await queryRunner.query(
      `DROP POLICY IF EXISTS "tenant_isolation_select" ON "iam_organizations"`,
    );
    await queryRunner.query(
      `DROP INDEX IF EXISTS "IDX_iam_organizations_tenant_id"`,
    );
    await queryRunner.query(`DROP TABLE IF EXISTS "iam_organizations"`);
  }
}
