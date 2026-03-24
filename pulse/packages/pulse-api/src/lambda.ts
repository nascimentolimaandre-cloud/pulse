import { NestFactory } from '@nestjs/core';
import { ExpressAdapter } from '@nestjs/platform-express';
import { ValidationPipe } from '@nestjs/common';
import serverlessExpress from '@vendia/serverless-express';
import express from 'express';
import { AppModule } from './app.module';
import type { Callback, Context, Handler } from 'aws-lambda';

let cachedHandler: Handler | undefined;

async function bootstrapLambda(): Promise<Handler> {
  const expressApp = express();
  const app = await NestFactory.create(AppModule, new ExpressAdapter(expressApp));

  app.setGlobalPrefix('api/v1');

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );

  app.enableCors({
    origin: process.env['CORS_ORIGIN'] ?? '*',
    credentials: true,
  });

  await app.init();

  return serverlessExpress({ app: expressApp });
}

export const handler: Handler = async (
  event: Record<string, unknown>,
  context: Context,
  callback: Callback,
) => {
  if (!cachedHandler) {
    cachedHandler = await bootstrapLambda();
  }
  return cachedHandler(event, context, callback);
};
