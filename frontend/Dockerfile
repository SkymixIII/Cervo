# syntax=docker/dockerfile:1
#
# Image `web` — build Vite (dist/) servi par nginx, qui proxifie /api vers le
# service `app` (backend). Seul le port de ce conteneur est publié côté hôte
# (un seul point d'entrée pour l'utilisateur, cf. docker-compose.yml).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1
