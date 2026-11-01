# Security policy

Security fixes are provided for the latest release. Report vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/manyakaistha/PullStar/security/advisories/new). Please avoid public issues containing exploitable details or private photo paths.

PullStar processes local files. Its desktop backend binds to a random loopback port and is terminated with the app. The MCP server can read and write files under the permissions of the user running it. Connect only trusted MCP clients. Network MCP transports default to loopback and have no application-level authentication; do not expose them on public interfaces without an authenticated gateway.

The initial macOS release is ad-hoc signed and not notarized. Release checksums detect accidental corruption; they are not a substitute for Apple notarization or signed release provenance.
