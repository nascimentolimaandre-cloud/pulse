import {
  ArrayMaxSize,
  IsArray,
  IsString,
  MaxLength,
  MinLength,
  ValidateNested,
} from 'class-validator';
import { Type } from 'class-transformer';

/**
 * DTO for a single vendor_team -> squad_key mapping.
 * Used in single-PUT and bulk import payloads.
 */
export class AliasMappingDto {
  @IsString()
  @MinLength(1)
  @MaxLength(128)
  vendor_team_value!: string;

  @IsString()
  @MinLength(1)
  @MaxLength(64)
  squad_key!: string;
}

/**
 * DTO for POST /api/v1/admin/integrations/{provider}/aliases/import.
 * Hard cap of 2000 mappings per call (matching FastAPI).
 */
export class AliasBulkImportDto {
  @IsArray()
  @ArrayMaxSize(2000)
  @ValidateNested({ each: true })
  @Type(() => AliasMappingDto)
  mappings!: AliasMappingDto[];
}
