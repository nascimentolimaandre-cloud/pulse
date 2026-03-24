# ---- Builder Stage ----
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (layer caching)
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts

# Copy source and build
COPY tsconfig.json tsconfig.build.json nest-cli.json ./
COPY src/ ./src/
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
COPY --from=builder --chown=pulse:pulse /app/dist ./dist
COPY --from=builder --chown=pulse:pulse /app/node_modules ./node_modules
COPY --from=builder --chown=pulse:pulse /app/package.json ./package.json

# Security: read-only filesystem where possible
USER pulse

EXPOSE 3000

ENV NODE_ENV=production
ENV PORT=3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/v1/health || exit 1

CMD ["node", "dist/main.js"]
