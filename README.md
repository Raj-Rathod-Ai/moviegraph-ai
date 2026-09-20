# 🎬 MovieGraph AI — Cinematic GraphRAG Intelligence Platform

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-Aura_Graph-45818e?style=for-the-badge&logo=neo4j&logoColor=white)](https://neo4j.com)
[![Pinecone](https://img.shields.io/badge/Pinecone-Serverless_1024d-black?style=for-the-badge&logo=pinecone&logoColor=white)](https://www.pinecone.io)
[![Mistral AI](https://img.shields.io/badge/Mistral_AI-Ministral_8B-FD5749?style=for-the-badge&logo=mistralai&logoColor=white)](https://mistral.ai)
[![Tavily](https://img.shields.io/badge/Tavily-Cinema_Search-4F46E5?style=for-the-badge)](https://tavily.com)
[![Render](https://img.shields.io/badge/Render-Backend_Ready-46E3B7?style=for-the-badge&logo=render&logoColor=black)](https://render.com)
[![Netlify](https://img.shields.io/badge/Netlify-Frontend_Ready-00C7B7?style=for-the-badge&logo=netlify&logoColor=white)](https://www.netlify.com)

**MovieGraph AI** is a production-grade, cinematic research and movie discovery assistant designed in the visual aesthetic of [MotionSites AI](https://motionsites.ai/?prompt=fastshot). It unifies a **Neo4j Knowledge Graph**, **Pinecone Serverless Vector Embeddings**, **Mistral AI Reasoning**, **Direct Wikipedia Archives**, and **Tavily Live Web & Web Series Search** across an extensive archive of approximately 35,000 films.

---

## 📽️ Visual Design Philosophy (MotionSites Aesthetic)

MovieGraph AI explicitly avoids generic AI chatbot clichés (no purple neon gradients, cyan lasers, glowing chat bubbles, or robot icons). Instead, it features:
- **Obsidian Dark Theme**: Base background `#08080A` with layered atmospheric glass (`rgba(18, 17, 23, 0.85)`).
- **Terracotta & Amber Accents**: Restrained terracotta `#FF6B35` highlights, amber `#F59E0B` director cues, and sky blue `#38BDF8` actor nodes.
- **Cinematic Typography**: *Playfair Display* editorial serif paired with *Plus Jakarta Sans* geometric UI and *JetBrains Mono* data telemetry.
- **Live Animated Canvas**: Ambient 60fps golden dust particle simulation drifting weightlessly across the background with mouse-tracking radial focus.
- **Aperture Loading Sequence**: Smooth camera aperture ring rotation with pulsing amber core and luminous shimmer gleam.

---

## 🏛️ System Architecture & GraphRAG Pipeline

```
                               ┌───────────────────────────┐
                               │   User Inquiry / Stream   │
                               │  (WebSocket or REST Chat) │
                               └─────────────┬─────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
          ┌───────────────────────────┐               ┌───────────────────────────┐
          │   1. Neo4j Knowledge DB   │               │ 2. Pinecone Vector Search │
          │  32,432 Films, 184k Edges │               │  1024-d Dense Embeddings  │
          │   (:Person)-[:DIRECTED]   │               │   Plot Semantics & Themes │
          └────────────┬──────────────┘               └─────────────┬─────────────┘
                       │                                           │
                       └─────────────────────┬─────────────────────┘
                                             ▼
                               ┌───────────────────────────┐
                               │    Candidate Synthesis    │
                               │  Direct Wikipedia Match   │
                               └─────────────┬─────────────┘
                                             │
                         [If modern web series or unindexed release]
                                             ▼
                               ┌───────────────────────────┐
                               │ 3. Tavily Cinema / Series │
                               │  Domain-Filtered Search   │
                               │  (IMDb, Variety, TVMaze)  │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │ 4. Mistral LLM Synthesis  │
                               │   (ministral-8b-latest)   │
                               │  Clean Editorial Markdown │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │  Client State / Renderer  │
                               │  Markdown Tables, Cards,  │
                               │    D3 Graph Relational    │
                               └───────────────────────────┘
```

---

## 🚀 Key Features

| View / Feature | Description |
| :--- | :--- |
| **Research Composer (`#/research`)** | Centered Fastshot composer card with atmospheric halo glow, live particle background, and curated inquiry chips. |
| **Intelligence Chat (`#/chat`)** | Multi-turn conversational research workspace with aperture loading sequence, GFM tables, extracted movie & web series cards, and inline D3 knowledge subgraphs. |
| **Cinema Discovery Catalog (`#/catalog`)** | High-resolution discovery carousel with dynamic backdrop imagery, director filmographies, plot archives, and direct Wikipedia links. |
| **Knowledge Graph Explorer (`#/graph`)** | Dense **449-node, 576-link** interactive relational force-directed canvas with multi-scale node sizing (Genres, Directors, Movies, Actors), hover path highlighting, and detail modal integration. |
| **Architecture Documentation (`#/docs`)** | In-app documentation covering the system architecture, Neo4j schema, Pinecone dense embeddings, Tavily validation allowlists, and API reference. |
| **Project Footer** | Platform navigation, architectural specifications, live status telemetry, `GraphRAG v1.0` badge, and copyright details (dynamically hidden on full-screen graph/chat routes). |
| **Cross-Device Responsiveness** | 4-tier responsive design with slide-over touch drawer (`#sidebar-backdrop`), mobile action header, fluid typography, and zero horizontal scroll overflow. |
| **User Privacy & Isolation** | Anonymous cookie (`mg_user_id`, 365-day expiry) + `localStorage` synchronization. Past conversations remain strictly isolated so new users never see previous users' search history. |
| **Security Middleware** | HTTP middleware blocks access to `.env`, checkpoints, secrets, git configurations, and bytecode with `HTTP 403 Forbidden`. Read-only Cypher enforcement prevents database modifications. |

---

## 📂 Project Structure

```
Graph Rag ChatBot/
├── server.py                     # FastAPI server, WebSocket stream, API endpoints & security middleware
├── main.py                       # LangChain GraphRAG core: Neo4j Cypher, Pinecone retrieval & Mistral synthesis
├── ingest_all.py                 # Resumable ingestion pipeline for Neo4j Aura & Pinecone Serverless
├── ingest_checkpoint.json        # Atomic progress tracker for vector ingestion
├── wiki_movie_plots_deduped.csv  # Core movie archive dataset (~35,000 films)
├── requirements.txt              # Production Python dependencies
├── render.yaml                   # Render Blueprint for automated backend deployment
├── Procfile                      # Process file for Render / cloud web services
├── netlify.toml                  # Netlify configuration for frontend publishing & SPA routing
├── .env.example                  # Environment variable reference template
├── .gitignore                    # Git exclusions
├── static/
│   ├── index.html                # Single Page App layout with 5 states, mobile drawer & project footer
│   ├── styles.css                # MotionSites dark design system, 4-tier responsive rules & keyframe animations
│   ├── app.js                    # Client-side router, D3 graph engine, WebSocket client & local storage
│   └── marked.min.js             # Local fallback Markdown parser
```

---

## 🛠️ Local Development Setup

### 1. Prerequisites
- Python 3.10, 3.11, or 3.12
- Neo4j Aura instance (Free tier or higher)
- Pinecone Index (`vectordb`, 1024 dimensions, cosine metric)
- Mistral AI API Key
- Tavily Search API Key

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/your-username/moviegraph-ai.git
cd moviegraph-ai

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

```env
NEO4J_URI=neo4j+s://your-instance-id.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-neo4j-password
NEO4J_DATABASE=neo4j

PINECONE_API_KEY=your-pinecone-api-key
PINECONE_INDEX_NAME=vectordb

MISTRAL_API_KEY=your-mistral-api-key
# Optional backup key for high-throughput batching:
MISTRAL_API_KEY_1=your-mistral-api-key-1
MISTRAL_API_KEY_2=your-mistral-api-key-2

TAVILY_API_KEY=your-tavily-api-key
```

### 4. Run the Application
```bash
python server.py
```
Open your browser at **`http://localhost:8000`**.

### 5. Resume or Run Ingestion (Optional)
```bash
python ingest_all.py
```
*Note: Neo4j is already 100% ingested, and Pinecone is pre-populated with tens of thousands of vectors. The script automatically resumes from the saved checkpoint.*

---

## 🌐 Production Deployment Guide

You can deploy MovieGraph AI using a decoupled production architecture:
- **Backend**: Hosted on [Render](https://render.com) (FastAPI + WebSocket).
- **Frontend**: Hosted on [Netlify](https://www.netlify.com) (Static CDN with SPA routing).

---

### Part A: Deploying Backend to Render

1. **Push your code to GitHub / GitLab**.
2. **Log in to [Render Dashboard](https://dashboard.render.com)**.
3. Click **New +** → **Web Service**.
4. Connect your repository.
5. Configure the Web Service:
   - **Name**: `moviegraph-ai-backend`
   - **Region**: Closest to your database (e.g., Oregon or Frankfurt)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**:
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt
     ```
   - **Start Command**:
     ```bash
     uvicorn server:app --host 0.0.0.0 --port $PORT
     ```
6. Under **Advanced** → **Add Environment Variable**, add the following keys from your `.env`:
   - `NEO4J_URI`
   - `NEO4J_USERNAME`
   - `NEO4J_PASSWORD`
   - `NEO4J_DATABASE` (value: `neo4j`)
   - `PINECONE_API_KEY`
   - `PINECONE_INDEX_NAME` (value: `vectordb`)
   - `MISTRAL_API_KEY`
   - `TAVILY_API_KEY`
7. Click **Create Web Service**. Render will install packages and start the backend.
8. Note your public backend URL, e.g.:
   ```
   https://moviegraph-ai-backend.onrender.com
   ```

*(Alternatively, use the included [`render.yaml`](file:///c:/RAG/Graph%20Rag%20ChatBot/render.yaml) by selecting **New +** → **Blueprint** in Render for automatic provisioning).*

---

### Part B: Deploying Frontend to Netlify

1. **Log in to [Netlify Dashboard](https://app.netlify.com)**.
2. Click **Add new site** → **Import an existing project**.
3. Link your GitHub repository.
4. Set the build settings:
   - **Base directory**: Leave blank (`/`)
   - **Build command**: Leave blank (no build step needed for pure vanilla static files)
   - **Publish directory**: `static`
5. Connect Frontend to your Render Backend (**Choose Option 1 or Option 2**):

#### Option 1: Configure Backend URL in Netlify (Recommended)
Open `static/index.html` in your repository and add your Render URL inside the `<head>` tag:
```html
<script>
  window.MOVIEGRAPH_API_URL = "https://moviegraph-ai-backend.onrender.com";
</script>
```
MovieGraph AI's client-side networking engine will automatically route all `/api/*` REST calls and `/ws/chat` WebSockets (`wss://...`) to your Render backend with zero CORS issues.

#### Option 2: Netlify Proxy Redirect
Open `netlify.toml` and uncomment the redirect proxy:
```toml
[[redirects]]
  from = "/api/*"
  to = "https://moviegraph-ai-backend.onrender.com/api/:splat"
  status = 200
  force = true
```
Push the commit. Netlify will publish your site instantly at `https://your-site-name.netlify.app`.

---

## 📡 API Reference

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/api/stats` | `GET` | Returns live counts for Neo4j movies, relationships, and Pinecone vectors. |
| `/api/movies?limit=18` | `GET` | Returns catalog films for discovery carousel. |
| `/api/movies/{title}` | `GET` | Retrieves full graph metadata, director, actors, genre, and plot for a movie. |
| `/api/graph?limit=150` | `GET` | Generates the dense 449-node, 576-link cinema relational graph slice. |
| `/api/graph?focus={query}` | `GET` | Focuses the knowledge graph on a specific director, actor, or movie title. |
| `/api/chat` | `POST` | REST chat endpoint with RAG synthesis, card extraction, and source links. |
| `/api/user/validate` | `POST` | Issues and validates persistent anonymous researcher IDs via cookies. |
| `/api/sessions/{session_id}` | `DELETE` | Deletes conversational memory for a thread on the server. |
| `/ws/chat` | `WebSocket` | Real-time bi-directional chat streaming 5 distinct research phases. |

---

## 🔒 Security Best Practices

1. **Zero Secret Leakage**: The server enforces HTTP blocking middleware that rejects requests for `.env`, checkpoints, and `.git` with `403 Forbidden`.
2. **CORS Hardening**: Allowed origins are configured via FastAPI middleware, supporting secure communication between Netlify and Render.
3. **Cypher Safety**: All dynamic Cypher queries strictly utilize parameterized bindings (`$focus`, `$title`, `$cand`) and read-only schema traversals.
4. **Session Isolation**: Chat history is segregated by `user_id` in both browser local storage and server session caches.

---

## 📄 License & Credits

- **Design Inspiration**: [MotionSites AI](https://motionsites.ai/?prompt=fastshot)
- **Dataset**: Wikipedia Movie Plots Dataset (~35,000 films)
- **Engine**: GraphRAG v1.0
- **Copyright**: © 2026 MovieGraph AI. All rights reserved.
