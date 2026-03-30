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

  async createConnection(
    plugin: string,
    name: string,
    endpoint: string,
    token: string,
    options?: {
      username?: string;
    },
  ): Promise<DevLakeConnection> {
    this.logger.log(`Creating DevLake connection: ${plugin}/${name}`);

    // Jenkins plugin uses username + token (Basic Auth), not bearer token
    const body: Record<string, unknown> = { name, endpoint };

    if (plugin === 'jenkins') {
      body.username = options?.username ?? '';
      body.password = token; // Jenkins API token goes in password field
    } else {
      body.token = token;
    }

    const response = await this.client.post<DevLakeConnection>(
      `/plugins/${plugin}/connections`,
      body,
    );
    return response.data;
  }

  async createBlueprint(
    name: string,
    cronConfig: string,
    connections: Array<{ plugin: string; connectionId: number; scopes: unknown[] }>,
  ): Promise<DevLakeBlueprint> {
    this.logger.log(`Creating DevLake blueprint: ${name}`);
    const response = await this.client.post<DevLakeBlueprint>('/blueprints', {
      name,
      mode: 'NORMAL',
      cronConfig,
      enable: true,
      connections,
    });
    return response.data;
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
}
