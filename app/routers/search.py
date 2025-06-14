
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from typing import Optional, List

router = APIRouter()

# Utility to get all year tables dynamically
async def get_year_tables(db: AsyncSession) -> List[str]:
    query = text("""
        SELECT tablename FROM pg_tables
        WHERE schemaname='public'
        AND tablename ~ '^[0-9]{4}_[0-9]{2}$'
        ORDER BY tablename ASC
    """)
    result = await db.execute(query)
    tables = [row[0] for row in result]
    # Convert 2024_25 -> 2024-25 for frontend
    return [t.replace("_", "-") for t in tables]

# Utility to check what columns exist in a table
async def get_table_columns(db: AsyncSession, table_name: str) -> List[str]:
    query = text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = :table_name 
        AND table_schema = 'public'
    """)
    result = await db.execute(query, {"table_name": table_name})
    return [row[0] for row in result]

async def search_projects(
    year: str, 
    search_term: str, 
    db: AsyncSession,
    search_type: str = "all"
):
    # Handle "all" for searching across all years
    if year == "all":
        tables = await get_year_tables(db)
        results = []
        for y in tables:
            table_name = y.replace("-", "_")
            try:
                sub_results = await search_single_table(table_name, search_term, db, search_type)
                # Add project_year for display
                for r in sub_results:
                    r = dict(r)
                    r["project_year"] = y
                    results.append(r)
            except Exception as e:
                print(f"Error searching table {table_name}: {e}")
                continue
        
        # Sort results by project_year (ascending) then by rank (descending)
        results.sort(key=lambda x: (x.get("project_year", ""), -x.get("rank", 0)))
        return results

    # Validate year
    tables = await get_year_tables(db)
    if year not in tables:
        raise HTTPException(status_code=400, detail="Invalid academic year format.")

    table_name = year.replace("-", "_")
    sub_results = await search_single_table(table_name, search_term, db, search_type)
    
    # Add project_year for display
    results = []
    for r in sub_results:
        r = dict(r)
        r["project_year"] = year
        results.append(r)
    
    return results

async def search_single_table(
    table_name: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    # Get available columns for this table
    columns = await get_table_columns(db, table_name)
    
    # Check if table has search_vector column
    has_search_vector = "search_vector" in columns
    has_ppt_links = "ppt_links" in columns
    has_report_links = "report_links" in columns
    
    # Build column selection with fallbacks for missing columns
    ppt_links_col = "COALESCE(ppt_links, '') as ppt_links" if has_ppt_links else "'' as ppt_links"
    report_links_col = "COALESCE(report_links, '') as report_links" if has_report_links else "'' as report_links"
    
    # Build the search condition and rank expression based on available columns
    if search_type == "title":
        search_condition = "to_tsvector('english', COALESCE(project_title, '')) @@ plainto_tsquery('english', :search_term)"
        rank_expression = "ts_rank(to_tsvector('english', COALESCE(project_title, '')), plainto_tsquery('english', :search_term))"
    elif search_type == "guide":
        search_condition = "to_tsvector('english', COALESCE(guide_name, '')) @@ plainto_tsquery('english', :search_term)"
        rank_expression = "ts_rank(to_tsvector('english', COALESCE(guide_name, '')), plainto_tsquery('english', :search_term))"
    else:
        # Use search_vector if available, otherwise create weighted vector on the fly
        if has_search_vector:
            search_condition = "search_vector @@ plainto_tsquery('english', :search_term)"
            rank_expression = "ts_rank(search_vector, plainto_tsquery('english', :search_term))"
        else:
            # Create weighted search vector on the fly for older tables
            weighted_vector = """
                setweight(to_tsvector('english', COALESCE(project_title, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(guide_name, '')), 'B')
            """
            search_condition = f"({weighted_vector}) @@ plainto_tsquery('english', :search_term)"
            rank_expression = f"ts_rank(({weighted_vector}), plainto_tsquery('english', :search_term))"

    query = text(f"""
        SELECT 
            group_no,
            usn,
            name,
            project_title,
            guide_name,
            outcomes,
            proof_link,
            {ppt_links_col},
            {report_links_col},
            {rank_expression} as rank
        FROM "{table_name}"
        WHERE {search_condition}
        ORDER BY rank DESC, project_title ASC
    """)
    
    try:
        result = await db.execute(query, {"search_term": search_term})
        return result.mappings().all()
    except Exception as e:
        print(f"Search error in table {table_name}: {e}")
        return []

async def get_suggestions(
    year: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    if year == "all":
        tables = await get_year_tables(db)
        all_suggestions = set()
        for y in tables:
            table_name = y.replace("-", "_")
            try:
                suggestions = await get_table_suggestions(table_name, search_term, db, search_type)
                all_suggestions.update(suggestions)
            except Exception as e:
                print(f"Error getting suggestions from table {table_name}: {e}")
                continue
        return sorted(list(all_suggestions))[:10]
    
    tables = await get_year_tables(db)
    if year not in tables:
        raise HTTPException(status_code=400, detail="Invalid academic year format.")

    table_name = year.replace("-", "_")
    return await get_table_suggestions(table_name, search_term, db, search_type)

async def get_table_suggestions(
    table_name: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    if search_type == "title":
        column = "project_title"
    elif search_type == "guide":
        column = "guide_name"
    else:
        # For "all", get suggestions from both project_title and guide_name
        query = text(f"""
            (SELECT DISTINCT project_title as suggestion
             FROM "{table_name}"
             WHERE to_tsvector('english', COALESCE(project_title, '')) @@ plainto_tsquery('english', :search_term)
             AND project_title IS NOT NULL AND project_title != ''
             LIMIT 5)
            UNION
            (SELECT DISTINCT guide_name as suggestion
             FROM "{table_name}"
             WHERE to_tsvector('english', COALESCE(guide_name, '')) @@ plainto_tsquery('english', :search_term)
             AND guide_name IS NOT NULL AND guide_name != ''
             LIMIT 5)
            ORDER BY suggestion
            LIMIT 10
        """)
        try:
            result = await db.execute(query, {"search_term": search_term})
            return [row[0] for row in result if row[0]]
        except Exception as e:
            print(f"Suggestions error in table {table_name}: {e}")
            return []

    query = text(f"""
        SELECT DISTINCT {column}
        FROM "{table_name}"
        WHERE to_tsvector('english', COALESCE({column}, '')) @@ plainto_tsquery('english', :search_term)
        AND {column} IS NOT NULL AND {column} != ''
        ORDER BY {column}
        LIMIT 5
    """)
    try:
        result = await db.execute(query, {"search_term": search_term})
        return [row[0] for row in result if row[0]]
    except Exception as e:
        print(f"Suggestions error in table {table_name}: {e}")
        return []

@router.get("/years")
async def get_years(db: AsyncSession = Depends(get_db)):
    """Return all available academic years (tables) in YYYY-YY format."""
    years = await get_year_tables(db)
    return {"years": years}

@router.get("/search/")
async def full_text_search(
    year: str = Query(..., description="Academic year in format YYYY-YY or 'all'"),
    q: str = Query(..., min_length=2),
    search_type: Optional[str] = Query("all", description="Search type: 'all', 'title', or 'guide'"),
    db: AsyncSession = Depends(get_db)
):
    results = await search_projects(year, q, db, search_type)
    return {"results": results}

@router.get("/suggestions/")
async def get_search_suggestions(
    year: str = Query(..., description="Academic year in format YYYY-YY or 'all'"),
    q: str = Query(..., min_length=2),
    search_type: Optional[str] = Query("all", description="Search type: 'all', 'title', or 'guide'"),
    db: AsyncSession = Depends(get_db)
):
    suggestions = await get_suggestions(year, q, db, search_type)
    return {"suggestions": suggestions}
