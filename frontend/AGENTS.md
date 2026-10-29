# SkillForge VM frontend — Local agent guide

Parent instructions apply. Read the root `AGENTS.LOCAL.md` if it exists.

## Scope and contracts

- This directory owns M-11: a Vite, React and TypeScript client of the local HTTP
  service. Use the design document's M-11 section and implementation contract's
  report, error and display acceptance rules before changing behavior.
- Keep API consumption aligned with the shared contract. Resolve a protocol change
  with its provider under the root authorization rules before implementing it.
- Preserve the existing CSS and component conventions. Use the installed CodeMirror
  MergeView for text diffs; clean up its view when the React effect unmounts.
- Use npm and `package-lock.json`. TypeScript strictness comes from `tsconfig.json`.
  Do not add a UI framework, formatter, dependency or test runner for routine edits.

## Commands and verification

The product display name is 留痕. Keep user content, paths, reference values and
technical identifiers unchanged. From the repository root, `test.cmd` runs the
standard checks, `test.cmd desktop` opens an isolated manual session, and
`test.cmd smoke` runs the real Electron check in a newly allocated test directory.
The canonical preparation and command table is in README.

Run from `frontend/`:

```sh
npm ci                 # Install locked dependencies only when needed
npm run dev            # Vite development server
npm run typecheck      # TypeScript check without output
npm run build          # TypeScript check, then Vite build to dist/
npm run preview        # Preview the existing build
```

Use `dev.cmd` from the repository root to start both servers. It passes the actual
backend URL through `SKILLFORGE_DEV_API_URL`; Vite proxies `/api` to that URL.
Standalone `npm run dev` defaults to `http://127.0.0.1:8756` unless that environment
variable is supplied. Ctrl+C in the unified launcher stops only its owned processes.

For behavior changes, run the build and verify the affected interaction against the
local service. State explicitly when browser verification could not be performed.
There is no frontend test, lint or format script in `package.json`; do not invent
one or report the build as browser coverage. Documentation-only edits need link,
command and diff checks; they do not require a frontend build.
