import { IsOptional, IsString, MaxLength } from 'class-validator';

/**
 * DTO for POST /projects/:key/{activate|pause|block|resume}.
 * Maps to JiraProjectActionInput from @pulse/shared.
 */
export class ProjectActionDto {
  @IsOptional()
  @IsString()
  @MaxLength(500)
  reason?: string;
}
