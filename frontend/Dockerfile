FROM node:24.21.0-bookworm-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.30.6-alpine AS runtime
COPY infra/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
RUN mkdir -p /tmp/nginx && chown -R nginx:nginx /tmp/nginx /etc/nginx/conf.d /var/cache/nginx /var/log/nginx \
    && sed -i -E 's|^pid[[:space:]]+[^;]+;|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf \
    && sed -i '/^user /d' /etc/nginx/nginx.conf
USER nginx
EXPOSE 8080
