import os
import sys
import json
import time
import urllib.parse
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

import pandas as pd
import httpx
from neo4j import GraphDatabase
from pinecone import Pinecone
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHECKPOINT_FILE = "ingest_checkpoint.json"
CSV_FILE = "wiki_movie_plots_deduped.csv"

# API Keys
KEYS = [
    os.getenv("MISTRAL_API_KEY_1", os.getenv("MISTRAL_API_KEY")),
    os.getenv("MISTRAL_API_KEY_2", os.getenv("MISTRAL_API_KEY"))
]
KEYS = [k for k in KEYS if k]

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USERNAME")
NEO4J_PWD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DATABASE")

PINECONE_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX_NAME", "vectordb")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"neo4j_index": 0, "pinecone_doc_index": 0}

def save_checkpoint(neo_idx, pine_idx):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"neo4j_index": neo_idx, "pinecone_doc_index": pine_idx}, f)

# Dual-Key Embeddings Function with Exponential Backoff
current_key_idx = 0
def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    global current_key_idx
    retries = 15
    base_delay = 3.0

    for attempt in range(retries):
        api_key = KEYS[current_key_idx % len(KEYS)]
        current_key_idx += 1
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "mistral-embed",
            "input": texts
        }
        try:
            r = httpx.post("https://api.mistral.ai/v1/embeddings", headers=headers, json=payload, timeout=45.0)
            if r.status_code == 200:
                data = r.json()
                return [item["embedding"] for item in data["data"]]
            elif r.status_code == 429:
                sleep_time = min(base_delay * (2 ** (attempt % 5)), 30.0)
                print(f"[RATE-LIMIT] Mistral 429. Rotating key & sleeping {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            else:
                print(f"[ERROR] Mistral Embed status {r.status_code}: {r.text[:100]}")
                time.sleep(3.0)
        except Exception as e:
            print(f"[EXCEPTION] Network/Embedding glitch ({e}). Retrying in 10s... (attempt {attempt+1}/{retries})")
            time.sleep(10.0)

    raise RuntimeError("Failed to obtain embeddings after 15 retries.")

def run_ingestion():
    print("=== Background Ingestion Pipeline Started ===")
    if not os.path.exists(CSV_FILE):
        print(f"[ERROR] CSV file {CSV_FILE} not found!")
        return

    checkpoint = load_checkpoint()
    neo_idx = checkpoint["neo4j_index"]
    pine_idx = checkpoint["pinecone_doc_index"]

    print(f"[RESUME] Checkpoint state: Neo4j at {neo_idx}, Pinecone at {pine_idx}")

    df = pd.read_csv(CSV_FILE)
    total_records = len(df)
    print(f"[INFO] Total movies in dataset: {total_records}")

    # Connect Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))
    
    # Setup Constraints
    with driver.session(database=NEO4J_DB) as s:
        s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:Movie) REQUIRE m.title IS UNIQUE")
        s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE")
        s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE")

    # Connect Pinecone
    pc = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index(PINECONE_INDEX)

    # 1. Ingest into Neo4j
    neo_batch_size = 500
    cypher_query = """
    UNWIND $batch AS row
    MERGE (m:Movie {title: row.title})
    SET m.releaseYear = row.year,
        m.origin = row.origin,
        m.wikiPage = row.wikiPage,
        m.plot = row.plot
    MERGE (g:Genre {name: row.genre})
    MERGE (m)-[:HAS_GENRE]->(g)
    FOREACH (dName IN row.directors | MERGE (d:Person {name: dName}) MERGE (d)-[:DIRECTED]->(m))
    FOREACH (aName IN row.actors | MERGE (a:Person {name: aName}) MERGE (a)-[:ACTED_IN]->(m))
    """

    print(f"\n--- Ingesting into Neo4j from {neo_idx} to {total_records} ---")
    while neo_idx < total_records:
        end_idx = min(neo_idx + neo_batch_size, total_records)
        sub_df = df.iloc[neo_idx:end_idx]
        batch_data = []

        for _, row in sub_df.iterrows():
            title = str(row.get("Title", "Unknown"))
            year_val = row.get("Release Year")
            year = int(year_val) if pd.notna(year_val) and str(year_val).isdigit() else None
            origin = str(row.get("Origin/Ethnicity", "Unknown"))
            wiki_page = str(row.get("Wiki Page", ""))
            plot = str(row.get("Plot", ""))
            genre = str(row.get("Genre", "Unknown")).strip().lower() or "unknown"
            
            raw_dir = str(row.get("Director", ""))
            directors = [d.strip() for d in raw_dir.split(",") if d.strip() and d.strip().lower() != "unknown"]
            
            raw_cast = str(row.get("Cast", ""))
            actors = [a.strip() for a in raw_cast.split(",") if a.strip() and a.strip().lower() != "unknown"]

            batch_data.append({
                "title": title,
                "year": year,
                "origin": origin,
                "wikiPage": wiki_page,
                "plot": plot,
                "genre": genre,
                "directors": directors,
                "actors": actors
            })

        with driver.session(database=NEO4J_DB) as s:
            s.run(cypher_query, batch=batch_data)

        neo_idx = end_idx
        save_checkpoint(neo_idx, pine_idx)
        print(f"  [Neo4j] Ingested {neo_idx}/{total_records} movies ({(neo_idx/total_records)*100:.1f}%)")

    print("[OK] Neo4j full ingestion complete!")

    # 2. Ingest into Pinecone
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)
    pine_movie_batch = 100
    print(f"\n--- Ingesting into Pinecone from {pine_idx} to {total_records} ---")

    while pine_idx < total_records:
        end_idx = min(pine_idx + pine_movie_batch, total_records)
        sub_df = df.iloc[pine_idx:end_idx]
        
        vectors_to_upsert = []
        for doc_i, (_, row) in enumerate(sub_df.iterrows(), start=pine_idx):
            title = str(row.get("Title", "Unknown"))
            year = str(row.get("Release Year", ""))
            genre = str(row.get("Genre", "Unknown"))
            wiki_page = str(row.get("Wiki Page", ""))
            plot = str(row.get("Plot", ""))

            chunks = text_splitter.split_text(plot)
            if not chunks:
                continue

            # Batch embed chunks with key rotation
            embeddings_list = get_embeddings_batch(chunks)
            for c_i, (chunk_text, emb) in enumerate(zip(chunks, embeddings_list)):
                v_id = f"m_{doc_i}_c_{c_i}"
                vectors_to_upsert.append({
                    "id": v_id,
                    "values": emb,
                    "metadata": {
                        "Title": title,
                        "Release Year": year,
                        "Genre": genre,
                        "Wiki Page": wiki_page,
                        "text": chunk_text
                    }
                })

            # Upsert in safe chunks of 100 vectors
            if len(vectors_to_upsert) >= 100:
                index.upsert(vectors=vectors_to_upsert)
                vectors_to_upsert = []
                time.sleep(0.1)

        if vectors_to_upsert:
            index.upsert(vectors=vectors_to_upsert)

        pine_idx = end_idx
        save_checkpoint(neo_idx, pine_idx)
        print(f"  [Pinecone] Indexed up to movie {pine_idx}/{total_records} ({(pine_idx/total_records)*100:.1f}%)")

    driver.close()
    print("=== Full Dataset Ingestion Successfully Finished! ===")

if __name__ == "__main__":
    run_ingestion()
