# ---- Builder Stage ----
# NOTE: build context is ./packages so we can access ../pulse-shared
FROM node:20-alpine AS builder

# Layout: /workspace/pulse-shared and /workspace/pulse-api
# tsconfig path "@pulse/shared/*" resolves to "../pulse-shared/src/*"
COPY pulse-shared/ /workspace/pulse-shared/

WORKDIR /workspace/pulse-api

# Install dependencies first (layer caching)
COPY pulse-api/package.json pulse-api/package-lock.json* ./
RUN npm ci --ignore-scripts

# Copy source and build
COPY pulse-api/tsconfig.json pulse-api/tsconfig.build.json pulse-api/nest-cli.json ./
COPY pulse-api/src/ ./src/
RUN npm run build

# Prune dev dependencies
RUN npm prune --production

# ---- Runner Stage ----
FROM node:20-alpine AS runner

# Security: non-root user
RUN addgroup -g 1001 -S pulse && \
    adduser -S pulse -u 1001 -G pulse

WORKDIR /app

# Copy built artifacts and production deps
COPY --from=builder --chown=pulse:pulse /workspace/pulse-api/dist ./dist
COPY --from=builder --chown=pulse:pulse /workspace/pulse-api/node_modules ./node_modules
COPY --from=builder --chown=pulse:pulse /workspace/pulse-api/package.json ./package.json

# Security: read-only filesystem where possible
USER pulse

EXPOSE 3000

ENV NODE_ENV=production
ENV PORT=3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/v1/health || exit 1

CMD ["node", "dist/pulse-api/src/main.js"]
