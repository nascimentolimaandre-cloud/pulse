import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import axios, { AxiosInstance } from 'axios';

export interface DevLakeConnection {
  id: number;
  name: string;
  endpoint: string;
  plugin: string;
}

export interface DevLakeBlueprint {
  id: number;
  name: string;
  mode: string;
  cronConfig: string;
  enable: boolean;
}

export interface DevLakePipelineRun {
  id: number;
  status: string;
  finishedAt: string | null;
}

export interface DevLakeConnectionStatus {
  id: number;
  name: string;
  status: string;
  message: string;
}

@Injectable()
export class DevLakeApiClient {
  private readonly logger = new Logger(DevLakeApiClient.name);
  private readonly client: AxiosInstance;

  constructor(private readonly configService: ConfigService) {
    const baseURL = this.configService.getOrThrow<string>('DEVLAKE_API_URL');

    this.client = axios.create({
      baseURL,
      timeout: 30_000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  async waitForReady(maxRetries = 10, intervalMs = 3000): Promise<boolean> {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        await this.client.get('/blueprints');
        this.logger.log(`DevLake API ready (attempt ${attempt})`);
        return true;
      } catch {
        this.logger.warn(
          `DevLake API not ready (attempt ${attempt}/${maxRetries}), retrying in ${intervalMs}ms...`,
        );
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
      }
    }
    throw new Error(`DevLake API not reachable after ${maxRetries} attempts`);
  }

  async listConnections(plugin: string): Promise<DevLakeConnection[]> {
    this.logger.log(`Listing DevLake connections for plugin: ${plugin}`);
    const response = await this.client.get<DevLakeConnection[]>(
      `/plugins/${plugin}/connections`,
    );
    return response.data;
  }

  async createConnection(
    plugin: string,
    name: string,
    endpoint: string,
    token: string,
    options?: {
      username?: string;
      rateLimitPerHour?: number;
      enableGraphql?: boolean;
    },
  ): Promise<DevLakeConnection> {
    this.logger.log(`Creating DevLake connection: ${plugin}/${name}`);

    // DevLake requires trailing slash on endpoint URLs
    let normalizedEndpoint = endpoint.endsWith('/')
      ? endpoint
      : `${endpoint}/`;

    // Jira Cloud plugin expects the endpoint to end with /rest/
    if (plugin === 'jira' && !normalizedEndpoint.endsWith('/rest/')) {
      normalizedEndpoint = normalizedEndpoint.replace(/\/$/, '') + '/rest/';
    }

    const body: Record<string, unknown> = {
      name,
      endpoint: normalizedEndpoint,
    };

    if (plugin === 'github') {
      body.token = token;
      body.rateLimitPerHour = options?.rateLimitPerHour ?? 4500;
      body.enableGraphql = options?.enableGraphql ?? true;
    } else if (plugin === 'jenkins') {
      body.username = options?.username ?? '';
      body.password = token;
    } else if (plugin === 'jira') {
      body.username = options?.username ?? '';
      body.password = token;
      body.authMethod = 'BasicAuth';
    } else if (plugin === 'gitlab') {
      body.token = token;
      body.rateLimitPerHour = options?.rateLimitPerHour ?? 3600;
    } else {
      body.token = token;
    }

    try {
      const response = await this.client.post<DevLakeConnection>(
        `/plugins/${plugin}/connections`,
        body,
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response) {
        this.logger.error(
          `DevLake API error ${error.response.status} creating ${plugin} connection: ${JSON.stringify(error.response.data)}`,
        );
      }
      throw error;
    }
  }

  async listBlueprints(): Promise<DevLakeBlueprint[]> {
    this.logger.log('Listing DevLake blueprints');
    const response = await this.client.get<DevLakeBlueprint[]>('/blueprints');
    const data = response.data as any;
    return Array.isArray(data) ? data : (data.blueprints ?? []);
  }

  async createBlueprint(
    name: string,
    cronConfig: string,
    connections: Array<{
      plugin: string;
      connectionId: number;
      scopes: unknown[];
    }>,
  ): Promise<DevLakeBlueprint> {
    this.logger.log(`Creating DevLake blueprint: ${name}`);

    // DevLake expects "pluginName" not "plugin" in the connections array
    const devlakeConnections = connections.map((c) => ({
      pluginName: c.plugin,
      connectionId: c.connectionId,
      scopes: c.scopes,
    }));

    try {
      const response = await this.client.post<DevLakeBlueprint>('/blueprints', {
        name,
        mode: 'NORMAL',
        cronConfig,
        enable: true,
        skipOnFail: true,
        connections: devlakeConnections,
      });
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response) {
        this.logger.error(
          `DevLake API error ${error.response.status} creating blueprint: ${JSON.stringify(error.response.data)}`,
        );
      }
      throw error;
    }
  }

  async triggerPipeline(blueprintId: number): Promise<DevLakePipelineRun> {
    this.logger.log(`Triggering DevLake pipeline for blueprint: ${blueprintId}`);
    const response = await this.client.post<DevLakePipelineRun>(
      `/blueprints/${blueprintId}/trigger`,
    );
    return response.data;
  }

  async getConnectionStatus(
    plugin: string,
    connectionId: number,
  ): Promise<DevLakeConnectionStatus> {
    this.logger.log(
      `Fetching DevLake connection status: ${plugin}/${connectionId}`,
    );
    const response = await this.client.get<DevLakeConnectionStatus>(
      `/plugins/${plugin}/connections/${connectionId}/test`,
    );
    return response.data;
  }

  /**
   * Register scopes (e.g., Jira boards, GitHub repos) in DevLake.
   * Uses PUT /plugins/{plugin}/connections/{id}/scopes with { data: [...] } body.
   */
  async registerScopes(
    plugin: string,
    connectionId: number,
    scopes: Array<Record<string, unknown>>,
  ): Promise<unknown[]> {
    this.logger.log(
      `Registering ${scopes.length} scope(s) for ${plugin}/connection ${connectionId}`,
    );
    const response = await this.client.put<unknown[]>(
      `/plugins/${plugin}/connections/${connectionId}/scopes`,
      { data: scopes },
    );
    return response.data;
  }

  /**
   * List all registered scopes for a connection.
   */
  async listScopes(
    plugin: string,
    connectionId: number,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.client.get<{
      count: number;
      scopes: Array<{ scope: Record<string, unknown> }>;
    }>(`/plugins/${plugin}/connections/${connectionId}/scopes`);
    return response.data.scopes.map((s) => s.scope);
  }

  /**
   * Update an existing blueprint (connections, scopes, cron, etc.).
   */
  async updateBlueprint(
    blueprintId: number,
    connections: Array<{
      pluginName: string;
      connectionId: number;
      scopes: Array<{ scopeId: string }>;
    }>,
  ): Promise<DevLakeBlueprint> {
    this.logger.log(`Updating DevLake blueprint: ${blueprintId}`);
    const response = await this.client.patch<DevLakeBlueprint>(
      `/blueprints/${blueprintId}`,
      { connections },
    );
    return response.data;
  }

  /**
   * Discover Jira boards for a project key via DevLake's proxy to Jira Agile API.
   * Returns boards belonging to the given project.
   */
  async discoverJiraBoards(
    connectionId: number,
    projectKey: string,
  ): Promise<
    Array<{ id: number; name: string; type: string; projectKey: string }>
  > {
    this.logger.log(
      `Discovering Jira boards for project: ${projectKey} (connection ${connectionId})`,
    );
    try {
      const response = await this.client.get<{
        values: Array<{
          id: number;
          name: string;
          type: string;
          location?: { projectKey?: string };
        }>;
      }>(
        `/plugins/jira/connections/${connectionId}/proxy/rest/agile/1.0/board`,
        { params: { projectKeyOrId: projectKey } },
      );
      return (response.data.values ?? [])
        .filter(
          (b) =>
            b.location?.projectKey?.toUpperCase() ===
            projectKey.toUpperCase(),
        )
        .map((b) => ({
          id: b.id,
          name: b.name,
          type: b.type,
          projectKey: b.location?.projectKey ?? projectKey,
        }));
    } catch (error) {
      this.logger.warn(
        `Could not discover boards for ${projectKey}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      return [];
    }
  }

  /**
   * Create a scope config for a connection.
   * Useful for customizing collection behaviour (e.g., skip epics).
   */
  async createScopeConfig(
    plugin: string,
    connectionId: number,
    config: Record<string, unknown>,
  ): Promise<{ id: number }> {
    this.logger.log(
      `Creating scope config for ${plugin}/connection ${connectionId}`,
    );
    const response = await this.client.post<{ id: number }>(
      `/plugins/${plugin}/connections/${connectionId}/scope-configs`,
      config,
    );
    return response.data;
  }
}
