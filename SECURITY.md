# Security

## Reporting

Open a GitHub issue for anything non-sensitive. For something you would rather
not post publicly, use GitHub's private vulnerability reporting on this
repository.

## What this application does and does not do

It makes outbound HTTPS requests to public data endpoints, writes a cache under
`.cache/` in the repo directory, and serves a local Streamlit page. It has **no
user accounts, no login, no database, and no write path to any remote service**.
It sends no telemetry (`gatherUsageStats = false`) and requires no API keys or
credentials to run.

## Things worth knowing before you deploy it

**It is not built to be exposed to the internet.** There is no authentication
of any kind. By default the server binds to `localhost` only. If you change
`server.address` to expose it on a network, anyone who can reach the port gets
the full dashboard. Put it behind a reverse proxy with authentication first, and
do not port-forward it.

**The cache uses `pickle`.** `ficc/cache.py` serialises pandas objects to
`.cache/*.pkl` and reads them back with `pickle.load`, which executes arbitrary
code on a malicious payload. The practical exposure is small: the app only ever
reads files it wrote itself, in a directory inside the repo, with hashed
filenames, and `.cache/` is gitignored so it is never distributed. An attacker
who can write into that directory can already edit the `.py` files next to it,
so pickle is not the weak link in that scenario. Still — **do not point this at
a cache directory you did not create**, do not share cache directories between
users, and delete `.cache/` if you ever receive one from someone else.

**`headers.local.json` will contain session cookies if you use it.** The file is
an escape hatch for sources that block scripted clients: you paste request
headers copied from your browser's network tab, and they are merged over the
defaults at import. Those headers usually authenticate as *you*. The file is
gitignored — keep it that way, never commit it, and never paste headers for a
site where your session carries privileges you would not want a script to use.

**Dependencies.** Runtime dependencies are `streamlit`, `plotly`, `pandas`,
`numpy`, `yfinance`, and `requests`, pinned transitively in `uv.lock`. `yfinance`
is an unofficial client that scrapes a public web endpoint; treat its output as
untrusted input, which is why nothing it returns is used to build file paths or
executed in any form.

## Supported versions

The `main` branch only. This is a personal project, not a maintained product.
