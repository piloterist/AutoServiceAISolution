# Multi-stage: `dev` target is used by docker-compose for local development
# (hot reload against a bind-mounted source tree); `prod` target is a small,
# standalone image suitable for any deployment target (single-tenant hosted
# or on-premise).

FROM node:20-alpine AS base
WORKDIR /app

FROM base AS deps
COPY package.json package-lock.json* ./
RUN npm install

FROM deps AS dev
COPY . .
ENV NODE_ENV=development
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY . .
# NEXT_PUBLIC_* vars are baked into the client bundle at build time, not read
# at container runtime - must be passed as a build ARG (Railway and most
# platforms pass service variables to `docker build` as build args when the
# Dockerfile declares them; a plain runtime env var set later is too late).
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM base AS prod
ENV NODE_ENV=production
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
