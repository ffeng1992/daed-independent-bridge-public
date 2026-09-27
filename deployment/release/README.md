# Release profile

The release profile installs dedicated bridge-lan-dns / bridge-policy-dns units,
plus existing bridge daemons and fixed official binaries. It does not adopt an
existing production DNS deployment or import databases. The old production
profile remains unchanged.

First installation asks for LAN address/interface/network, DNS upstream, health
DNS name and Web listen address, or reads `--settings settings.json` (see the
example). The installer leaves a new official database with zero users. Visit
HTTP port 2023 to create the first official account and log in. The original
frontend creates its default resources; the installer does not write defaults.
Add your LAN/DNS settings, proxy nodes and rules in official daed. Group DNS
providers live in release.json; unsupported DNS-policy domain rules fail closed.

Bridge authentication is separate: bridge-login.token (root:independent-bridge
0640) is a local Bridge login credential, never a daed password or API token.
After official setup, `sudo sh install.sh --connect-daed` explicitly authorizes
collection using an existing official account. No password is saved. Only the
daed API token is stored for the collector and attestor. This command validates
and applies the selected configuration without changing official account/config
fields. Before this step, managementReady is not a data-plane health PASS.
Web TLS is self-signed initially. The API is loopback-only. Official daed Web v1.28 is a separate immutable static
frontend on HTTP port 2023, with same-origin GraphQL reverse-proxied to the loopback API on port 2024.
Bridge Web remains on HTTPS port 8443. See DAED_WEB.md. No public unauthenticated control API is created.

Uninstall retains configuration, database, credentials, bundle, extension store
and geodata. Reinstall reuses these without recreating an account or altering
configuration. Purge requires --purge --confirm-purge DELETE-INDEPENDENT-BRIDGE.
Shared DNS components from other deployments are not owned or removed.

The packaging VM runs only the clean lifecycle using synthetic settings and an
in-guest DNS responder. See its actual Actions result; unit checks alone do not
establish clean-machine readiness. No Release is automatically published.
