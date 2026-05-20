import { IsOptional, IsString, MaxLength } from 'class-validator';

/**
 * DTO for PUT /api/v1/admin/integrations/{provider}/ownership/{id}/override.
 *
 * `squad_key = null` clears the override.
 */
export class OverrideRequestDto {
  @IsOptional()
  @IsString()
  @MaxLength(64)
  squad_key!: string | null;
}
