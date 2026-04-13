import {
  Injectable,
  Logger,
  NotFoundException,
  BadRequestException,
  InternalServerErrorException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DataSource, QueryRunner } from 'typeorm';
import axios from 'axios';
import type {
  TenantJiraConfig,
  JiraProjectCatalogEntry,
  JiraProjectCatalogListResponse,
  JiraProjectStatus,
  JiraDiscoveryStatusResponse,
  JiraDiscoveryAuditEntry,
  JiraAuditListResponse,
  JiraSmartSuggestionsResponse,
  JiraSmartSuggestion,
  JiraAuditEventType,
} from '@pulse/shared/types/jira-admin';
import type { UpdateConfigDto } from './dto/update-config.dto';
import type { ProjectActionDto } from './dto/project-action.dto';
import type { ProjectCatalogQueryDto, AuditQueryDto } from './dto/list-query.dto';

// Valid status transitions for project actions
const STATUS_TRANSITIONS: Record<string, { from: JiraProjectStatus[]; to: JiraProjectStatus; event: JiraAuditEventType }> = {
  activate: { from: ['discovered', 'paused'], to: 'active', event: 'project_activated' },
  pause:    { from: ['active'], to: 'paused', event: 'project_paused' },
  block:    { from: ['discovered', 'active', 'paused'], to: 'blocked', event: 'project_blocked' },
  resume:   { from: ['paused', 'blocked'], to: 'active', event: 'project_resumed' },
};

@Injectable()
export class JiraAdminService {
  private readonly logger = new Logger(JiraAdminService.name);

  constructor(
    private readonly dataSource: DataSource,
    private readonly configService: ConfigService,
  ) {}

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /**
   * Execute a callback within a transaction that has RLS tenant context set.
   */
  private async withTenant<T>(
    tenantId: string,
    fn: (qr: QueryRunner) => Promise<T>,
  ): Promise<T> {
    const qr = this.dataSource.createQueryRunner();
    await qr.connect();
    await qr.startTransaction();

    try {
      // Set RLS context — validated UUID format via TenantGuard already
      await qr.query(`SET LOCAL app.current_tenant = '${tenantId}'`);
      const result = await fn(qr);
      await qr.commitTransaction();
      return result;
    } catch (err) {
      await qr.rollbackTransaction();
      throw err;
    } finally {
      await qr.release();
    }
  }

  /**
   * Map snake_case DB row to camelCase TenantJiraConfig shape.
   */
  private mapConfigRow(row: Record<string, unknown>): TenantJiraConfig {
    return {
      tenantId: row['tenant_id'] as string,
      mode: row['mode'] as TenantJiraConfig['mode'],
      discoveryEnabled: row['discovery_enabled'] as boolean,
      discoveryScheduleCron: row['discovery_schedule_cron'] as string,
      maxActiveProjects: row['max_active_projects'] as number,
      maxIssuesPerHour: row['max_issues_per_hour'] as number,
      smartPrScanDays: row['smart_pr_scan_days'] as number,
      smartMinPrReferences: row['smart_min_pr_references'] as number,
      lastDiscoveryAt: (row['last_discovery_at'] as string) ?? null,
      lastDiscoveryStatus: (row['last_discovery_status'] as TenantJiraConfig['lastDiscoveryStatus']) ?? null,
      lastDiscoveryError: (row['last_discovery_error'] as string) ?? null,
      createdAt: String(row['created_at']),
      updatedAt: String(row['updated_at']),
    };
  }

  /**
   * Map snake_case DB row to camelCase JiraProjectCatalogEntry shape.
   */
  private mapCatalogRow(row: Record<string, unknown>): JiraProjectCatalogEntry {
    return {
      id: row['id'] as string,
      tenantId: row['tenant_id'] as string,
      projectKey: row['project_key'] as string,
      projectId: (row['project_id'] as string) ?? null,
      name: (row['name'] as string) ?? null,
      projectType: (row['project_type'] as string) ?? null,
      leadAccountId: (row['lead_account_id'] as string) ?? null,
      status: row['status'] as JiraProjectStatus,
      activationSource: (row['activation_source'] as JiraProjectCatalogEntry['activationSource']) ?? null,
      issueCount: (row['issue_count'] as number) ?? 0,
      prReferenceCount: (row['pr_reference_count'] as number) ?? 0,
      firstSeenAt: String(row['first_seen_at']),
      activatedAt: row['activated_at'] ? String(row['activated_at']) : null,
      lastSyncAt: row['last_sync_at'] ? String(row['last_sync_at']) : null,
      lastSyncStatus: (row['last_sync_status'] as JiraProjectCatalogEntry['lastSyncStatus']) ?? null,
      consecutiveFailures: (row['consecutive_failures'] as number) ?? 0,
      lastError: (row['last_error'] as string) ?? null,
      metadata: (row['metadata'] as Record<string, unknown>) ?? {},
      createdAt: String(row['created_at']),
      updatedAt: String(row['updated_at']),
    };
  }

  /**
   * Map snake_case DB row to camelCase JiraDiscoveryAuditEntry shape.
   */
  private mapAuditRow(row: Record<string, unknown>): JiraDiscoveryAuditEntry {
    return {
      id: row['id'] as string,
      tenantId: row['tenant_id'] as string,
      eventType: row['event_type'] as JiraAuditEventType,
      projectKey: (row['project_key'] as string) ?? null,
      actor: row['actor'] as string,
      beforeValue: row['before_value'] ?? null,
      afterValue: row['after_value'] ?? null,
      reason: (row['reason'] as string) ?? null,
      createdAt: String(row['created_at']),
    };
  }

  // ---------------------------------------------------------------------------
  // Config
  // ---------------------------------------------------------------------------

  async getConfig(tenantId: string): Promise<TenantJiraConfig> {
    return this.withTenant(tenantId, async (qr) => {
      const rows = await qr.query(
        `SELECT * FROM tenant_jira_config WHERE tenant_id = $1`,
        [tenantId],
      );
      if (!rows.length) {
        throw new NotFoundException(
          `No Jira configuration found for tenant ${tenantId}`,
        );
      }
      return this.mapConfigRow(rows[0]);
    });
  }

  async updateConfig(
    tenantId: string,
    dto: UpdateConfigDto,
    actorId: string,
  ): Promise<TenantJiraConfig> {
    return this.withTenant(tenantId, async (qr) => {
      // Fetch current config
      const currentRows = await qr.query(
        `SELECT * FROM tenant_jira_config WHERE tenant_id = $1`,
        [tenantId],
      );
      if (!currentRows.length) {
        throw new NotFoundException(
          `No Jira configuration found for tenant ${tenantId}`,
        );
      }
      const current = currentRows[0] as Record<string, unknown>;

      // Build SET clause dynamically from provided fields
      const setClauses: string[] = [];
      const params: unknown[] = [];
      let paramIndex = 1;

      const fieldMap: Record<string, string> = {
        mode: 'mode',
        discoveryEnabled: 'discovery_enabled',
        discoveryScheduleCron: 'discovery_schedule_cron',
        maxActiveProjects: 'max_active_projects',
        maxIssuesPerHour: 'max_issues_per_hour',
        smartPrScanDays: 'smart_pr_scan_days',
        smartMinPrReferences: 'smart_min_pr_references',
      };

      for (const [dtoField, dbField] of Object.entries(fieldMap)) {
        const value = dto[dtoField as keyof UpdateConfigDto];
        if (value !== undefined) {
          setClauses.push(`${dbField} = $${paramIndex}`);
          params.push(value);
          paramIndex++;
        }
      }

      if (setClauses.length === 0) {
        return this.mapConfigRow(current);
      }

      // Always update updated_at
      setClauses.push(`updated_at = NOW()`);

      params.push(tenantId);
      const sql = `UPDATE tenant_jira_config SET ${setClauses.join(', ')} WHERE tenant_id = $${paramIndex} RETURNING *`;
      const result = await qr.query(sql, params);

      // Audit: if mode changed, write audit entry
      if (dto.mode !== undefined && dto.mode !== current['mode']) {
        await qr.query(
          `INSERT INTO jira_discovery_audit (tenant_id, event_type, actor, before_value, after_value, reason)
           VALUES ($1, 'mode_changed', $2, $3, $4, $5)`,
          [
            tenantId,
            actorId,
            JSON.stringify({ mode: current['mode'] }),
            JSON.stringify({ mode: dto.mode }),
            `Mode changed from ${current['mode'] as string} to ${dto.mode}`,
          ],
        );
      }

      return this.mapConfigRow(result[0]);
    });
  }

  // ---------------------------------------------------------------------------
  // Project Catalog
  // ---------------------------------------------------------------------------

  async listProjects(
    tenantId: string,
    query: ProjectCatalogQueryDto,
  ): Promise<JiraProjectCatalogListResponse> {
    return this.withTenant(tenantId, async (qr) => {
      const conditions: string[] = ['tenant_id = $1'];
      const params: unknown[] = [tenantId];
      let paramIndex = 2;

      // Status filter
      if (query.status && query.status.length > 0) {
        conditions.push(`status = ANY($${paramIndex})`);
        params.push(query.status);
        paramIndex++;
      }

      // Search filter (project_key or name, case-insensitive)
      if (query.search) {
        conditions.push(
          `(project_key ILIKE $${paramIndex} OR name ILIKE $${paramIndex})`,
        );
        params.push(`%${query.search}%`);
        paramIndex++;
      }

      const where = conditions.join(' AND ');

      // Sort
      const sortField = query.sortBy ?? 'project_key';
      const sortDir = query.sortDir ?? 'asc';
      const orderBy = `ORDER BY ${sortField} ${sortDir}`;

      // Pagination
      const limit = query.limit ?? 50;
      const offset = query.offset ?? 0;

      // Fetch items
      const items = await qr.query(
        `SELECT * FROM jira_project_catalog WHERE ${where} ${orderBy} LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`,
        [...params, limit, offset],
      );

      // Fetch total
      const countResult = await qr.query(
        `SELECT COUNT(*)::int AS total FROM jira_project_catalog WHERE ${where}`,
        params,
      );
      const total = countResult[0]?.total ?? 0;

      // Fetch status counts
      const countsResult = await qr.query(
        `SELECT status, COUNT(*)::int AS count FROM jira_project_catalog WHERE tenant_id = $1 GROUP BY status`,
        [tenantId],
      );
      const counts: Record<string, number> = {
        discovered: 0,
        active: 0,
        paused: 0,
        blocked: 0,
        archived: 0,
      };
      for (const row of countsResult) {
        counts[row.status as string] = row.count as number;
      }

      return {
        items: items.map((r: Record<string, unknown>) => this.mapCatalogRow(r)),
        total,
        counts: counts as Record<JiraProjectStatus, number>,
      };
    });
  }

  async getProject(
    tenantId: string,
    projectKey: string,
  ): Promise<JiraProjectCatalogEntry> {
    return this.withTenant(tenantId, async (qr) => {
      const rows = await qr.query(
        `SELECT * FROM jira_project_catalog WHERE tenant_id = $1 AND project_key = $2`,
        [tenantId, projectKey.toUpperCase()],
      );
      if (!rows.length) {
        throw new NotFoundException(
          `Project ${projectKey} not found in catalog`,
        );
      }
      return this.mapCatalogRow(rows[0]);
    });
  }

  async changeProjectStatus(
    tenantId: string,
    projectKey: string,
    action: string,
    dto: ProjectActionDto,
    actorId: string,
  ): Promise<JiraProjectCatalogEntry> {
    const transition = STATUS_TRANSITIONS[action];
    if (!transition) {
      throw new BadRequestException(`Unknown action: ${action}`);
    }

    return this.withTenant(tenantId, async (qr) => {
      const rows = await qr.query(
        `SELECT * FROM jira_project_catalog WHERE tenant_id = $1 AND project_key = $2`,
        [tenantId, projectKey.toUpperCase()],
      );
      if (!rows.length) {
        throw new NotFoundException(
          `Project ${projectKey} not found in catalog`,
        );
      }

      const current = rows[0] as Record<string, unknown>;
      const currentStatus = current['status'] as JiraProjectStatus;

      if (!transition.from.includes(currentStatus)) {
        throw new BadRequestException(
          `Cannot ${action} project in '${currentStatus}' status. Allowed from: ${transition.from.join(', ')}`,
        );
      }

      // Determine activation_source for activate action
      const extraSets =
        action === 'activate'
          ? `, activation_source = 'manual', activated_at = NOW()`
          : action === 'resume'
            ? `, activation_source = 'manual', activated_at = NOW()`
            : '';

      // Reset consecutive_failures on activate/resume
      const resetFailures =
        action === 'activate' || action === 'resume'
          ? ', consecutive_failures = 0'
          : '';

      const result = await qr.query(
        `UPDATE jira_project_catalog
         SET status = $1, updated_at = NOW()${extraSets}${resetFailures}
         WHERE tenant_id = $2 AND project_key = $3
         RETURNING *`,
        [transition.to, tenantId, projectKey.toUpperCase()],
      );

      // Write audit entry
      await qr.query(
        `INSERT INTO jira_discovery_audit
           (tenant_id, event_type, project_key, actor, before_value, after_value, reason)
         VALUES ($1, $2, $3, $4, $5, $6, $7)`,
        [
          tenantId,
          transition.event,
          projectKey.toUpperCase(),
          actorId,
          JSON.stringify({ status: currentStatus }),
          JSON.stringify({ status: transition.to }),
          dto.reason ?? null,
        ],
      );

      return this.mapCatalogRow(result[0]);
    });
  }

  // ---------------------------------------------------------------------------
  // Discovery trigger / status
  // ---------------------------------------------------------------------------

  async triggerDiscovery(tenantId: string): Promise<{ runId: string }> {
    const baseUrl = this.configService.get<string>(
      'PULSE_DATA_URL',
      'http://localhost:8001',
    );
    const token = this.configService.get<string>('INTERNAL_API_TOKEN', '');

    try {
      const response = await axios.post<{ run_id: string }>(
        `${baseUrl}/internal/discovery/trigger`,
        { tenant_id: tenantId },
        {
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'X-Internal-Token': token } : {}),
          },
          timeout: 30_000,
        },
      );
      return { runId: response.data.run_id };
    } catch (err) {
      this.logger.error('Failed to trigger discovery via pulse-data', err);
      if (axios.isAxiosError(err) && err.response) {
        throw new InternalServerErrorException(
          `Discovery trigger failed: ${err.response.status} — ${JSON.stringify(err.response.data)}`,
        );
      }
      throw new InternalServerErrorException(
        'Failed to communicate with discovery service',
      );
    }
  }

  async getDiscoveryStatus(
    tenantId: string,
  ): Promise<JiraDiscoveryStatusResponse> {
    return this.withTenant(tenantId, async (qr) => {
      // Get config
      const configRows = await qr.query(
        `SELECT mode, discovery_enabled, discovery_schedule_cron,
                last_discovery_at, last_discovery_status
         FROM tenant_jira_config WHERE tenant_id = $1`,
        [tenantId],
      );
      if (!configRows.length) {
        throw new NotFoundException(
          `No Jira configuration found for tenant ${tenantId}`,
        );
      }
      const cfg = configRows[0] as Record<string, unknown>;

      // Get latest audit entry for discovery_run
      const lastRunRows = await qr.query(
        `SELECT * FROM jira_discovery_audit
         WHERE tenant_id = $1 AND event_type = 'discovery_run'
         ORDER BY created_at DESC LIMIT 1`,
        [tenantId],
      );

      let lastRun = null;
      if (lastRunRows.length > 0) {
        const r = lastRunRows[0] as Record<string, unknown>;
        const afterVal = r['after_value'] as Record<string, unknown> | null;
        lastRun = {
          runId: (afterVal?.['runId'] as string) ?? r['id'] as string,
          startedAt: String(r['created_at']),
          finishedAt: afterVal?.['finishedAt'] ? String(afterVal['finishedAt']) : null,
          status: (afterVal?.['status'] as string) ?? 'success',
          discoveredCount: (afterVal?.['discoveredCount'] as number) ?? 0,
          activatedCount: (afterVal?.['activatedCount'] as number) ?? 0,
          archivedCount: (afterVal?.['archivedCount'] as number) ?? 0,
          updatedCount: (afterVal?.['updatedCount'] as number) ?? 0,
          errors: (afterVal?.['errors'] as string[]) ?? [],
        };
      }

      return {
        inFlight: false, // TODO: check Redis for in-progress run
        currentRunId: null,
        lastRun,
        tenantConfig: {
          mode: cfg['mode'] as string,
          discoveryEnabled: cfg['discovery_enabled'] as boolean,
          discoveryScheduleCron: cfg['discovery_schedule_cron'] as string,
          lastDiscoveryAt: cfg['last_discovery_at'] ? String(cfg['last_discovery_at']) : null,
          lastDiscoveryStatus: (cfg['last_discovery_status'] as string) ?? null,
        },
      } as JiraDiscoveryStatusResponse;
    });
  }

  // ---------------------------------------------------------------------------
  // Audit
  // ---------------------------------------------------------------------------

  async listAudit(
    tenantId: string,
    query: AuditQueryDto,
  ): Promise<JiraAuditListResponse> {
    return this.withTenant(tenantId, async (qr) => {
      const conditions: string[] = ['tenant_id = $1'];
      const params: unknown[] = [tenantId];
      let paramIndex = 2;

      if (query.eventType && query.eventType.length > 0) {
        conditions.push(`event_type = ANY($${paramIndex})`);
        params.push(query.eventType);
        paramIndex++;
      }

      if (query.projectKey) {
        conditions.push(`project_key = $${paramIndex}`);
        params.push(query.projectKey.toUpperCase());
        paramIndex++;
      }

      if (query.since) {
        conditions.push(`created_at >= $${paramIndex}`);
        params.push(query.since);
        paramIndex++;
      }

      const where = conditions.join(' AND ');
      const limit = query.limit ?? 50;
      const offset = query.offset ?? 0;

      const items = await qr.query(
        `SELECT * FROM jira_discovery_audit WHERE ${where} ORDER BY created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`,
        [...params, limit, offset],
      );

      const countResult = await qr.query(
        `SELECT COUNT(*)::int AS total FROM jira_discovery_audit WHERE ${where}`,
        params,
      );

      return {
        items: items.map((r: Record<string, unknown>) => this.mapAuditRow(r)),
        total: countResult[0]?.total ?? 0,
      };
    });
  }

  // ---------------------------------------------------------------------------
  // Smart Suggestions
  // ---------------------------------------------------------------------------

  async getSmartSuggestions(
    tenantId: string,
  ): Promise<JiraSmartSuggestionsResponse> {
    return this.withTenant(tenantId, async (qr) => {
      // Get smart threshold from config
      const configRows = await qr.query(
        `SELECT smart_min_pr_references FROM tenant_jira_config WHERE tenant_id = $1`,
        [tenantId],
      );
      const threshold = configRows.length > 0
        ? (configRows[0]['smart_min_pr_references'] as number)
        : 5;

      // Find discovered/paused projects with pr_reference_count >= threshold
      const rows = await qr.query(
        `SELECT project_key, pr_reference_count
         FROM jira_project_catalog
         WHERE tenant_id = $1
           AND status IN ('discovered', 'paused')
           AND pr_reference_count >= $2
         ORDER BY pr_reference_count DESC
         LIMIT 20`,
        [tenantId, threshold],
      );

      const items: JiraSmartSuggestion[] = rows.map(
        (row: Record<string, unknown>) => ({
          projectKey: row['project_key'] as string,
          prReferenceCount: row['pr_reference_count'] as number,
          suggestedAction: 'activate' as const,
          reason: `Referenced in ${row['pr_reference_count'] as number} PRs — meets smart activation threshold`,
        }),
      );

      return { items, thresholdPrReferences: threshold };
    });
  }
}
