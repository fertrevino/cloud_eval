FROM node:18-alpine

WORKDIR /app

RUN npm config set cache /tmp/npm-cache
COPY package.json ./
RUN npm install --production

COPY server.js ./
COPY public ./public

EXPOSE 3000
CMD ["npm", "start"]
