# Pure static SPA build (vite build -> dist/, no SSR) served by Caddy.
# Only VITE_API_BASE_URL is a build ARG — deliberately NOT
# VITE_AGENT_FORGE_API_TOKEN, which used to be baked into the bundle here
# and was a live security bug (see frontend/src/pages/LoginPage.tsx /
# frontend/src/lib/auth.ts — admin token verification is server-side now).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
