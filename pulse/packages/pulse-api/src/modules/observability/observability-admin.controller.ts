import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  Post,
  Put,
  UseGuards,
} from '@nestjs/common';
import { CurrentTenant } from '@/common/decorators/current-tenant.decorator';
import { AdminRoleGuard } from '@/modules/integrations/jira-admin/guards/admin-role.guard';
import { ObservabilityProxyService } from './observability-proxy.service';
import { DatadogValidateDto } from './dto/datadog-validate.dto';
import { OverrideRequestDto } from './dto/override-request.dto';
import { AliasMappingDto, AliasBulkImportDto } from './dto/alias-mapping.dto';
import type {
  DatadogValidateResponse,
  CredentialMetadataResponse,
  OwnershipSyncResponse,
  OwnershipRowResponse,
  OwnershipListResponse,
  AliasListResponse,
  AliasResponse,
  AliasBulkImportResponse,
  AliasSuggestionsResponse,
} from '@pulse/shared';

/**
 * Admin controller for observability endpoints (FDD-OBS-001 Phase 2).
 *
 * Thin HTTP proxy — all business logic lives in pulse-data (FastAPI).
 * This controller validates auth/tenant, forwards to pulse-data, and
 * returns sanitized responses.
 *
 * Route prefix: /api/v1/admin/integrations
 * (global prefix `api/v1` is set in main.ts)
 */
@Controller('admin/integrations')
@UseGuards(AdminRoleGuard)
export class ObservabilityAdminController {
  constructor(private readonly proxy: ObservabilityProxyService) {}

  // ---------------------------------------------------------------------------
  // 1. POST /datadog/validate
  // ---------------------------------------------------------------------------

  @Post('datadog/validate')
  validateDatadogCredential(
    @CurrentTenant() tenantId: string,
    @Body() dto: DatadogValidateDto,
  ): Promise<DatadogValidateResponse> {
    return this.proxy.post<DatadogValidateResponse>(
      'admin/integrations/datadog/validate',
      tenantId,
      dto,
    );
  }

  // ---------------------------------------------------------------------------
  // 2. GET /:provider/metadata
  // ---------------------------------------------------------------------------

  @Get(':provider/metadata')
  getProviderMetadata(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
  ): Promise<CredentialMetadataResponse> {
    return this.proxy.get<CredentialMetadataResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/metadata`,
      tenantId,
    );
  }

  // ---------------------------------------------------------------------------
  // 3. POST /:provider/ownership/sync
  // ---------------------------------------------------------------------------

  @Post(':provider/ownership/sync')
  syncOwnership(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
  ): Promise<OwnershipSyncResponse> {
    return this.proxy.post<OwnershipSyncResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/ownership/sync`,
      tenantId,
    );
  }

  // ---------------------------------------------------------------------------
  // 4. PUT /:provider/ownership/:serviceExternalId/override
  // ---------------------------------------------------------------------------

  @Put(':provider/ownership/:serviceExternalId/override')
  upsertOverride(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
    @Param('serviceExternalId') serviceExternalId: string,
    @Body() dto: OverrideRequestDto,
  ): Promise<OwnershipRowResponse> {
    return this.proxy.put<OwnershipRowResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/ownership/${encodeURIComponent(serviceExternalId)}/override`,
      tenantId,
      dto,
    );
  }

  // ---------------------------------------------------------------------------
  // 5. GET /:provider/ownership
  // ---------------------------------------------------------------------------

  @Get(':provider/ownership')
  listOwnership(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
  ): Promise<OwnershipListResponse> {
    return this.proxy.get<OwnershipListResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/ownership`,
      tenantId,
    );
  }

  // ---------------------------------------------------------------------------
  // 6. GET /:provider/aliases
  // ---------------------------------------------------------------------------

  @Get(':provider/aliases')
  listAliases(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
  ): Promise<AliasListResponse> {
    return this.proxy.get<AliasListResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/aliases`,
      tenantId,
    );
  }

  // ---------------------------------------------------------------------------
  // 7. PUT /:provider/aliases/:vendorTeamValue
  // ---------------------------------------------------------------------------

  @Put(':provider/aliases/:vendorTeamValue')
  upsertAlias(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
    @Param('vendorTeamValue') vendorTeamValue: string,
    @Body() dto: AliasMappingDto,
  ): Promise<AliasResponse> {
    return this.proxy.put<AliasResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/aliases/${encodeURIComponent(vendorTeamValue)}`,
      tenantId,
      dto,
    );
  }

  // ---------------------------------------------------------------------------
  // 8. DELETE /:provider/aliases/:vendorTeamValue
  // ---------------------------------------------------------------------------

  @Delete(':provider/aliases/:vendorTeamValue')
  @HttpCode(204)
  async deleteAlias(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
    @Param('vendorTeamValue') vendorTeamValue: string,
  ): Promise<void> {
    await this.proxy.delete(
      `admin/integrations/${encodeURIComponent(provider)}/aliases/${encodeURIComponent(vendorTeamValue)}`,
      tenantId,
    );
  }

  // ---------------------------------------------------------------------------
  // 9. POST /:provider/aliases/import
  // ---------------------------------------------------------------------------

  @Post(':provider/aliases/import')
  bulkImportAliases(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
    @Body() dto: AliasBulkImportDto,
  ): Promise<AliasBulkImportResponse> {
    return this.proxy.post<AliasBulkImportResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/aliases/import`,
      tenantId,
      dto,
    );
  }

  // ---------------------------------------------------------------------------
  // 10. GET /:provider/aliases/suggestions
  // ---------------------------------------------------------------------------

  @Get(':provider/aliases/suggestions')
  aliasSuggestions(
    @CurrentTenant() tenantId: string,
    @Param('provider') provider: string,
  ): Promise<AliasSuggestionsResponse> {
    return this.proxy.get<AliasSuggestionsResponse>(
      `admin/integrations/${encodeURIComponent(provider)}/aliases/suggestions`,
      tenantId,
    );
  }
}
