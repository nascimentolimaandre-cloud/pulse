import {
  IsBoolean,
  IsIn,
  IsInt,
  IsOptional,
  IsString,
  Max,
  Min,
} from 'class-validator';

const DISCOVERY_MODES = ['auto', 'allowlist', 'blocklist', 'smart'] as const;

/**
 * DTO for PUT /api/v1/admin/integrations/jira/config.
 * Maps to UpdateTenantJiraConfigInput from @pulse/shared.
 */
export class UpdateConfigDto {
  @IsOptional()
  @IsIn(DISCOVERY_MODES)
  mode?: 'auto' | 'allowlist' | 'blocklist' | 'smart';

  @IsOptional()
  @IsBoolean()
  discoveryEnabled?: boolean;

  @IsOptional()
  @IsString()
  discoveryScheduleCron?: string;

  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(500)
  maxActiveProjects?: number;

  @IsOptional()
  @IsInt()
  @Min(100)
  @Max(100_000)
  maxIssuesPerHour?: number;

  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(365)
  smartPrScanDays?: number;

  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(1000)
  smartMinPrReferences?: number;
}
