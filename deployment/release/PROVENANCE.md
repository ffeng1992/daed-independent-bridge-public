# Generic DNS code provenance

The project owner's existing DNS generator and dnsdist console client were
reused with explicit permission. Only generic ordered-domain rule generation,
protobuf geosite decoding, Backend, parse_servers and DnsdistControl were
retained in `bridge_m4/release_policy.py` and `bridge_m4/dnsdist_control.py`.

No database contents, credentials, provider addresses, fixed group names,
private PTR networks or ingress hostnames are included. Unknown compound rules
are rejected. The release profile uses administrator-supplied DNS providers;
first installation initializes an explicit direct-only policy.
