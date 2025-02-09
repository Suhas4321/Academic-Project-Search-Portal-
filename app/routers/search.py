from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from typing import Optional

router = APIRouter()

VALID_YEARS = {"2021-22", "2022-23", "2023-24", "2024-25"}

async def search_projects(
    year: str, 
    search_term: str, 
    db: AsyncSession,
    search_type: str = "all"
):
    if year not in VALID_YEARS:
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
            ts_rank({search_vector}, to_tsquery('english', :search_term)) as rank
        FROM "{table_name}"
        WHERE {search_vector} @@ to_tsquery('english', :search_term)
        ORDER BY rank DESC, project_title ASC
    """)
    
    try:
        # Convert space-separated terms to tsquery format
        tsquery_terms = ' & '.join(search_term.split())
        result = await db.execute(query, {"search_term": tsquery_terms})
        return result.mappings().all()
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(status_code=500, detail="Database search error")

async def get_suggestions(
    year: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    if year not in VALID_YEARS:
        raise HTTPException(status_code=400, detail="Invalid academic year format.")
    
    table_name = year.replace("-", "_")
    
    # Select column based on search type
    if search_type == "title":
        column = "project_title"
    elif search_type == "guide":
        column = "guide_name"
    else:
        column = "project_title"  # Default to project_title for suggestions
    
    query = text(f"""
        SELECT DISTINCT {column}
        FROM "{table_name}"
        WHERE to_tsvector('english', {column}) @@ to_tsquery('english', :search_term)
        ORDER BY {column}
        LIMIT 10
    """)
    
    try:
        # Convert space-separated terms to tsquery format
        tsquery_terms = ' & '.join(f"{term}:*" for term in search_term.split())
        result = await db.execute(query, {"search_term": tsquery_terms})
        return [row[0] for row in result]
    except Exception as e:
        print(f"Suggestions error: {e}")
        raise HTTPException(status_code=500, detail="Database error while fetching suggestions")

@router.get("/search/")
async def full_text_search(
    year: str = Query(..., description="Academic year in format YYYY-YY"),
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