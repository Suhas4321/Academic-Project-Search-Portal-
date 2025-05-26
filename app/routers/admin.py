
from fastapi import APIRouter, Depends, Path, Body, Form, HTTPException, status, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os

from app.database import get_db

# For Excel upload
import pandas as pd
import io
import re
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import create_engine

# Sync/async DB URLs for pandas to_sql
ASYNC_DB_URL = os.getenv("ASYNC_DB_URL", "postgresql+asyncpg://admin:admin123@localhost:5432/mydatabase")
SYNC_DB_URL  = os.getenv("SYNC_DB_URL", "postgresql://admin:admin123@localhost:5432/mydatabase")

async_engine = create_async_engine(ASYNC_DB_URL, echo=True)
sync_engine  = create_engine(SYNC_DB_URL, echo=True)

router = APIRouter(prefix="/admin", tags=["admin"])

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
    Returns list of year-based tables in public schema.
    """
    query = text(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname='public' "
        "AND tablename ~ '^[0-9]{4}_[0-9]{2}$';"
    )
    result = await db.execute(query)
    tables = [row[0] for row in result]
    return {"tables": tables}

@router.get("/tables/{table_name}")
async def get_table(
    table_name: str = Path(..., regex=r"^[0-9]{4}_[0-9]{2}$"),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns all rows from specified table ordered by group_no.
    """
    query = text(f'SELECT * FROM "{table_name}" ORDER BY group_no;')
    result = await db.execute(query)
    rows = result.mappings().all()
    return {"rows": rows}

@router.post("/tables/{table_name}")
async def insert_row(
    table_name: str = Path(..., regex=r"^[0-9]{4}_[0-9]{2}$"),
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Inserts new row into specified table.
    """
    cols = ", ".join(data.keys())
    vals = ", ".join(f":{k}" for k in data.keys())
    query = text(f'INSERT INTO "{table_name}" ({cols}) VALUES ({vals});')
    await db.execute(query, data)
    await db.commit()
    return {"success": True}

@router.put("/tables/{table_name}/{group_no}")
async def update_row(
    table_name: str = Path(..., regex=r"^[0-9]{4}_[0-9]{2}$"),
    group_no: int = Path(...),
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates row identified by group_no in specified table.
    """
    # Remove search_vector from data if present (we'll regenerate it)
    data_clean = {k: v for k, v in data.items() if k != 'search_vector'}
    
    if not data_clean:
        return {"success": True}
    
    assignments = ", ".join(f"{col} = :{col}" for col in data_clean.keys())
    params = {**data_clean, "group_no": group_no}
    
    # Update the row
    query = text(f'UPDATE "{table_name}" SET {assignments} WHERE group_no = :group_no;')
    await db.execute(query, params)
    
    # Regenerate search_vector
    try:
        # Build the search vector update query for this specific row
        text_columns = ['project_title', 'guide_name', 'outcomes']
        
        # For usn and name columns, treat them as text (they contain string representations of arrays)
        text_parts = []
        for col in text_columns:
            text_parts.append(f"COALESCE({col}, '')")
        
        # For usn and name columns, treat them as text
        text_parts.append("COALESCE(usn, '')")
        text_parts.append("COALESCE(name, '')")
        
        concat_expression = " || ' ' || ".join(text_parts)
        
        search_query = text(f'''
            UPDATE "{table_name}"
            SET search_vector = to_tsvector('english', {concat_expression})
            WHERE group_no = :group_no;
        ''')
        await db.execute(search_query, {"group_no": group_no})
    except Exception as e:
        # If search vector update fails, continue anyway
        print(f"Warning: Could not update search vector: {e}")
    
    await db.commit()
    return {"success": True}

@router.delete("/tables/{table_name}/{group_no}")
async def delete_row(
    table_name: str = Path(..., regex=r"^[0-9]{4}_[0-9]{2}$"),
    group_no: int = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes row identified by group_no in specified table.
    """
    query = text(f'DELETE FROM "{table_name}" WHERE group_no = :group_no;')
    await db.execute(query, {"group_no": group_no})
    await db.commit()
    return {"success": True}

# ----------------- Excel Upload Endpoint -----------------

@router.post("/upload-excel")
async def upload_excel(
    request: Request,
    new_table: str = Form(...),
    file: UploadFile = Form(...),
):
    """
    Uploads an Excel file, cleans it using robust logic, and creates a new table.
    """
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=403, detail="Not logged in")

    # Validate table name (e.g., 2025_01)
    if not re.match(r"^[0-9]{4}_[0-9]{2}$", new_table):
        raise HTTPException(status_code=400, detail="Table name must be in YYYY_MM format.")

    # Read Excel file into DataFrame
    contents = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            xls = pd.ExcelFile(io.BytesIO(contents))
            sheet_name = xls.sheet_names[0]
            df = xls.parse(sheet_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File read error: {str(e)}")

    # --- Enhanced cleaning logic based on your Excel structure ---
    def normalize_columns(cols):
        """Normalize column names for consistent matching"""
        normalized = []
        for c in cols:
            if pd.isna(c):
                normalized.append("")
            else:
                normalized.append(str(c).strip().upper().replace('\n', ' ').replace('\\N', '').replace('\\', ''))
        return normalized

    def find_column(columns, keywords):
        """Find column by multiple possible keywords"""
        if isinstance(keywords, str):
            keywords = [keywords]
        
        for keyword in keywords:
            keyword_clean = keyword.lower().replace(" ", "").replace("_", "")
            for i, col in enumerate(columns):
                col_clean = col.lower().replace(" ", "").replace("_", "")
                if keyword_clean in col_clean:
                    return col
        
        raise KeyError(f"Missing column matching any of: {keywords}")

    def clean_and_structure(sheet_df):
        """Clean and structure the Excel data"""
        df = sheet_df.copy()
        
        # Find the header row (look for row containing "GROUP NO" or similar)
        header_row = None
        for i in range(min(5, len(df))):
            row_values = [str(val).upper() for val in df.iloc[i].values if pd.notna(val)]
            if any('GROUP' in val and 'NO' in val for val in row_values):
                header_row = i
                break
        
        if header_row is None:
            # Try using row 2 as default (3rd row, 0-indexed)
            header_row = 2
        
        # Set headers and clean data
        df.columns = df.iloc[header_row]
        df = df[header_row + 1:].reset_index(drop=True)
        
        # Remove completely empty rows
        df = df.dropna(how='all')
        
        # Normalize column names
        df.columns = normalize_columns(df.columns)
        print(f"DEBUG: Columns after normalization: {df.columns.tolist()}")
        
        # Forward-fill merged cells
        df = df.ffill()
        
        # Remove rows where group_no is empty after forward fill
        try:
            group_col = find_column(df.columns, ['groupno', 'group', 'grp'])
            df = df[pd.notna(df[group_col]) & (df[group_col] != '')]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Could not find GROUP NO column. Available columns: {df.columns.tolist()}")
        
        # Identify required columns with flexible matching
        try:
            group_col = find_column(df.columns, ['groupno', 'group', 'grp'])
            usn_col = find_column(df.columns, ['usn'])
            name_col = find_column(df.columns, ['name', 'student'])
            project_col = find_column(df.columns, ['projecttitle', 'project', 'title'])
            guide_col = find_column(df.columns, ['guidename', 'guide', 'mentor'])
            outcome_col = find_column(df.columns, ['outcomes', 'outcome', 'result'])
            proof_col = find_column(df.columns, ['prooflink', 'proof', 'link'])
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"Column mapping error: {str(e)}\nAvailable columns: {df.columns.tolist()}")
        
        # Clean and convert group numbers to integers
        df[group_col] = pd.to_numeric(df[group_col], errors='coerce')
        df = df.dropna(subset=[group_col])
        df[group_col] = df[group_col].astype(int)
        
        # Group the data by group number
        def safe_list(x):
            """Safely convert series to list, filtering out NaN values"""
            return [str(val) for val in x if pd.notna(val) and str(val).strip()]
        
        def safe_first(x):
            """Safely get first non-null value"""
            valid_values = [val for val in x if pd.notna(val) and str(val).strip()]
            return valid_values[0] if valid_values else ""
        
        grouped = df.groupby(group_col).agg({
            usn_col: safe_list,
            name_col: safe_list,
            project_col: safe_first,
            guide_col: safe_first,
            outcome_col: safe_first,
            proof_col: safe_first
        }).reset_index()
        
        # Convert lists to strings for database storage
        grouped[usn_col] = grouped[usn_col].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
        grouped[name_col] = grouped[name_col].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
        
        # Rename columns to match database schema
        grouped.columns = [
            'group_no', 'usn', 'name', 'project_title',
            'guide_name', 'outcomes', 'proof_link'
        ]
        
        # Add missing columns that might be needed
        if 'report_links' not in grouped.columns:
            grouped['report_links'] = ""
        if 'ppt_links' not in grouped.columns:
            grouped['ppt_links'] = ""
        
        # Clean empty strings and None values
        for col in ['project_title', 'guide_name', 'outcomes', 'proof_link', 'report_links', 'ppt_links', 'usn', 'name']:
            grouped[col] = grouped[col].fillna("").astype(str)
            grouped[col] = grouped[col].replace('nan', '')
        
        return grouped

    try:
        cleaned_df = clean_and_structure(df)
        print(f"DEBUG: Successfully cleaned data. Shape: {cleaned_df.shape}")
        print(f"DEBUG: Sample data:\n{cleaned_df.head()}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data cleaning error: {str(e)}")

    if cleaned_df.empty:
        raise HTTPException(status_code=400, detail="No valid data found in the uploaded file")

    # Write to database using sync engine
    try:
        # Drop table if it exists to replace it
        with sync_engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{new_table}"'))
            conn.commit()
        
        # Write cleaned data to database
        cleaned_df.to_sql(new_table, sync_engine, index=False, if_exists="replace")
        
        # Add tsvector column for full-text search
        with sync_engine.connect() as conn:
            # Add search vector column
            conn.execute(text(f'''
                ALTER TABLE "{new_table}"
                ADD COLUMN IF NOT EXISTS search_vector tsvector;
            '''))
            
            # Update search vector with text from relevant columns
            # Since usn and name are now stored as comma-separated text, we can treat them as regular text fields
            text_columns = ['project_title', 'guide_name', 'outcomes', 'usn', 'name']
            
            # Build the search vector update query
            text_parts = []
            for col in text_columns:
                text_parts.append(f"COALESCE({col}, '')")
            
            concat_expression = " || ' ' || ".join(text_parts)
            
            conn.execute(text(f'''
                UPDATE "{new_table}"
                SET search_vector = to_tsvector('english', {concat_expression});
            '''))
            
            # Create GIN index for fast full-text search with a valid index name
            # PostgreSQL index names cannot start with numbers, so prefix with 'idx_'
            index_name = f"idx_{new_table}_search"
            conn.execute(text(f'''
                CREATE INDEX IF NOT EXISTS {index_name}
                ON "{new_table}" USING GIN (search_vector);
            '''))
            
            conn.commit()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {
        "success": True, 
        "table": new_table,
        "rows_imported": len(cleaned_df),
        "message": f"Successfully imported {len(cleaned_df)} groups into table {new_table}"
    }
