# Astral-AI Launcher Architecture

## High-Level Overview

- **Purpose**: desktop Minecraft launcher focused on visual modpack authoring, powered by AI-assisted conflict resolution and diagnostics.
- **Stack**: React + TypeScript (Vite) in the webview, Rust + Tauri on the native side, with auxiliary Go and Kotlin projects for transport and P2P distribution.
- **Key capabilities**:
  - Drag-and-drop board for building and categorising modpacks.
  - Automated dependency resolution, Java runtime provisioning, and project lifecycle management.
  - Deep integration with Astral AI cloud (accounts, AI pipelines, crash doctor).
  - Multi-language UI, theming, and custom context menu/overlay system.

## Frontend (React + Vite)

### Entry Flow and Providers

- `src/main.tsx` bootstraps React and hydrates the Tauri webview.
- `App.tsx` orchestrates authentication, window lifecycle, and view switching between `HomePage` (project browser) and `BoardPage` (mod workspace).
- Providers include:
  - `KeyboardProvider` (`src/global/KeyboardContext.tsx`) to track hotkeys and focus.
  - `ModalProvider` / `ModalContext` for stackable modals.
  - `ContextMenuProvider` (`src/contexts/ContextMenuContext.tsx`) for the custom right-click and version selector experience.
  - `i18n/config.ts` initialises react-i18next; translations live under `src/i18n/locales/*`.

### Authentication & Session UX

- `astralAuth` service handles login via OTP or OAuth, synchronises tokens with secure storage, and refreshes tokens every four minutes.
- Login flow:
  1. User submits email → OTP API (`/api/auth/otp`).
  2. Verify OTP → tokens returned, persisted via Tauri command `save_astral_session`.
  3. `App.tsx` listens for session changes and toggles between `LoginScreen` and main app.

### Home Page (Project Hub)

- `src/pages/HomePage/index.tsx` renders featured modpacks, pinned projects, and cosmic background animations.
- Background assets are memoised and seeded to avoid CPU spikes; state persists to `localStorage`.
- Project cards pull metadata from Tauri (`invoke('list_projects')`) and allow creation, pinning, and deletion.

### Board Workspace

- `src/pages/BoardPage.tsx` loads a project into the interactive canvas (`src/board/Board.tsx`).
- Features:
  - Zoom/pan via `usePanZoom`.
  - Node-based editing using custom components under `src/components/nodes/*`.
  - AI panels (`src/board/hooks/useAIPanel.ts`) spawn phantom recommendations and integrate with backend pipelines.
  - Dependencies and metadata fetched via `modsApi` service with Tauri commands.
- State persistence:
  - `useBoardPersistence` syncs positions, categories, AI summaries, and Fabric Fix state via `load_board_state` / `save_board_state`.

### Context Menus & Version Selector

- `ContextMenuContext` manages lifecycle of right-click menus, including the in-place loader/version selector overlay.
- `VersionSelectorInMenu.tsx` fetches all loaders/versions via `getModVersions` and renders them inline without modal transitions.
- Menu behaviour is finely tuned (no close on scroll, back navigation on Esc, grey-out during download).

### AI & Diagnostics Integrations

- `useAIApi.ts`, `CrashDoctorSplash.tsx`, and board hooks talk to Astral AI endpoints for:
  - Modpack summaries and auto-sort suggestions.
  - Crash analysis via `/api/crash-doctor`.
  - Usage limits and friend presence (for social features).

### Services and API Calls

- `src/services/modsApi.ts` bridges React → Tauri commands (`invoke('search_mods')`, `invoke('download_mod')`).
- `src/services/astralAuth.ts` handles HTTPS calls directly to `astral-ai.online`.
- Additional services:
  - `astralAuth` token refresh.
  - `settings` service for local preferences.
  - `modsBrowser` for pagination and filters.

### Persistence & Local Data

- Local UI state persists through:
  - Tauri board-state storage (JSON per project).
  - `localStorage` for quick UI bits (Home page animation seeds, pinned projects).
  - Filesystem watchers to refresh listings when mods change.

### Internationalisation & Styling

- `i18n` keys structured by feature (version selector, board, auth).
- Styling uses a mix of CSS modules (e.g., `LanguageButton.css`), global utility sheets, and dynamic theme variables in `variables.css`.
- Focus styles are customised to remove browser defaults while maintaining accessibility cues.

## Backend (Rust + Tauri)

### Command Surface

- `src-tauri/src/main.rs` registers all Tauri commands and initialises global managers:
  - Project management (`projects.rs`, `project_commands.rs`).
  - Minecraft core orchestration (`minecraft_core.rs`).
  - Mod lifecycle (`mods.rs`).
  - Authentication/session storage (`astral_session.rs`, `auth.rs`).
  - Crash doctor, wardrobe, and watchdog services.
- Watchdog ensures UI responsiveness via periodic heartbeat:

```100:108:src-tauri/src/watchdog.rs
#[tauri::command]
pub fn watchdog_heartbeat() {
    update_heartbeat();
}
```

### Mod Discovery & Installation

- `mods.rs` wraps Modrinth API:
  - `search_mods` builds facet queries.
  - `get_mod_versions` filters by Minecraft version and loader.
  - `download_mod` pulls version metadata, validates hashes, and streams files into the project `mods/` folder.
- Dependency metadata is preserved to allow Fabric Fix fallback and NeoForge prioritisation.
- Mod toggling and deletion manipulate filesystem state (`.disabled` suffix).

### Minecraft Core & Runtime Provisioning

- `minecraft_core.rs` handles:
  - Creating and maintaining launcher profiles (`launcher_profiles.json`).
  - Installing loaders (NeoForge, Forge, Fabric) with cached installers.
  - Downloading Minecraft assets via Nitrolaunch libraries.
  - Determining and provisioning the correct Java runtime per project:

```540:548:src-tauri/src/minecraft_core.rs
let java_version = determine_java_version(&minecraft_version);
let java_path = find_or_download_java(&base, java_version).await?;
println!("Using Java: {}", java_path);
let install_client_arg = format!("--installClient={}", base.to_string_lossy());
println!("Executing: {} -jar {:?} {}", java_path, installer_path, install_client_arg);
```

- Java management downloads isolated JVM builds into launcher storage, ensuring system-wide setups remain untouched.

### Project & Board State

- `board_state.rs` stores board snapshots, categories, AI summaries, and migration versions.
- `project_commands.rs` covers project creation, deletion, metadata updates, and linking to filesystem paths.
- `dependency_cache.rs` caches Modrinth dependencies to reduce API churn and accelerate dependency trees.

### Session, Auth, and Settings

- `astral_session.rs` persists encrypted session data in the Tauri side, exposed via commands `get_astral_session` and `save_astral_session`.
- `settings.rs` stores global launcher preferences (language, telemetry, Fabric Fix flag).
- `auth.rs` coordinates OAuth redirect handling via deep link (`astral-ai://callback`).

### Diagnostics & Reliability

- `watchdog.rs` terminates the app if UI fails to report ready/heartbeat.
- `crash_doctor.rs` and related assets integrate with the Crash Doctor pipeline for log ingestion and AI-assisted fixes.
- `performance.rs` monitors CPU-intensive tasks and provides telemetry hooks.
- Live events emitted via `Emitter` let the frontend show progress toasts and status updates.

## External Integrations

### Astral AI Cloud

- HTTPS endpoints under `https://astral-ai.online` for:
  - Authentication (`/api/auth/*`, OAuth).
  - AI build services, crash doctor, usage limits, friends lists.
- Communication pattern: fetch with bearer token (frontend), or Tauri command that proxies HTTP (backend modules in `src-tauri`).

### Modrinth API

- Rust-side `reqwest` client handles both search and project version queries, enforcing `User-Agent: ASTRAL-AI-Launcher`.
- Responses map into strongly typed structs (`ModrinthMod`, `ModVersion`) shared with the frontend through Tauri invokes.

### Nitrolaunch & JVM Tooling

- The embedded Nitrolaunch library (Rust crate) provides Minecraft asset downloading, version metadata, and installer pipelines.
- Java runtimes fetched from Mojang/Adoptium mirrors via Nitrolaunch helpers, cached per launcher instance.

### P2P & Transport Utilities

- `gole-source/` (Go) implements a hole-punching client/server leveraging KCP and S5 tunnels for peer connections—used for future multiplayer file sync.
- `p2p-mod/` (Gradle project) adds Minecraft-side hooks for Astral peer networking.

## Data Flow Summary

1. **User Authentication**: `LoginScreen` calls `astralAuth` → Astral API → session stored via Tauri.
2. **Project Selection**: `HomePage` lists projects from `invoke('list_projects')`; selecting opens board via `open_board_window`.
3. **Board Editing**:
   - Adding mod triggers `search_mods` → `download_mod` → board updates.
   - Context menu `Change version` uses `getModVersions`, updates via `handleVersionChange`.
   - State persists through `save_board_state`.
4. **Launch/Install**: User commands lead to `minecraft_core` routines—downloads loaders, assets, and Java, building runnable instance.
5. **Monitoring**: Watchdog heartbeats and performance telemetry keep the native process aware of stalls; crash logs can be sent to Crash Doctor pipelines.

## Build & Packaging

- **Development**: `npm run tauri:dev` boots Vite + Tauri dev process.
- **Production**: `npm run tauri:build` compiles React, builds Rust binary, and packages MSI/DMG via Tauri bundler.
- TypeScript project references (`tsconfig.*`) split app/node builds; ESLint and PostCSS provide linting and styling pipelines.
- `src-tauri/tauri.conf.json` defines updater channels, bundle settings, and deep link permissions.

## Additional Documentation & References

- `docs/connection-lines-improvements.md`, `docs/persistence.md`, and `src/board/HOOK_MAPPING.md` cover feature-specific behaviour.
- `ROADMAP/` tracks planned modules (auto-update, accounts, settings).
- `AI_API_SECURITY.md` and `AI_INTEGRATION_PLAN.md` document backend security posture and API usage policies.

---

**Summary**: Astral-AI Launcher blends React-driven UX with a Rust/Tauri backend to deliver a mod-centric workspace that automates dependency management, Java provisioning, and AI-assisted tooling. The architecture cleanly separates UI concerns, native operations, and cloud integrations, enabling fast iteration on both launcher features and AI services.

