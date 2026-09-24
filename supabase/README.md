# SAULI database

`../SAULI_Anonymous_Reset.sql` is the authoritative reset supplied for this
prototype. The identically named migration in `migrations/` is an unchanged
copy so the reset can also be applied through a migration workflow.

## Important reset warning

The reset drops and rebuilds only the four SAULI prototype tables, SAULI helper
functions, and the SAULI item-code sequence. It deletes existing data in those
tables. It does not drop the `public` schema, touch Supabase Auth, or modify
unrelated tables.

Review the target project, back up anything needed, and then run
`SAULI_Anonymous_Reset.sql` once in the Supabase SQL Editor as the project
owner. Do not run it automatically from the application.

The reset configures a private `sauli-item-images` bucket with a 10 MiB limit
and JPEG/PNG/WebP MIME types. SQL does not delete Storage objects. If the former
`found-item-images` bucket contains test files, empty and delete it manually in
the Supabase Storage Dashboard or through the Storage API.

## Access model

There is no Supabase Auth in this prototype. The browser talks only to FastAPI.
FastAPI uses `SUPABASE_SECRET_KEY` on the server; never expose that value in a
`NEXT_PUBLIC_*` variable. RLS is enabled and no application-table or RPC access
is granted to `anon` or `authenticated`.

Postgres stores only private object paths. FastAPI creates short-lived signed
URLs when the UI needs an image. The atomic retrieval RPC validates that the
requested item is an eligible match belonging to the same anonymous browser
session, locks it, marks it retrieved, and writes the retrieval audit event.

## Verification

After the reset, run `verify.sql` separately as the database owner. Its fixtures
are rolled back. It checks the exact temporal boundaries, anonymous-session
isolation, atomic and duplicate retrieval behavior, private bucket setting, and
browser-role denial.

For an isolated local SQL check with no credentials:

```powershell
cd supabase\tests
npm ci --ignore-scripts
npm test
```

PGlite exercises the real reset and verification SQL in memory. It does not
replace a final live Supabase test of the HTTP Data API, Storage uploads/signed
URLs, or concurrent sessions.
