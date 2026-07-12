# Security policy

This is a private repository. Report suspected vulnerabilities directly to the repository owner; do not disclose them in public issues.

Never commit browser cookies, Yuanbao cookies, exported `cookies.txt` files, `.env` files, access tokens, private keys, downloaded media, Whisper models, or debug captures. Configure credentials only in the MCP client's local environment or other machine-local secret storage.

Before every push, inspect `git status` and confirm that no local outputs or credentials are staged.
