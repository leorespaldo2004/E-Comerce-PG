"""
Products CRUD endpoints backed by MongoDB.
Handles normalization, serialization, and input parsing for product management.
"""
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Request
from fastapi.responses import JSONResponse, RedirectResponse
from typing import List, Optional
from datetime import datetime
import re

from app.db import mongo

router = APIRouter()

def _parse_tags(tags_str: str) -> List[str]:
    """
    Parses a comma-separated string into a list of unique, cleaned tags.
    
    Args:
        tags_str (str): Input string (e.g., "shoes, summer, sale").
        
    Returns:
        List[str]: Cleaned list (e.g., ["shoes", "summer", "sale"]).
    """
    if not tags_str:
        return []
    # Split by comma, strip whitespace, remove empty strings, and deduplicate
    return list(set([t.strip() for t in tags_str.split(',') if t.strip()]))

def _normalize_product(doc: dict) -> dict:
    """
    Map DB document keys to frontend fields: id, name, price, image, description, images, tags.
    Ensures 'tags' is always returned as a list.
    """
    if not doc:
        return doc
    
    # Fallback keys logic
    name = doc.get('name') or doc.get('titulo') or doc.get('nombre') or "Sin Nombre"
    description = doc.get('description') or doc.get('descripcion') or ''
    price = doc.get('price') or doc.get('precio') or 0
    
    # Image logic
    image = doc.get('image')
    images = doc.get('images') or []
    
    # Legacy structure handling (if any)
    if not image and isinstance(doc.get('imagenes'), dict):
        image = doc['imagenes'].get('portada')
        images = doc['imagenes'].get('lista_completa') or images
        
    if not images and isinstance(doc.get('imagenes'), list):
        images = doc.get('imagenes')

    # Tags normalization
    tags = doc.get('tags') or []
    if isinstance(tags, str):
        tags = _parse_tags(tags) # Safe fallback if DB has string instead of list

    return {
        'id': doc.get('id') or str(doc.get('_id') or ''),
        'name': name,
        'description': description,
        'price': price,
        'image': image,
        'images': images or [],
        'tags': tags, # Added tags field
        'category': doc.get('category') # Keep legacy category just in case
    }

@router.get("/products", tags=["products"])
def list_products(limit: Optional[int] = 0):
    """List products from MongoDB with normalization."""
    try:
        prods = mongo.list_products_from_db(limit=limit or 0)
        items = [_normalize_product(d) for d in prods]
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/products/{product_id}", tags=["products"])
def get_product(product_id: str):
    """Retrieve a single product by ID."""
    prod = mongo.get_product_from_db(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    return _normalize_product(prod)

# --- Form Actions (POST/PUT) handled directly here or via main.py delegation ---
# Note: The main logic for create/update with Files is currently in main.py 
# due to UploadFile handling complexity in router separation without shared dependencies.
# However, purely JSON endpoints would go here. 
# For this specific project structure, ensure main.py calls DB functions correctly.
