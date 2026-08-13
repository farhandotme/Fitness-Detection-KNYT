# syntax=docker/dockerfile:1
FROM oven/bun:1-slim AS base
WORKDIR /app

# Install deps first so this layer is cached unless package.json changes.
COPY package.json ./
RUN bun install --production

COPY tsconfig.json ./
COPY src ./src

# Type-check against the real source before shipping - fails the build
# instead of failing at runtime in prod. (bun executes TS directly, this is
# purely a safety gate.)
RUN bunx tsc -p tsconfig.json --noEmit

ENV NODE_ENV=production
EXPOSE 4000

# Run as a non-root user.
RUN addgroup --system app && adduser --system --ingroup app app
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD bun -e "fetch('http://localhost:'+(process.env.PORT||4000)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["bun", "src/index.ts"]
