const path = require("path");
// Load local .env first
require("dotenv").config({ path: path.resolve(__dirname, "../.env") });
// Load parent/root .env as fallback for missing environment variables
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") });

// Helper to parse MinIO endpoint and port robustly
let minioHost = process.env.MINIO_ENDPOINT || 'localhost';
let minioPort = parseInt(process.env.MINIO_PORT || process.env.MINIO_ENDPOINT_PORT || '9000');

// If MINIO_ENDPOINT includes the port (e.g. "localhost:9005"), split it out
if (minioHost.includes(':')) {
  const parts = minioHost.split(':');
  minioHost = parts[0];
  // Only override the port if not explicitly set via environment variables
  if (!process.env.MINIO_PORT && !process.env.MINIO_ENDPOINT_PORT) {
    minioPort = parseInt(parts[1]) || 9000;
  }
}

const config = {
  db: {
    user: process.env.DB_USER,
    host: process.env.DB_HOST,
    database: process.env.DB_NAME,
    password: process.env.DB_PASS,
    port: parseInt(process.env.DB_PORT) || 5432,
  },
  hosts: {
    backend: process.env.BACKEND_HOST || "http://192.168.18.132:3000",
    agent: process.env.AGENT_HOST || "http://127.0.0.1:3034",
  },
  minio: {
    endPoint: minioHost,
    port: minioPort,
    useSSL: false,
    accessKey: process.env.MINIO_ACCESS_KEY || process.env.MINIO_ROOT_USER || 'minioadmin',
    secretKey: process.env.MINIO_SECRET_KEY || process.env.MINIO_ROOT_PASSWORD || 'minioadmin',
    bucket: process.env.MINIO_WHATSAPP_BUCKET || 'whatsapp-attachments',
  },
  isProduction: process.env.NODE_ENV === "production",
};

// Freeze the object so it can't be modified at runtime
module.exports = Object.freeze(config);
