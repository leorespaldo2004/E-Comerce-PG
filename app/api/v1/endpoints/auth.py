"""Google OAuth2 endpoints (minimal example).

Notes:
- Requires `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI` set in environment or .env.
- This is a simple example for local development and demonstration.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
import os
import httpx
import certifi
import requests 
from datetime import datetime, timedelta

from app.db.mongo import get_or_create_user_from_info, get_user_by_dbid, create_session, create_session_with_meta, delete_session, get_session
from bson.objectid import ObjectId

from dotenv import load_dotenv

load_dotenv()

def _get_secret(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Environment variable {name} is required")
    return val

router = APIRouter()


def _get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        # Provide a helpful error explaining how to fix the missing variable
        raise RuntimeError(
            f"Environment variable {name} is required.\n"
            "Create a `.env` file at the project root or export the variable in your shell.\n"
            "You can copy `.env.example` to `.env` and fill the values.\n"
            "Example (in project root):\n"
            "  cp .env.example .env   # then edit .env and restart the server\n"
            "Or in PowerShell temporarily: $env:GOOGLE_REDIRECT_URI='http://localhost:8000/api/v1/auth/google/callback'"
        )
    return val


@router.get("/auth/google")
def google_login():
    """Redirect user to Google's OAuth 2.0 consent screen."""
    client_id = _get_env("GOOGLE_CLIENT_ID")
    redirect_uri = _get_env("GOOGLE_REDIRECT_URI")
    scope = "openid email profile"
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&scope={scope.replace(' ', '%20')}"
        f"&redirect_uri={redirect_uri}"
        f"&access_type=offline"
        f"&prompt=select_account"
    )
    # Debug output to help verify which redirect URI is being sent to Google
    try:
        print(f"[auth] Using GOOGLE_CLIENT_ID={client_id}")
        print(f"[auth] Using GOOGLE_REDIRECT_URI={redirect_uri}")
        print(f"[auth] Built auth_url={auth_url}")
    except Exception:
        pass
    return RedirectResponse(auth_url)


@router.get("/auth/google/callback")
async def google_callback(request: Request):
    """Handle OAuth2 callback, exchange code for tokens and return user info."""
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code in callback")

    client_id = _get_env("GOOGLE_CLIENT_ID")
    client_secret = _get_env("GOOGLE_CLIENT_SECRET")
    redirect_uri = _get_env("GOOGLE_REDIRECT_URI")

    token_url = "https://oauth2.googleapis.com/token"
    # Allow skipping SSL verification in development via env var SKIP_SSL_VERIFY=1
    skip_verify = os.environ.get('SKIP_SSL_VERIFY') in ('1', 'true', 'True')
    if skip_verify:
        verify_arg = False
    else:
        # Use certifi CA bundle to avoid SSL verification issues on some Windows installs
        verify_arg = certifi.where()

    try:
        async with httpx.AsyncClient(verify=verify_arg) as client:
            data = {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
            token_resp = await client.post(token_url, data=data, headers={"Accept": "application/json"})
            if token_resp.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch token from Google")
            tokens = token_resp.json()

            access_token = tokens.get("access_token")
            if not access_token:
                raise HTTPException(status_code=500, detail="No access token returned")

            # Fetch user info
            userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
            user_resp = await client.get(userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
            if user_resp.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch user info")
            user_info = user_resp.json()
    except httpx.HTTPError as e:
        # Common cause on Windows: missing CA bundle. Suggest installing certifi.
        msg = (
            f"HTTP error while contacting Google APIs: {e}. \n"
            "If you see an SSL certificate verification error on Windows, install the 'certifi' package:\n"
            "  pip install certifi\n"
            "Then restart the app.\n"
        )
        raise HTTPException(status_code=502, detail=msg)

    # Persist or retrieve user in MongoDB
    try:
        user = await get_or_create_user_from_info(user_info)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"User persistence error: {exc}")

    # Create a server-side session for the user and set a session cookie
    try:
        # Store minimal token info in the session meta so logout can attempt revocation.
        # WARNING: In production avoid storing long-term secrets in session documents.
        sid = create_session_with_meta(user.get('id'), meta={
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token') if 'refresh_token' in tokens else None,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed creating session: {e}")

    redirect_to = "/login/success"
    response = RedirectResponse(url=redirect_to)
    cookie_secure = os.environ.get('COOKIE_SECURE') in ('1', 'true', 'True') or request.url.scheme == 'https'
    response.set_cookie(
        key="session_id",
        value=sid,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
        max_age=3600 * 2,
    )
    return response



@router.get("/auth/logout")
def google_logout(request: Request):
    """Clear the session cookie and redirect to login.

    Also remove the server-side session if present (best-effort).
    """
    response = RedirectResponse(url="/login")
    sid = request.cookies.get('session_id')
    if sid:
        # Try to revoke tokens stored in the session (best-effort). If revocation fails
        # we still remove the session and the cookie.
        try:
            sess = get_session(sid)
            if sess and isinstance(sess, dict):
                meta = sess.get('meta') or {}
                # Prefer revoking refresh_token if available, otherwise access_token
                token_to_revoke = meta.get('refresh_token') or meta.get('access_token')
                if token_to_revoke:
                    revoke_url = 'https://oauth2.googleapis.com/revoke'
                    # Use requests synchronously here (logout is a short operation)
                    try:
                        # Respect SKIP_SSL_VERIFY if set in env
                        skip = os.environ.get('SKIP_SSL_VERIFY') in ('1', 'true', 'True')
                        verify_arg = False if skip else certifi.where()
                        resp = requests.post(revoke_url, params={'token': token_to_revoke}, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=5, verify=verify_arg)
                        # Google returns 200 on success; ignore other responses
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            delete_session(sid)
        except Exception:
            pass
    response.delete_cookie("session_id")
    return response


@router.get("/auth/me")
def auth_me(request: Request):
    """Return the current user based on the JWT stored in the cookie `access_token`.

    This is a convenience/test endpoint. In production, protect it and use proper session handling.
    """
    # Prefer middleware-populated user
    user = getattr(request.state, 'user', None)
    if user:
        return {"user": user}

    # Fallback: try to read session_id cookie and resolve session
    session_id = request.cookies.get('session_id')
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sess = get_session(session_id)
    if not sess:
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    try:
        user = get_user_by_dbid(sess.get('user_id'))
    except Exception:
        user = None
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {"user": user}