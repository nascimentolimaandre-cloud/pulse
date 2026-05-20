import {
  IsBoolean,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from 'class-validator';

/**
 * DTO for POST /api/v1/admin/integrations/datadog/validate.
 *
 * Lightweight validation on the NestJS side — the heavy validation
 * (site allowlist, key format) stays in FastAPI.
 */
export class DatadogValidateDto {
  @IsString()
  @MinLength(10)
  @MaxLength(512)
  api_key!: string;

  @IsOptional()
  @IsString()
  @MinLength(10)
  @MaxLength(512)
  app_key?: string | null;

  @IsString()
  @MinLength(4)
  @MaxLength(64)
  site!: string;

  @IsOptional()
  @IsBoolean()
  persist?: boolean;
}
