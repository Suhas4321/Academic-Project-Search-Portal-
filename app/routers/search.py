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
        ORDER BY tablename DESC
    """)
    result = await db.execute(query)
    tables = [row[0] for row in result]
    # Convert 2024_25 -> 2024-25 for frontend
    return [t.replace("_", "-") for t in tables]

async def search_projects(
    year: str, 
    search_term: str, 
    db: AsyncSession,
    search_type: str = "all"
):
    # Accept "all" for searching across all years
    if year == "all":
        tables = await get_year_tables(db)
        results = []
        for y in tables:
            table_name = y.replace("-", "_")
            try:
                sub_results = await search_projects(y, search_term, db, search_type)
                # Add project_year for display
                for r in sub_results:
                    r = dict(r)
                    r["project_year"] = y
                    results.append(r)
            except Exception:
                continue
        return results

    # Validate year
    tables = await get_year_tables(db)
    if year not in tables:
        raise HTTPException(status_code=400, detail="Invalid academic year format.")

    table_name = year.replace("-", "_")
    # Build the search query based on type
    if search_type == "title":
        search_vector = "setweight(to_tsvector('english', project_title), 'A')"
    elif search_type == "guide":
        search_vector = "setweight(to_tsvector('english', guide_name), 'A')"
    else:
        search_vector = "search_vector"  # Use pre-computed vector

    query = text(f"""
        SELECT 
            group_no,
            usn,
            name,
            project_title,
            guide_name,
            outcomes,
            proof_link,
            ppt_links,
            report_links,
            ts_rank({search_vector}, to_tsquery('english', :search_term)) as rank
        FROM "{table_name}"
        WHERE {search_vector} @@ to_tsquery('english', :search_term)
        ORDER BY rank DESC, project_title ASC
    """)
    try:
        tsquery_terms = ' & '.join(search_term.split())
        result = await db.execute(query, {"search_term": tsquery_terms})
        rows = result.mappings().all()
        # Add project_year for display
        for r in rows:
            r = dict(r)
            r["project_year"] = year
        return rows
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(status_code=500, detail="Database search error")

async def get_suggestions(
    year: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    tables = await get_year_tables(db)
    if year not in tables:
        raise HTTPException(status_code=400, detail="Invalid academic year format.")

    table_name = year.replace("-", "_")
    if search_type == "title":
        column = "project_title"
    elif search_type == "guide":
        column = "guide_name"
    else:
        column = "project_title"

    query = text(f"""
        SELECT DISTINCT {column}
        FROM "{table_name}"
        WHERE to_tsvector('english', {column}) @@ to_tsquery('english', :search_term)
        ORDER BY {column}
        LIMIT 10
    """)
    try:
        tsquery_terms = ' & '.join(f"{term}:*" for term in search_term.split())
        result = await db.execute(query, {"search_term": tsquery_terms})
        return [row[0] for row in result]
    except Exception as e:
        print(f"Suggestions error: {e}")
        raise HTTPException(status_code=500, detail="Database error while fetching suggestions")

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
    year: str = Query(..., description="Academic year in format YYYY-YY"),
    q: str = Query(..., min_length=2),
    search_type: Optional[str] = Query("all", description="Search type: 'all', 'title', or 'guide'"),
    db: AsyncSession = Depends(get_db)
):
    suggestions = await get_suggestions(year, q, db, search_type)
    return {"suggestions": suggestions}