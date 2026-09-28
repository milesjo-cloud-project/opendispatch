FROM node:26-slim AS deps
WORKDIR /srv/web
COPY package*.json ./
RUN npm install

# Local development: hot reload, src is mounted by docker compose
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

# Production build: static files for Firebase Hosting later
FROM deps AS build
COPY . .
RUN npm run build
