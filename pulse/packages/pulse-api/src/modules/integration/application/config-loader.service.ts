import {
  Injectable,
  Logger,
  OnModuleInit,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';

import { ConnectionEntity, SourceType } from '../domain/entities/connection.entity';
import { TeamEntity } from '../../identity/domain/entities/team.entity';
import { OrganizationEntity } from '../../identity/domain/entities/organization.entity';

/**
 * Shape of the connections.yaml configuration file.
 */
interface ConnectionConfig {
  name: string;
  source: SourceType;
  token_env: string;
  username_env?: string;
  base_url: string;
  sync_interval_minutes: number;
  scope: {
    repositories?: string[];
    projects?: string[];
    jobs?: JenkinsJobScope[];
  };
}

/**
 * Jenkins job scope configuration.
 * Each job needs its own deploymentPattern and productionPattern
 * because Webmotors has no standard pipeline naming convention.
 */
interface JenkinsJobScope {
  /** Full job path (e.g., "folder/job-name" or just "job-name") */
  fullName: string;
  /** Regex to identify deployment runs (e.g., "(?i)deploy|release") */
  deploymentPattern?: string;
  /** Regex to identify production deployments (e.g., "(?i)prod|production") */
  productionPattern?: string;
}

interface TeamConfig {
  name: string;
  slug: string;
  mappings: Record<string, {
    repositories?: string[];
    projects?: string[];
  }>;
}

interface OrganizationConfig {
  name: string;
  slug: string;
  plan: string;
}

interface PulseConfig {
  organization: OrganizationConfig;
  connections: ConnectionConfig[];
  teams: TeamConfig[];
  status_mapping?: Record<string, string>;
}

/**
 * ConfigLoaderService reads config/connections.yaml at startup,
 * creates PULSE connection records and team records in the database.
 *
 * With custom connectors (ADR-005), there is no DevLake provisioning.
 * The sync worker in pulse-data reads directly from source APIs.
 *
 * Runs as a NestJS OnModuleInit lifecycle hook so that configuration
 * is loaded before any API requests are served.
 */
@Injectable()
export class ConfigLoaderService implements OnModuleInit {
  private readonly logger = new Logger(ConfigLoaderService.name);

  /** Status mapping loaded from config, available for the sync worker. */
  private statusMapping: Record<string, string> = {};

  /** Loaded YAML config, cached for the lifetime of the module. */
  private config: PulseConfig | null = null;

  constructor(
    private readonly configService: ConfigService,
    @InjectRepository(ConnectionEntity)
    private readonly connectionRepo: Repository<ConnectionEntity>,
    @InjectRepository(TeamEntity)
    private readonly teamRepo: Repository<TeamEntity>,
    @InjectRepository(OrganizationEntity)
    private readonly orgRepo: Repository<OrganizationEntity>,
  ) {}

  async onModuleInit(): Promise<void> {
    this.logger.log('Loading configuration from connections.yaml...');

    try {
      this.config = this.loadYamlConfig();
      if (!this.config) {
        this.logger.warn('No connections.yaml found -- skipping config load');
        return;
      }

      // Store status mapping for use by sync worker
      this.statusMapping = this.config.status_mapping ?? {};

      // Ensure organization exists
      const org = await this.ensureOrganization(this.config.organization);

      // Create PULSE connection records
      await this.provisionConnections(this.config.connections, org.id);

      // Create team records
      await this.provisionTeams(this.config.teams, org.id);

      this.logger.log('Configuration loaded successfully');
    } catch (error) {
      // Log but do not crash -- the app can still serve cached data
      this.logger.error(
        'Failed to load configuration -- app will continue with existing data',
        error instanceof Error ? error.stack : String(error),
      );
    }
  }

  /**
   * Get the status mapping loaded from config.
   * Used by the sync worker to normalize issue statuses.
   */
  getStatusMapping(): Record<string, string> {
    return { ...this.statusMapping };
  }

  /**
   * Get the loaded config (if available).
   */
  getConfig(): PulseConfig | null {
    return this.config;
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private loadYamlConfig(): PulseConfig | null {
    // Look for connections.yaml relative to the project root
    const configPaths = [
      path.resolve(process.cwd(), 'config', 'connections.yaml'),
      path.resolve(process.cwd(), '..', 'config', 'connections.yaml'),
      path.resolve(process.cwd(), '..', '..', 'config', 'connections.yaml'),
    ];

    for (const configPath of configPaths) {
      if (fs.existsSync(configPath)) {
        this.logger.log(`Found config at: ${configPath}`);
        const rawYaml = fs.readFileSync(configPath, 'utf-8');

        // Resolve ${ENV_VAR} references in the YAML content
        const resolvedYaml = rawYaml.replace(
          /\$\{(\w+)\}/g,
          (_match, envVar) => {
            const value = process.env[envVar];
            if (!value) {
              this.logger.warn(`Environment variable ${envVar} not set -- using empty string`);
              return '';
            }
            return value;
          },
        );

        return yaml.load(resolvedYaml) as PulseConfig;
      }
    }

    return null;
  }

  private async ensureOrganization(
    orgConfig: OrganizationConfig,
  ): Promise<OrganizationEntity> {
    const tenantId = this.configService.getOrThrow<string>('DEFAULT_TENANT_ID');

    // Check if org already exists
    let org = await this.orgRepo.findOne({
      where: { slug: orgConfig.slug },
    });

    if (org) {
      this.logger.log(`Organization '${orgConfig.name}' already exists (id=${org.id})`);
      return org;
    }

    // Create new organization
    org = this.orgRepo.create({
      tenantId,
      name: orgConfig.name,
      slug: orgConfig.slug,
    });
    org = await this.orgRepo.save(org);
    this.logger.log(`Created organization '${orgConfig.name}' (id=${org.id})`);
    return org;
  }

  private async provisionConnections(
    connections: ConnectionConfig[],
    orgId: string,
  ): Promise<void> {
    const tenantId = this.configService.getOrThrow<string>('DEFAULT_TENANT_ID');

    for (const conn of connections) {
      // Check if connection already exists in PULSE DB
      const existing = await this.connectionRepo.findOne({
        where: {
          tenantId,
          orgId,
          sourceType: conn.source,
        },
      });

      if (existing) {
        this.logger.log(
          `Connection '${conn.name}' (${conn.source}) already exists in PULSE DB — skipping`,
        );
        continue;
      }

      // Resolve token from environment
      const token = process.env[conn.token_env];
      if (!token) {
        this.logger.warn(
          `Token env '${conn.token_env}' not set — skipping ${conn.name}`,
        );
        continue;
      }

      try {
        // Create PULSE connection record (no DevLake — direct connectors)
        const connectionEntity = this.connectionRepo.create({
          tenantId,
          orgId,
          sourceType: conn.source,
          config: {
            base_url: conn.base_url,
            sync_interval_minutes: conn.sync_interval_minutes,
            scope: conn.scope,
          },
          status: 'active',
        });
        await this.connectionRepo.save(connectionEntity);

        this.logger.log(
          `Created PULSE connection record for '${conn.name}' (${conn.source})`,
        );
      } catch (error) {
        this.logger.error(
          `Failed to provision connection '${conn.name}': ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }
    }
  }

  private async provisionTeams(
    teams: TeamConfig[],
    orgId: string,
  ): Promise<void> {
    const tenantId = this.configService.getOrThrow<string>('DEFAULT_TENANT_ID');

    for (const teamConfig of teams) {
      // Check if team already exists
      const existing = await this.teamRepo.findOne({
        where: {
          tenantId,
          orgId,
          name: teamConfig.name,
        },
      });

      if (existing) {
        // Update repo_ids and board_config from mappings
        const repoIds = this.extractRepoIds(teamConfig.mappings);
        existing.repoIds = repoIds;
        existing.boardConfig = this.extractBoardConfig(teamConfig.mappings);
        await this.teamRepo.save(existing);
        this.logger.log(
          `Updated team '${teamConfig.name}' with latest mappings`,
        );
        continue;
      }

      // Create new team
      const repoIds = this.extractRepoIds(teamConfig.mappings);
      const boardConfig = this.extractBoardConfig(teamConfig.mappings);

      const team = this.teamRepo.create({
        tenantId,
        orgId,
        name: teamConfig.name,
        repoIds,
        boardConfig,
      });
      await this.teamRepo.save(team);
      this.logger.log(`Created team '${teamConfig.name}' (id=${team.id})`);
    }
  }

  /**
   * Extract repository IDs from team mappings.
   */
  private extractRepoIds(
    mappings: Record<string, { repositories?: string[]; projects?: string[] }>,
  ): string[] {
    const repos: string[] = [];
    for (const sourceMapping of Object.values(mappings)) {
      if (sourceMapping.repositories) {
        repos.push(...sourceMapping.repositories);
      }
    }
    return repos;
  }

  /**
   * Extract board/project config from team mappings.
   */
  private extractBoardConfig(
    mappings: Record<string, { repositories?: string[]; projects?: string[] }>,
  ): Record<string, unknown> {
    const config: Record<string, unknown> = {};
    for (const [source, sourceMapping] of Object.entries(mappings)) {
      config[source] = {
        repositories: sourceMapping.repositories ?? [],
        projects: sourceMapping.projects ?? [],
      };
    }
    return config;
  }
}
