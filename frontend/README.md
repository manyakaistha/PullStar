# PullStar desktop UI

The React app mounts `src/App.tsx`, which renders the Alignment studio: `WorkspaceNav`, `CelestialViewfinder`, `ParameterBays`, and `LiveTelemetry`. `src/index.css` supplies the studio styling. These entry-point files and every supporting component must be committed together for a fresh clone to show the same UI.

## Run the desktop app

From the repository root, install Python dependencies with `uv sync`. Then:

```bash
cd frontend
npm ci
npm start
```

`npm start` type-checks and builds the current source, then opens Electron using `dist/index.html`. Electron starts the Python API using the project `.venv` and exposes the native folder chooser through its preload bridge. `dist` is generated locally and is not stored in Git.

For development with live updates:

```bash
npm run desktop
```

This starts Vite on port 5173 and Electron against that server. Vite stops if the port is already occupied; close an older development server before retrying.

## Browser development

Start the API from the repository root:

```bash
uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, run `npm run dev` from `frontend`, then open the displayed URL. In a browser, enter the photo directory path in Alignment setup; the native folder picker is available inside Electron.

## Update an existing clone

Close the app, run `git pull --ff-only` from the repository root, then `uv sync`, `cd frontend`, `npm ci`, and `npm start`.

The redesigned workspace says **Alignment studio** and includes **Detect references**. If an older UI appears, verify that the clone is on the updated `main`, close older app/development-server instances, and use `npm start` to rebuild before launching. Check any terminal errors from dependency installation or the build.

## Verification

`npm run build` checks TypeScript and produces the production bundle. To check the UI that a clone receives, build and open a clean checkout containing only committed files; a successful build alone does not establish that the expected interface is mounted.
