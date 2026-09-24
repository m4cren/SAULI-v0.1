import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { PGlite } from "@electric-sql/pglite";
import { pgcrypto } from "@electric-sql/pglite/contrib/pgcrypto";
import { pg_trgm } from "@electric-sql/pglite/contrib/pg_trgm";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const source = await readFile(resolve(root, "SAULI_Anonymous_Reset.sql"), "utf8");
const migration = await readFile(
  resolve(root, "supabase/migrations/202609230001_sauli_anonymous_reset.sql"),
  "utf8",
);
const verification = await readFile(resolve(root, "supabase/verify.sql"), "utf8");
assert.equal(migration, source, "migration must be an unchanged copy of the supplied reset");

const db = new PGlite({ extensions: { pgcrypto, pg_trgm } });
await db.exec(`
  create role anon nologin;
  create role authenticated nologin;
  create role service_role nologin bypassrls;
  create schema storage;
  create table storage.buckets (
    id text primary key,
    name text not null,
    public boolean not null default false,
    file_size_limit bigint,
    allowed_mime_types text[]
  );
`);
await db.exec(migration);
await db.exec(verification);

const tables = await db.query("select count(*)::int as count from public.found_items");
assert.equal(tables.rows[0].count, 0, "verification fixtures must roll back");

const bucket = await db.query(`
  select public, file_size_limit::int as file_size_limit, allowed_mime_types
  from storage.buckets where id = 'sauli-item-images'
`);
assert.equal(bucket.rows.length, 1);
assert.equal(bucket.rows[0].public, false);
assert.equal(bucket.rows[0].file_size_limit, 10_485_760);
assert.deepEqual(bucket.rows[0].allowed_mime_types, ["image/jpeg", "image/png", "image/webp"]);

for (const role of ["anon", "authenticated"]) {
  let denied = false;
  try {
    await db.exec(`set role ${role}; select * from public.found_items; reset role;`);
  } catch {
    denied = true;
    await db.exec("reset role");
  }
  assert.equal(denied, true, `${role} must not read application tables`);
  denied = false;
  try {
    await db.exec(`set role ${role}; select * from public.get_eligible_found_items(now(), 10); reset role;`);
  } catch {
    denied = true;
    await db.exec("reset role");
  }
  assert.equal(denied, true, `${role} must not execute application RPCs`);
}

console.log("PASS: authoritative reset and transactional verification SQL");
console.log("PASS: temporal boundaries and session-bound atomic retrieval");
console.log("PASS: private bucket and browser-role denial");
await db.close();
