import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ConnectionEntity } from './domain/entities/connection.entity';
import { ConfigLoaderService } from './application/config-loader.service';
import { IntegrationController } from './presentation/controllers/integration.controller';
import { TeamEntity } from '../identity/domain/entities/team.entity';
import { OrganizationEntity } from '../identity/domain/entities/organization.entity';

@Module({
  imports: [
    TypeOrmModule.forFeature([
      ConnectionEntity,
      TeamEntity,
      OrganizationEntity,
    ]),
  ],
  controllers: [IntegrationController],
  providers: [ConfigLoaderService],
  exports: [ConfigLoaderService, TypeOrmModule],
})
export class IntegrationModule {}
