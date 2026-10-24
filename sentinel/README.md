# Sentinel

This tree is part of Arelis and is licensed under AGPL-3.0.

Sentinel runs research and inspection jobs and displays their activity as a 3D Matrix-inspired swarm. Arelis can submit work through the loopback command bridge; the Overseer displays jobs, source receipts, file-integrity findings and socket observations.

## Working roles

- Harvesters retrieve remote sources through the guarded HTTP path and pass content through sanitization before returning it. Research receipts identify retrieved content; hashes do not prove factual accuracy.
- Sanitizers inspect content, redact recognized credentials and quarantine detected hostile payloads. These checks are bounded heuristics, not a guarantee against all prompt injection.
- Wardens inspect host sockets and provide application admission/egress checks. Stored peer bans apply where a caller actually uses the policy. Sentinel does not install host firewall rules.
- Tripwires compare registered file baselines and report changes. Detection does not prevent writes. Runtime source rollback has been disabled.

## Overseer

The renderer retains 3D Sentinels, tentacles, lighting, camera modes and caste identities. Model tiers describe appearance and movement only. Scripted scenarios and synthetic research are rejected by operational interfaces. Enter a topic for arXiv/Wikipedia research, or a specific Horizons target for ephemerides. Inspect missions observe sockets and file integrity. Failed and partial missions remain visible as needing attention.

The emergency stop cancels tracked asyncio tasks and closes registered network clients. It is a software stop, not a hardware network cutoff.

Existing bridge command names remain for compatibility; retired demos and self-heal return explicit errors. The legacy threats_neutralized field is retained for old clients but is not used by the Overseer; security_events counts current-process observations/policy events, not kills. Existing historical receipts are preserved and may contain legacy demo output.

Start with `python -m sentinel` or `scripts/run_sentinel.ps1`. Do not launch a host evaluation until the isolated evaluation plan permits it. This change does not establish or certify end-to-end Arelis integration.
