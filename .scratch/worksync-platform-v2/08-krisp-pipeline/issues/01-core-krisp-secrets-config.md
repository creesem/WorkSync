# 01: `core`: Krisp secrets and machine config

**What to build:** The platform can resolve the Krisp API key and the Krisp machine
settings from `core`, so no other layer reads secrets and no key is ever committed. The
key resolves by precedence, a missing key fails loudly rather than inventing one, and the
Krisp window and inbox location are configurable with safe defaults. The committed config
example stays key-free.

**Blocked by:** None (can start immediately).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `core` resolves the Krisp API key with precedence `--api-key` > `KRISP_API_KEY`
      environment variable > the gitignored secrets file; a missing key returns no value
      and never invents one.
- [x] The gitignored secrets file loads a `krisp_api_key` entry; an absent or unreadable
      secrets file is tolerated (no key) and never raises for the whole app.
- [x] Machine config resolves `krisp_since_days` (default 14) and `krisp_inbox_path`
      (default runtime-relative), with no development-machine path baked in.
- [x] The committed config example and every tracked `config/*.json` carry no key; a
      secret-scan test asserts this.
- [x] Secret loading is owned solely by `core`; no other layer reads the secrets file.
