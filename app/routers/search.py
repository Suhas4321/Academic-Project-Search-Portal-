from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from typing import Optional, List
import re


router = APIRouter()


# ────────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────────
SAFE_TABLE_RE = re.compile(r"^[A-Za-z0-9_]{1,63}$")      # backend + frontend rule
BLOCKLIST     = {"alembic_version"}                      # skip system tables



async def get_year_tables(db: AsyncSession) -> List[str]:
    """
    Return every user-created table whose name is “safe” (letters / digits /
    underscores, ≤63 chars).  The list is converted from underscores to hyphens
    before being sent to the UI so that names read nicely there.
    """
    query = text(
        """
        SELECT tablename
        FROM   pg_tables
        WHERE  schemaname = 'public'
        """
    )
    result = await db.execute(query)


    tables = [
        row[0] for row in result
        if SAFE_TABLE_RE.match(row[0]) and row[0] not in BLOCKLIST
    ]


    # foo_bar → foo-bar  (purely cosmetic for the frontend)
    return [t.replace("_", "-") for t in sorted(tables)]



async def get_table_columns(db: AsyncSession, table_name: str) -> List[str]:
    query = text(
        """
        SELECT column_name
        FROM   information_schema.columns
        WHERE  table_name   = :table_name
          AND  table_schema = 'public'
        """
    )
    result = await db.execute(query, {"table_name": table_name})
    return [row[0] for row in result]



# ────────────────────────────────────────────────────────────────────────────────
# Core search logic
# ────────────────────────────────────────────────────────────────────────────────
async def search_projects(
    year: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    # ── Search across every table ───────────────────────────────────────────────
    if year == "all":
        tables  = await get_year_tables(db)
        results = []


        for y in tables:
            table_name = y.replace("-", "_")
            try:
                sub = await search_single_table(table_name, search_term, db, search_type)
                for r in sub:
                    r = dict(r)
                    r["project_year"] = y          # keep hyphen format for UI
                    results.append(r)
            except Exception as exc:               # noqa: BLE001 – want wide catch
                print(f"[search] error in {table_name}: {exc}")
                continue


        # sort by year asc  ➜  rank desc
        results.sort(key=lambda x: (x.get("project_year", ""), -x.get("rank", 0)))
        return results


    # ── Single-table search ────────────────────────────────────────────────────
    tables = await get_year_tables(db)
    if year not in tables:
        raise HTTPException(status_code=400, detail="Unknown table name.")


    table_name = year.replace("-", "_")
    sub = await search_single_table(table_name, search_term, db, search_type)


    results = []
    for r in sub:
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
    # figure out which optional columns exist
    columns           = await get_table_columns(db, table_name)
    has_search_vector = "search_vector"  in columns
    has_ppt_links     = "ppt_links"      in columns
    has_report_links  = "report_links"   in columns


    ppt_links_col    = "COALESCE(ppt_links, '')  AS ppt_links"   if has_ppt_links   else "'' AS ppt_links"
    report_links_col = "COALESCE(report_links, '') AS report_links" if has_report_links else "'' AS report_links"


    # build search condition ----------------------------------------------------
    if search_type == "title":
        search_condition = (
            "to_tsvector('english', COALESCE(project_title, '')) "
            "@@ plainto_tsquery('english', :search_term)"
        )
        rank_expression  = (
            "ts_rank(to_tsvector('english', COALESCE(project_title, '')), "
            "plainto_tsquery('english', :search_term))"
        )
    elif search_type == "guide":
        search_condition = (
            "to_tsvector('english', COALESCE(guide_name, '')) "
            "@@ plainto_tsquery('english', :search_term)"
        )
        rank_expression  = (
            "ts_rank(to_tsvector('english', COALESCE(guide_name, '')), "
            "plainto_tsquery('english', :search_term))"
        )
    else:
        if has_search_vector:
            search_condition = "search_vector @@ plainto_tsquery('english', :search_term)"
            rank_expression  = "ts_rank(search_vector, plainto_tsquery('english', :search_term))"
        else:
            weighted_vector = """
                setweight(to_tsvector('english', COALESCE(project_title, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(guide_name,  '')), 'B')
            """
            search_condition = f"({weighted_vector}) @@ plainto_tsquery('english', :search_term)"
            rank_expression  = f"ts_rank(({weighted_vector}), plainto_tsquery('english', :search_term))"


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
            {rank_expression} AS rank
        FROM "{table_name}"
        WHERE {search_condition}
        ORDER BY rank DESC, project_title ASC
    """)


    try:
        result = await db.execute(query, {"search_term": search_term})
        return result.mappings().all()
    except Exception as exc:                     # noqa: BLE001 – want wide catch
        print(f"[search] query error in {table_name}: {exc}")
        return []



# ────────────────────────────────────────────────────────────────────────────────
# Autocomplete helpers
# ────────────────────────────────────────────────────────────────────────────────
async def get_suggestions(
    year: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    if year == "all":
        tables          = await get_year_tables(db)
        all_suggestions = set()


        for y in tables:
            try:
                sub = await get_table_suggestions(y.replace("-", "_"), search_term, db, search_type)
                all_suggestions.update(sub)
            except Exception as exc:
                print(f"[suggest] error in {y}: {exc}")
                continue


        return sorted(all_suggestions)[:10]


    tables = await get_year_tables(db)
    if year not in tables:
        raise HTTPException(status_code=400, detail="Unknown table name.")


    return await get_table_suggestions(year.replace("-", "_"), search_term, db, search_type)



async def get_table_suggestions(
    table_name: str,
    search_term: str,
    db: AsyncSession,
    search_type: str = "all"
):
    # decide which column(s) to sample for suggestions -------------------------
    if search_type == "title":
        column = "project_title"
    elif search_type == "guide":
        column = "guide_name"
    else:
        # title + guide combined
        query = text(f"""
            (SELECT DISTINCT project_title AS suggestion
             FROM   "{table_name}"
             WHERE  to_tsvector('english', COALESCE(project_title, ''))
                    @@ plainto_tsquery('english', :search_term)
               AND  project_title <> ''
             LIMIT 5)
            UNION
            (SELECT DISTINCT guide_name AS suggestion
             FROM   "{table_name}"
             WHERE  to_tsvector('english', COALESCE(guide_name, ''))
                    @@ plainto_tsquery('english', :search_term)
               AND  guide_name <> ''
             LIMIT 5)
            ORDER BY suggestion
            LIMIT 10
        """)
        result = await db.execute(query, {"search_term": search_term})
        return [row[0] for row in result if row[0]]


    # single column suggestion query ------------------------------------------
    query = text(f"""
        SELECT DISTINCT {column}
        FROM   "{table_name}"
        WHERE  to_tsvector('english', COALESCE({column}, ''))
               @@ plainto_tsquery('english', :search_term)
          AND  {column} <> ''
        ORDER BY {column}
        LIMIT 5
    """)
    result = await db.execute(query, {"search_term": search_term})
    return [row[0] for row in result if row[0]]



# ────────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────────
@router.get("/years")
async def get_years(db: AsyncSession = Depends(get_db)):
    """
    Return every available data table name (with hyphens instead of underscores
    for readability).
    """
    years = await get_year_tables(db)
    return {"years": years}



@router.get("/search/")
async def full_text_search(
    year: str = Query(..., description="Table name shown in the dropdown or 'all'"),
    q:   str = Query(..., min_length=2),
    search_type: Optional[str] = Query("all", regex="^(all|title|guide)$"),
    db:  AsyncSession = Depends(get_db)
):
    results = await search_projects(year, q, db, search_type)
    return {"results": results}



@router.get("/suggestions/")
async def get_search_suggestions(
    year: str = Query(..., description="Table name shown in the dropdown or 'all'"),
    q:   str = Query(..., min_length=2),
    search_type: Optional[str] = Query("all", regex="^(all|title|guide)$"),
    db:  AsyncSession = Depends(get_db)
):
    suggestions = await get_suggestions(year, q, db, search_type)
    return {"suggestions": suggestions}