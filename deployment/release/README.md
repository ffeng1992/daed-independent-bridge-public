# Release profile

The release profile installs dedicated bridge-lan-dns / bridge-policy-dns units,
plus existing bridge daemons and fixed official binaries. It does not adopt an
existing production DNS deployment or import databases. The old production
profile remains unchanged.

First installation asks for LAN address/interface/network, DNS upstream, health
DNS name and Web listen address, or reads `--settings settings.json` (see the
example). Initial routing is explicitly **direct-only**. Add your proxy nodes and
rules in official daed, then preview/validate/apply from bridge Web. Group DNS
providers live in release.json; unsupported DNS-policy domain rules fail closed.

Administrator credentials are generated uniquely per host and saved only at
/etc/daed-independent-bridge/initial-admin.json (root:root 0600), never printed.
Web TLS is self-signed initially. The API is loopback-only. Official daed Web v1.28 is a separate immutable static
frontend on HTTPS port 8444, with same-origin GraphQL reverse-proxied to the API.
Bridge Web remains on HTTPS port 8443. See DAED_WEB.md. No public unauthenticated control API is created.

Uninstall retains configuration, database, credentials, bundle, extension store
and geodata. Reinstall reuses these without recreating an account or altering
configuration. Purge requires --purge --confirm-purge DELETE-INDEPENDENT-BRIDGE.
Shared DNS components from other deployments are not owned or removed.

The packaging VM runs only the clean lifecycle using synthetic settings and an
in-guest DNS responder. See its actual Actions result; unit checks alone do not
establish clean-machine readiness. No Release is automatically published.
