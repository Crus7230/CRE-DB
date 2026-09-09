import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createClient } from '@libsql/client';

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const projectRoot = path.dirname(webRoot);
const args = process.argv.slice(2);
const option = (name, fallback) => { const index = args.indexOf(name); return index < 0 ? fallback : args[index + 1]; };
const manifestPath = path.resolve(option('--manifest', path.join(projectRoot, 'data/split/manifest.json')));
const authPath = path.resolve(option('--auth-db', path.join(projectRoot, 'data/local-access.db')));
const seedPath = option('--seed-auth-db');
const port = Number(option('--port', '3005'));
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Use a valid local port');

async function ensureLocalAccess() {
  if (fs.existsSync(authPath)) {
    const existing = createClient({ url: pathToFileURL(authPath).toString() });
    try {
      const count = await existing.execute('SELECT count(access_subject_id) AS n FROM dashboard_access_allowlist');
      await existing.execute('SELECT rate_limit_key FROM dashboard_login_rate_limits LIMIT 0');
      if (Number(count.rows[0].n) < 1) throw new Error('Local access list is empty');
    } finally { existing.close(); }
    return;
  }
  if (!seedPath || !fs.existsSync(path.resolve(seedPath))) throw new Error('First start requires --seed-auth-db pointing to an existing approved local access database');
  const source = createClient({ url: pathToFileURL(path.resolve(seedPath)).toString() });
  let target;
  // Exclusively reserve a new file: never replace an existing access list.
  const descriptor = fs.openSync(authPath, 'wx');
  fs.closeSync(descriptor);
  try {
    const allowlist = await source.execute('SELECT * FROM dashboard_access_allowlist');
    if (!allowlist.rows.length || allowlist.rows.length > 100) throw new Error('Unexpected local approved-subject seed');
    const definitions = await source.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' AND name IN ('dashboard_access_allowlist','dashboard_login_rate_limits') ORDER BY name");
    if (definitions.rows.length !== 2) throw new Error('Local access schema is incomplete');
    target = createClient({ url: pathToFileURL(authPath).toString() });
    const tx = await target.transaction('write');
    try {
      for (const row of definitions.rows) await tx.execute(String(row.sql));
      const columns = allowlist.columns;
      if (columns.some(name => !/^[a-z_]+$/i.test(name))) throw new Error('Unexpected access columns');
      const sql = `INSERT INTO dashboard_access_allowlist (${columns.map(name => `"${name}"`).join(',')}) VALUES (${columns.map(() => '?').join(',')})`;
      for (const row of allowlist.rows) await tx.execute({ sql, args: columns.map(column => row[column]) });
      const count = await tx.execute('SELECT count(*) AS n FROM dashboard_access_allowlist');
      if (Number(count.rows[0].n) !== allowlist.rows.length) throw new Error('Access seed parity failed');
      await tx.commit();
    } catch (error) { await tx.rollback(); throw error; }
    console.log(`Local access database prepared: ${allowlist.rows.length} existing subjects preserved.`);
  } catch (error) {
    // Leave the reserved file for inspection; never silently retry/overwrite it.
    throw new Error('Could not prepare local access database; inspect the newly reserved file before retrying', { cause: error });
  } finally { source.close(); target?.close(); }
}

function verifiedManifest() {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (manifest.complete !== true || !manifest.crossOutput?.sourceRowParity) throw new Error('Split snapshot is not verified');
  const base = fs.realpathSync(path.dirname(manifestPath));
  const directory = fs.realpathSync(manifest.snapshotDirectory);
  const relative = path.relative(base, directory);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Snapshot must remain below the split directory');
  const result = { snapshotId: manifest.snapshotId };
  for (const name of ['news', 'timeseries']) {
    const item = manifest.outputs[name];
    if (!item?.allTableParity || item.integrity !== 'ok' || item.foreignKeyViolations !== 0 || item.filename !== `${name}.db`) throw new Error('Invalid split output');
    const filename = path.join(directory, item.filename);
    if (!fs.existsSync(filename) || fs.statSync(filename).size !== item.bytes) throw new Error('Split database file is missing or changed');
    result[name] = pathToFileURL(filename).toString();
  }
  return result;
}

const snapshot = verifiedManifest();
await ensureLocalAccess();
if (args.includes('--check')) {
  console.log(JSON.stringify({ ready: true, snapshot: snapshot.snapshotId, port, authDatabase: authPath }));
} else {
  const child = spawn(process.execPath, [path.join(webRoot, 'node_modules/next/dist/bin/next'), 'start', '--hostname', '127.0.0.1', '--port', String(port)], {
    cwd: webRoot,
    windowsHide: true,
    stdio: 'inherit',
    env: {
      ...process.env,
      DASHBOARD_DATA_PROVIDER: 'sqlite', DASHBOARD_DATASET_VERSION: snapshot.snapshotId,
      TURSO_DATABASE_URL: pathToFileURL(authPath).toString(), TURSO_AUTH_TOKEN: '',
      NEWS_DATABASE_URL: snapshot.news, NEWS_AUTH_TOKEN: '',
      TIMESERIES_DATABASE_URL: snapshot.timeseries, TIMESERIES_AUTH_TOKEN: '',
      DASHBOARD_SESSION_SECRET: process.env.DASHBOARD_SESSION_SECRET || randomBytes(48).toString('hex'),
    },
  });
  console.log(`Local only: http://127.0.0.1:${port}/ · snapshot ${snapshot.snapshotId}`);
  for (const event of ['SIGINT', 'SIGTERM']) process.on(event, () => child.kill());
  child.on('exit', code => { process.exitCode = code ?? 0; });
}
