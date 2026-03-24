import { DataSource, DataSourceOptions } from 'typeorm';
import { OrganizationEntity } from '@/modules/identity/domain/entities/organization.entity';
import { UserEntity } from '@/modules/identity/domain/entities/user.entity';
import { TeamEntity } from '@/modules/identity/domain/entities/team.entity';
import { MembershipEntity } from '@/modules/identity/domain/entities/membership.entity';
import { ConnectionEntity } from '@/modules/integration/domain/entities/connection.entity';

const isProduction = process.env['NODE_ENV'] === 'production';

export const typeOrmConfig: DataSourceOptions = {
  type: 'postgres',
  url: process.env['DATABASE_URL'],
  entities: [
    OrganizationEntity,
    UserEntity,
    TeamEntity,
    MembershipEntity,
    ConnectionEntity,
  ],
  migrations: ['dist/migrations/*.js'],
  synchronize: false,
  logging: isProduction ? ['error'] : ['query', 'error'],
  ssl: isProduction ? { rejectUnauthorized: true } : false,
};

export default new DataSource(typeOrmConfig);
