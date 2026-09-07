import hmac
import logging
import secrets
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import Flask, Response, jsonify, render_template, request, session

from auth_service.config import AuthSettings
from auth_service.repository import AuthRepository, ConflictError

F = TypeVar("F", bound=Callable[..., Response | tuple[Response, int]])


def create_app(settings: AuthSettings | None = None) -> Flask:
    config = settings or AuthSettings()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=config.cookie_secure,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    repository = AuthRepository(config.database_path)
    repository.bootstrap_admin(config.bootstrap_username, config.bootstrap_password)
    app.extensions["auth_repository"] = repository
    app.extensions["auth_settings"] = config

    def repo() -> AuthRepository:
        return cast(AuthRepository, app.extensions["auth_repository"])

    def json_body() -> dict[str, Any]:
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def admin_required(function: F) -> F:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            user_id = session.get("user_id")
            user = repo().get_user(str(user_id)) if user_id else None
            if not user or not user["active"] or not user["is_admin"]:
                return jsonify(error="admin_authentication_required"), 401
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                supplied = request.headers.get("X-CSRF-Token", "")
                expected = str(session.get("csrf_token", ""))
                if not expected or not hmac.compare_digest(supplied, expected):
                    return jsonify(error="invalid_csrf_token"), 403
            return function(*args, **kwargs)

        return cast(F, wrapped)

    @app.get("/admin")
    def index() -> str:
        return render_template("index.html")

    from auth_service.workspace import workspace

    app.register_blueprint(workspace)

    @app.after_request
    def prevent_private_caching(response: Response) -> Response:
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> Response:
        repo().list_departments()
        return jsonify(status="ok")

    @app.post("/api/login")
    def login() -> tuple[Response, int] | Response:
        data = json_body()
        user = repo().authenticate(str(data.get("username", "")), str(data.get("password", "")))
        if user is None:
            return jsonify(error="invalid_credentials"), 401
        token, expires_at = repo().issue_token(user["id"], config.token_ttl_hours)
        session.clear()
        session["user_id"] = user["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        response = jsonify(
            user=user,
            token=token,
            expires_at=expires_at,
            csrf_token=session.get("csrf_token"),
        )
        response.set_cookie(
            "rag_token",
            token,
            httponly=True,
            secure=config.cookie_secure,
            samesite="Strict",
            max_age=config.token_ttl_hours * 3600,
        )
        return response

    @app.post("/api/logout")
    def logout() -> Response:
        token = request.cookies.get("rag_token")
        if token:
            repo().revoke_token(token)
        session.clear()
        response = jsonify(status="ok")
        response.delete_cookie("rag_token")
        return response

    @app.get("/api/me")
    @admin_required
    def me() -> Response:
        return jsonify(
            user=repo().get_user(str(session["user_id"])), csrf_token=session["csrf_token"]
        )

    @app.post("/api/introspect")
    def introspect() -> tuple[Response, int] | Response:
        supplied_secret = request.headers.get("X-Auth-Service-Secret", "")
        if not hmac.compare_digest(supplied_secret, config.service_secret):
            return jsonify(error="invalid_service_credentials"), 401
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return jsonify(active=False), 401
        principal = repo().introspect(token)
        if principal is None:
            return jsonify(active=False), 401
        return jsonify(active=True, principal=principal)

    @app.get("/api/admin/users")
    @admin_required
    def list_users() -> Response:
        return jsonify(users=repo().list_users())

    @app.post("/api/admin/users")
    @admin_required
    def create_user() -> tuple[Response, int]:
        return jsonify(user=repo().create_user(json_body())), 201

    @app.put("/api/admin/users/<user_id>")
    @admin_required
    def update_user(user_id: str) -> Response:
        return jsonify(user=repo().update_user(user_id, json_body()))

    @app.post("/api/admin/users/<user_id>/token")
    @admin_required
    def issue_user_token(user_id: str) -> Response:
        token, expires_at = repo().issue_token(user_id, config.token_ttl_hours)
        return jsonify(token=token, expires_at=expires_at)

    @app.post("/api/admin/users/<user_id>/revoke-tokens")
    @admin_required
    def revoke_tokens(user_id: str) -> Response:
        return jsonify(revoked=repo().revoke_user_tokens(user_id))

    @app.get("/api/admin/departments")
    @admin_required
    def list_departments() -> Response:
        return jsonify(departments=repo().list_departments())

    @app.post("/api/admin/departments")
    @admin_required
    def create_department() -> tuple[Response, int]:
        return jsonify(department=repo().create_department(json_body())), 201

    @app.delete("/api/admin/departments/<identifier>")
    @admin_required
    def delete_department(identifier: str) -> Response:
        repo().delete_department(identifier)
        return jsonify(status="deleted")

    @app.errorhandler(ValueError)
    def invalid_input(error: ValueError) -> tuple[Response, int]:
        return jsonify(error="invalid_input", message=str(error)), 422

    @app.errorhandler(ConflictError)
    def conflict(error: ConflictError) -> tuple[Response, int]:
        return jsonify(error="conflict", message=str(error)), 409

    @app.errorhandler(KeyError)
    def not_found(error: KeyError) -> tuple[Response, int]:
        return jsonify(error="not_found"), 404

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> tuple[Response, int]:
        logging.getLogger("auth.audit").exception("auth_request_failed", exc_info=error)
        return jsonify(error="internal_error"), 500

    return app
