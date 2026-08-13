# syntax=docker/dockerfile:1

# --- Build stage ---
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .

# Vite bakes VITE_* vars into the JS bundle at build time (they are NOT
# runtime env vars once served by nginx), so they must be passed as
# build-args, e.g.:
#   docker build \
#     --build-arg VITE_COMPETITION_API_URL=https://api.example.com \
#     --build-arg VITE_COMPETITION_WS_URL=https://api.example.com \
#     --build-arg VITE_WEBSOCKET_FASTAPI_URL=wss://detect.example.com \
#     -t fitness-frontend .
ARG VITE_COMPETITION_API_URL
ARG VITE_COMPETITION_WS_URL
ARG VITE_WEBSOCKET_FASTAPI_URL
ENV VITE_COMPETITION_API_URL=$VITE_COMPETITION_API_URL \
    VITE_COMPETITION_WS_URL=$VITE_COMPETITION_WS_URL \
    VITE_WEBSOCKET_FASTAPI_URL=$VITE_WEBSOCKET_FASTAPI_URL \
    NODE_ENV=production

RUN npx tsc -p tsconfig.json --noEmit && npm run build

# --- Serve stage ---
FROM nginx:1.27-alpine AS serve

RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist/public /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx:alpine already runs as non-root by default in recent images via the
# nginx user + unprivileged config; keep the default here for simplicity.
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:80/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
