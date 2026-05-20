import { IsOptional, IsString, MaxLength } from 'class-validator';

/**
 * DTO for GET /api/v1/obs/timeline query parameters.
 *
 * One of `squad_key` or `service` is required — that validation is
 * in the controller (matches the FastAPI pattern).
 */
export class TimelineQueryDto {
  @IsOptional()
  @IsString()
  @MaxLength(64)
  squad_key?: string;

  @IsOptional()
  @IsString()
  @MaxLength(256)
  service?: string;

  @IsOptional()
  @IsString()
  since?: string;

  @IsOptional()
  @IsString()
  until?: string;

  @IsOptional()
  @IsString()
  @MaxLength(32)
  provider?: string;
}
