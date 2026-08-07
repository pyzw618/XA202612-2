const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const { Readable } = require("node:stream");
const { pathToFileURL } = require("node:url");

const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml; charset=utf-8",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

async function readIncomingBody(request) {
  if (request.method === "GET" || request.method === "HEAD") return undefined;
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return chunks.length ? Buffer.concat(chunks) : undefined;
}

function createAssetFetcher(clientDir) {
  const root = path.resolve(clientDir);
  return async (request) => {
    const url = new URL(request.url);
    let pathname;
    try {
      pathname = decodeURIComponent(url.pathname);
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    const relativePath = pathname.replace(/^\/+/, "");
    const filePath = path.resolve(root, relativePath);
    if (!filePath.startsWith(`${root}${path.sep}`)) {
      return new Response("Forbidden", { status: 403 });
    }

    try {
      const body = await fs.readFile(filePath);
      return new Response(body, {
        status: 200,
        headers: {
          "content-type": MIME_TYPES[path.extname(filePath).toLowerCase()] || "application/octet-stream",
          "cache-control": relativePath.startsWith("assets/")
            ? "public, max-age=31536000, immutable"
            : "no-cache",
        },
      });
    } catch {
      return new Response("Not Found", { status: 404 });
    }
  };
}

async function sendWebResponse(nodeResponse, webResponse) {
  nodeResponse.statusCode = webResponse.status;
  webResponse.headers.forEach((value, name) => nodeResponse.setHeader(name, value));
  if (!webResponse.body) {
    nodeResponse.end();
    return;
  }
  Readable.fromWeb(webResponse.body).pipe(nodeResponse);
}

async function startUiServer({ distDir, host = "127.0.0.1", port = 0 }) {
  const serverEntry = path.join(distDir, "server", "index.js");
  const clientDir = path.join(distDir, "client");
  const workerModule = await import(`${pathToFileURL(serverEntry).href}?desktop=${Date.now()}`);
  const worker = workerModule.default;
  const fetchAsset = createAssetFetcher(clientDir);

  const server = http.createServer(async (request, response) => {
    try {
      const origin = `http://${host}:${server.address()?.port || port}`;
      const body = await readIncomingBody(request);
      const webRequest = new Request(new URL(request.url || "/", origin), {
        method: request.method,
        headers: request.headers,
        body,
      });
      const webResponse = await worker.fetch(
        webRequest,
        {
          ASSETS: { fetch: fetchAsset },
          IMAGES: {
            input: () => ({
              transform: () => ({
                output: async () => ({ response: () => new Response("Image optimization unavailable", { status: 501 }) }),
              }),
            }),
          },
        },
        { waitUntil() {}, passThroughOnException() {} },
      );
      await sendWebResponse(response, webResponse);
    } catch (error) {
      response.statusCode = 500;
      response.setHeader("content-type", "text/plain; charset=utf-8");
      response.end(error instanceof Error ? error.message : "Desktop UI server failed");
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, resolve);
  });

  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Unable to resolve desktop UI address");

  return {
    url: `http://${host}:${address.port}`,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

module.exports = { startUiServer };
