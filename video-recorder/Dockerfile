FROM mcr.microsoft.com/playwright:v1.40.0-jammy

WORKDIR /app

COPY package.json ./
RUN npm install --production && npx playwright install chromium --with-deps

COPY server.js recorder.js ./

EXPOSE 3000

CMD ["node", "server.js"]
