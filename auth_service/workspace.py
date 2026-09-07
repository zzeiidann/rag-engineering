"""Same-origin browser gateway. Only server-validated cookies become RAG bearer tokens."""

import hmac
import secrets
from threading import BoundedSemaphore

import httpx
from flask import Blueprint, Response, current_app, jsonify, render_template, request, session

workspace = Blueprint("workspace", __name__)
# Keep auth threads available for RAG API introspection during generation.
# Compose runs four threads per worker; at most two may wait on the RAG API.
upstream_slots = BoundedSemaphore(2)


@workspace.get("/")
def home() -> str:
    return render_template("workspace.html")


@workspace.after_request
def privacy_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def identity() -> tuple[dict | None, str | None]:
    token = request.cookies.get("rag_token")
    if not token:
        return None, None
    repository = current_app.extensions["auth_repository"]
    principal = repository.introspect(token)
    if not principal:
        return None, token
    return repository.get_user(principal["user_id"]), token


@workspace.get("/api/workspace/session")
def current_identity() -> Response | tuple[Response, int]:
    user, token = identity()
    if token and not user:
        return jsonify(error="session_expired"), 401
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(user=user, csrf_token=session["csrf_token"])


@workspace.get("/api/workspace/documents")
@workspace.post("/api/workspace/query")
def proxy() -> Response | tuple[Response, int]:
    user, token = identity()
    if token and not user:
        return jsonify(error="session_expired"), 401
    data = None
    path = "/documents"
    if request.method == "POST":
        csrf = session.get("csrf_token", "")
        if not csrf or not hmac.compare_digest(csrf, request.headers.get("X-CSRF-Token", "")):
            return jsonify(error="invalid_csrf_token"), 403
        body = request.get_json(silent=True)
        if (
            not isinstance(body, dict)
            or set(body) != {"query"}
            or not isinstance(body["query"], str)
            or not 1 <= len(body["query"].strip()) <= 4000
        ):
            return jsonify(error="invalid_query"), 422
        data, path = {"query": body["query"].strip()}, "/query"
    config = current_app.extensions["auth_settings"]
    # Never forward a caller-supplied Authorization header or principal body.
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if not upstream_slots.acquire(blocking=False):
        return jsonify(error="workspace_busy"), 429
    try:
        upstream = httpx.request(
            request.method, config.rag_api_url + path, headers=headers, json=data, timeout=75
        )
        if upstream.status_code != 200:
            status = upstream.status_code if upstream.status_code in {401, 403, 422, 429} else 503
            return jsonify(error="query_unavailable"), status
        return jsonify(upstream.json())
    except (httpx.HTTPError, ValueError):
        return jsonify(error="query_unavailable"), 503
    finally:
        upstream_slots.release()
