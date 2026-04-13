import {
  Body,
  Controller,
  Get,
  Param,
  Post,
  Put,
  Query,
  UseGuards,
} from '@nestjs/common';
import { CurrentTenant } from '@/common/decorators/current-tenant.decorator';
import { CurrentUser } from '@/common/decorators/current-user.decorator';
import type { CurrentUserPayload } from '@/common/decorators/current-user.decorator';
import { AdminRoleGuard } from './guards/admin-role.guard';
import { JiraAdminService } from './jira-admin.service';
import { UpdateConfigDto } from './dto/update-config.dto';
import { ProjectActionDto } from './dto/project-action.dto';
import { ProjectCatalogQueryDto, AuditQueryDto } from './dto/list-query.dto';
import type {
  TenantJiraConfig,
  JiraProjectCatalogEntry,
  JiraProjectCatalogListResponse,
  JiraDiscoveryStatusResponse,
  JiraAuditListResponse,
  JiraSmartSuggestionsResponse,
} from '@pulse/shared';

@Controller('admin/integrations/jira')
@UseGuards(AdminRoleGuard)
export class JiraAdminController {
  constructor(private readonly jiraAdminService: JiraAdminService) {}

  // -------------------------------------------------------------------------
  // Config
  // -------------------------------------------------------------------------

  @Get('config')
  getConfig(
    @CurrentTenant() tenantId: string,
  ): Promise<TenantJiraConfig> {
    return this.jiraAdminService.getConfig(tenantId);
  }

  @Put('config')
  updateConfig(
    @CurrentTenant() tenantId: string,
    @CurrentUser() user: CurrentUserPayload,
    @Body() dto: UpdateConfigDto,
  ): Promise<TenantJiraConfig> {
    return this.jiraAdminService.updateConfig(tenantId, dto, user.id);
  }

  // -------------------------------------------------------------------------
  // Project Catalog
  // -------------------------------------------------------------------------

  @Get('projects')
  listProjects(
    @CurrentTenant() tenantId: string,
    @Query() query: ProjectCatalogQueryDto,
  ): Promise<JiraProjectCatalogListResponse> {
    return this.jiraAdminService.listProjects(tenantId, query);
  }

  @Get('projects/:key')
  getProject(
    @CurrentTenant() tenantId: string,
    @Param('key') key: string,
  ): Promise<JiraProjectCatalogEntry> {
    return this.jiraAdminService.getProject(tenantId, key);
  }

  @Post('projects/:key/activate')
  activateProject(
    @CurrentTenant() tenantId: string,
    @CurrentUser() user: CurrentUserPayload,
    @Param('key') key: string,
    @Body() dto: ProjectActionDto,
  ): Promise<JiraProjectCatalogEntry> {
    return this.jiraAdminService.changeProjectStatus(
      tenantId, key, 'activate', dto, user.id,
    );
  }

  @Post('projects/:key/pause')
  pauseProject(
    @CurrentTenant() tenantId: string,
    @CurrentUser() user: CurrentUserPayload,
    @Param('key') key: string,
    @Body() dto: ProjectActionDto,
  ): Promise<JiraProjectCatalogEntry> {
    return this.jiraAdminService.changeProjectStatus(
      tenantId, key, 'pause', dto, user.id,
    );
  }

  @Post('projects/:key/block')
  blockProject(
    @CurrentTenant() tenantId: string,
    @CurrentUser() user: CurrentUserPayload,
    @Param('key') key: string,
    @Body() dto: ProjectActionDto,
  ): Promise<JiraProjectCatalogEntry> {
    return this.jiraAdminService.changeProjectStatus(
      tenantId, key, 'block', dto, user.id,
    );
  }

  @Post('projects/:key/resume')
  resumeProject(
    @CurrentTenant() tenantId: string,
    @CurrentUser() user: CurrentUserPayload,
    @Param('key') key: string,
    @Body() dto: ProjectActionDto,
  ): Promise<JiraProjectCatalogEntry> {
    return this.jiraAdminService.changeProjectStatus(
      tenantId, key, 'resume', dto, user.id,
    );
  }

  // -------------------------------------------------------------------------
  // Discovery
  // -------------------------------------------------------------------------

  @Post('discovery/trigger')
  triggerDiscovery(
    @CurrentTenant() tenantId: string,
  ): Promise<{ runId: string }> {
    return this.jiraAdminService.triggerDiscovery(tenantId);
  }

  @Get('discovery/status')
  getDiscoveryStatus(
    @CurrentTenant() tenantId: string,
  ): Promise<JiraDiscoveryStatusResponse> {
    return this.jiraAdminService.getDiscoveryStatus(tenantId);
  }

  // -------------------------------------------------------------------------
  // Audit
  // -------------------------------------------------------------------------

  @Get('audit')
  listAudit(
    @CurrentTenant() tenantId: string,
    @Query() query: AuditQueryDto,
  ): Promise<JiraAuditListResponse> {
    return this.jiraAdminService.listAudit(tenantId, query);
  }

  // -------------------------------------------------------------------------
  // Smart Suggestions
  // -------------------------------------------------------------------------

  @Get('smart-suggestions')
  getSmartSuggestions(
    @CurrentTenant() tenantId: string,
  ): Promise<JiraSmartSuggestionsResponse> {
    return this.jiraAdminService.getSmartSuggestions(tenantId);
  }
}
