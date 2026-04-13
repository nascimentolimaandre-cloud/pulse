import {
  IsIn,
  IsInt,
  IsOptional,
  IsString,
  Max,
  Min,
} from 'class-validator';
import { Transform, Type } from 'class-transformer';

const PROJECT_STATUSES = [
  'discovered',
  'active',
  'paused',
  'blocked',
  'archived',
] as const;

const PROJECT_SORT_FIELDS = [
  'project_key',
  'pr_reference_count',
  'issue_count',
  'last_sync_at',
] as const;

const AUDIT_EVENT_TYPES = [
  'discovery_run',
  'mode_changed',
  'project_activated',
  'project_paused',
  'project_blocked',
  'project_resumed',
  'project_auto_paused',
  'project_cap_enforced',
] as const;

/**
 * DTO for GET /projects query params.
 * Maps to JiraProjectCatalogQuery from @pulse/shared.
 */
export class ProjectCatalogQueryDto {
  @IsOptional()
  @Transform(({ value }: { value: unknown }) =>
    typeof value === 'string' ? value.split(',') : value,
  )
  @IsIn(PROJECT_STATUSES, { each: true })
  status?: string[];

  @IsOptional()
  @IsString()
  search?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(200)
  limit?: number;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  offset?: number;

  @IsOptional()
  @IsIn([...PROJECT_SORT_FIELDS])
  sortBy?: string;

  @IsOptional()
  @IsIn(['asc', 'desc'])
  sortDir?: 'asc' | 'desc';
}

/**
 * DTO for GET /audit query params.
 * Maps to JiraAuditQuery from @pulse/shared.
 */
export class AuditQueryDto {
  @IsOptional()
  @Transform(({ value }: { value: unknown }) =>
    typeof value === 'string' ? value.split(',') : value,
  )
  @IsIn([...AUDIT_EVENT_TYPES], { each: true })
  eventType?: string[];

  @IsOptional()
  @IsString()
  projectKey?: string;

  @IsOptional()
  @IsString()
  since?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(200)
  limit?: number;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  offset?: number;
}
