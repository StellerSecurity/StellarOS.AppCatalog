"""Pinned, independently approved bootstrap root for the StellarOS app catalog."""
import hashlib
from pathlib import Path
from tuf.api.metadata import Metadata

ROOT_SHA256 = "5b03c1dcb252c0df6a4d85675986ba9903ea16a7fbd5df66a0d400337b479b95"
ROOT_PATH = Path(__file__).resolve().parents[1] / "trust/root.json"


def require_trusted_root(path=ROOT_PATH):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != ROOT_SHA256:
        raise ValueError("Catalog bootstrap root does not match the approved SHA-256 pin")
    root = Metadata.from_bytes(data)
    root.signed.verify_delegate("root", root.signed_bytes, root.signatures)
    if root.signed.is_expired():
        raise ValueError("Catalog bootstrap root has expired")
    return data
