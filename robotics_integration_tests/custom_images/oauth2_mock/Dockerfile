FROM node:24-alpine
RUN mkdir -p /app && chown node:node /app
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY index.mjs .
USER node
EXPOSE 8080
CMD ["node", "index.mjs"]
