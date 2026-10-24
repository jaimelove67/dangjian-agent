ARG NODE_IMAGE=docker.io/library/node:24-alpine
ARG NGINX_IMAGE=docker.io/library/nginx:1.28-alpine
FROM ${NODE_IMAGE} AS build
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG VITE_DATA_MODE=live
ARG VITE_API_BASE_URL=/api/v1
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --registry=${NPM_REGISTRY}
COPY . ./
RUN VITE_DATA_MODE=${VITE_DATA_MODE} VITE_API_BASE_URL=${VITE_API_BASE_URL} npm run build

FROM ${NGINX_IMAGE}
COPY deploy/nginx-http.conf /etc/nginx/conf.d/default.conf
COPY --from=build /frontend/dist /usr/share/nginx/html
EXPOSE 80
