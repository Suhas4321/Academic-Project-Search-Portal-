import os
from dotenv import load_dotenv
load_dotenv()

import re
import io
import pandas as pd
import logging

from fastapi import (
    APIRouter, Depends, Path, Body, Form,
    HTTPException, status, Request, UploadFile
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import create_engine, text

from app.database import get_db

# Enable DEBUG logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Sync/async DB URLs
ASYNC_DB_URL = os.getenv(
    "ASYNC_DB_URL",
    "postgresql+asyncpg://admin:admin123@localhost:5432/mydatabase"
)
SYNC_DB_URL = os.getenv(
    "SYNC_DB_URL",
    "postgresql://admin:admin123@localhost:5432/mydatabase"
)

async_engine = create_async_engine(ASYNC_DB_URL, echo=True)
sync_engine = create_engine(SYNC_DB_URL, echo=True)

router = APIRouter(prefix="/admin", tags=["admin"])

# Safe table name validator
def is_safe_table_name(name):
    """
    Validates table name to only contain letters, numbers, and underscores.
    Prevents SQL injection by blocking dangerous characters.
    """
    if not name or len(name) > 63:  # PostgreSQL table name limit
        return False
    return bool(re.match(r"^[A-Za-z0-9_]+$", name))

@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    Validates admin credentials and returns JSON on success/failure.
    """
    admin_user = os.getenv("ADMIN_USERNAME")
    admin_pass = os.getenv("ADMIN_PASSWORD")

    if username == admin_user and password == admin_pass:
        request.session["admin_authenticated"] = True
        return JSONResponse({"success": True})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials"
    )

@router.get("/tables")
async def list_tables(db: AsyncSession = Depends(get_db)):
    """
    Returns list of all tables in public schema (excluding system tables).
    """
    query = text(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname='public' "
        "AND tablename NOT LIKE 'pg_%' "
        "AND tablename NOT LIKE 'sql_%';"
    )
    result = await db.execute(query)
    tables = [row[0] for row in result]
    return {"tables": tables}

@router.get("/tables/{table_name}")
async def get_table(
    table_name: str = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns all rows from specified table ordered by group_no.
    """
    if not is_safe_table_name(table_name):
        raise HTTPException(
            status_code=400,
            detail="Table name may only contain letters, numbers, and underscore (_)."
        )
    
    query = text(f'SELECT * FROM "{table_name}" ORDER BY group_no;')
    try:
        result = await db.execute(query)
        rows = result.mappings().all()
        return {"rows": rows}
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{table_name}' not found or error accessing it: {e}"
        )

@router.post("/tables/{table_name}")
async def insert_row(
    table_name: str = Path(...),
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Inserts new row into specified table.
    """
    if not is_safe_table_name(table_name):
        raise HTTPException(
            status_code=400,
            detail="Table name may only contain letters, numbers, and underscore (_)."
        )
    
    cols = ", ".join(data.keys())
    vals = ", ".join(f":{k}" for k in data.keys())
    query = text(f'INSERT INTO "{table_name}" ({cols}) VALUES ({vals});')
    try:
        await db.execute(query, data)
        await db.commit()
        return {"success": True}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error inserting row: {e}"
        )

@router.put("/tables/{table_name}/{group_no}")
async def update_row(
    table_name: str = Path(...),
    group_no: int = Path(...),
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates row identified by group_no in specified table and returns the updated row.
    """
    if not is_safe_table_name(table_name):
        raise HTTPException(
            status_code=400,
            detail="Table name may only contain letters, numbers, and underscore (_)."
        )
    
    logger.debug(f"→ PUT /admin/tables/{table_name}/{group_no} payload: {data!r}")

    # Strip out search_vector if sent by frontend
    data_clean = {k: v for k, v in data.items() if k != "search_vector"}

    # Convert any list values to comma-separated strings
    for key, val in list(data_clean.items()):
        if isinstance(val, list):
            data_clean[key] = ", ".join(str(item) for item in val)

    updated = None
    if data_clean:
        assignments = ", ".join(f"{col} = :{col}" for col in data_clean.keys())
        params = {**data_clean, "group_no": group_no}

        sql = (
            f'UPDATE "{table_name}" '
            f"SET {assignments} "
            f"WHERE group_no = :group_no "
            f"RETURNING *;"
        )
        logger.debug(f"   Running SQL: {sql} with {params}")
        try:
            result = await db.execute(text(sql), params)
            updated = result.mappings().first()
        except Exception as e:
            logger.error(f"   ✗ UPDATE failed: {e!r}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not update row: {e}"
            )

        if not updated:
            logger.warning(f"   ✗ No row with group_no={group_no} in {table_name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Row {group_no} not found in {table_name}"
            )
        logger.debug(f"   ✔️ UPDATE returned: {dict(updated)}")
    else:
        logger.debug("   No updatable fields found; skipping main UPDATE.")

    # Rebuild full-text search_vector with correct single quotes
    sv_sql = f"""
        UPDATE "{table_name}"
        SET search_vector =
          setweight(to_tsvector('english', COALESCE(project_title, '')), 'A') ||
          setweight(to_tsvector('english', COALESCE(guide_name, '')), 'B')
        WHERE group_no = :group_no;
    """
    logger.debug(f"   Rebuilding search_vector for group_no={group_no}")
    try:
        await db.execute(text(sv_sql), {"group_no": group_no})
    except Exception as e:
        logger.warning(f"   ⚠️ Could not update search_vector: {e}")

    await db.commit()
    logger.debug("   ✅ Committed transaction")

    return {
        "success": True,
        "row": dict(updated) if updated else None
    }

@router.delete("/tables/{table_name}/{group_no}")
async def delete_row(
    table_name: str = Path(...),
    group_no: int = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes row identified by group_no in specified table.
    """
    if not is_safe_table_name(table_name):
        raise HTTPException(
            status_code=400,
            detail="Table name may only contain letters, numbers, and underscore (_)."
        )
    
    query = text(f'DELETE FROM "{table_name}" WHERE group_no = :group_no;')
    try:
        await db.execute(query, {"group_no": group_no})
        await db.commit()
        return {"success": True}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting row: {e}"
        )

@router.post("/upload-excel")
async def upload_excel(
    request: Request,
    new_table: str = Form(...),
    file: UploadFile = Form(...),
):
    """
    Uploads an Excel/CSV file, cleans it, and creates/replaces the specified table.
    """
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=403, detail="Not logged in")

    # Validate table name instead of enforcing format
    if not is_safe_table_name(new_table):
        raise HTTPException(
            status_code=400,
            detail="Table name may only contain letters, numbers, and underscore (_). Max 63 characters."
        )

    contents = await file.read()
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            xls = pd.ExcelFile(io.BytesIO(contents))
            df = xls.parse(xls.sheet_names[0])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File read error: {e}")

    # --- Cleaning utilities ---
    def normalize_columns(cols):
        normalized = []
        for c in cols:
            if pd.isna(c):
                normalized.append("")
            else:
                normalized.append(
                    str(c).strip()
                          .upper()
                          .replace("\n", " ")
                          .replace("\\N", "")
                          .replace("\\", "")
                )
        return normalized

    def find_column(columns, keywords):
        if isinstance(keywords, str):
            keywords = [keywords]
        for keyword in keywords:
            key_clean = keyword.lower().replace(" ", "").replace("_", "")
            for col in columns:
                if key_clean in col.lower().replace(" ", "").replace("_", ""):
                    return col
        raise KeyError(f"Missing column matching any of: {keywords}")

    def clean_and_structure(sheet_df):
        df = sheet_df.copy()

        # Detect header row
        header_row = None
        for i in range(min(5, len(df))):
            vals = [str(v).upper() for v in df.iloc[i] if pd.notna(v)]
            if any("GROUP" in v and "NO" in v for v in vals):
                header_row = i
                break
        header_row = header_row if header_row is not None else 2

        df.columns = df.iloc[header_row]
        df = df[header_row + 1:].reset_index(drop=True)
        df = df.dropna(how="all")
        df.columns = normalize_columns(df.columns)
        df = df.ffill()

        # Ensure integer group_no
        grp_col = find_column(df.columns, ["groupno", "group", "grp"])
        df[grp_col] = pd.to_numeric(df[grp_col], errors="coerce")
        df = df.dropna(subset=[grp_col]).astype({grp_col: int})

        # Map columns
        usn_c   = find_column(df.columns, ["usn"])
        name_c  = find_column(df.columns, ["name", "student"])
        proj_c  = find_column(df.columns, ["projecttitle", "project"])
        guide_c = find_column(df.columns, ["guidename", "guide"])
        outc_c  = find_column(df.columns, ["outcomes", "outcome", "result"])
        proof_c = find_column(df.columns, ["prooflink", "link"])

        # Aggregators
        def safe_list(x):
            return [str(v) for v in x if pd.notna(v) and str(v).strip()]

        def safe_first(x):
            L = [v for v in x if pd.notna(v) and str(v).strip()]
            return L[0] if L else ""

        grouped = df.groupby(grp_col).agg({
            usn_c: safe_list,
            name_c: safe_list,
            proj_c: safe_first,
            guide_c: safe_first,
            outc_c: safe_first,
            proof_c: safe_first
        }).reset_index()

        # Flatten lists for storage
        for c in [usn_c, name_c]:
            grouped[c] = grouped[c].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))

        # Rename to match schema
        grouped.columns = [
            "group_no", "usn", "name", "project_title",
            "guide_name", "outcomes", "proof_link"
        ]

        # Ensure extra columns exist
        for extra in ("report_links", "ppt_links"):
            if extra not in grouped:
                grouped[extra] = ""

        # Clean any NaNs
        for col in grouped.columns:
            grouped[col] = grouped[col].fillna("").astype(str).replace("nan", "")

        return grouped

    try:
        cleaned_df = clean_and_structure(df)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data cleaning error: {e}")

    if cleaned_df.empty:
        raise HTTPException(status_code=400, detail="No valid data found in the uploaded file")

    # Write to DB
    try:
        with sync_engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{new_table}";'))
            conn.commit()

        cleaned_df.to_sql(new_table, sync_engine, index=False, if_exists="replace")

        with sync_engine.connect() as conn:
            conn.execute(text(f'''
                ALTER TABLE "{new_table}"
                ADD COLUMN IF NOT EXISTS search_vector tsvector;
            '''))
            conn.execute(text(f'''
                UPDATE "{new_table}"
                SET search_vector =
                  setweight(to_tsvector('english', COALESCE(project_title, '')), 'A') ||
                  setweight(to_tsvector('english', COALESCE(guide_name, '')), 'B');
            '''))
            idx_name = f"idx_{new_table}_search"
            conn.execute(text(f'''
                CREATE INDEX IF NOT EXISTS {idx_name}
                ON "{new_table}" USING GIN (search_vector);
            '''))
            conn.commit()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    return {
        "success": True,
        "table": new_table,
        "rows_imported": len(cleaned_df),
        "message": f"Successfully imported {len(cleaned_df)} groups into table {new_table}"
    }
