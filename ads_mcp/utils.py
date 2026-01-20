#!/usr/bin/env python
# Copyright 2025 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Common utilities used by the MCP server."""
from __future__ import annotations

from typing import Any
import logging
import os
import importlib.resources
from collections.abc import Mapping

import proto
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.v21.services.services.google_ads_service import (
    GoogleAdsServiceClient,
)
from google.oauth2.credentials import Credentials

from ads_mcp.mcp_header_interceptor import MCPHeaderInterceptor

try:
    from google.protobuf.message import Message as ProtobufMessage
    from google.protobuf.json_format import MessageToDict
except Exception:  # pragma: no cover
    ProtobufMessage = None  # type: ignore
    MessageToDict = None  # type: ignore

# filename for generated field information used by search
_GAQL_FILENAME = "gaql_resources.json"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Read-only scope for Google Ads API.
_READ_ONLY_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


def _create_credentials() -> Credentials:
    """Returns OAuth credentials from environment variables."""
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Missing OAuth credentials. Set GOOGLE_ADS_CLIENT_ID, "
            "GOOGLE_ADS_CLIENT_SECRET, and GOOGLE_ADS_REFRESH_TOKEN."
        )

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[_READ_ONLY_ADS_SCOPE],
    )


def _get_developer_token() -> str:
    """Returns the developer token from the env var GOOGLE_ADS_DEVELOPER_TOKEN."""
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if dev_token is None:
        raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN environment variable not set.")
    return dev_token


def _get_login_customer_id() -> str | None:
    """Returns login customer id if set from env var GOOGLE_ADS_LOGIN_CUSTOMER_ID."""
    return os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")


def _get_googleads_client() -> GoogleAdsClient:
    return GoogleAdsClient(
        credentials=_create_credentials(),
        developer_token=_get_developer_token(),
        login_customer_id=_get_login_customer_id(),
    )


_googleads_client = _get_googleads_client()


def get_googleads_service(serviceName: str) -> GoogleAdsServiceClient:
    return _googleads_client.get_service(serviceName, interceptors=[MCPHeaderInterceptor()])


def get_googleads_type(typeName: str):
    return _googleads_client.get_type(typeName)


def _is_repeated_container(value: Any) -> bool:
    """
    Detect protobuf repeated containers, including upb-backed containers that
    sometimes don't present a normal __iter__ attribute.
    """
    if value is None:
        return False

    if isinstance(value, (str, bytes, bytearray)):
        return False

    if isinstance(value, Mapping):
        return False

    # proto.Message is handled separately (it serializes to dict via ListFields)
    if isinstance(value, proto.Message):
        return False

    t = type(value)
    mod = getattr(t, "__module__", "") or ""
    name = getattr(t, "__name__", "") or ""

    # Common C++ upb container types:
    # google._upb._message.RepeatedScalarContainer
    # google._upb._message.RepeatedCompositeContainer
    if mod.startswith("google._upb._message") and name.startswith("Repeated"):
        return True

    # Fallback: sequence protocol support
    # Many containers implement __len__ and __getitem__ even if __iter__ isn't obvious.
    if hasattr(value, "__iter__"):
        return True

    if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        return True

    return False


def _get_attr_with_reserved_fallback(obj: Any, name: str) -> Any:
    """
    Proto-plus sometimes exposes reserved proto field names with a trailing underscore
    (example: field 'type' becomes attribute 'type_').
    """
    if obj is None:
        raise AttributeError(name)

    try:
        return getattr(obj, name)
    except Exception:
        pass

    try:
        return getattr(obj, f"{name}_")
    except Exception:
        pass

    if name.endswith("_"):
        try:
            return getattr(obj, name[:-1])
        except Exception:
            pass

    raise AttributeError(name)


def get_nested_attr_safe(obj: Any, path: str) -> Any:
    """
    Safe nested attribute getter that supports proto-plus reserved-word suffixing.
    Example: 'ad_group_ad.ad.type' will successfully resolve to Python attr 'type_'.
    """
    cur = obj
    for part in path.split("."):
        cur = _get_attr_with_reserved_fallback(cur, part)
    return cur


def format_output_value(value: Any) -> Any:
    """
    Convert Google Ads / proto-plus / protobuf objects to JSON-serializable primitives.

    Special cases:
      - AdTextAsset -> return .text
      - repeated containers -> list (recursively converted)
      - proto.Enum -> its name
      - proto.Message / protobuf Message -> dict recursively
    """
    try:
        if value is None:
            return None

        # proto-plus enums
        if isinstance(value, proto.Enum):
            return value.name

        # RSA asset objects (headlines/descriptions list items)
        # Convert each AdTextAsset to plain text.
        tname = type(value).__name__
        if tname == "AdTextAsset" and hasattr(value, "text"):
            return getattr(value, "text")

        # Dict-like
        if isinstance(value, Mapping):
            return {str(k): format_output_value(v) for k, v in value.items()}

        # Protobuf repeated containers / list-like objects
        if _is_repeated_container(value):
            return [format_output_value(v) for v in value]

        # proto-plus messages
        if isinstance(value, proto.Message):
            pb = getattr(value, "_pb", None)
            if pb is not None and hasattr(pb, "ListFields"):
                out: dict[str, Any] = {}
                for field_desc, field_val in pb.ListFields():
                    out[field_desc.name] = format_output_value(field_val)
                return out

            # Fallback: best-effort scan
            out: dict[str, Any] = {}
            for attr in dir(value):
                if attr.startswith("_"):
                    continue
                try:
                    v = getattr(value, attr)
                except Exception:
                    continue
                if callable(v):
                    continue
                out[attr] = format_output_value(v)
            return out

        # protobuf messages (raw protobuf types)
        if (
            ProtobufMessage is not None
            and isinstance(value, ProtobufMessage)
            and MessageToDict is not None
        ):
            return MessageToDict(value, preserving_proto_field_name=True)

        # Basic scalars
        return value

    except Exception:
        try:
            logger.exception("format_output_value failed for %s", type(value))
        except Exception:
            pass
        return str(value)


def format_output_row(row: Any, attributes: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in attributes:
        try:
            raw_val = get_nested_attr_safe(row, attr)
            out[attr] = format_output_value(raw_val)
        except Exception:
            try:
                logger.exception("Failed to extract field '%s'", attr)
            except Exception:
                pass
            out[attr] = None
    return out


def get_gaql_resources_filepath():
    package_root = importlib.resources.files("ads_mcp")
    return package_root.joinpath(_GAQL_FILENAME)
