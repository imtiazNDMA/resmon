# Phase 0 placeholder: static page served by nginx. Phase 7/8 replaces this with the
# real Vite + React + TS build (multi-stage: node build -> nginx static).
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 80
