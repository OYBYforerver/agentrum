"""Editor support: JSON Schema for agentrum.yaml manifests.

Served unauthenticated at /v1/schema/manifest.json — it is pure shape
information, and editors (yaml-language-server via the `$schema` key) need
to fetch it without registry credentials.
"""

from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agentrum.schemas.specs import SPEC_MODELS
from agentrum.services.resource_service import NAME_RE, TAG_RE

router = APIRouter()

# Manifests can also carry Secret documents (see `agentrum export`); their
# spec shape is defined by the secrets service, not a pydantic model.
_SECRET_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "data": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["data"],
}


@lru_cache(maxsize=1)
def build_manifest_schema() -> dict:
    kind_to_ref = {kind: f"#/$defs/{kind}Spec" for kind in SPEC_MODELS}
    kind_selectors = [
        {
            "if": {"properties": {"kind": {"const": kind}}, "required": ["kind"]},
            "then": {"properties": {"spec": {"$ref": ref}}},
        }
        for kind, ref in kind_to_ref.items()
    ]
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "agentrum-manifest",
        "title": "Agentrum manifest (agentrum.yaml)",
        "type": "object",
        "properties": {
            "kind": {"enum": [*SPEC_MODELS, "Secret"]},
            "metadata": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "pattern": NAME_RE.pattern},
                    "namespace": {"type": "string"},
                    "labels": {"type": "object"},
                },
            },
            "spec": {"type": "object"},
            "tag": {"type": ["string", "null"], "pattern": TAG_RE.pattern},
            "description": {"type": ["string", "null"]},
            "labels": {"type": "object"},
            "visibility": {"enum": ["internal", "restricted"]},
            "change_notes": {"type": ["string", "null"]},
        },
        "required": ["kind", "spec"],
        "allOf": kind_selectors,
        "$defs": {
            **{f"{kind}Spec": model.model_json_schema(ref_template="#/$defs/{model}") for kind, model in SPEC_MODELS.items()},
            "SecretSpec": _SECRET_SPEC_SCHEMA,
        },
    }


@router.get("/v1/schema/manifest.json", include_in_schema=False)
async def manifest_schema() -> JSONResponse:
    return JSONResponse(build_manifest_schema())
