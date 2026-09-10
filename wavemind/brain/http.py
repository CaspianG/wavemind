"""Strict local Brain JSON boundary and browser sessions (CORS disabled)."""

import base64
import binascii
import json
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .models import BrainError

Text = Annotated[str, Field(min_length=1, max_length=256)]
Ids = Annotated[list[Text], Field(max_length=100)]
Page = Annotated[int, Field(ge=1, le=100)]
MAX_BODY = 1024 * 1024
MAX_UPLOAD_BODY = 70 * 1024 * 1024
COOKIE = "brain_session"


class Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, str_max_length=16384
    )


class Empty(Strict):
    pass


class CreateBrain(Strict):
    title: Annotated[str, Field(min_length=1, max_length=500)]
    mode: Literal["personal", "team"] = "personal"


class Login(Strict):
    secret: Annotated[str, Field(min_length=32, max_length=256)]


class UploadFile(Strict):
    name: Annotated[str, Field(min_length=1, max_length=500)]
    content_base64: Annotated[str, Field(max_length=13981016)]
    source_id: Text | None = None


class Preview(Strict):
    files: Annotated[list[UploadFile], Field(min_length=1, max_length=20)]
    new_source_readers: Ids | None = None


class Commit(Strict):
    preview_id: Text
    accepted_ids: Annotated[list[Text], Field(max_length=20)]


class Claims(Strict):
    claims: Annotated[list[dict], Field(min_length=1, max_length=100)]


class ReviewClaims(Strict):
    claim_ids: Ids
    action: Literal["approve", "reject", "recheck"]


class ReviewRecords(Strict):
    record_type: Literal["entity", "relation"]
    record_ids: Ids
    action: Literal["approve", "reject", "recheck"]


class Entity(Strict):
    kind: Literal["person", "organization", "project", "client", "artifact"]
    name: Annotated[str, Field(min_length=1, max_length=500)]
    citation_ids: Ids


class Relation(Strict):
    relation: dict


class ContextRequest(Strict):
    question: Annotated[str, Field(min_length=1, max_length=8192)]
    moment: float | None = None
    project_id: Text | None = None
    max_bytes: Annotated[int, Field(ge=512, le=262144)] = 16384


class Packet(Strict):
    packet_id: Text


class Action(Packet):
    run_id: Text
    action: Annotated[str, Field(min_length=1, max_length=8192)]


class Outcome(Strict):
    receipt_id: Text
    outcome: dict


class Verify(Strict):
    success: bool
    evidence_citation_ids: Ids
    note: Annotated[str, Field(max_length=8192)] = ""


class VerifyWith(Strict):
    verifier_id: Annotated[str, Field(min_length=1, max_length=128)]
    evidence_citation_ids: Ids
    note: Annotated[str, Field(max_length=8192)] = ""


class ReviewExperience(Strict):
    limit: Page = 100
    outcome_cursor: Text | None = None
    procedure_cursor: Text | None = None


class ManagedSources(Strict):
    limit: Page = 100
    cursor: Text | None = None


class SourceCitations(Strict):
    limit: Page = 50
    cursor: Text | None = None
    versions: Literal["current", "all"] = "current"


class RestoredSource(Strict):
    limit: Page = 100
    version_cursor: Text | None = None
    citation_cursor: Text | None = None


class Admit(Strict):
    source_ids: Annotated[Ids, Field(min_length=1)]


class Member(Strict):
    identity: Text
    role: Literal["owner", "editor", "reader"] | None


class SourceAccess(Strict):
    source_id: Text
    readers: Ids | None


class AgentGrant(Strict):
    brain_ids: Annotated[Ids, Field(min_length=1)]
    operations: Annotated[
        list[Literal["read", "import", "propose", "record_outcome", "export"]],
        Field(min_length=1, max_length=5),
    ]
    label: Annotated[str, Field(min_length=1, max_length=128)]
    source_grants: dict[Text, Ids] | None = None
    grant_selected_sources: bool = False


# Fixed data operations only; transport never exposes verifier registration,
# local paths, callbacks, SQL, arbitrary commands or service internals.
OPERATIONS = {
    "create_brain": CreateBrain,
    "list_brains": Empty,
    "preview_import": Preview,
    "commit_import": Commit,
    "list_sources": Empty,
    "list_source_citations": SourceCitations,
    "propose_claims": Claims,
    "review_claims": ReviewClaims,
    "review_records": ReviewRecords,
    "recheck_dependencies": Empty,
    "create_entity": Entity,
    "add_relation": Relation,
    "review_memory": Empty,
    "build_context": ContextRequest,
    "validate_packet": Packet,
    "begin_action": Action,
    "record_outcome": Outcome,
    "verify_outcome": Verify,
    "verify_outcome_with": VerifyWith,
    "review_experience": ReviewExperience,
    "export_brain": Empty,
    "list_managed_sources": ManagedSources,
    "review_restored_source": RestoredSource,
    "admit_restored_sources": Admit,
    "set_member": Member,
    "set_source_access": SourceAccess,
    "read_citation": Empty,
    "change_source": Empty,
}


def validated(model, data):
    try:
        return model.model_validate(data).model_dump()
    except (ValidationError, ValueError, TypeError):
        raise BrainError("invalid_input", "Invalid request fields.") from None


def invoke(service, principal, operation, data, **path):
    fields = validated(OPERATIONS[operation], data)
    if operation == "preview_import":
        files, total = [], 0
        for file in fields["files"]:
            try:
                content = base64.b64decode(file["content_base64"], validate=True)
            except (ValueError, binascii.Error):
                raise BrainError("invalid_input", "Invalid upload encoding.") from None
            total += len(content)
            if len(content) > 10 * 1024 * 1024 or total > 50 * 1024 * 1024:
                raise BrainError("body_too_large", "Upload exceeds import limits.")
            item = {"name": file["name"], "content": content}
            if file["source_id"] is not None:
                item["source_id"] = file["source_id"]
            files.append(item)
        fields["files"] = files
    result = getattr(service, operation)(principal=principal, **path, **fields)
    return {"status": "ok"} if result is None else result


def _json(raw):
    def pairs(items):
        data = {}
        for key, value in items:
            if key in data:
                raise ValueError()
            data[key] = value
        return data

    def invalid(_):
        raise ValueError()

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(value, dict):
            raise ValueError()
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise BrainError("invalid_input", "Expected a strict JSON object.") from None


def error_response(error):
    status = {
        "unauthenticated": 401,
        "csrf_required": 403,
        "forbidden_origin": 403,
        "not_found": 404,
        "body_too_large": 413,
    }.get(error.code, 422)
    return JSONResponse(
        {"error": {"code": error.code, "message": error.message}}, status_code=status
    )


class BrainBoundary:
    """Validate raw Host/Origin and body limits before JSON parsing."""

    def __init__(self, app, *, hosts):
        self.app, self.hosts = app, frozenset(hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/brain"):
            return await self.app(scope, receive, send)
        headers = {}

        async def private_send(message):
            if message["type"] == "http.response.start":
                privacy = {
                    b"cache-control": b"no-store",
                    b"referrer-policy": b"no-referrer",
                    b"x-content-type-options": b"nosniff",
                    b"content-security-policy": (
                        b"default-src 'none'; script-src 'self'; style-src 'self'; "
                        b"connect-src 'self'; img-src 'self'; base-uri 'none'; "
                        b"form-action 'self'; frame-ancestors 'none'"
                    ),
                }
                message["headers"] = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in privacy
                ] + list(privacy.items())
            await send(message)

        try:
            for key, value in scope["headers"]:
                if key in headers and key in (
                    b"host",
                    b"authorization",
                    b"origin",
                    b"cookie",
                    b"content-length",
                ):
                    raise BrainError("invalid_input", "Ambiguous request headers.")
                headers[key] = value.decode("latin-1")
            host = headers.get(b"host", "")
            origin = headers.get(b"origin")
            if host not in self.hosts or (
                origin is not None and origin != scope["scheme"] + "://" + host
            ):
                raise BrainError(
                    "forbidden_origin", "Local Host and same Origin required."
                )
            maximum = (
                MAX_UPLOAD_BODY
                if scope["path"].endswith("/sources/preview")
                else MAX_BODY
            )
            length = headers.get(b"content-length")
            if length is not None and (not length.isdecimal() or int(length) > maximum):
                raise BrainError("body_too_large", "Request body exceeds limits.")
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > maximum:
                    raise BrainError("body_too_large", "Request body exceeds limits.")
                if not message.get("more_body", False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, bounded_receive, private_send)
        except BrainError as error:
            await error_response(error)(scope, receive, private_send)


ROUTES = [
    ("POST", "/brains", "create_brain"),
    ("GET", "/brains", "list_brains"),
    ("POST", "/{brain_id}/sources/preview", "preview_import"),
    ("POST", "/{brain_id}/sources/commit", "commit_import"),
    ("GET", "/{brain_id}/sources", "list_sources"),
    ("GET", "/{brain_id}/sources/{source_id}/citations", "list_source_citations"),
    ("GET", "/{brain_id}/sources/managed", "list_managed_sources"),
    ("POST", "/{brain_id}/sources/admit", "admit_restored_sources"),
    ("GET", "/{brain_id}/sources/{source_id}/review", "review_restored_source"),
    ("POST", "/{brain_id}/sources/{source_id}/{action}", "change_source"),
    ("POST", "/{brain_id}/claims/propose", "propose_claims"),
    ("POST", "/{brain_id}/claims/review", "review_claims"),
    ("POST", "/{brain_id}/entities", "create_entity"),
    ("POST", "/{brain_id}/relations", "add_relation"),
    ("GET", "/{brain_id}/memory", "review_memory"),
    ("POST", "/{brain_id}/memory/review", "review_records"),
    ("POST", "/{brain_id}/dependencies/recheck", "recheck_dependencies"),
    ("POST", "/{brain_id}/context", "build_context"),
    ("POST", "/{brain_id}/context/validate", "validate_packet"),
    ("GET", "/{brain_id}/citations/{citation_id}", "read_citation"),
    ("POST", "/{brain_id}/actions", "begin_action"),
    ("POST", "/{brain_id}/outcomes", "record_outcome"),
    ("POST", "/{brain_id}/outcomes/{outcome_id}/verify", "verify_outcome"),
    ("POST", "/{brain_id}/outcomes/{outcome_id}/verify-with", "verify_outcome_with"),
    ("GET", "/{brain_id}/experience", "review_experience"),
    ("GET", "/{brain_id}/export", "export_brain"),
    ("POST", "/{brain_id}/access/members", "set_member"),
    ("POST", "/{brain_id}/access/sources", "set_source_access"),
]


def mount_brain(app: FastAPI, service, auth) -> None:
    if service is None or auth is None:
        raise ValueError("Brain service and auth must be configured together.")
    hosts = getattr(
        auth, "allowed_hosts", ("127.0.0.1:8000", "localhost:8000", "[::1]:8000")
    )
    app.add_middleware(BrainBoundary, hosts=hosts)

    async def owner_page():
        return Response(
            files("wavemind.brain").joinpath("ui", "index.html").read_bytes(),
            media_type="text/html",
        )

    app.add_api_route("/brain", owner_page, methods=["GET"], include_in_schema=False)
    app.add_api_route("/brain/", owner_page, methods=["GET"], include_in_schema=False)

    @app.get("/brain/favicon.ico", include_in_schema=False)
    async def owner_icon():
        return Response(status_code=204)

    @app.get("/brain/ui/{asset}", include_in_schema=False)
    async def owner_asset(asset: str):
        media = {
            "app.js": "text/javascript",
            "ui.js": "text/javascript",
            "panels.js": "text/javascript",
            "style.css": "text/css",
        }
        if asset not in media:
            raise BrainError("not_found", "Resource not found.")
        return Response(
            files("wavemind.brain").joinpath("ui", asset).read_bytes(),
            media_type=media[asset],
        )

    @app.exception_handler(BrainError)
    async def handle_error(request, error):
        return error_response(error)

    def principal(request):
        authorization = request.headers.get("authorization")
        if authorization is not None:
            if not authorization.startswith("Bearer ") or " " in authorization[7:]:
                raise BrainError("unauthenticated", "Authentication required.")
            return auth.authenticate(authorization[7:])
        return auth.authenticate_session(
            request.cookies.get(COOKIE, ""),
            csrf=request.headers.get("x-brain-csrf"),
            mutation=request.method != "GET",
        )

    async def body(request):
        if request.query_params:
            raise BrainError("invalid_input", "Query fields are not accepted here.")
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise BrainError("invalid_input", "JSON content type required.")
        return _json(await request.body())

    @app.post("/brain/api/login")
    async def login(request: Request):
        data = validated(Login, await body(request))
        session, csrf = await run_in_threadpool(auth.login, data["secret"])
        response = JSONResponse({"csrf_token": csrf, "expires_in": 3600})
        response.set_cookie(
            COOKIE,
            session,
            httponly=True,
            samesite="strict",
            path="/brain",
            max_age=3600,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/brain/api/logout")
    async def logout(request: Request):
        await run_in_threadpool(principal, request)
        validated(Empty, await body(request))
        if request.cookies.get(COOKIE):
            await run_in_threadpool(auth.logout, request.cookies[COOKIE])
        response = JSONResponse({"status": "signed_out"})
        response.delete_cookie(COOKIE, path="/brain")
        return response

    @app.get("/brain/api/session")
    async def session(request: Request):
        if request.query_params:
            raise BrainError("invalid_input", "Query fields are not accepted here.")
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site is not None and fetch_site != "same-origin":
            raise BrainError(
                "forbidden_origin", "Same-origin session bootstrap required."
            )
        return await run_in_threadpool(
            auth.session_info, request.cookies.get(COOKIE, "")
        )

    @app.post("/brain/api/credentials/agents")
    async def issue(request: Request):
        who = await run_in_threadpool(principal, request)
        data = validated(AgentGrant, await body(request))
        return await run_in_threadpool(auth.issue_agent, principal=who, **data)

    @app.get("/brain/api/credentials")
    async def credentials(request: Request):
        validated(Empty, dict(request.query_params))
        return await run_in_threadpool(
            auth.list_tokens, principal=await run_in_threadpool(principal, request)
        )

    @app.post("/brain/api/credentials/{token_id}/revoke")
    async def revoke(token_id: str, request: Request):
        who = await run_in_threadpool(principal, request)
        validated(Empty, await body(request))
        await run_in_threadpool(auth.revoke_token, principal=who, token_id=token_id)
        return {
            "status": "revoked",
            "membership_cleanup": "best_effort",
            "historical_acl_identities_retained": True,
        }

    def endpoint(operation):
        async def call(request: Request):
            who = await run_in_threadpool(principal, request)
            if request.method == "GET":
                if len(request.query_params) != len(request.query_params.multi_items()):
                    raise BrainError("invalid_input", "Duplicate query fields.")
                data = dict(request.query_params)
                if "limit" in data and data["limit"].isdecimal():
                    data["limit"] = int(data["limit"])
            else:
                data = await body(request)
            return await run_in_threadpool(
                invoke, service, who, operation, data, **request.path_params
            )

        return call

    for method, path, operation in ROUTES:
        app.add_api_route(
            "/brain/api" + path,
            endpoint(operation),
            methods=[method],
            name="brain_" + operation,
        )
    from .maintenance import BrainMaintenance

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def brain_lifespan(application):
        maintenance = BrainMaintenance(service)
        try:
            async with previous_lifespan(application) as state:
                await maintenance.start()
                try:
                    yield state
                finally:
                    await maintenance.stop()
        finally:
            service.close()
            auth.close()

    app.router.lifespan_context = brain_lifespan
