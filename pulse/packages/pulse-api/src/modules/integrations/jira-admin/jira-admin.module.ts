import { Module } from '@nestjs/common';
import { JiraAdminController } from './jira-admin.controller';
import { JiraAdminService } from './jira-admin.service';

/**
 * Module for the Jira Dynamic Discovery admin surface (ADR-014).
 *
 * Provides CRUD over tenant_jira_config, jira_project_catalog,
 * and jira_discovery_audit tables via direct SQL (no TypeORM entities
 * needed — these tables are owned by pulse-data migrations).
 *
 * Discovery trigger proxies to pulse-data's internal HTTP endpoint.
 */
@Module({
  controllers: [JiraAdminController],
  providers: [JiraAdminService],
})
export class JiraAdminModule {}
