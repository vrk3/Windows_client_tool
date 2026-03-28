import datetime
import ssl
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CertInfo:
    subject_cn: str
    subject_full: str
    issuer: str
    expiry: datetime.datetime
    thumbprint: str        # hex string
    key_usage: str
    has_private_key: bool
    raw_der: bytes         # raw certificate bytes for export
    days_until_expiry: int
    flag: str              # "" | "🔴 Expired" | "🟠 Expiring Soon"


def _parse_dn(dn: str, field: str = "CN") -> str:
    """Extract field from a DN string like 'CN=foo, O=bar'."""
    for part in dn.split(","):
        part = part.strip()
        if part.upper().startswith(field + "="):
            return part[len(field) + 1:].strip()
    return dn  # fallback to full DN


def fetch_certs(store_name: str, store_location: str = "user") -> List[CertInfo]:
    """
    Load certificates from a Windows certificate store.
    store_name: "MY", "ROOT", "CA", "TrustedPublisher", etc.
    store_location: "user" or "machine"
    """
    import wincertstore
    certs = []
    today = datetime.datetime.utcnow()
    thirty_days = datetime.timedelta(days=30)

    try:
        if store_location == "machine":
            store = wincertstore.CertSystemStore(store_name, wincertstore.CERT_SYSTEM_STORE_LOCAL_MACHINE)
        else:
            store = wincertstore.CertSystemStore(store_name)
        for cert in store.itercerts(usage=None):
            try:
                der_bytes = cert.get_der()
                pem = ssl.DER_cert_to_PEM_cert(der_bytes)
                info = _parse_cert(der_bytes, pem, today, thirty_days)
                if info:
                    certs.append(info)
            except Exception:
                continue
        store.close()
    except Exception:
        pass
    return certs


def _parse_cert(der_bytes: bytes, pem: str, today: datetime.datetime,
                thirty_days: datetime.timedelta) -> Optional[CertInfo]:
    """Parse certificate. Try cryptography library first, fallback to ssl."""
    try:
        from cryptography import x509 as cx509
        from cryptography.hazmat.primitives import hashes
        from cryptography.x509.oid import NameOID, ExtensionOID
        import binascii

        cert = cx509.load_pem_x509_certificate(pem.encode())

        # Subject CN
        try:
            cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        except (IndexError, Exception):
            cn = str(cert.subject)

        # Issuer
        try:
            issuer = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        except (IndexError, Exception):
            issuer = str(cert.issuer)

        # Expiry — handle timezone-aware vs naive
        if hasattr(cert, 'not_valid_after_utc'):
            expiry = cert.not_valid_after_utc
        else:
            expiry = cert.not_valid_after
        if hasattr(expiry, 'tzinfo') and expiry.tzinfo is not None:
            expiry_naive = expiry.replace(tzinfo=None)
        else:
            expiry_naive = expiry

        # Thumbprint (SHA1)
        thumbprint = binascii.hexlify(cert.fingerprint(hashes.SHA1())).decode().upper()

        # Key usage
        try:
            ku_ext = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
            ku = ku_ext.value
            usages = []
            if ku.digital_signature:
                usages.append("Digital Signature")
            try:
                if ku.key_encipherment:
                    usages.append("Key Encipherment")
            except Exception:
                pass
            try:
                if ku.data_encipherment:
                    usages.append("Data Encipherment")
            except Exception:
                pass
            key_usage = ", ".join(usages) if usages else "N/A"
        except Exception:
            key_usage = "N/A"

        days = (expiry_naive - today).days
        flag = ""
        if days < 0:
            flag = "🔴 Expired"
        elif days <= 30:
            flag = "🟠 Expiring Soon"

        return CertInfo(
            subject_cn=cn,
            subject_full=str(cert.subject),
            issuer=issuer,
            expiry=expiry_naive,
            thumbprint=thumbprint,
            key_usage=key_usage,
            has_private_key=False,  # wincertstore doesn't expose this easily
            raw_der=der_bytes,
            days_until_expiry=days,
            flag=flag,
        )
    except ImportError:
        pass
    except Exception:
        return None

    # Fallback: minimal info when cryptography library not available
    try:
        return CertInfo(
            subject_cn="(parse error)",
            subject_full="",
            issuer="",
            expiry=datetime.datetime.min,
            thumbprint="",
            key_usage="",
            has_private_key=False,
            raw_der=der_bytes,
            days_until_expiry=-1,
            flag="",
        )
    except Exception:
        return None
