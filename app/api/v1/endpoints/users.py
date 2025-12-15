from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi import status
import asyncio
from pathlib import Path
import time
import os
import re

from app.db.mongo import update_user_by_dbid

router = APIRouter()


@router.patch("/users/me")
async def update_me(request: Request):
    """Update current user's editable fields (name, picture).

    Expects JSON body with optional keys: `name`, `picture`.
    Requires an authenticated user (middleware populates `request.state.user`).
    """
    current = getattr(request.state, 'user', None)
    if not current:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    allowed = {"name", "picture"}
    updates = {k: v for k, v in payload.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updatable fields provided")

    # set updated_at timestamp on server side
    from datetime import datetime
    updates['updated_at'] = datetime.utcnow()

    user_id = current.get('id') or current.get('_id')
    if not user_id:
        raise HTTPException(status_code=500, detail="User id not available")

    # Call blocking DB update in thread
    def _update():
        return update_user_by_dbid(user_id, updates)

    updated = await asyncio.to_thread(_update)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update user")

    # Normalize response
    return {"ok": True, "user": updated}



@router.post('/users/avatar')
async def upload_avatar(request: Request, file: UploadFile = File(...)):
    """Upload a profile picture, save under `static/uploads/` and update user.picture.

    Returns JSON with `picture` URL on success.
    """
    current = getattr(request.state, 'user', None)
    if not current:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Compute project root (4 parents up from this file points to project root)
    base_dir = Path(__file__).resolve().parents[4]
    upload_dir = base_dir / 'static' / 'uploads'
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # sanitize filename
    original_name = Path(file.filename).name
    safe_name = re.sub(r'[^0-9A-Za-z_.-]', '_', original_name)
    fn = f"{current.get('id')}_{int(time.time())}_{safe_name}"
    dest = upload_dir / fn
    try:
        content = await file.read()
        with open(dest, 'wb') as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed saving file: {e}")

    # build accessible URL served under /static/uploads/<fn>
    picture_url = f"/static/uploads/{fn}"

    # update user document (blocking call)
    user_id = current.get('id') or current.get('_id')
    if not user_id:
        raise HTTPException(status_code=500, detail="User id not available")

    def _update():
        return update_user_by_dbid(user_id, {'picture': picture_url})

    updated = await asyncio.to_thread(_update)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update user picture")

    # If request came from a browser form, redirect back; else return JSON
    referer = request.headers.get('referer')
    if referer:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=referer)

    return {"ok": True, "picture": picture_url}


# --- Favorites endpoint ---
@router.post("/users/favorites/{product_id}")
async def toggle_favorite(product_id: str, request: Request):
    """
    Toggles the favorite status of a product for the current user.
    """
    current = getattr(request.state, 'user', None)
    if not current:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Must be logged in")

    user_id = current.get('id') or current.get('_id')
    
    # Execute DB operation in thread
    def _op():
        from app.db.mongo import toggle_user_favorite
        return toggle_user_favorite(user_id, product_id)
    
    is_favorite = await asyncio.to_thread(_op)
    
    return {"ok": True, "is_favorite": is_favorite}
