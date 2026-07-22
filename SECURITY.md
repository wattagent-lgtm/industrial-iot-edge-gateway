# Security

Never commit Wi-Fi passwords, WebREPL passwords, SIM credentials, AWS account
identifiers, X.509 device certificates, or private keys.

Use the example configuration files as templates and keep real `config.py`
files local. If a credential is committed accidentally, revoke or rotate it
immediately; deleting it from the latest commit is not sufficient.

Please report security issues privately to the repository owner rather than
opening a public issue.
