# certs

Drop the OTEL/OpenObserve server's `ca.crt` here (get it from whoever runs the
server for your team). It's a public certificate, not a secret, so it's fine
to commit.

`Setup-CopilotOtelAgent.ps1` / `setup-copilot-otel-env.sh` prompt for the path
to this file during setup.
