import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { APP_GUARD, APP_INTERCEPTOR } from '@nestjs/core';
import { AppConfigModule, getConfig } from './config/app.config';
import { typeOrmConfig } from './common/database/typeorm.config';
import { KafkaModule } from './common/kafka/kafka.module';
import { AuthGuard } from './common/guards/auth.guard';
import { TenantGuard } from './common/guards/tenant.guard';
import { TenantInterceptor } from './common/interceptors/tenant.interceptor';
import { IdentityModule } from './modules/identity/identity.module';
import { IntegrationModule } from './modules/integration/integration.module';

@Module({
  imports: [
    AppConfigModule,
    TypeOrmModule.forRootAsync({
      useFactory: () => {
        // Ensure env is validated before TypeORM initializes
        getConfig();
        return typeOrmConfig;
      },
    }),
    KafkaModule,
    IdentityModule,
    IntegrationModule,
  ],
  providers: [
    {
      provide: APP_GUARD,
      useClass: AuthGuard,
    },
    {
      provide: APP_GUARD,
      useClass: TenantGuard,
    },
    {
      provide: APP_INTERCEPTOR,
      useClass: TenantInterceptor,
    },
  ],
})
export class AppModule {}
