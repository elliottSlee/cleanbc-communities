"""Build an SSL context that trusts what macOS trusts.

This python.org interpreter ships with no configured CA file
(`ssl.get_default_verify_paths().cafile is None`), so on a network behind a
TLS-inspecting proxy every HTTPS request fails with
CERTIFICATE_VERIFY_FAILED / "self-signed certificate in certificate chain"
even though curl succeeds - curl reads the macOS keychain.

Rather than disabling verification, export the keychain roots (including any
corporate root) to a PEM bundle once and verify against that.
"""

import os
import ssl
import subprocess
import sys

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "data", "macos-ca-bundle.pem")

KEYCHAINS = [
    "/System/Library/Keychains/SystemRootCertificates.keychain",
    "/Library/Keychains/System.keychain",
]


def build_bundle(path=BUNDLE, verbose=True):
    """Export macOS trust roots to a PEM bundle. Returns the path."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    chunks = []
    for kc in KEYCHAINS:
        if not os.path.exists(kc):
            continue
        try:
            out = subprocess.run(
                ["security", "find-certificate", "-a", "-p", kc],
                capture_output=True, text=True, timeout=60, check=True).stdout
            if out.strip():
                chunks.append(out)
        except (subprocess.SubprocessError, OSError) as e:
            if verbose:
                print(f"  warn: could not read {kc}: {e}", file=sys.stderr)
    # User keychain may hold the proxy root on a managed laptop.
    try:
        out = subprocess.run(["security", "find-certificate", "-a", "-p"],
                             capture_output=True, text=True, timeout=60).stdout
        if out.strip():
            chunks.append(out)
    except (subprocess.SubprocessError, OSError):
        pass

    if not chunks:
        raise RuntimeError("no certificates exported from the macOS keychain")

    # De-duplicate, keeping only well-formed PEM blocks.
    seen, blocks = set(), []
    for chunk in chunks:
        for part in chunk.split("-----END CERTIFICATE-----"):
            if "-----BEGIN CERTIFICATE-----" not in part:
                continue
            body = part[part.index("-----BEGIN CERTIFICATE-----"):]
            pem = body.strip() + "\n-----END CERTIFICATE-----\n"
            if pem not in seen:
                seen.add(pem)
                blocks.append(pem)
    with open(path, "w", encoding="ascii") as f:
        f.write("".join(blocks))
    if verbose:
        print(f"  wrote {len(blocks)} CA certificates -> {path}", file=sys.stderr)
    return path


def make_context(verbose=False):
    """Verifying SSLContext that works on this machine.

    Order of preference: SSL_CERT_FILE, an existing exported bundle, the
    interpreter's own store, then a freshly exported bundle.
    """
    env = os.environ.get("SSL_CERT_FILE")
    if env and os.path.exists(env):
        return ssl.create_default_context(cafile=env)

    bundle = os.path.abspath(BUNDLE)
    if os.path.exists(bundle) and os.path.getsize(bundle) > 0:
        return ssl.create_default_context(cafile=bundle)

    if ssl.get_default_verify_paths().cafile:
        return ssl.create_default_context()

    if sys.platform == "darwin":
        return ssl.create_default_context(cafile=build_bundle(verbose=verbose))
    return ssl.create_default_context()


if __name__ == "__main__":
    build_bundle()
