"""
FastAPI application entrypoint.
Orchestrates routing, template rendering, and session management.
Adheres to SOLID and Clean Code principles.
"""
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi import Response
from pathlib import Path
from dotenv import load_dotenv
from bson import ObjectId
from typing import List, Optional
import os
import time
import re
import shutil
import math
import asyncio
from datetime import datetime

# Import database layer
from app.db import mongo
# Import Router V1
from app.api.v1 import router as v1_router

# --- Configuration & Setup ---
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
TEMPLATES_DIR = BASE_DIR / "templates"
SESSION_COOKIE_NAME = "session_id"

# Ensure critical directories exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Punto G Ecommerce", version="1.1.0")

# Static & Templates Mounts
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Register API routes
v1_router.include_v1_routes(app)


# --- Helper Services ---

def _serialize_mongo_doc(value: any) -> any:
    """Recursively serializes MongoDB documents for Jinja2 rendering."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_mongo_doc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_mongo_doc(x) for x in value]
    return value

def render_template(request: Request, template_name: str, context: dict = None):
    """
    Renders a Jinja2 template ensuring user context is present and serializable.
    """
    ctx = {"request": request}
    if context:
        ctx.update(context)

    user = getattr(request.state, "user", None)
    ctx["current_user"] = _serialize_mongo_doc(user) if user else None
        
    return templates.TemplateResponse(template_name, ctx)

async def save_upload_files(files: List[UploadFile]) -> List[str]:
    """
    Saves a list of uploaded files to the static uploads directory.
    
    Args:
        files: List of UploadFile objects from FastAPI.
        
    Returns:
        List[str]: A list of relative web paths to the saved files.
    """
    saved_paths = []
    
    for file in files:
        if not file.filename:
            continue
            
        try:
            # Sanitize filename
            clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '', file.filename)
            timestamp = int(time.time() * 1000) # Use ms for uniqueness
            safe_filename = f"{timestamp}_{clean_name}"
            disk_path = UPLOADS_DIR / safe_filename
            
            # Use strict blocking IO in a thread if files are large, 
            # but for simplicity/speed in this context standard read/write:
            with open(disk_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            saved_paths.append(f"/static/uploads/{safe_filename}")
            
        except Exception as e:
            print(f"[Error] Failed to save file {file.filename}: {e}")
            # Continue saving other files even if one fails
            continue
            
    return saved_paths


# --- Middleware ---

@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """Resolves the session_id cookie to a user from MongoDB."""
    request.state.user = None
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    
    if session_id:
        def _resolve_user():
            try:
                from app.db.mongo import get_session, get_user_by_dbid
                sess = get_session(session_id)
                if not sess: return None
                return get_user_by_dbid(sess.get('user_id'))
            except Exception:
                return None

        # Asyncio wrapper for DB call
        user = await asyncio.to_thread(_resolve_user)
        request.state.user = user
        
    return await call_next(request)


@app.get("/logout")
async def logout(request: Request):
    """Terminate the current session and redirect to the home page.

    This clears the session cookie stored under `SESSION_COOKIE_NAME` and
    attempts to remove the server-side session document (best-effort).
    """
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    response = RedirectResponse(url="/", status_code=302)

    if sid:
        try:
            # Run blocking DB call in thread
            await asyncio.to_thread(mongo.delete_session, sid)
        except Exception:
            # Best-effort cleanup; do not fail the logout if DB call fails
            pass
        # Remove cookie from client
        response.delete_cookie(SESSION_COOKIE_NAME)

    return response


@app.get("/profile", response_class=HTMLResponse)
async def view_profile(request: Request):
    """Render the user profile page for authenticated users.

    If the user is not authenticated, redirect to the login page.
    """
    user = getattr(request.state, "user", None)
    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "current_user": user, "page_title": "Mi Perfil"},
    )


# --- HTML Routes (View Controller) ---

@app.get("/")
async def index(request: Request, page: int = 1, q: Optional[str] = None):
    """
    Renders the home page.
    Handles both standard pagination and global search via 'q' parameter.
    """
    PAGE_SIZE = 12
    
    # Logic Fork: Search vs List
    if q:
        search_query = q.strip()
        total_products = mongo.count_products_search(search_query)
        raw_products = mongo.search_products_db(search_query, page=page, page_size=PAGE_SIZE)
    else:
        search_query = ""
        total_products = mongo.count_products()
        raw_products = mongo.list_products_from_db(page=page, page_size=PAGE_SIZE)
    
    total_pages = math.ceil(total_products / PAGE_SIZE) if total_products > 0 else 1
    
    products_view_model = []
    for p in raw_products:
        # Determine main image (cover)
        img_source = p.get('image')
        if not img_source and p.get('images') and isinstance(p['images'], list) and len(p['images']) > 0:
            img_source = p['images'][0]
        elif not img_source and isinstance(p.get('imagenes'), dict):
            img_source = p['imagenes'].get('cover') or p['imagenes'].get('portada')

        image_url = img_source if img_source else "/static/images/placeholder.svg"
        if image_url and not image_url.startswith(('http', '/')):
             image_url = f"/static/uploads/{image_url}"

        # Normalize tags for display (optional usage in frontend)
        tags_raw = p.get('tags')
        if not tags_raw:
            ia_data = p.get('ia_tags', {})
            tags_raw = ia_data.get('tags') if isinstance(ia_data, dict) else []
        if not isinstance(tags_raw, list): tags_raw = []

        products_view_model.append({
            "id": str(p.get('_id') or p.get('id')),
            "name": p.get('name') or "Producto Sin Nombre",
            "price_fmt": f"${p.get('price', 0):,.0f}".replace(",", "."),
            "image": image_url,
            "is_new": p.get('is_new', False),
            "tags": tags_raw
        })

    # Prepare pagination URL builder
    # We pass 'q' back to context so pagination links can preserve it (e.g. /?page=2&q=nike)
    pagination_ctx = {
        "current_page": page,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "next_page": page + 1,
        "prev_page": page - 1,
        "q": search_query # Important for preserving search state in UI
    }

    return render_template(request, "index.html", {
        "products": products_view_model,
        "page_title": f"Resultados para '{search_query}'" if search_query else "Catálogo Exclusivo",
        "pagination": pagination_ctx,
        "q": search_query # To populate input field
    })

@app.get("/login")
async def login_page(request: Request):
    if getattr(request.state, 'user', None):
        return RedirectResponse(url="/")
    return render_template(request, "login.html")

@app.get("/login/success")
async def login_success(request: Request):
    return render_template(request, "login_success.html")

# --- Admin Routes (Protected) ---

def _ensure_admin(request: Request):
    user = getattr(request.state, 'user', None)
    if not user or user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access denied: Admins only")
    return user

@app.get("/manage/catalog")
async def manage_catalog(request: Request):
    """Admin catalog view."""
    user = getattr(request.state, 'user', None)
    if not user or user.get('role') != 'admin':
        return RedirectResponse(url="/")

    db_products = mongo.list_products_from_db(limit=100)
    products = []
    for p in db_products:
        # Determine image logic for admin view
        img = p.get('image')
        if not img and p.get('images') and len(p['images']) > 0:
            img = p['images'][0]
            
        products.append({
            "id": str(p.get('_id') or p.get('id')),
            "name": p.get('name', 'Sin título'),
            "price": f"${p.get('price', 0)}",
            "image": img or '/static/images/product1.svg'
        })

    return render_template(request, "catalog_edit.html", {"products": products})

@app.get("/product/new")
async def product_new_form(request: Request):
    """Render the Create Product form."""
    user = getattr(request.state, 'user', None)
    if not user or user.get('role') != 'admin':
        return RedirectResponse(url="/")
    return render_template(request, "products_edits.html", {"product": None})

@app.get("/product/edit/{product_id}")
async def product_edit_form(request: Request, product_id: str):
    """Render the Edit Product form."""
    user = getattr(request.state, 'user', None)
    if not user or user.get('role') != 'admin':
        return RedirectResponse(url="/")

    prod = mongo.get_product_from_db(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    # The DB layer (_doc_to_dict) already normalizes and provides `id`.
    # Do NOT attempt to re-derive '_id' here because it may have been removed.

    # Ensure images is a list and main image is included as first element
    images_list = prod.get('images', [])
    if not isinstance(images_list, list):
        images_list = []

    main_img = prod.get('image')
    if main_img and main_img not in images_list:
        images_list.insert(0, main_img)
    elif not main_img and images_list:
        prod['image'] = images_list[0]

    prod['images'] = images_list

    return render_template(request, "products_edits.html", {"product": prod})


# --- API Actions (RESTful) ---

@app.post("/product")
async def create_product(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    price: str = Form("0"),
    tags: str = Form(""), # Changed from category to tags
    image_files: List[UploadFile] = File(default=[])
):
    """
    Creates a new product with tags and images.
    """
    _ensure_admin(request)

    # 1. Process Data
    try:
        clean_price = int(re.sub(r'[^\d]', '', price))
    except ValueError:
        clean_price = 0

    # Process Tags
    tag_list = [t.strip() for t in tags.split(',') if t.strip()]

    # 2. Process Files
    saved_images = await save_upload_files(image_files)
    cover_image = saved_images[0] if saved_images else ""

    payload = {
        "name": title,
        "description": description,
        "price": clean_price,
        "tags": tag_list,           # Save as Array
        "category": tag_list[0] if tag_list else "General", # Fallback for legacy compatibility
        "image": cover_image,
        "images": saved_images,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # 3. Save to DB
    new_id = mongo.create_product_in_db(payload)
    return JSONResponse({"status": "created", "id": new_id}, status_code=201)


@app.put("/product/{product_id}")
async def update_product(
    request: Request,
    product_id: str,
    title: str = Form(...),
    description: str = Form(""),
    price: str = Form("0"),
    tags: str = Form(""), # Changed from category to tags
    kept_images: List[str] = Form(default=[]),
    image_files: List[UploadFile] = File(default=[])
):
    """
    Updates an existing product, parsing tags into a list.
    """
    _ensure_admin(request)

    # 1. Process Data
    try:
        clean_price_str = str(price).replace('$', '').replace(',', '')
        clean_price = float(clean_price_str) if '.' in clean_price_str else int(clean_price_str)
    except Exception:
        clean_price = 0

    # Process Tags
    tag_list = [t.strip() for t in tags.split(',') if t.strip()]

    # 2. Process Files
    new_images = await save_upload_files(image_files)

    # 3. Construct Gallery
    if not isinstance(kept_images, list):
        kept_images = [kept_images] if kept_images else []

    updated_gallery = []
    # Deduplicate while preserving order
    seen = set()
    for img in kept_images + new_images:
        if img and img not in seen:
            updated_gallery.append(img)
            seen.add(img)

    final_cover = updated_gallery[0] if updated_gallery else ''

    payload = {
        "name": title.strip(),
        "description": description.strip(),
        "price": clean_price,
        "tags": tag_list, # Save as Array
        "category": tag_list[0] if tag_list else "General", # Legacy support
        "image": final_cover,
        "images": updated_gallery,
        "updated_at": datetime.utcnow()
    }

    try:
        modified = mongo.update_product_in_db(product_id, payload)
        return JSONResponse({"status": "updated", "modified": modified, "matched": True})
    except Exception as e:
        print(f"[Error] Update failed: {e}")
        raise HTTPException(status_code=500, detail="Database update failed")


@app.post('/product/delete/{product_id}')
async def delete_product_action(request: Request, product_id: str):
    """Deletes a product (Admin only)."""
    _ensure_admin(request)
    mongo.delete_product_in_db(product_id)
    return RedirectResponse(url='/manage/catalog', status_code=303)


# --- Public Product Routes ---

@app.get("/product/{product_id}")
async def product_detail(request: Request, product_id: str):
    """Renders the single product detail page."""
    prod = mongo.get_product_from_db(product_id)
    if not prod:
        return render_template(request, "product_details.html", {"product": None})
        
    # Normalize for template
    # Ensure 'images' is a list and includes the main image if not already in list
    images_list = prod.get('images', [])
    main_img = prod.get('image')
    
    if not isinstance(images_list, list):
        images_list = [images_list] if images_list else []
    
    # Deduplicate main image from list if present
    if main_img and main_img not in images_list:
        images_list.insert(0, main_img)
    elif not main_img and images_list:
        main_img = images_list[0]
    # Use the 'id' already provided by the DB helper (_doc_to_dict)
    normalized_prod = {
        "id": prod.get('id'),
        "name": prod.get('name') or "Sin Nombre",
        "description": prod.get('description') or "",
        "price": f"${prod.get('price', 0):,}".replace(",", "."),
        "image": main_img,
        "images": images_list
    }
    
    return render_template(request, "product_details.html", {"product": normalized_prod})

# --- Main Entry Point ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="localhost", port=8000, reload=True)