# Security

Proxenos holds a person's whole record, so a security problem here matters more than in most projects.

**Please don't open a public issue for a vulnerability.** Report it privately: on this repository's Security tab, choose **Report a vulnerability**. Say what an attacker could reach and how. Never include anyone's personal data, yours included.

What counts:
- anything that lets another website, another device or another person read the vault or reach the local page. The page should answer only itself on 127.0.0.1, and, through `proxenos phone`, only your own Tailscale login;
- anything that makes Proxenos send, post or buy something you didn't approve, including instructions hidden in a message, page or document it reads;
- a token, password or key showing up anywhere outside `.env` or the service's own store: a log, the page, a job's output, an error.
