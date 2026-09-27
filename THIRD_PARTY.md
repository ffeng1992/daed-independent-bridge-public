# Third-party components

The MIT license covers this repository's bridge and packaging code. Official
daed and DAE are separate upstream programs downloaded from the immutable URLs
in `upstream.lock.json`; their sources and binaries are not included in this
source distribution. Their own licenses apply. Refer to the corresponding
[daed](https://github.com/daeuniverse/daed) and
[DAE](https://github.com/daeuniverse/dae) releases and source trees.

Python dependency versions and wheel hashes are recorded in
`deployment/m4/requirements.lock`. Installed wheels retain their license metadata.
Debian system packages retain Debian's copyright and license information.
See `deployment/release/PROVENANCE.md` for the generic DNS implementation origin.
