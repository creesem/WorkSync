"""Vault migrations: detection and reviewable repair of the authoritative vault.

A migration reads the vault through the single inventory scanner and applies its
writes through the single safety gateway. It never adds a read parser and never
imports a write helper directly.
"""
