# -*- coding: utf-8 -*-
"""credential：SSO → OIDC → CPA JSON。"""

from .mint import mint_and_export
from .protocol_mint import ProtocolMintError, extract_sso_from_cookies, mint_with_sso_protocol
from .schema import DEFAULT_BASE_URL, build_cpa_xai_auth, credential_file_name
from .writer import write_cpa_xai_auth
from .probe import probe_models, probe_mini_response

__all__ = [
    "DEFAULT_BASE_URL",
    "ProtocolMintError",
    "build_cpa_xai_auth",
    "credential_file_name",
    "extract_sso_from_cookies",
    "mint_and_export",
    "mint_with_sso_protocol",
    "probe_mini_response",
    "probe_models",
    "write_cpa_xai_auth",
]
