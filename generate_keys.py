"""
generate_keys.py
------------------------------------------------------------------
Generates an RSA 2048 key-pair for Snowflake key-pair authentication.

WHY key-pair auth?
  The Snowpipe Streaming SDK does NOT support password auth. Key-pair
  auth is the enterprise standard for machine/service identities: the
  PRIVATE key stays on the client, and only the PUBLIC key is registered
  on the Snowflake user. Even if Snowflake's side is compromised, the
  attacker never gets your private key. This is the same pattern you'd
  defend in a KPMG security-controls review.

WHY this Python script instead of openssl?
  openssl isn't reliably installed on Windows. The `cryptography`
  library is cross-platform and produces the exact same unencrypted
  PKCS#8 format the SDK expects.

Output:
  keys/rsa_key.p8   -> PRIVATE key (PKCS#8, unencrypted). NEVER commit this.
  keys/rsa_key.pub  -> PUBLIC key (PEM).
  Prints the public key body (no headers) for the ALTER USER command.
"""

import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS_DIR = "keys"
os.makedirs(KEYS_DIR, exist_ok=True)

# 1. Generate a 2048-bit RSA private key.
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

# 2. Serialize the PRIVATE key as unencrypted PKCS#8 PEM (what the SDK reads).
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)

# 3. Serialize the matching PUBLIC key.
public_pem = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

priv_path = os.path.join(KEYS_DIR, "rsa_key.p8")
pub_path = os.path.join(KEYS_DIR, "rsa_key.pub")

with open(priv_path, "wb") as f:
    f.write(private_pem)
with open(pub_path, "wb") as f:
    f.write(public_pem)

# 4. Print the public key BODY (strip the -----BEGIN/END----- header lines
#    and newlines) -- this is exactly what ALTER USER ... SET RSA_PUBLIC_KEY
#    expects.
public_key_body = "".join(
    line for line in public_pem.decode().splitlines() if not line.startswith("-----")
)

print(f"Private key written to: {priv_path}")
print(f"Public key written to : {pub_path}")
print("\n" + "=" * 70)
print("Copy the line below into the ALTER USER command in Snowsight:")
print("=" * 70)
print(public_key_body)
