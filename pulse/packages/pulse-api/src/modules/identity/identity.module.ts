import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { OrganizationEntity } from './domain/entities/organization.entity';
import { UserEntity } from './domain/entities/user.entity';
import { TeamEntity } from './domain/entities/team.entity';
import { MembershipEntity } from './domain/entities/membership.entity';
import { HealthController } from './presentation/controllers/health.controller';

@Module({
  imports: [
    TypeOrmModule.forFeature([
      OrganizationEntity,
      UserEntity,
      TeamEntity,
      MembershipEntity,
    ]),
  ],
  controllers: [HealthController],
  providers: [],
  exports: [TypeOrmModule],
})
export class IdentityModule {}
