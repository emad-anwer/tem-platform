# W4-07 · TLS certificate parsing, and SANs back into discovery

**Owner:** Arwa · **Reviewer:** Tasneem · **Effort:** 4h · **Depends on:** W4-04

> ⚠️ **Scope.** Until W4-02 merges, `localhost` and the four `just lab-up` containers are the
> only things you may point any of this at. After it merges, the allowlist is. Anything else —
> a domain you own, your VPS, "just to test it" — **ask first, every time.**

The one task this week that closes a loop: what it finds becomes input to the discovery code you
wrote last week.

## What

For every open port that negotiates TLS, fetch the certificate and record what is in it.

- **Fetch the certificate without validating it.** This is the part that feels wrong and is correct:
  you are scanning, not connecting as a client. A self-signed or expired certificate is a *finding*,
  not an error — `lab-tls-san` is self-signed precisely so this is not theoretical. Set the SSL
  context deliberately, with a comment saying why, so the next reader does not "fix" it
- **Parse it with `cryptography`.** Record: subject CN, issuer, `not_valid_before_utc` /
  `not_valid_after_utc`, the SHA-256 fingerprint, the signature algorithm, and the full SAN list
- **Record expiry as data, not as a judgement.** Store the date. Whether "expires in 12 days" is
  `high` severity is a policy question, and policy belongs in one place, not in the parser
- **Feed the SANs back into discovery.** This is the interesting half. `lab-tls-san`'s certificate
  lists `target4.lab.local`, `sub1.target4.lab.local`, `api.target4.lab.local`,
  `admin.internal.tem.local` and `127.0.0.1`. The three DNS names under the target domain become
  `subdomain` findings on the same target, through the same generic finding path W3-07 uses
- Writes `tls_certificate` findings through W4-03's path, with the identity ADR-0004 chose

**`cryptography` is a direct runtime dependency.** Do not rely on it arriving transitively through
`pyjwt[cryptography]`; the scanner imports it directly to parse peer certificates.

SAN policy: retain the full typed SAN list, including IPs and names outside the target domain, in
the `tls_certificate` finding. Only DNS SANs accepted by W3-07's `_belongs_to_domain` for the
normalized target domain become `subdomain` findings. This keeps `admin.internal.tem.local` useful
as certificate data without misclassifying it as a subdomain or expanding the target's discovery
scope; `127.0.0.1` is retained as an IP SAN, not converted into a hostname finding.

Tests:

- `lab-tls-san` → certificate parsed, all five SANs extracted, self-signed recorded rather than
  raised. (Its TLS port is `8443` from your laptop and `443` from the worker — see W4-04)
- The three in-domain DNS SANs become subdomain findings
- The IP SAN (`127.0.0.1`) and out-of-domain DNS SAN remain in certificate details only
- A plain HTTP port is not treated as TLS and does not hang
- An expired certificate is a finding, not an exception

## Expected outcome

Scanning `lab-tls-san` yields one `tls_certificate` finding plus subdomain findings for names nobody
typed in. Running discovery again afterwards does not duplicate them — W3-08's fingerprint already
handles that, and this proves it.

## Think about

You wrote `discovery.py` last week. This task writes findings that it has to accept **without a
special case**. If you find yourself needing one, that is not a W4-07 problem — it means W4-03's
abstraction is wrong, and that conversation belongs to you and Zyad, together, on Wednesday. Have it
rather than working around it.

Certificate transparency in W3-07 found subdomains from a public log. This finds them from the host
itself. They overlap heavily and they are not the same set — a cert on an internal host never
appears in a CT log. Being able to say why you want both is the domain lesson of this task.

If this week runs late, **this is the task the mentor will cut** to protect W4-06 and W4-10. That is
not a reflection on it — it is the most interesting thing in the week and also the most droppable.
Land it Wednesday.

## Search for

- python ssl get_peer_cert verify_mode CERT_NONE
- cryptography x509 load_der_x509_certificate
- x509 SubjectAlternativeName extension DNSName IPAddress
- ssl create_default_context check_hostname False
- certificate sha256 fingerprint
- asyncio open_connection ssl context server_hostname
