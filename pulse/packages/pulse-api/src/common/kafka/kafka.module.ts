import { Module, OnModuleDestroy, OnModuleInit, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Kafka, Producer } from 'kafkajs';

export const KAFKA_PRODUCER = 'KAFKA_PRODUCER';

@Module({
  providers: [
    {
      provide: KAFKA_PRODUCER,
      useFactory: async (configService: ConfigService): Promise<Producer> => {
        const logger = new Logger('KafkaModule');
        const brokers = configService
          .getOrThrow<string>('KAFKA_BROKERS')
          .split(',')
          .map((b) => b.trim());

        const kafka = new Kafka({
          clientId: 'pulse-api',
          brokers,
          retry: {
            initialRetryTime: 300,
            retries: 5,
          },
        });

        const producer = kafka.producer();

        try {
          await producer.connect();
          logger.log(`Kafka producer connected to ${brokers.join(', ')}`);
        } catch (error) {
          logger.warn(
            `Kafka producer connection failed — will retry on first publish: ${String(error)}`,
          );
        }

        return producer;
      },
      inject: [ConfigService],
    },
  ],
  exports: [KAFKA_PRODUCER],
})
export class KafkaModule implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(KafkaModule.name);

  onModuleInit(): void {
    this.logger.log('KafkaModule initialized');
  }

  async onModuleDestroy(): Promise<void> {
    this.logger.log('KafkaModule shutting down');
  }
}
