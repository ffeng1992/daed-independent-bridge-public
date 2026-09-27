# Official daed Web v1.28.0

This is an independent static frontend, not an additional daed daemon.
No upstream source or compiled frontend byte is patched.

The official `v2.1.1` source commit is
`b3043aa7ce07c774c65e546112aa2c7a1c12edb5`; its
[apps/web/package.json](https://github.com/daeuniverse/daed/blob/b3043aa7ce07c774c65e546112aa2c7a1c12edb5/apps/web/package.json)
declares frontend **1.28.0** and `vite build`. The monorepo uses pnpm;
[Vite config](https://github.com/daeuniverse/daed/blob/b3043aa7ce07c774c65e546112aa2c7a1c12edb5/apps/web/vite.config.ts)
uses relative asset paths. Production uses HashRouter, not a Node API server.
There is no separate `v1.28.0` release tag assumed by this installer.

We use the already-built official `gh-pages` commit
`f85de847461824232366fec62f08206cbfcea99b` whose upstream commit message is
`deploy: b3043aa7ce07c774c65e546112aa2c7a1c12edb5`.
`upstream.lock.json.webFrontend` pins the archive, every member and upstream MIT
license. Installation checks all bytes before adding them to the install manifest.
No npm install or frontend rebuild runs on the user's machine.

Official
[defaults](https://github.com/daeuniverse/daed/blob/b3043aa7ce07c774c65e546112aa2c7a1c12edb5/apps/web/src/constants/default.ts)
use `${location.protocol}//${location.hostname}:2023/graphql`.
The frontend is served on HTTP port 2023, matching that default without a launcher
or localStorage rewriting. nginx serves the original index.html at `/` and proxies
same-origin `/graphql` to the loopback-only API backend on port 2024.

- Daed Web: `http://<webAddress>:2023/`, configuration management.
- Bridge Web: `https://<webAddress>:8443/`, independent DAE control and real state.
- Backend: `http://127.0.0.1:2024/graphql`, still `--api-only`, not LAN-bound.
- `daed-web.service`: non-root standalone nginx, fixed loopback reverse proxy,
  no capabilities; only its runtime directory is writable. The distro default
  nginx service is disabled only when newly installed by this package.

The official Run API retains upstream API-only behavior; use Bridge Web to apply
or start the separate official DAE. The two Web interfaces do not merge their
state models. TLS keys, accounts and databases are retained across uninstall.
Static frontend assets and its service are removed with other programs.

## Original first-account flow

The pinned official Setup.tsx reads `numberUsers`. Zero users presents Create
Account (`createUser`), then login (`token`); initialize.ts creates missing default
resources after login. The installer invokes none of these mutations. Existing
users and passwords are retained on upgrade/reinstall. Account settings invokes
upstream `updatePassword`; no direct SQLite password edits are supported.

Bridge Web uses a separate local login token. The separately authorized daed API
token is used only for read-only source collection and receipt observation.
