import os
import re
import sys
import json
import asyncio
import urllib.parse
from typing import List, Optional
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

import time
import secrets

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import main
from neo4j import GraphDatabase
from pinecone import Pinecone
from contextlib import asynccontextmanager

# ---------------------------------------------------------
# Startup / Shutdown Lifespan (keep-alive ping task)
# ---------------------------------------------------------
RENDER_BACKEND_URL = os.getenv("RENDER_BACKEND_URL", "https://moviegraph-ai.onrender.com")

async def _keep_alive_ping():
    """Pings /health every 14 minutes so Render free-tier never sleeps."""
    import httpx
    await asyncio.sleep(30)  # wait for server to fully start first
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{RENDER_BACKEND_URL}/health")
                print(f"[KEEP-ALIVE] ping → {r.status_code}")
        except Exception as e:
            print(f"[KEEP-ALIVE] ping failed: {e}")
        await asyncio.sleep(14 * 60)   # 14 minutes

@asynccontextmanager
async def lifespan(application: FastAPI):
    task = asyncio.create_task(_keep_alive_ping())
    print("[KEEP-ALIVE] Background ping task started (every 14 min → /health)")
    yield
    task.cancel()

app = FastAPI(title="MovieGraph AI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Strict Environment & Security Protection Middleware
@app.middleware("http")
async def block_sensitive_files(request: Request, call_next):
    raw_path = request.url.path.lower()
    # Block any attempt to inspect .env, server configs, or secrets
    if any(bad in raw_path for bad in [".env", "checkpoint", "secret", ".git", ".pyc"]):
        return JSONResponse(status_code=403, content={"detail": "Access forbidden: Protected system resource"})
    return await call_next(request)

# Neo4j connection helper
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USERNAME")
NEO4J_PWD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DATABASE")

def get_neo4j_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))

# Curated backdrop mapping for prominent films
POSTER_DATABASE = {
    "inception": "https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=1200&q=80",
    "the matrix": "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1200&q=80",
    "donnie darko": "https://images.unsplash.com/photo-1509347528160-9a9e33742cdb?auto=format&fit=crop&w=1200&q=80",
    "eternal sunshine": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
    "the prestige": "https://images.unsplash.com/photo-1478760329108-5c3ed9d495a0?auto=format&fit=crop&w=1200&q=80",
    "the godfather": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=1200&q=80",
    "the dark knight": "https://images.unsplash.com/photo-1509347528160-9a9e33742cdb?auto=format&fit=crop&w=1200&q=80",
    "interstellar": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80",
    "forrest gump": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=1200&q=80",
    "memento": "https://images.unsplash.com/photo-1594909122845-11baa439b7bf?auto=format&fit=crop&w=1200&q=80",
    "tenet": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
    "paprika": "https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=1200&q=80",
    "coherence": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80",
    "annihilation": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
    "pulp fiction": "https://images.unsplash.com/photo-1594909122845-11baa439b7bf?auto=format&fit=crop&w=1200&q=80",
    "default": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=1200&q=80"
}

def get_backdrop(title: str) -> str:
    cleaned = title.lower().strip()
    for key, url in POSTER_DATABASE.items():
        if key in cleaned:
            return url
    return POSTER_DATABASE["default"]

# Common non-movie words to exclude from title matching
STOP_WORDS = {
    "work", "works", "revenge", "love", "game", "life", "time", "story", "stories",
    "cinema", "movie", "movies", "film", "films", "director", "directors", "unknown",
    "true", "false", "good", "year", "years", "theme", "themes", "overview", "sources",
    "scene", "scenes", "world", "depth", "reality", "dreams", "plot"
}

# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------
class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = "default"
    user_id: Optional[str] = None
    history: Optional[List[dict]] = []

class UserValidateRequest(BaseModel):
    user_id: Optional[str] = None

# ---------------------------------------------------------
# Core Helper: Extract Genuine Movies & Clean Top 4-5 Sources
# ---------------------------------------------------------
def extract_snippet_for_movie(candidate: str, text: str) -> tuple[str, str, str, str]:
    """Extracts authentic snippet, year/seasons, director/creator, and media genre for movies or web series."""
    # 1. Search for bullet or numbered entry with candidate
    pattern = rf"(?:^|\n)[#*\s\d\.\-—:]*{re.escape(candidate)}[^\n:]*[-—:\n]+([^\n#]+)"
    m = re.search(pattern, text, re.IGNORECASE)
    snippet = ""
    if m:
        raw_snippet = m.group(1).strip()
        cleaned_snippet = re.sub(r"[*_`]", "", raw_snippet).strip()
        if len(cleaned_snippet) > 15:
            snippet = (cleaned_snippet[:170] + "...") if len(cleaned_snippet) > 170 else cleaned_snippet

    # 2. Extract year or series duration e.g. (2024), (2008–2013), (Season 1-3)
    year_match = re.search(rf"{re.escape(candidate)}[^\n(]*\(((?:19|20)\d\d(?:[–\-](?:19|20)?\d\d)?|Season\s*\d+)\)", text, re.IGNORECASE)
    year = year_match.group(1) if year_match else "Featured"

    # 3. Extract director or creator/showrunner
    creator_match = re.search(rf"(?:Creator|Created by|Showrunner|Director|Directed by)[:\s]+([A-Za-z\s\.\-]{{2,30}})", text, re.IGNORECASE)
    director = creator_match.group(1).strip().split(",")[0] if creator_match else "Cinema / Web Series"

    # 4. Media category (Web Series vs Film)
    category = "Curated Cinema"
    pos = text.lower().find(candidate.lower())
    nearby_text = text[max(0, pos - 100):min(len(text), pos + 250)] if pos != -1 else text
    if any(term in nearby_text.lower() for term in ["web series", "series", "season", "episodes", "showrunner", "limited series", "tv series", "miniseries", "ott"]):
        category = "Web Series"

    if not snippet:
        # Fallback to sentence mentioning candidate
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for s in sentences:
            if candidate.lower() in s.lower() and len(s) > 25 and not s.strip().startswith("#"):
                clean_s = re.sub(r"[*_`#]", "", s).strip()
                snippet = (clean_s[:170] + "...") if len(clean_s) > 170 else clean_s
                break

    if not snippet:
        snippet = f"Curated cinema & series work featuring standout narrative depth, performances, and thematic resonance."

    return snippet, year, director, category

def process_chat_result(query: str, answer_markdown: str) -> dict:
    # 1. Clean meta-commentary if the LLM leaked apologies, constraints or search preambles
    cleaned_answer = re.sub(
        r"^(?:Movies similar to [^\n]+\n+)?(?:It seems the initial query did not yield[^\n]*\n*)+(?:However,[^\n]*\n*)*",
        "",
        answer_markdown,
        flags=re.IGNORECASE
    ).strip()
    cleaned_answer = re.sub(
        r"^(?:I apologize, but.*?\n\n|Based on the live web search.*?\n\n)",
        "",
        cleaned_answer,
        flags=re.IGNORECASE | re.DOTALL
    ).strip()

    # Normalize double/nested headings like '#### **### Overview**' or '### **### Overview**' -> '### Overview'
    cleaned_answer = re.sub(r'#{1,6}\s*(?:\*{1,2}|_{1,2})?\s*#{1,6}\s*', '### ', cleaned_answer)
    cleaned_answer = re.sub(r'(?m)^(#{1,6}\s+)(?:\*{1,2}|_{1,2})\s*(.*?)\s*(?:\*{1,2}|_{1,2})$', r'\1\2', cleaned_answer)
    # Ensure headings always have preceding blank lines so Markdown parsers recognize them as ATX headers
    cleaned_answer = re.sub(r'([^\n])\n(#{1,6}\s+)', r'\1\n\n\2', cleaned_answer)

    # 2. Extract specific candidate movie titles from markdown recommendations
    candidate_titles = []
    
    # Pattern A: Any line with title followed by release year (19xx or 20xx)
    line_year_matches = re.findall(
        r"(?:^|\n)[#*\s\d\.\-—:]*?([A-Za-z0-9][A-Za-z0-9\s:,\'-]{1,40}?)[*_]*\s*\(((?:19|20)\d\d)\)",
        cleaned_answer
    )
    for match in line_year_matches:
        if isinstance(match, tuple):
            candidate_titles.append(match[0].strip())
        else:
            candidate_titles.append(match.strip())

    # Pattern B: Numbered items like "1. The Matrix" or "1. **The Matrix**"
    numbered_matches = re.findall(r"(?:^|\n)\d+\.\s+(?:\*\*|\*|_)?([A-Za-z0-9\s:,'-]{2,45}?)(?:\*\*|\*|_)?(?:\s*[-—:]|\n)", cleaned_answer)
    candidate_titles.extend([m.strip() for m in numbered_matches if m.strip()])

    # Pattern C: Extract directly from premier source citations e.g. [Wikipedia: The Matrix] or [IMDb: The Prestige]
    source_title_matches = re.findall(r"\[(?:Wikipedia|IMDb|The Guardian|Rotten Tomatoes):\s*([A-Za-z0-9\s:,'-]{2,45}?)\]", cleaned_answer, re.IGNORECASE)
    candidate_titles.extend([s.strip() for s in source_title_matches if s.strip()])

    # Clean and filter candidate titles
    filtered_candidates = []
    for ct in candidate_titles:
        cleaned_ct = re.sub(r"^\d+\.\s*", "", ct).strip().strip("*").strip("_").strip('"')
        if cleaned_ct.lower() not in STOP_WORDS and len(cleaned_ct) > 2 and len(cleaned_ct) < 45:
            if not any(sw in cleaned_ct.lower() for sw in ["director", "synopsis", "themes", "recommendation", "overview", "sources"]):
                if cleaned_ct not in filtered_candidates:
                    filtered_candidates.append(cleaned_ct)

    # Fallback: If no candidate extracted from lists, check if query itself is a movie
    if not filtered_candidates:
        clean_q = re.sub(r"\b(movie|film|cinema|tell me about|recommend|films similar to|similar to|movies like|details of|who directed|what is)\b", "", query, flags=re.IGNORECASE).strip()
        if clean_q and len(clean_q) > 2 and clean_q.lower() not in STOP_WORDS:
            filtered_candidates.append(clean_q)

    # 3. Match against Neo4j Knowledge Graph
    matched_movies = []
    graph_nodes = []
    graph_links = []

    driver = get_neo4j_driver()
    try:
        with driver.session(database=NEO4J_DB) as s:
            # Query Neo4j for each legitimate candidate title
            for candidate in filtered_candidates[:5]:
                cypher = """
                MATCH (m:Movie)
                WHERE toLower(m.title) = toLower($cand) OR toLower(m.title) CONTAINS toLower($cand)
                OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
                OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
                OPTIONAL MATCH (a:Person)-[:ACTED_IN]->(m)
                RETURN m.title AS title, m.releaseYear AS year, m.plot AS plot,
                       m.wikiPage AS wikiPage, d.name AS director, g.name AS genre,
                       collect(DISTINCT a.name)[..4] AS cast
                LIMIT 1
                """
                rec = s.run(cypher, cand=candidate).data()
                if rec:
                    r = rec[0]
                    m_title = r["title"]
                    matched_movies.append({
                        "title": m_title,
                        "year": str(r.get("year") or ""),
                        "director": r.get("director") or "Unknown",
                        "genre": (r.get("genre") or "Cinema").capitalize(),
                        "plot": (r.get("plot")[:180] + "...") if r.get("plot") else "",
                        "wiki_url": r.get("wikiPage") or "",
                        "backdrop": get_backdrop(m_title)
                    })

                    # Graph links
                    graph_nodes.append({"id": m_title, "label": m_title, "type": "movie"})
                    if r.get("director"):
                        d_id = f"dir_{r['director']}"
                        graph_nodes.append({"id": d_id, "label": r["director"], "type": "director"})
                        graph_links.append({"source": d_id, "target": m_title, "label": "DIRECTED"})

                    if r.get("genre"):
                        g_id = f"genre_{r['genre']}"
                        graph_nodes.append({"id": g_id, "label": r["genre"].capitalize(), "type": "genre"})
                        graph_links.append({"source": m_title, "target": g_id, "label": "HAS_GENRE"})

                    for actor in (r.get("cast") or []):
                        if actor and actor != "nan":
                            a_id = f"act_{actor}"
                            graph_nodes.append({"id": a_id, "label": actor, "type": "actor"})
                            graph_links.append({"source": a_id, "target": m_title, "label": "ACTED_IN"})
                else:
                    # Construct movie/series card dynamically with authentic extracted snippet
                    dyn_plot, dyn_year, dyn_dir, dyn_genre = extract_snippet_for_movie(candidate, cleaned_answer)
                    matched_movies.append({
                        "title": candidate,
                        "year": dyn_year,
                        "director": dyn_dir,
                        "genre": dyn_genre,
                        "plot": dyn_plot,
                        "wiki_url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(candidate.replace(' ', '_'))}",
                        "backdrop": get_backdrop(candidate)
                    })
                    graph_nodes.append({"id": candidate, "label": candidate, "type": "movie" if dyn_genre != "Web Series" else "series"})
                    if dyn_dir and dyn_dir not in ["Cinema Classic", "Cinema / Web Series"]:
                        d_id = f"dir_{dyn_dir}"
                        graph_nodes.append({"id": d_id, "label": dyn_dir, "type": "director"})
                        graph_links.append({"source": d_id, "target": candidate, "label": "DIRECTED" if dyn_genre != "Web Series" else "CREATED"})

    except Exception as e:
        print(f"[WARN] Card extraction notice: {e}")
    finally:
        driver.close()

    unique_nodes = list({n["id"]: n for n in graph_nodes}.values())

    # 4. Extract and clean sources (Limit to BEST 4-5 verified sources)
    all_url_matches = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', cleaned_answer)
    sources = []
    seen_urls = set()

    for title, url in all_url_matches:
        # Filter out noisy or repetitive inline links like "[Wikipedia]" or "[IMDb]"
        clean_title = title.strip()
        if clean_title.lower() in ["wikipedia", "imdb", "the guardian", "box office mojo"]:
            slug = url.split("/")[-1].replace("_", " ").replace("-", " ")
            clean_title = f"{clean_title}: {urllib.parse.unquote(slug)}"

        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        if url not in seen_urls and len(sources) < 5:
            seen_urls.add(url)
            sources.append({
                "title": clean_title,
                "url": url,
                "domain": domain
            })

    # Clean inline repetitive "[Wikipedia] | [IMDb]" links from the markdown body
    display_markdown = re.sub(
        r"\[(?:Wikipedia|IMDb)\]\(https?://[^\)]+\)(?:\s*\|\s*\[(?:Wikipedia|IMDb)\]\(https?://[^\)]+\))?",
        "",
        cleaned_answer
    ).strip()

    # Final markdown header normalization
    display_markdown = re.sub(r'#{1,6}\s*(?:\*{1,2}|_{1,2})?\s*#{1,6}\s*', '### ', display_markdown)
    display_markdown = re.sub(r'(?m)^(#{1,6}\s+)(?:\*{1,2}|_{1,2})\s*(.*?)\s*(?:\*{1,2}|_{1,2})$', r'\1\2', display_markdown)
    display_markdown = re.sub(r'([^\n])\n(#{1,6}\s+)', r'\1\n\n\2', display_markdown)

    retrieval_status = {
        "neo4j": True,
        "pinecone": True,
        "wikipedia": True,
        "tavily": True
    }

    return {
        "answer": display_markdown,
        "movies": matched_movies[:5],  # Best 4-5 cards max
        "graph": {
            "nodes": unique_nodes,
            "links": graph_links
        },
        "sources": sources[:5],        # Best 4-5 sources max
        "retrieval": retrieval_status
    }

# ---------------------------------------------------------
# Health Check — keeps Render backend alive 24/7
# ---------------------------------------------------------
_SERVER_START_TIME = time.time()

@app.get("/health")
def health_check():
    """
    Lightweight health probe.
    - Used by Render's health check system
    - Pinged every 14 min by the built-in keep-alive task
    - Can be monitored externally (UptimeRobot, BetterStack, etc.)
    """
    uptime_seconds = int(time.time() - _SERVER_START_TIME)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return JSONResponse(content={
        "status": "healthy",
        "service": "MovieGraph AI",
        "version": "1.0.0",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_seconds,
        "timestamp": int(time.time()),
    })

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.get("/api/stats")
def get_stats():
    neo_movies = 0
    neo_persons = 0
    neo_rels = 0
    vector_count = 0

    try:
        driver = get_neo4j_driver()
        with driver.session(database=NEO4J_DB) as s:
            neo_movies = s.run("MATCH (m:Movie) RETURN count(m) AS c").single()["c"]
            neo_persons = s.run("MATCH (p:Person) RETURN count(p) AS c").single()["c"]
            neo_rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        driver.close()
    except Exception as e:
        print(f"[WARN] Error fetching Neo4j stats: {e}")

    try:
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        stats = pc.Index(os.getenv("PINECONE_INDEX_NAME", "vectordb")).describe_index_stats()
        vector_count = stats.total_vector_count
    except Exception as e:
        print(f"[WARN] Error fetching Pinecone stats: {e}")

    return {
        "status": "online",
        "movies_count": neo_movies,
        "persons_count": neo_persons,
        "relationships_count": neo_rels,
        "vectors_count": vector_count,
        "dataset_total": 34886
    }

@app.get("/api/movies")
def get_featured_movies(limit: int = 15, query: Optional[str] = None):
    driver = get_neo4j_driver()
    movies = []
    try:
        with driver.session(database=NEO4J_DB) as s:
            if query:
                cypher = """
                MATCH (m:Movie)
                WHERE toLower(m.title) CONTAINS toLower($query)
                OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
                OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
                RETURN m.title AS title, m.releaseYear AS year, m.plot AS plot,
                       m.wikiPage AS wikiPage, d.name AS director, g.name AS genre
                LIMIT $limit
                """
                results = s.run(cypher, query=query, limit=limit).data()
            else:
                cypher = """
                MATCH (m:Movie)
                WHERE m.plot IS NOT NULL AND size(m.plot) > 100
                OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
                OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
                RETURN m.title AS title, m.releaseYear AS year, m.plot AS plot,
                       m.wikiPage AS wikiPage, d.name AS director, g.name AS genre
                ORDER BY m.releaseYear DESC
                LIMIT $limit
                """
                results = s.run(cypher, limit=limit).data()

            for r in results:
                title = r.get("title") or "Unknown"
                plot_raw = r.get("plot") or ""
                plot_excerpt = (plot_raw[:220] + "...") if len(plot_raw) > 220 else plot_raw
                movies.append({
                    "title": title,
                    "year": str(r.get("year") or ""),
                    "director": r.get("director") or "Unknown",
                    "genre": (r.get("genre") or "Cinema").capitalize(),
                    "plot": plot_excerpt,
                    "wiki_url": r.get("wikiPage") or "",
                    "backdrop": get_backdrop(title)
                })
    finally:
        driver.close()

    return {"movies": movies}

@app.get("/api/movies/{title}")
def get_movie_detail(title: str):
    driver = get_neo4j_driver()
    try:
        with driver.session(database=NEO4J_DB) as s:
            cypher = """
            MATCH (m:Movie)
            WHERE toLower(m.title) = toLower($title)
            OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
            OPTIONAL MATCH (a:Person)-[:ACTED_IN]->(m)
            OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
            RETURN m.title AS title, m.releaseYear AS year, m.origin AS origin,
                   m.plot AS plot, m.wikiPage AS wikiPage,
                   collect(DISTINCT d.name) AS directors,
                   collect(DISTINCT a.name) AS actors,
                   collect(DISTINCT g.name) AS genres
            LIMIT 1
            """
            res = s.run(cypher, title=title).single()
            if not res or not res["title"]:
                raise HTTPException(status_code=404, detail="Movie not found in knowledge graph")

            movie_title = res["title"]
            directors = [d for d in res["directors"] if d and d != "nan"]
            actors = [a for a in res["actors"] if a and a != "nan"][:8]
            genres = [g for g in res["genres"] if g and g != "nan" and g != "unknown"]

            nodes = [{"id": movie_title, "label": movie_title, "type": "movie"}]
            links = []

            for d in directors:
                nodes.append({"id": f"person_{d}", "label": d, "type": "director"})
                links.append({"source": f"person_{d}", "target": movie_title, "label": "DIRECTED"})

            for a in actors:
                nodes.append({"id": f"person_{a}", "label": a, "type": "actor"})
                links.append({"source": f"person_{a}", "target": movie_title, "label": "ACTED_IN"})

            for g in genres:
                nodes.append({"id": f"genre_{g}", "label": g.capitalize(), "type": "genre"})
                links.append({"source": movie_title, "target": f"genre_{g}", "label": "HAS_GENRE"})

            return {
                "title": movie_title,
                "year": str(res["year"] or ""),
                "origin": res["origin"] or "Unknown",
                "directors": directors,
                "actors": actors,
                "genres": genres,
                "plot": res["plot"] or "",
                "wiki_url": res["wikiPage"] or "",
                "backdrop": get_backdrop(movie_title),
                "graph": {"nodes": nodes, "links": links}
            }
    finally:
        driver.close()

@app.get("/api/graph")
def get_graph_slice(limit: int = 150, focus: Optional[str] = None):
    driver = get_neo4j_driver()
    nodes_dict = {}
    links = []

    try:
        with driver.session(database=NEO4J_DB) as s:
            if focus:
                focus_term = focus.strip().lower()
                # 1. Search movie titles matching focus
                cypher_movie = """
                MATCH (m:Movie)
                WHERE toLower(m.title) CONTAINS toLower($focus)
                OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
                OPTIONAL MATCH (a:Person)-[:ACTED_IN]->(m)
                OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
                RETURN d.name AS director, m.title AS movie, m.releaseYear AS year,
                       collect(DISTINCT g.name)[..3] AS genres,
                       collect(DISTINCT a.name)[..5] AS actors
                LIMIT 35
                """
                results = s.run(cypher_movie, focus=focus_term).data()

                # 2. If few or no movies found, search person names (directors/actors)
                if len(results) < 5:
                    cypher_person = """
                    MATCH (p:Person)
                    WHERE toLower(p.name) CONTAINS toLower($focus)
                    MATCH (p)-[r]->(m:Movie)
                    OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
                    OPTIONAL MATCH (other:Person)-[:ACTED_IN]->(m)
                    WHERE other <> p
                    RETURN p.name AS director, m.title AS movie, m.releaseYear AS year,
                           collect(DISTINCT g.name)[..3] AS genres,
                           collect(DISTINCT other.name)[..4] AS actors
                    LIMIT 35
                    """
                    person_results = s.run(cypher_person, focus=focus_term).data()
                    results.extend(person_results)
            else:
                # Default exploration: Prolific directors, their movies, genres, and shared cast
                cypher = """
                MATCH (d:Person)-[:DIRECTED]->(m:Movie)
                WHERE d.name <> 'nan' AND m.title <> 'nan'
                WITH d, count(m) AS cnt, collect(m)[..5] AS films
                WHERE cnt >= 4
                WITH d, films
                ORDER BY cnt DESC
                LIMIT 24
                UNWIND films AS m
                OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
                WHERE g.name <> 'nan' AND g.name <> 'unknown'
                OPTIONAL MATCH (a:Person)-[:ACTED_IN]->(m)
                WHERE a.name <> 'nan' AND a.name <> d.name
                RETURN d.name AS director, m.title AS movie, m.releaseYear AS year,
                       collect(DISTINCT g.name)[..3] AS genres,
                       collect(DISTINCT a.name)[..4] AS actors
                """
                results = s.run(cypher).data()

            for r in results:
                m_title = r["movie"]
                d_name = r.get("director")
                genres = r.get("genres") or []
                actors = r.get("actors") or []

                if not m_title or m_title == 'nan':
                    continue

                if m_title not in nodes_dict:
                    nodes_dict[m_title] = {
                        "id": m_title,
                        "label": m_title,
                        "type": "movie",
                        "year": str(r.get("year") or "")
                    }

                if d_name and d_name != 'nan':
                    d_id = f"dir_{d_name}"
                    if d_id not in nodes_dict:
                        nodes_dict[d_id] = {
                            "id": d_id,
                            "label": d_name,
                            "type": "director"
                        }
                    links.append({
                        "source": d_id,
                        "target": m_title,
                        "label": "DIRECTED"
                    })

                for g in genres:
                    if g and g != 'nan' and g != 'unknown':
                        g_label = g.capitalize()
                        g_id = f"genre_{g.lower()}"
                        if g_id not in nodes_dict:
                            nodes_dict[g_id] = {
                                "id": g_id,
                                "label": g_label,
                                "type": "genre"
                            }
                        links.append({
                            "source": m_title,
                            "target": g_id,
                            "label": "HAS_GENRE"
                        })

                for a in actors:
                    if a and a != 'nan' and a != d_name:
                        a_id = f"act_{a}"
                        if a_id not in nodes_dict:
                            nodes_dict[a_id] = {
                                "id": a_id,
                                "label": a,
                                "type": "actor"
                            }
                        links.append({
                            "source": a_id,
                            "target": m_title,
                            "label": "ACTED_IN"
                        })
    finally:
        driver.close()

    return {
        "nodes": list(nodes_dict.values()),
        "links": links
    }

@app.post("/api/user/validate")
def validate_user(req: Optional[UserValidateRequest] = None, request: Request = None, response: Response = None):
    """Validates or issues a persistent anonymous researcher identity via cookie + localStorage."""
    uid = None
    if req and req.user_id:
        cand = req.user_id.strip()
        if re.match(r"^usr_[a-zA-Z0-9_\-]+$", cand):
            uid = cand
    if not uid and request and request.cookies.get("mg_user_id"):
        cand = request.cookies.get("mg_user_id").strip()
        if re.match(r"^usr_[a-zA-Z0-9_\-]+$", cand):
            uid = cand
    
    if not uid:
        uid = f"usr_{secrets.token_hex(8)}"
    
    if response:
        response.set_cookie(
            key="mg_user_id",
            value=uid,
            max_age=31536000,
            path="/",
            samesite="lax"
        )
    
    return {
        "user_id": uid,
        "valid": True,
        "timestamp": int(time.time())
    }

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, user_id: Optional[str] = None, request: Request = None):
    """Deletes conversation memory for a specific session on the server."""
    uid = user_id or (request.cookies.get("mg_user_id") if request else None) or "anon"
    session_key = f"{uid}_{session_id}"
    deleted = main.clear_session_history(session_key)
    return {"status": "success", "session_id": session_id, "deleted_from_memory": deleted}

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest, request: Request, response: Response):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    user_id = req.user_id or request.cookies.get("mg_user_id") or "anon"
    session_id = req.session_id or "default"
    session_key = f"{user_id}_{session_id}"

    # Sync cookie to response if provided
    if req.user_id and not request.cookies.get("mg_user_id"):
        response.set_cookie(key="mg_user_id", value=user_id, max_age=31536000, path="/", samesite="lax")

    try:
        raw_answer = main.chat(query, session_id=session_key)
        res = process_chat_result(query, raw_answer)
        res["user_id"] = user_id
        res["session_id"] = session_id
        return res
    except Exception as e:
        print(f"[API ERROR] {e}")
        res = process_chat_result(query, f"An issue occurred while processing your cinema inquiry: {e}")
        res["user_id"] = user_id
        res["session_id"] = session_id
        return res

# ---------------------------------------------------------
# WebSocket Real-Time Chat & Loading Stream
# ---------------------------------------------------------
@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query", "").strip()
            if not query:
                continue

            user_id = data.get("user_id") or websocket.cookies.get("mg_user_id") or "anon"
            session_id = data.get("session_id") or "default"
            session_key = f"{user_id}_{session_id}"

            try:
                # Stream Phase 1: Archive
                await websocket.send_json({"type": "phase", "phase": 1, "text": "Searching the movie archive..."})

                # Stream Phase 2: Connections
                await websocket.send_json({"type": "phase", "phase": 2, "text": "Connecting stories and relationships..."})

                # Stream Phase 3: Semantic
                await websocket.send_json({"type": "phase", "phase": 3, "text": "Finding relevant passages & themes..."})

                # Stream Phase 4: Live Sources
                await websocket.send_json({"type": "phase", "phase": 4, "text": "Checking additional cinema archives & web..."})

                # Run GraphRAG Pipeline asynchronously to keep WebSocket heartbeat responsive
                raw_answer = await asyncio.to_thread(main.chat, query, session_key)

                # Stream Phase 5: Synthesis
                await websocket.send_json({"type": "phase", "phase": 5, "text": "Preparing your answer..."})

                # Process clean output with top 4-5 cards and sources
                processed = await asyncio.to_thread(process_chat_result, query, raw_answer)

                # Send complete payload scoped to user and session
                await websocket.send_json({
                    "type": "complete",
                    "user_id": user_id,
                    "session_id": session_id,
                    **processed
                })
            except Exception as query_err:
                print(f"[WS QUERY ERROR] {query_err}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(query_err)
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS CONNECTION ERROR] {e}")

# ---------------------------------------------------------
# Static File Mounting
# ---------------------------------------------------------
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
@app.get("/research")
@app.get("/chat")
@app.get("/catalog")
@app.get("/graph")
@app.get("/documentation")
def serve_index():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    print("\n=======================================================")
    print("🎬 MovieGraph AI Server Running with WebSocket at: http://localhost:8000")
    print("=======================================================\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
