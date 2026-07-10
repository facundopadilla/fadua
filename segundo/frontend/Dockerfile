# syntax=docker/dockerfile:1

# --- Stage 1: build the Vite/React SPA -------------------------------------
# The API base URL must be baked in at build time because Vite inlines
# import.meta.env.VITE_API_URL into the static bundle. In production the SPA is
# served same-origin behind nginx, so we pass VITE_API_URL=/api (see compose).
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first so this layer is cached across source changes.
COPY package.json package-lock.json ./
RUN npm ci

# Build the production bundle with the API base baked in.
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

COPY . .
RUN npm run build

# --- Stage 2: serve the static bundle with nginx ---------------------------
FROM nginx:alpine AS runtime

# Replace the default site with our SPA + /api reverse-proxy config.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets produced by `vite build` (output dir defaults to dist/).
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine's base image already runs `nginx -g 'daemon off;'` as CMD.
