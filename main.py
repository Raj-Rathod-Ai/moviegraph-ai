import os
import re
import sys
import time
import urllib.parse
from dotenv import load_dotenv

# Fix Windows console encoding for UTF-8 compatibility
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pinecone import Pinecone
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_neo4j import Neo4jGraph
from langchain_pinecone import PineconeVectorStore
from langchain_core.output_parsers import StrOutputParser
from langchain.tools import tool
from langchain_neo4j.chains.graph_qa.cypher import extract_cypher
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tavily import TavilyClient
import wikipedia
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# Load environment variables
load_dotenv()

console = Console(safe_box=True)

# Configure Wikipedia User Agent
wikipedia.set_user_agent("MovieGraphRAG/1.0 (https://github.com/dhruv608/graphrag; cinema-rag@example.com)")

# ---------------------------------------------------------
# 1. LLM & Embeddings Setup (Mistral AI)
# ---------------------------------------------------------
mistral_api_key = os.getenv("MISTRAL_API_KEY_1", os.getenv("MISTRAL_API_KEY"))
mistral_model_name = os.getenv("MISTRAL_MODEL", "ministral-8b-latest")

if not mistral_api_key:
    console.print("[bold red][ERROR] MISTRAL_API_KEY is not set in .env[/bold red]")
    sys.exit(1)

# Embeddings: mistral-embed produces 1024-dimensional vectors matching Pinecone
embeddings = MistralAIEmbeddings(
    model="mistral-embed",
    api_key=mistral_api_key
)

# Chat Model: Fast, intelligent reasoning with tool support
model = ChatMistralAI(
    model=mistral_model_name,
    temperature=0.3,
    api_key=mistral_api_key
)

# ---------------------------------------------------------
# 2. Neo4j Knowledge Graph Setup
# ---------------------------------------------------------
neo4j_uri = os.getenv("NEO4J_URI")
neo4j_user = os.getenv("NEO4J_USERNAME")
neo4j_pwd = os.getenv("NEO4J_PASSWORD")
neo4j_db = os.getenv("NEO4J_DATABASE")

graph = None
neo4j_count = 0

try:
    graph = Neo4jGraph(
        url=neo4j_uri,
        username=neo4j_user,
        password=neo4j_pwd,
        database=neo4j_db
    )
    count_res = graph.query("MATCH (m:Movie) RETURN count(m) AS total")
    neo4j_count = count_res[0]["total"] if count_res else 0
except Exception as e:
    console.print(f"[bold yellow][WARN] Neo4j connection notice: {e}[/bold yellow]")

# ---------------------------------------------------------
# 3. Pinecone Vector Store Setup
# ---------------------------------------------------------
index_name = os.getenv("PINECONE_INDEX_NAME", "vectordb")
pinecone_api_key = os.getenv("PINECONE_API_KEY")

vector_store = None
vector_count = 0

if pinecone_api_key:
    try:
        pc = Pinecone(api_key=pinecone_api_key)
        indexes = [idx.name for idx in pc.list_indexes()]
        if index_name in indexes:
            stats = pc.Index(index_name).describe_index_stats()
            vector_count = stats.total_vector_count
            vector_store = PineconeVectorStore(index_name=index_name, embedding=embeddings)
        else:
            console.print(f"[yellow][WARN] Pinecone index '{index_name}' not in {indexes}[/yellow]")
    except Exception as e:
        console.print(f"[bold yellow][WARN] Pinecone notice: {e}[/bold yellow]")

console.print(
    f"[green][OK] Knowledge Base Online:[/green] "
    f"[cyan]{neo4j_count}[/cyan] Neo4j movies, [cyan]{vector_count}[/cyan] Pinecone vectors."
)

# ---------------------------------------------------------
# 4. Retrieval Tools (Dataset First + Exact Wikipedia + Validated Tavily)
# ---------------------------------------------------------

# Tool 1: Neo4j Graph Tool
FORBIDDEN_KEYWORDS = [
    r"\bDELETE\b", r"\bDETACH\b", r"\bDROP\b", r"\bCREATE\b",
    r"\bSET\b", r"\bREMOVE\b", r"\bMERGE\b"
]

def check_cypher_guardrail(query: str) -> tuple[bool, str]:
    """Ensures query is read-only and blocks destructive operations."""
    for pattern in FORBIDDEN_KEYWORDS:
        if re.search(pattern, query, re.IGNORECASE):
            return False, f"Security Violation: Destructive command matching '{pattern}' is blocked."
    if not re.search(r"\b(MATCH|RETURN|OPTIONAL MATCH)\b", query, re.IGNORECASE):
        return False, "Security Violation: Query must be a read-only MATCH/RETURN statement."
    return True, "Valid"

correction_prompt = """You are a Neo4j Cypher expert.
A previously generated Cypher query failed. Analyze the error message and graph schema, and fix the query.

GRAPH SCHEMA:
- (:Person {{name}})-[:DIRECTED]->(:Movie {{title, releaseYear, origin, wikiPage}})
- (:Person {{name}})-[:ACTED_IN]->(:Movie {{title, releaseYear, origin, wikiPage}})
- (:Movie {{title}})-[:HAS_GENRE]->(:Genre {{name}})

RULES:
1. ONLY return the valid Cypher query inside a ```cypher ... ``` code block.
2. Ensure read-only syntax (MATCH and RETURN only).
3. Use case-insensitive matching where applicable: WHERE toLower(m.title) CONTAINS toLower('...')

FAILED QUERY:
{failed_query}

ERROR MESSAGE FROM NEO4J:
{error_message}

CORRECTED CYPHER QUERY:"""

strParser = StrOutputParser()
correction_chain = ChatPromptTemplate.from_template(correction_prompt) | model | strParser

@tool
def graph_tool(cypher_query: str) -> str:
    """
    [STEP 1 - LOCAL DATASET] Execute a read-only Cypher query against the Neo4j Movie Knowledge Graph.
    SCHEMA:
    - (:Person {name})-[:DIRECTED]->(:Movie {title, releaseYear, origin, wikiPage, plot})
    - (:Person {name})-[:ACTED_IN]->(:Movie {title, releaseYear, origin, wikiPage, plot})
    - (:Movie {title, releaseYear, origin, wikiPage, plot})-[:HAS_GENRE]->(:Genre {name})
    (Note: There are no :Actor or :Director labels. Use :Person with -[:DIRECTED]-> or -[:ACTED_IN]->. Always return m.wikiPage if available).
    """
    console.print(f"[dim cyan][Neo4j Graph Tool][/dim cyan] Cypher: '{cypher_query}'")
    if not graph:
        return "Neo4j database connection is not available."

    current_query = cypher_query
    max_retries = 2

    for attempt in range(max_retries + 1):
        clean_cypher = extract_cypher(current_query)
        is_safe, security_msg = check_cypher_guardrail(clean_cypher)
        if not is_safe:
            if attempt < max_retries:
                corrected = correction_chain.invoke({
                    "failed_query": clean_cypher,
                    "error_message": security_msg
                })
                current_query = corrected
                continue
            return security_msg

        try:
            results = graph.query(clean_cypher)
            if results:
                return str(results)
            return "No graph records found for this query in Neo4j."
        except Exception as e:
            error_msg = str(e)
            if attempt < max_retries:
                corrected = correction_chain.invoke({
                    "failed_query": clean_cypher,
                    "error_message": error_msg
                })
                current_query = corrected
            else:
                return f"Cypher execution failed: {error_msg}"

    return "Unable to execute query."

# Tool 2: Pinecone Vector Tool
@tool
def vector_tool(query: str, k: int = 3) -> str:
    """
    [STEP 1 - LOCAL DATASET] Search the Pinecone vector database for movie plot summaries, scene descriptions, themes,
    and narrative details. Each chunk also contains the movie's 'Wiki Page' metadata.
    """
    console.print(f"[dim green][Pinecone Vector Search][/dim green] Query: '{query}'")
    if not vector_store:
        return "Pinecone vector store is not available."
    try:
        docs = vector_store.similarity_search(query, k=k)
        if not docs:
            return "No relevant movie plot chunks found in vector database."
        formatted_results = []
        for i, doc in enumerate(docs, 1):
            title = doc.metadata.get("Title", "Unknown")
            genre = doc.metadata.get("Genre", "Unknown")
            year = doc.metadata.get("Release Year", "Unknown")
            wiki = doc.metadata.get("Wiki Page", "")
            page_content = doc.page_content
            formatted_results.append(
                f"[Chunk {i}]\nMovie: {title} ({year})\nGenre: {genre}\nWiki Page URL: {wiki}\nPlot Excerpt: {page_content}"
            )
        return "\n\n".join(formatted_results)
    except Exception as e:
        return f"Pinecone query error: {e}"

# Tool 3: Direct Wikipedia URL Fetcher
@tool
def fetch_wikipedia_by_url(wiki_url: str) -> str:
    """
    [STEP 1 ENRICHMENT] Fetch verified, in-depth encyclopedic movie information directly from the exact Wikipedia URL
    found in the dataset (m.wikiPage).
    This provides 100% authentic plot summaries, awards, box office trivia, and cast details without guesswork.
    """
    console.print(f"[dim magenta][Direct Wikipedia Link Fetch][/dim magenta] URL: '{wiki_url}'")
    try:
        if "/wiki/" not in wiki_url:
            return f"Invalid Wikipedia URL: {wiki_url}"
        raw_slug = wiki_url.split("/wiki/")[-1]
        page_title = urllib.parse.unquote(raw_slug).replace("_", " ")

        page = wikipedia.page(page_title, auto_suggest=False)
        summary = wikipedia.summary(page_title, sentences=6, auto_suggest=False)
        return (
            f"Official Wikipedia Page: {page.title}\n"
            f"URL: {page.url}\n\n"
            f"Verified Summary:\n{summary}"
        )
    except Exception as e:
        return f"Could not load direct Wikipedia page: {e}"

# Tool 4: Cinema-Validated Tavily Web Search (Fallback Only)
tavily_api_key = os.getenv("TAVILY_API_KEY")
tavily_client = TavilyClient(api_key=tavily_api_key) if tavily_api_key else None

VALID_ENTERTAINMENT_DOMAINS = [
    "imdb.com", "wikipedia.org", "rottentomatoes.com",
    "themoviedb.org", "tvmaze.com", "variety.com",
    "hollywoodreporter.com", "rogerebert.com", "metacritic.com",
    "deadline.com", "indiewire.com", "collider.com"
]

@tool
def tavily_movie_search(query: str, max_results: int = 5) -> str:
    """
    [STEP 2 - LIVE WEB SEARCH] Search the live web for movies, web series, television shows, limited series,
    anime, and streaming originals across vintage/classic eras and modern/latest releases (2020-2026+).
    Use this whenever an inquiry involves web series, TV shows, recent 2024-2026 releases, upcoming seasons,
    cast & crew, streaming platforms, or films not in the historical 1901-2017 dataset.
    """
    console.print(f"[dim blue][Tavily Entertainment Search (Movies & Web Series)][/dim blue] Query: '{query}'")
    if not tavily_client:
        return "Tavily API key not configured."

    # Validate and ensure context for movies or web series
    sanitized_query = query
    entertainment_keywords = [
        "movie", "film", "cinema", "series", "web series", "tv show", "tv series",
        "season", "episode", "director", "creator", "showrunner", "cast", "plot",
        "ott", "netflix", "prime", "hbo", "apple tv", "disney", "box office", "reviews"
    ]
    if not any(kw in query.lower() for kw in entertainment_keywords):
        sanitized_query = f"{query} movie series cinema"

    try:
        response = tavily_client.search(
            query=sanitized_query,
            max_results=max_results,
            search_depth="basic",
            include_domains=VALID_ENTERTAINMENT_DOMAINS
        )
        results = response.get("results", [])
        if not results:
            # Fallback to broader entertainment search if domain filter was too restrictive
            response = tavily_client.search(
                query=f"{sanitized_query}",
                max_results=max_results,
                search_depth="basic"
            )
            results = response.get("results", [])

        if not results:
            return "No verified cinema or web series search results found."

        formatted = []
        for idx, r in enumerate(results, 1):
            title = r.get("title", "No Title")
            url = r.get("url", "")
            snippet = r.get("content", "")
            formatted.append(f"[{idx}] {title}\nURL: {url}\nExcerpt: {snippet}")

        return "\n\n".join(formatted)
    except Exception as e:
        return f"Tavily search error: {e}"

# ---------------------------------------------------------
# 5. Multi-Tool Agent & ChatGPT-Style Formatting
# ---------------------------------------------------------
tools = [graph_tool, vector_tool, fetch_wikipedia_by_url, tavily_movie_search]
tools_with_name = {t.name: t for t in tools}
llm_with_tools = model.bind_tools(tools)

system_prompt_text = """You are an elite, comprehensive Cinema & Web Series Intelligence Assistant powered by a Hybrid GraphRAG architecture. You possess master-level, authoritative knowledge spanning feature films, web series, television dramas, limited series, anime, documentaries, and franchise sagas — across vintage golden-age classics and the latest releases (up through 2024–2026+).

RETRIEVAL WORKFLOW (MANDATORY ORDER):
1. **STEP 1 - DATASET FIRST (Historical Feature Films)**:
   - For movie plot queries, themes, and film relationships, query `graph_tool` (for relationships, cast, director, release year, genre) and `vector_tool` (for plot excerpts and themes) FIRST.
   - If a `wikiPage` URL is present, call `fetch_wikipedia_by_url` to get verified, rich encyclopedic knowledge directly from Wikipedia without hallucination.
2. **STEP 2 - LIVE CINEMA & WEB SERIES SEARCH (tavily_movie_search)**:
   - Use `tavily_movie_search` for:
     a) Web series, television shows, mini-series, and streaming OTT titles (e.g. Breaking Bad, Stranger Things, Mirzapur, Succession, The Last of Us, Panchayat, Shogun, etc.).
     b) Recent movies and releases from 2020 through 2026+ (not found in the 1901-2017 dataset).
     c) Real-time live data: current box office, streaming platforms, latest season renewals, and release dates.
   - Ground all web series responses with creators/showrunners, main cast, seasons/episodes, core premises, and platform/reception.

RESPONSE GUIDELINES (BIG MODEL / CHATGPT QUALITY):
- **Tone & Authority**: Speak with the elegance, expertise, and depth of a seasoned film and television curator. NEVER apologize, never say "due to dataset constraints", and never discuss internal database limitations. Dive straight into your authoritative, curated answer.
- **Clean Structure**: Use clear headers (e.g. `### Overview`, `### Thematic Recommendations`, `### Key Cast & Crew`, `### Sources & Links`).
- **NO LINK CLUTTER**: DO NOT put repeated Wikipedia or IMDb links inside every numbered list item or bullet. Keep descriptions clean and readable.
- **Top 4-5 Sources Only**: Provide ONLY the top 4 to 5 premier, verified reference links at the very end under `### Sources & Links` (e.g. `[Wikipedia: Title](url)` or `[IMDb: Title](url)`). Never list dozens of raw links."""

prompt_template = ChatPromptTemplate.from_messages([
    ("system", system_prompt_text),
    MessagesPlaceholder(variable_name="messages")
])

chain_with_tools = prompt_template | llm_with_tools
synthesis_model = model.bind(tool_choice="none")
chain_synthesis = prompt_template | synthesis_model

# Session-isolated memory store mapping session_id -> message list
session_histories = {}

def get_session_history(session_id: str = "default") -> list:
    if session_id not in session_histories:
        session_histories[session_id] = []
    # Prune old sessions if memory grows beyond 2000 active sessions
    if len(session_histories) > 2000:
        first_key = next(iter(session_histories))
        del session_histories[first_key]
    return session_histories[session_id]

def clear_session_history(session_id: str) -> bool:
    if session_id in session_histories:
        del session_histories[session_id]
        return True
    return False

def chat(user_input: str, session_id: str = "default") -> str:
    history = get_session_history(session_id)

    # 1. Clean history: only retain HumanMessage and conversational AIMessage (no tool_calls)
    clean_history = []
    for msg in history:
        if isinstance(msg, HumanMessage) and msg.content:
            clean_history.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            clean_history.append(AIMessage(content=msg.content))

    # Keep up to the last 6 messages (3 full conversational turns)
    active_history = list(clean_history[-6:])
    current_human = HumanMessage(content=user_input)
    active_history.append(current_human)

    # Phase 1: Controlled Tool Retrieval Phase (up to 2 iterations)
    max_tool_turns = 2
    try:
        for turn in range(max_tool_turns):
            ai_response = chain_with_tools.invoke({"messages": active_history})
            active_history.append(ai_response)

            if not ai_response.tool_calls:
                final_text = ai_response.content if isinstance(ai_response.content, str) else str(ai_response.content)
                history.append(current_human)
                history.append(AIMessage(content=final_text))
                if len(history) > 20:
                    del history[:-20]
                return final_text

            # Execute all requested tool calls
            for tool_call in ai_response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_instance = tools_with_name.get(tool_name)
                if tool_instance:
                    try:
                        tool_output = tool_instance.invoke(tool_args)
                    except Exception as e:
                        tool_output = f"Tool execution error: {e}"
                else:
                    tool_output = f"Tool '{tool_name}' not found."

                tool_msg = ToolMessage(
                    content=str(tool_output),
                    name=tool_name,
                    tool_call_id=tool_call["id"]
                )
                active_history.append(tool_msg)

        # Phase 2: Guaranteed Synthesis Phase (ChatGPT-quality output)
        final_response = chain_synthesis.invoke({"messages": active_history})
        final_text = final_response.content if isinstance(final_response.content, str) else str(final_response.content)
        history.append(current_human)
        history.append(AIMessage(content=final_text))
        if len(history) > 20:
            del history[:-20]
        return final_text
    except Exception as e:
        console.print(f"[bold red][Mistral Chat Error][/bold red] {e}")
        try:
            fallback_res = tavily_movie_search.invoke({"query": f"{user_input} movie"})
        except Exception:
            fallback_res = "Information could not be fetched at this moment."
        return (
            f"### Overview\n"
            f"Information retrieved regarding **{user_input}**:\n\n"
            f"{fallback_res}\n\n"
            f"### Sources & Links\n"
            f"- [Cinema Search](https://www.themoviedb.org/search?query={urllib.parse.quote(user_input)})"
        )

# ---------------------------------------------------------
# 6. CLI Execution Loop
# ---------------------------------------------------------
def main():
    console.print(
        Panel.fit(
            "[bold cyan]🎬 GraphRAG Cinema Intelligence Assistant[/bold cyan]\n"
            "[white]Powered by Mistral AI, Neo4j Graph, Pinecone Vector, Wikipedia & Tavily[/white]\n"
            "[dim]Dataset-First Retrieval with Cinema-Validated Web Fallback. Type 'exit' to quit.[/dim]",
            border_style="cyan"
        )
    )

    while True:
        try:
            user_query = input("\nYou: ").strip()
            if user_query.lower() in ["exit", "quit", "q"]:
                console.print("\n[bold cyan]Goodbye! Have a great day![/bold cyan]\n")
                break
            if not user_query:
                continue

            with console.status("[bold green]Checking dataset & retrieving intelligence...[/bold green]", spinner="dots"):
                response = chat(user_query)

            console.print("\n[bold purple]AI Assistant:[/bold purple]")
            console.print(Markdown(response))
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold cyan]Session closed. Goodbye![/bold cyan]\n")
            break
        except Exception as e:
            console.print(f"\n[bold red]An error occurred: {e}[/bold red]\n")

if __name__ == "__main__":
    main()
