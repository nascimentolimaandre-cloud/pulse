import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ConnectionEntity } from './domain/entities/connection.entity';
import { DevLakeApiClient } from './infrastructure/devlake/devlake-api.client';
import { IntegrationController } from './presentation/controllers/integration.controller';

@Module({
  imports: [TypeOrmModule.forFeature([ConnectionEntity])],
  controllers: [IntegrationController],
  providers: [DevLakeApiClient],
  exports: [DevLakeApiClient, TypeOrmModule],
})
export class IntegrationModule {}
