#!/bin/sh
set -e

# Remove stale Chromium profile lock files left by previous container crashes.
# These files persist in the named volume and block Chromium from launching.
# Only the locks are removed — session auth data is preserved.
echo "🧹 Cleaning stale Chromium lock files..."
find /app/.wwebjs_auth -name "SingletonLock" \
                       -o -name "SingletonCookie" \
                       -o -name "SingletonSocket" \
  2>/dev/null | xargs rm -f 2>/dev/null || true

echo "🔄 Running database migrations..."
node migrate.js

echo "🚀 Starting WhatsApp service..."
exec node app.js
