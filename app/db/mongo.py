import pandas as pd
from pymongo import MongoClient, errors
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import re
import logging


# 1. Cargar variables de entorno
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
print(f"Usando MONGO_URI: {MONGO_URI}")
DB_NAME = os.getenv("DB_NAME", "mi_ecommerce")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "productos")

# Configuración básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_client() -> MongoClient:
    """Return a MongoClient instance with error handling."""
    if not MONGO_URI:
        logger.warning("MONGO_URI not found in env, using default localhost.")
        return MongoClient()
    return MongoClient(MONGO_URI)

def get_collection():
    """Returns the database client and the specific collection."""
    client = get_client()
    db = client[DB_NAME]
    return client, db[COLLECTION_NAME]

def _doc_to_dict(doc):
    """Convert a MongoDB document to a JSON-serializable dict (stringify _id)."""
    if not doc:
        return None
    out = dict(doc)
    _id = out.pop('_id', None)
    out['id'] = str(_id) if _id is not None else None
    return out


def list_products_from_db(page: int = 1, page_size: int = 12, limit: int = 0) -> list:
    """
    Retrieves products from the database. Supports standard pagination OR a hard limit.
    
    If 'limit' is provided (> 0), pagination parameters (page, page_size) are ignored 
    to support legacy admin views or specific queries.

    Args:
        page (int): Current page number (1-based index). Defaults to 1.
        page_size (int): Number of items per page. Defaults to 12.
        limit (int): Hard limit of items to retrieve. Defaults to 0 (no limit/use pagination).

    Returns:
        list: List of dictionaries representing products with stringified IDs.
    """
    client, coll = get_collection()
    try:
        # Sort by creation date descending (newest first) by default
        cursor = coll.find().sort("created_at", -1)
        
        if limit > 0:
            # Case 1: Hard limit (Admin view usage)
            cursor = cursor.limit(limit)
        else:
            # Case 2: Pagination (Catalog view usage)
            skip = (page - 1) * page_size
            cursor = cursor.skip(skip).limit(page_size)
        
        return [_doc_to_dict(d) for d in cursor]
    except Exception as e:
        logger.error(f"Error listing products: {e}")
        return []
    finally:
        client.close()

def count_products() -> int:
    """
    Counts the total number of product documents in the collection.
    
    Returns:
        int: Total count of products.
    """
    client, coll = get_collection()
    try:
        return coll.count_documents({})
    except Exception as e:
        logger.error(f"Error counting products: {e}")
        return 0
    finally:
        client.close()

# NOTE: `list_products_from_db` unified above (supports both pagination and hard limit)

def get_product_from_db(product_id):
    client, coll = get_collection()
    try:
        # try ObjectId first
        try:
            _id = ObjectId(product_id)
            doc = coll.find_one({"_id": _id})
        except Exception:
            # fallback to searching by string id field
            doc = coll.find_one({"id": product_id})
        return _doc_to_dict(doc)
    finally:
        client.close()

def create_product_in_db(payload: dict):
    client, coll = get_collection()
    try:
        res = coll.insert_one(payload)
        return str(res.inserted_id)
    finally:
        client.close()


def update_product_in_db(product_id: str, payload: dict) -> int:
    """
    Updates a product document identified by product_id with the given payload.
    Returns the number of modified documents (0 if no changes or not found).
    """
    client, coll = get_collection()
    try:
        # Sanitize ID to prevent InvalidId errors from hidden whitespace
        clean_id = str(product_id).strip()

        try:
            _id = ObjectId(clean_id)
            filter_query = {"_id": _id}
        except InvalidId:
            # Fallback only if the ID is definitely not an ObjectId
            logger.warning(f"Invalid ObjectId format for: {clean_id}. Attempting fallback to 'id' field.")
            filter_query = {"id": clean_id}

        result = coll.update_one(filter_query, {"$set": payload})

        # Log if document matched but wasn't modified (idempotency check)
        if result.matched_count > 0 and result.modified_count == 0:
            logger.info(f"Product {clean_id} found but payload was identical to existing data.")

        # Log warning if absolutely no document was found
        if result.matched_count == 0:
            logger.warning(f"Update failed: Product {clean_id} not found in database.")

        return result.modified_count

    except Exception as e:
        logger.error(f"Critical DB Error updating product {product_id}: {e}")
        raise
    finally:
        client.close()


def delete_product_in_db(product_id):
    client, coll = get_collection()
    try:
        try:
            _id = ObjectId(product_id)
            res = coll.delete_one({"_id": _id})
        except Exception:
            res = coll.delete_one({"id": product_id})
        return res.deleted_count
    finally:
        client.close()


# ---------------------------
# Usuarios helpers
# ---------------------------
def _now():
    return datetime.utcnow()


def ensure_users_indexes():
    """Create unique indexes for usuarios collection to enforce google_id and email uniqueness."""
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['usuarios']
        # create unique index on google_id and email
        try:
            coll.create_index('google_id', unique=True)
        except Exception:
            pass
        try:
            coll.create_index('email', unique=True)
        except Exception:
            pass
    finally:
        client.close()


async def get_or_create_user_from_info(user_info: dict):
    """
    Retrieves an existing user or creates a new one based on Google OAuth info.
    
    Architecture Note:
    - Implements strict separation between 'Identity Data' (from Google) and 'Domain Data' (Role).
    - BUG FIX: The 'role' field is only assigned upon creation. It is explicitly excluded 
      from updates to prevent overwriting 'admin' status with the default 'user' role on login.
    """
    
    # Run blocking DB operations in a thread to avoid blocking the async event loop
    def _sync_op(user_info_local):
        client = get_client()
        try:
            db = client[DB_NAME]
            coll = db['usuarios']
            ensure_users_indexes()

            google_id = user_info_local.get('sub') or user_info_local.get('id')
            if not google_id:
                raise ValueError('google_id (sub) is required from Identity Provider')

            now = _now()

            # 1. Prepare Identity Data (Mutable fields from Google)
            # These fields are allowed to update on every login to keep profile fresh.
            identity_data = {
                'google_id': str(google_id),
                'email': user_info_local.get('email'),
                'email_verified': bool(user_info_local.get('email_verified')),
                'name': user_info_local.get('name'),
                'given_name': user_info_local.get('given_name'),
                'family_name': user_info_local.get('family_name'),
                'picture': user_info_local.get('picture'),
                'locale': user_info_local.get('locale'),
                # NOTE: 'role' is INTENTIONALLY OMITTED here to protect it during updates.
            }

            # Remove None values to avoid overwriting existing data with nulls unnecessarily
            identity_data = {k: v for k, v in identity_data.items() if v is not None}

            # 2. Check for Existing User
            existing_user = coll.find_one({'google_id': str(google_id)})

            if existing_user:
                # --- UPDATE STRATEGY ---
                # Only update identity fields and login timestamps.
                # The 'role' field remains untouched in the DB.
                
                identity_data['updated_at'] = now
                identity_data['last_login_at'] = now
                
                coll.update_one({'_id': existing_user['_id']}, {'$set': identity_data})
                
                # Merge updates into the existing document for return
                existing_user.update(identity_data)
                return _doc_to_dict(existing_user)

            else:
                # --- CREATE STRATEGY ---
                # New user provisioning. Here we MUST assign the default domain role.
                
                new_user_doc = identity_data.copy()
                # Default role assignment (Business Logic)
                new_user_doc['role'] = user_info_local.get('role') or 'user' 
                
                new_user_doc['created_at'] = now
                new_user_doc['updated_at'] = now
                new_user_doc['last_login_at'] = now

                res = coll.insert_one(new_user_doc)
                
                # Normalize ID for return
                new_user_doc['_id'] = res.inserted_id
                return _doc_to_dict(new_user_doc)

        finally:
            client.close()

    import asyncio
    return await asyncio.to_thread(_sync_op, user_info)


def get_user_by_dbid(user_id):
    """Return user document by Mongo _id (string) or by stored 'id' field."""
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['usuarios']
        try:
            _id = ObjectId(user_id)
            doc = coll.find_one({'_id': _id})
        except Exception:
            doc = coll.find_one({'id': user_id})
        if not doc:
            return None
        return _doc_to_dict(doc)
    finally:
        client.close()


def get_user_by_googleid(google_id):
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['usuarios']
        doc = coll.find_one({'google_id': str(google_id)})
        if not doc:
            return None
        return _doc_to_dict(doc)
    finally:
        client.close()


def update_user_by_dbid(user_id, updates: dict):
    """Update fields for a user by Mongo _id or by stored 'id'. Returns updated doc or None."""
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['usuarios']
        try:
            _id = ObjectId(user_id)
            res = coll.update_one({'_id': _id}, {'$set': updates})
            doc = coll.find_one({'_id': _id})
        except Exception:
            res = coll.update_one({'id': user_id}, {'$set': updates})
            doc = coll.find_one({'id': user_id})
        if not doc:
            return None
        return _doc_to_dict(doc)
    finally:
        client.close()


def create_session(user_id: str, ttl_seconds: int = 3600 * 2):
    """Create a session document for `user_id`. Returns the session id string."""
    from uuid import uuid4
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['sessions']
        sid = str(uuid4())
        now = datetime.utcnow()
        session = {
            '_id': sid,
            'user_id': str(user_id),
            'created_at': now,
            'expires_at': now + timedelta(seconds=ttl_seconds),
            # Optional place for short-lived metadata such as OAuth tokens.
            # Keep minimal information here and avoid long-term secrets in production.
            'meta': {},
        }
        coll.insert_one(session)
        return sid
    finally:
        client.close()


def create_session_with_meta(user_id: str, meta: dict = None, ttl_seconds: int = 3600 * 2):
    """Create a session storing optional `meta` information.

    Args:
        user_id: Database id of the user.
        meta: Optional dict with metadata (e.g. tokens). Keep sensitive data minimal.
        ttl_seconds: Session time-to-live in seconds.

    Returns:
        The created session id string.
    """
    from uuid import uuid4
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['sessions']
        sid = str(uuid4())
        now = datetime.utcnow()
        session = {
            '_id': sid,
            'user_id': str(user_id),
            'created_at': now,
            'expires_at': now + timedelta(seconds=ttl_seconds),
            'meta': meta or {},
        }
        coll.insert_one(session)
        return sid
    finally:
        client.close()


def get_session(session_id: str):
    """Return session document or None. Also returns None if expired."""
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['sessions']
        doc = coll.find_one({'_id': session_id})
        if not doc:
            return None
        # check expiry
        if doc.get('expires_at') and doc['expires_at'] < datetime.utcnow():
            # expired: delete and return None
            try:
                coll.delete_one({'_id': session_id})
            except Exception:
                pass
            return None
        # normalize and return safe dict
        return _doc_to_dict(doc)
    finally:
        client.close()


def delete_session(session_id: str):
    client = get_client()
    try:
        db = client[DB_NAME]
        coll = db['sessions']
        res = coll.delete_one({'_id': session_id})
        return res.deleted_count
    finally:
        client.close()


# --- Search Logic ---

def _build_search_query(query: str):
    """
    Constructs a MongoDB query for partial matching on name, description, and tags.
    """
    if not query:
        return {}
    
    # Escape regex characters to avoid errors
    safe_query = re.escape(query)
    regex = {"$regex": safe_query, "$options": "i"} # Case-insensitive
    
    return {
        "$or": [
            {"name": regex},
            {"description": regex},
            {"tags": regex},          # Manual tags
            {"ia_tags.tags": regex}   # AI/ETL tags
        ]
    }

def count_products_search(query: str) -> int:
    """Counts total products matching the search query."""
    client, coll = get_collection()
    try:
        filter_q = _build_search_query(query)
        return coll.count_documents(filter_q)
    except Exception as e:
        logger.error(f"Error counting search results: {e}")
        return 0
    finally:
        client.close()

def search_products_db(query: str, page: int = 1, page_size: int = 12) -> list:
    """
    Searches products across the DB with pagination.
    """
    client, coll = get_collection()
    try:
        filter_q = _build_search_query(query)
        skip = (page - 1) * page_size
        
        cursor = coll.find(filter_q).sort("created_at", -1).skip(skip).limit(page_size)
        return [_doc_to_dict(d) for d in cursor]
    except Exception as e:
        logger.error(f"Error searching products: {e}")
        return []
    finally:
        client.close()

# --- Helpers de Limpieza ---

def clean_price(value) -> int:
    """
    Parses price string to integer, removing currency symbols and separators.
    Example: '💰70.000' -> 70000
    """
    if pd.isna(value):
        return 0
    value_str = str(value)
    # Remove everything except digits
    digits_only = re.sub(r'[^\d]', '', value_str)
    try:
        return int(digits_only)
    except ValueError:
        return 0

def process_images(image_string: str) -> list[str]:
    """Converts a comma-separated string of filenames into a list."""
    if pd.isna(image_string):
        return []
    return [img.strip() for img in str(image_string).split(',') if img.strip()]

def generate_title_from_description(description: str) -> str:
    """
    Generates a short title from the description.
    Strategy: Takes the first non-empty line or the first 50 chars.
    """
    if not description or pd.isna(description):
        return "Producto Sin Título"
    
    # Intentar tomar la primera línea limpia
    lines = [line.strip() for line in str(description).split('\n') if line.strip()]
    
    if lines:
        # Limpiar emojis o caracteres markdown básicos de la primera línea para el título
        first_line = lines[0]
        clean_title = re.sub(r'[*_~]', '', first_line) # Quitar markdown básico
        return clean_title[:60] # Limitar longitud
        
    return "Nuevo Producto"
# --- Helper para extracción de etiquetas (Nuevo) ---
def extract_tags_from_description(description: str) -> list:
    """
    Extracts potential tags from description text using heuristics.
    Rule: Extracts words or phrases enclosed in asterisks (*) common in WhatsApp messages.
    Example: "*NUEVA COLECCIÓN*" -> "NUEVA COLECCIÓN"
    """
    if not description:
        return []
    # Regex to find text between asterisks (markdown style bold)
    matches = re.findall(r'\*([^\*]+)\*', description)
    # Clean and filter matches
    tags = [m.strip().upper() for m in matches if len(m.strip()) > 2]
    return list(set(tags)) # Remove duplicates

def load_data_etl():
    """
    ETL Process: Extracts data from CSV, Transforms it (adding Title and Tags), and Loads to MongoDB.
    Applies Data Normalization to ensure schema consistency with the application.
    """
    logger.info("🚀 Starting ETL process...")

    # 1. Connection Check
    try:
        client = get_client()
        client.admin.command('ping')
        logger.info("✅ Connected to MongoDB.")
    except errors.ConnectionFailure as e:
        logger.error(f"❌ Connection failed: {e}")
        return

    # 2. Extract (Read CSV)
    csv_filename = 'productos_ecommerce.csv'
    try:
        df = pd.read_csv(csv_filename)
        logger.info(f"📂 CSV loaded: {len(df)} records found.")
    except FileNotFoundError:
        logger.error(f"❌ File not found: {csv_filename}")
        return

    # 3. Transform & Load
    client, collection = get_collection()
    data_to_insert = []

    for index, row in df.iterrows():
        try:
            # Parse Date
            try:
                created_at = pd.to_datetime(row.get('Fecha'), dayfirst=True)
            except Exception:
                created_at = datetime.utcnow()

            description = str(row.get('Descripcion', '')).strip()
            
            # --- Logic: Title Generation ---
            title = generate_title_from_description(description)

            # --- Logic: Tag Extraction (Fix for Search) ---
            # Extract tags from description or use an empty list if none found
            extracted_tags = extract_tags_from_description(description)

            # Build Document (Schema Normalized)
            doc = {
                "name": title,
                "description": description,
                "price": clean_price(row.get('Precio')),
                "tags": extracted_tags, # <--- CRITICAL FIX: Root level tags field
                "created_at": created_at,
                "images": {
                    "all": process_images(row.get('Imagenes_Agrupadas')),
                    "cover": str(row.get('Imagen_Representativa', '')).strip(),
                    "count": int(row.get('Cantidad_Imagenes', 0)) if pd.notna(row.get('Cantidad_Imagenes')) else 0
                },
                "ia_tags": {
                    "status": str(row.get('Etiquetas_IA', 'PENDING')),
                    "tags": [] # Placeholder for future AI processing
                },
                "metadata": {
                    "excel_row": index + 2
                }
            }
            data_to_insert.append(doc)

        except Exception as e:
            logger.warning(f"⚠️ Error processing row {index}: {e}")

    # Bulk Insert with cleanup
    if data_to_insert:
        try:
            # OPTIONAL: Uncomment the next line to wipe old non-tagged data and reload clean data
            # logger.info("🧹 Clearing existing collection for fresh load...")
            # collection.delete_many({}) 
            
            result = collection.insert_many(data_to_insert)
            logger.info(f"🎉 SUCCESS: {len(result.inserted_ids)} products inserted with TAGS.")
        except Exception as e:
            logger.error(f"❌ Insert error: {e}")
    else:
        logger.warning("⚠️ No valid data to upload.")
    
    client.close()

if __name__ == "__main__":
    load_data_etl()