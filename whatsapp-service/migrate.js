// migrate.js
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
const config = require('./config');

const pool = new Pool(config.db);

async function runMigrations() {
    const migrationsDir = path.join(__dirname, 'migrations');
    const files = fs.readdirSync(migrationsDir).sort();

    for (const file of files) {
        if (file.endsWith('.sql')) {
            const sql = fs.readFileSync(path.join(migrationsDir, file)).toString();
            console.log(`Running migration: ${file}...`);
            await pool.query(sql);
        }
    }
    console.log("✅ All migrations completed successfully.");
    process.exit();
}

runMigrations().catch(err => {
    console.error("❌ Migration failed:", err);
    process.exit(1);
});