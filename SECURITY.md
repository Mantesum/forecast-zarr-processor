# Security policy

Please report suspected vulnerabilities privately through GitHub's security advisory feature after publication. Do not include provider credentials, private forecast URLs, server paths, or production data in a public issue.

The processor treats manifest file names as untrusted, resolves artifacts below the input directory, verifies size and SHA-256 before decoding, and only resumes a staging directory carrying its deterministic dataset ID. Operators should run the hardened service as an unprivileged account with write access limited to the forecast data root.

Security fixes are supported for the latest minor release. There are no secrets required by this processor; provider credentials belong to the upstream ingestion service.

