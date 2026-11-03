"""PII Vault & Compliance Module — Task 5/5 reference implementation."""
from .audit import AuditLog, AuditEntry
from .kms import KMSAdapter, LocalFileKMS, VaultKMS, load_kms_from_env
from .masking import Masker, MaskResult, id_checksum_valid, luhn_valid
from .rbac import AccessDenied, Principal, ROLES, principal_from_headers
from .retention import DeletionRecord, Record, RetentionPolicy
from .vault import PIIVault, SealedField

__all__ = [
    "AuditLog", "AuditEntry", "KMSAdapter", "LocalFileKMS", "VaultKMS", "load_kms_from_env",
    "Masker", "MaskResult", "id_checksum_valid", "luhn_valid",
    "AccessDenied", "Principal", "ROLES", "principal_from_headers",
    "DeletionRecord", "Record", "RetentionPolicy", "PIIVault", "SealedField",
]
__version__ = "1.0.0"
