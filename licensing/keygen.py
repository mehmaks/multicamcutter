"""
resolve-toolkit — Ed25519 Keypair Generator
============================================
Einmalig ausführen um ein Schlüsselpaar zu erzeugen.

Output:
  licensing/license_private.key  — Private Key (NIE ins Repo, in .gitignore)
  Konsole                        — Public Key Base64 → in license.py eintragen

Danach keysign.py nutzen um Lizenzdateien für Betatester zu signieren.
"""

import base64
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)

_DIR = Path(__file__).parent
_KEY_FILE = _DIR / "license_private.key"

if _KEY_FILE.exists():
    print(f"WARNUNG: {_KEY_FILE} existiert bereits.")
    print("Wenn du einen neuen Key generierst, werden alle bestehenden Lizenzen ungültig!")
    confirm = input("Trotzdem neu generieren? (ja/nein): ").strip().lower()
    if confirm != "ja":
        print("Abgebrochen.")
        exit(0)

key = Ed25519PrivateKey.generate()
priv_bytes = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
pub_bytes  = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

priv_b64 = base64.b64encode(priv_bytes).decode()
pub_b64  = base64.b64encode(pub_bytes).decode()

_KEY_FILE.write_text(priv_b64 + "\n")

print(f"\nPrivate Key gespeichert in: {_KEY_FILE}  ← GEHEIM HALTEN\n")
print("Public Key (in license.py bei _PUBLIC_KEY_B64 eintragen):")
print(f"\n  {pub_b64}\n")
