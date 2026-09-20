/* =========================================================
   MovieGraph AI — Application Orchestration & MotionSites Engine
   Routes: #/research, #/chat, #/catalog, #/graph, #/docs
   ========================================================= */

let currentState = 'research';
let currentUserId = null;
let currentSessionId = null;
let userChatSessions = [];
let discoveryMovies = [];
let currentDiscoveryIndex = 0;
let d3Simulation = null;
let chatSocket = null;

const VALID_ROUTES = ['research', 'chat', 'catalog', 'graph', 'docs'];

// Dynamic backend configuration (Supports local, Netlify proxy, or direct Render URL)
const BACKEND_API_BASE = (window.MOVIEGRAPH_API_URL || localStorage.getItem('mg_api_url') || '').replace(/\/+$/, '');

function getApiUrl(endpoint) {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return BACKEND_API_BASE ? `${BACKEND_API_BASE}${cleanEndpoint}` : cleanEndpoint;
}

function getWebSocketUrl() {
  if (window.MOVIEGRAPH_WS_URL) return window.MOVIEGRAPH_WS_URL;
  if (BACKEND_API_BASE && BACKEND_API_BASE.startsWith('http')) {
    return BACKEND_API_BASE.replace(/^http/, 'ws') + '/ws/chat';
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/chat`;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  // Show UI immediately — don't block on backend calls
  if (window.lucide) lucide.createIcons();
  initRouter();
  initMotionSitesLiveBackground();
  initGlobalEvents();

  // Background: API calls (Render may be cold-starting, don't block UI)
  initUserSession().then(() => {
    fetchSystemStats();
    loadDiscoveryCatalog();
    initWebSocket();
  }).catch(() => {
    // Backend offline/cold — still show UI, retry stats quietly
    fetchSystemStats();
    loadDiscoveryCatalog();
    initWebSocket();
  });
});

// ---------------------------------------------------------
// Hash Routing & State Management
// ---------------------------------------------------------
function initRouter() {
  window.addEventListener('hashchange', () => {
    parseRoute();
  });
  parseRoute();
}

function parseRoute() {
  const rawHash = window.location.hash.replace(/^#\/?/, '').trim().toLowerCase();
  const route = VALID_ROUTES.includes(rawHash) ? rawHash : 'research';
  navigateTo(route, false);
}

function navigateTo(state, updateHash = true) {
  if (!VALID_ROUTES.includes(state)) state = 'research';
  currentState = state;

  if (updateHash) {
    window.location.hash = `#/${state}`;
  }

  // Update Body State Class
  document.body.className = `state-${state}`;

  // Update State Containers
  document.querySelectorAll('.state-container').forEach(el => el.classList.remove('active'));
  const targetEl = document.getElementById(`${state}-state`);
  if (targetEl) targetEl.classList.add('active');

  // Update Navbar Active Pills
  document.querySelectorAll('.nav-pill').forEach(el => el.classList.remove('active'));
  const navItem = document.getElementById(`nav-${state}`);
  if (navItem) navItem.classList.add('active');

  // State-specific initializations
  if (state === 'graph') {
    initKnowledgeGraphExplorer();
  } else if (state === 'catalog') {
    renderDiscoveryMovie();
  } else if (state === 'research') {
    const input = document.getElementById('main-composer-input');
    if (input) input.focus();
  } else if (state === 'chat') {
    renderActiveChatSession();
    const input = document.getElementById('chat-composer-input');
    if (input) input.focus();
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (window.lucide) lucide.createIcons();
}

function startNewChat() {
  toggleMobileSidebar(false);
  const newSession = {
    id: `sess_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
    title: 'New Research Thread',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    turns: []
  };
  userChatSessions.unshift(newSession);
  currentSessionId = newSession.id;
  saveUserSessionsToStorage();
  renderHistoryList();
  navigateTo('chat');
  renderActiveChatSession();

  const input = document.getElementById('chat-composer-input');
  if (input) {
    input.value = '';
    input.focus();
  }
}

function applySuggestion(text) {
  const input = document.getElementById('main-composer-input');
  if (input) {
    input.value = text;
    submitMainQuery();
  }
}

function handleComposerKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitMainQuery();
  }
}

function handleChatComposerKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitChatQuery();
  }
}

// ---------------------------------------------------------
// Documentation Tab Navigation
// ---------------------------------------------------------
function switchDocSection(sectionId, event) {
  if (event) event.preventDefault();

  document.querySelectorAll('.docs-nav-link').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.doc-article').forEach(el => el.classList.remove('active'));

  const link = event ? event.currentTarget : document.querySelector(`.docs-nav-link[href="#doc-${sectionId}"]`);
  if (link) link.classList.add('active');

  const article = document.getElementById(`doc-section-${sectionId}`);
  if (article) article.classList.add('active');

  if (window.lucide) lucide.createIcons();
}

// ---------------------------------------------------------
// System Stats & Catalog Loading
// ---------------------------------------------------------
async function fetchSystemStats() {
  try {
    const res = await fetch(getApiUrl('/api/stats'));
    if (res.ok) {
      const data = await res.json();
      const elNavStatus = document.getElementById('nav-status-text');
      const elMovies = document.getElementById('stat-movies');
      const elRels = document.getElementById('stat-rels');
      const elVec = document.getElementById('stat-vectors');

      if (elNavStatus && data.movies_count) {
        elNavStatus.textContent = `${Number(data.movies_count).toLocaleString()} Films Online`;
      }
      if (elMovies) elMovies.textContent = Number(data.movies_count).toLocaleString();
      if (elRels) elRels.textContent = Number(data.relationships_count).toLocaleString();
      if (elVec && data.vectors_count > 0) {
        elVec.textContent = `${Number(data.vectors_count).toLocaleString()} Vectors`;
      }
    }
  } catch (err) {
    console.warn('Could not load stats:', err);
  }
}

async function loadDiscoveryCatalog() {
  try {
    const res = await fetch(getApiUrl('/api/movies?limit=18'));
    if (res.ok) {
      const data = await res.json();
      discoveryMovies = data.movies || [];
      if (discoveryMovies.length > 0 && currentState === 'catalog') {
        renderDiscoveryMovie();
      }
    }
  } catch (err) {
    console.warn('Could not load discovery movies:', err);
  }
}

// ---------------------------------------------------------
// WebSocket Real-Time Connection
// ---------------------------------------------------------
function initWebSocket() {
  try {
    const wsUrl = getWebSocketUrl();
    chatSocket = new WebSocket(wsUrl);

    chatSocket.onopen = () => {
      console.log('✓ MovieGraph AI WebSocket Connected to', wsUrl);
    };

    chatSocket.onerror = (err) => {
      console.warn('WebSocket notice (will fall back to HTTP if needed):', err);
    };

    chatSocket.onclose = () => {
      console.log('WebSocket connection closed. Reconnecting in 5s...');
      setTimeout(initWebSocket, 5000);
    };
  } catch (e) {
    console.warn('Could not initialize WebSocket:', e);
  }
}

// ---------------------------------------------------------
// Chat Submission & MotionSites Loading Sequence
// ---------------------------------------------------------
function submitMainQuery() {
  const input = document.getElementById('main-composer-input');
  const query = input ? input.value.trim() : '';
  if (!query) return;
  input.value = '';

  navigateTo('chat');
  processUserQuery(query);
}

function submitChatQuery() {
  const input = document.getElementById('chat-composer-input');
  const query = input ? input.value.trim() : '';
  if (!query) return;
  input.value = '';

  processUserQuery(query);
}

async function processUserQuery(query) {
  const scrollArea = document.getElementById('chat-scroll-area');

  // Ensure active session exists
  let session = userChatSessions.find(s => s.id === currentSessionId);
  if (!session) {
    session = {
      id: `sess_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      title: query.length > 34 ? query.slice(0, 34) + '...' : query,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      turns: []
    };
    userChatSessions.unshift(session);
    currentSessionId = session.id;
  } else if (session.title === 'New Research Thread' || !session.turns || session.turns.length === 0) {
    session.title = query.length > 34 ? query.slice(0, 34) + '...' : query;
    session.updatedAt = Date.now();
  }

  saveUserSessionsToStorage();
  renderHistoryList();

  // Clear welcome screen if present
  const emptyWelcome = scrollArea.querySelector('.chat-empty-welcome');
  if (emptyWelcome) {
    emptyWelcome.remove();
  }

  // Render User Message Block
  const blockId = `msg-${Date.now()}`;
  const block = document.createElement('div');
  block.className = 'message-block';
  block.id = blockId;
  block.innerHTML = `
    <h2 class="user-query-heading">${escapeHtml(query)}</h2>
    <div class="loading-host-container"></div>
    <div class="assistant-content-container" style="display:none;"></div>
  `;
  scrollArea.appendChild(block);
  scrollArea.scrollTop = scrollArea.scrollHeight;

  // Start MotionSites 5-Phase Loading Sequence
  const loadingHost = block.querySelector('.loading-host-container');
  const animController = startCinematicLoadingSequence(loadingHost, query);

  // Try WebSocket First, with HTTP Fallback
  if (chatSocket && chatSocket.readyState === WebSocket.OPEN) {
    const handleWsMessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'phase') {
          animController.setPhase(payload.phase, payload.text);
        } else if (payload.type === 'complete') {
          chatSocket.removeEventListener('message', handleWsMessage);
          animController.finish(() => {
            // Save turn to user session
            session.turns.push({
              id: `turn_${Date.now()}`,
              query: query,
              result: payload,
              timestamp: Date.now()
            });
            session.updatedAt = Date.now();
            saveUserSessionsToStorage();
            renderHistoryList();
            renderAssistantResponse(block, payload);
          });
        } else if (payload.type === 'error') {
          chatSocket.removeEventListener('message', handleWsMessage);
          animController.finish(() => {
            const assistantContainer = block.querySelector('.assistant-content-container');
            if (assistantContainer) {
              assistantContainer.style.display = 'block';
              assistantContainer.innerHTML = `
                <div class="assistant-document">
                  <p style="color: #ff6b35; font-weight: 500;">
                    We encountered an issue retrieving movie knowledge: ${escapeHtml(payload.message || 'Unknown error')}
                  </p>
                </div>
              `;
            }
          });
        }
      } catch (err) {
        console.error('Error handling WebSocket message:', err);
      }
    };

    chatSocket.addEventListener('message', handleWsMessage);
    chatSocket.send(JSON.stringify({
      query: query,
      user_id: currentUserId,
      session_id: currentSessionId
    }));
  } else {
    // HTTP Fallback
    try {
      const response = await fetch(getApiUrl('/api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          user_id: currentUserId,
          session_id: currentSessionId,
          history: []
        })
      });

      if (!response.ok) throw new Error('API server returned an error.');
      const data = await response.json();

      animController.finish(() => {
        // Save turn to user session
        session.turns.push({
          id: `turn_${Date.now()}`,
          query: query,
          result: data,
          timestamp: Date.now()
        });
        session.updatedAt = Date.now();
        saveUserSessionsToStorage();
        renderHistoryList();
        renderAssistantResponse(block, data);
      });
    } catch (err) {
      animController.finish(() => {
        const assistantContainer = block.querySelector('.assistant-content-container');
        assistantContainer.style.display = 'block';
        assistantContainer.innerHTML = `
          <div class="assistant-document">
            <p style="color: #ff6b35;">We encountered an issue retrieving movie knowledge: ${escapeHtml(err.message)}</p>
          </div>
        `;
      });
    }
  }
}

// ---------------------------------------------------------
// MotionSites Live Animated Dynamic Background Engine
// ---------------------------------------------------------
function initMotionSitesLiveBackground() {
  const canvas = document.getElementById('motion-bg-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  window.addEventListener('resize', () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  // Track cursor position for subtle ambient glow
  window.addEventListener('mousemove', (e) => {
    const xPct = Math.round((e.clientX / width) * 100);
    const yPct = Math.round((e.clientY / height) * 100);
    document.documentElement.style.setProperty('--mouse-x', `${xPct}%`);
    document.documentElement.style.setProperty('--mouse-y', `${yPct}%`);
  });

  // Ambient floating bokeh / cinema particles (warm terracotta, ember, golden dust)
  const particles = [];
  const particleCount = 32;
  const colors = [
    'rgba(255, 107, 53, ',   // amber terracotta
    'rgba(224, 90, 58, ',    // deep terracotta
    'rgba(251, 191, 36, ',   // warm golden ember
    'rgba(200, 120, 77, '    // warm sand
  ];

  for (let i = 0; i < particleCount; i++) {
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height,
      radius: Math.random() * 2.2 + 0.8,
      colorPrefix: colors[Math.floor(Math.random() * colors.length)],
      alpha: Math.random() * 0.18 + 0.05,
      baseAlpha: Math.random() * 0.18 + 0.05,
      vx: (Math.random() - 0.5) * 0.25,
      vy: -(Math.random() * 0.35 + 0.1), // gentle upward float
      phase: Math.random() * Math.PI * 2
    });
  }

  let isPaused = false;
  document.addEventListener('visibilitychange', () => {
    isPaused = document.hidden;
    if (!isPaused) loop();
  });

  function loop() {
    if (isPaused) return;
    ctx.clearRect(0, 0, width, height);

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.phase += 0.015;
      p.x += p.vx + Math.sin(p.phase) * 0.15;
      p.y += p.vy;

      // Wrap around edges
      if (p.y < -10) {
        p.y = height + 10;
        p.x = Math.random() * width;
      }
      if (p.x < -10) p.x = width + 10;
      if (p.x > width + 10) p.x = -10;

      // Soft breathing alpha
      const currentAlpha = p.baseAlpha * (0.8 + 0.4 * Math.sin(p.phase));

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fillStyle = `${p.colorPrefix}${currentAlpha.toFixed(3)})`;
      ctx.shadowColor = 'rgba(255, 107, 53, 0.4)';
      ctx.shadowBlur = 8;
      ctx.fill();
    }

    ctx.shadowBlur = 0;
    requestAnimationFrame(loop);
  }

  loop();
}

// ---------------------------------------------------------
// MotionSites Cinematic Aperture & Shimmer Loading Sequence
// ---------------------------------------------------------
function startCinematicLoadingSequence(container, queryPreview) {
  container.innerHTML = `
    <div class="cinematic-loading-box">
      <div class="loading-query-preview">
        <span class="loading-query-prefix">Exploring:</span>
        <span class="loading-query-text">"${escapeHtml(queryPreview)}"</span>
      </div>
      
      <div class="loading-stage-cinematic">
        <!-- Cinematic Aperture Lens Spinner (Single MotionSites Element) -->
        <div class="aperture-lens-spinner">
          <svg class="aperture-svg" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="24" cy="24" r="21" stroke="rgba(255, 107, 53, 0.25)" stroke-width="1.5" stroke-dasharray="6 4" class="spinning-ring"/>
            <circle cx="24" cy="24" r="14" stroke="rgba(255, 255, 255, 0.12)" stroke-width="1.2"/>
            <polygon points="24,14 32,20 32,28 24,34 16,28 16,20" stroke="url(#spinnerGrad)" stroke-width="1.6" fill="none" class="pulsing-prism"/>
            <circle cx="24" cy="24" r="3.5" fill="url(#spinnerGrad)" class="glowing-core"/>
            <defs>
              <linearGradient id="spinnerGrad" x1="16" y1="14" x2="32" y2="34" gradientUnits="userSpaceOnUse">
                <stop stop-color="#FF6B35"/>
                <stop offset="0.6" stop-color="#E05A3A"/>
                <stop offset="1" stop-color="#FBBF24"/>
              </linearGradient>
            </defs>
          </svg>
        </div>

        <!-- Editorial status text with smooth updates -->
        <div class="loading-editorial-status">
          <span class="pulse-amber-beacon"></span>
          <span id="loading-status-label" class="loading-status-text">Synthesizing cinema intelligence &amp; archive graph...</span>
        </div>
      </div>
    </div>
  `;

  if (window.lucide) lucide.createIcons();

  const statusLabel = container.querySelector('#loading-status-label');

  return {
    setPhase: (phaseNum, text) => {
      if (statusLabel && text) {
        statusLabel.style.opacity = '0';
        setTimeout(() => {
          statusLabel.textContent = text;
          statusLabel.style.opacity = '1';
        }, 150);
      }
    },
    finish: (callback) => {
      if (statusLabel) {
        statusLabel.textContent = 'Cinema knowledge curated.';
      }
      setTimeout(() => {
        container.innerHTML = '';
        if (callback) callback();
      }, 250);
    }
  };
}

// ---------------------------------------------------------
// Bulletproof Markdown Parser with GFM Tables, Headers, Lists
// ---------------------------------------------------------
function parseCleanMarkdown(rawMd) {
  if (!rawMd) return '';
  
  // 1. Preprocess: Clean double/nested ### hashes and stray formatting
  let md = rawMd
    .replace(/#{1,6}\s*(?:\*{1,2}|_{1,2})?\s*#{1,6}\s*/g, '### ')
    .replace(/^(#{1,6}\s+)(?:\*{1,2}|_{1,2})(.*?)(?:\*{1,2}|_{1,2})$/gm, '$1$2')
    .replace(/([^\n])\n(#{1,6}\s+)/g, '$1\n\n$2')
    .replace(/\[(?:Wikipedia|IMDb)\]\(https?:\/\/[^\)]+\)(?:\s*\|\s*\[(?:Wikipedia|IMDb)\]\(https?:\/\/[^\)]+\))?/gi, '');

  // 2. Try marked if available
  if (typeof marked !== 'undefined' && marked.parse) {
    try {
      if (marked.setOptions) {
        marked.setOptions({ gfm: true, breaks: true });
      }
      const html = marked.parse(md);
      // Ensure no raw ### remains inside headings or text
      return html.replace(/<h([1-6])>\s*###+\s*/gi, '<h$1>');
    } catch (e) {
      console.warn('Marked parse error, using native parser:', e);
    }
  }

  // 3. Native Robust Fallback Parser
  const blocks = md.split(/\n\s*\n/);
  const htmlParts = [];

  for (let block of blocks) {
    block = block.trim();
    if (!block) continue;

    // Headings
    if (/^######\s+(.*)/s.test(block)) {
      htmlParts.push(`<h6>${inlineFormat(block.replace(/^######\s+/, ''))}</h6>`);
    } else if (/^#####\s+(.*)/s.test(block)) {
      htmlParts.push(`<h5>${inlineFormat(block.replace(/^#####\s+/, ''))}</h5>`);
    } else if (/^####\s+(.*)/s.test(block)) {
      htmlParts.push(`<h4>${inlineFormat(block.replace(/^####\s+/, ''))}</h4>`);
    } else if (/^###\s+(.*)/s.test(block)) {
      htmlParts.push(`<h3>${inlineFormat(block.replace(/^###\s+/, ''))}</h3>`);
    } else if (/^##\s+(.*)/s.test(block)) {
      htmlParts.push(`<h2>${inlineFormat(block.replace(/^##\s+/, ''))}</h2>`);
    } else if (/^#\s+(.*)/s.test(block)) {
      htmlParts.push(`<h1>${inlineFormat(block.replace(/^#\s+/, ''))}</h1>`);
    } else if (/^---|\*\*\*|___$/.test(block)) {
      htmlParts.push('<hr>');
    } else if (/^>\s+(.*)/s.test(block)) {
      htmlParts.push(`<blockquote>${inlineFormat(block.replace(/^>\s+/gm, ''))}</blockquote>`);
    } else if (block.includes('|') && block.split('\n').length > 1) {
      htmlParts.push(parseTableBlock(block));
    } else if (/^[\*\-\+]\s+/.test(block)) {
      const items = block.split('\n').filter(l => l.trim()).map(l => `<li>${inlineFormat(l.replace(/^[\*\-\+]\s+/, ''))}</li>`).join('');
      htmlParts.push(`<ul>${items}</ul>`);
    } else if (/^\d+\.\s+/.test(block)) {
      const items = block.split('\n').filter(l => l.trim()).map(l => `<li>${inlineFormat(l.replace(/^\d+\.\s+/, ''))}</li>`).join('');
      htmlParts.push(`<ol>${items}</ol>`);
    } else {
      htmlParts.push(`<p>${inlineFormat(block).replace(/\n/g, '<br>')}</p>`);
    }
  }

  return htmlParts.join('\n');
}

function inlineFormat(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function parseTableBlock(block) {
  const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return `<p>${inlineFormat(block)}</p>`;
  
  let html = '<table><thead><tr>';
  const headerCells = lines[0].split('|').map(c => c.trim()).filter(Boolean);
  headerCells.forEach(c => { html += `<th>${inlineFormat(c)}</th>`; });
  html += '</tr></thead><tbody>';

  const startIdx = lines[1].includes('---') ? 2 : 1;
  for (let i = startIdx; i < lines.length; i++) {
    const cells = lines[i].split('|').map(c => c.trim()).filter(Boolean);
    if (cells.length > 0) {
      html += '<tr>';
      cells.forEach(c => { html += `<td>${inlineFormat(c)}</td>`; });
      html += '</tr>';
    }
  }
  html += '</tbody></table>';
  return html;
}

// ---------------------------------------------------------
// Render Assistant Response
// ---------------------------------------------------------
function renderAssistantResponse(block, data) {
  const container = block.querySelector('.assistant-content-container');
  container.style.display = 'block';

  // 1. Markdown Content (Clean Parsed HTML)
  const markdownText = data.answer || 'No response details received.';
  const parsedHtml = parseCleanMarkdown(markdownText);

  // 2. Movie Cards
  let cardsHtml = '';
  if (data.movies && data.movies.length > 0) {
    cardsHtml = `
      <div class="movie-cards-grid">
        ${data.movies.map(m => `
          <div class="movie-card" onclick="openMovieDetail('${escapeHtml(m.title)}')">
            <div class="movie-card-backdrop" style="background-image: url('${escapeHtml(m.backdrop || '')}');"></div>
            <div class="movie-card-content">
              <div class="movie-card-title">${escapeHtml(m.title)}</div>
              <div class="movie-card-meta">${escapeHtml(m.year || '')} · ${escapeHtml(m.director || 'Director')}</div>
              <div class="movie-card-plot">${escapeHtml(m.plot || '')}</div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  // 3. Inline Relational Graph Diagram
  let graphHtml = '';
  if (data.graph && data.graph.nodes && data.graph.nodes.length > 1) {
    const graphId = `graph-${Date.now()}`;
    graphHtml = `
      <div class="inline-graph-box">
        <div class="inline-graph-title">Knowledge Graph Traversal</div>
        <svg id="${graphId}" class="inline-graph-svg"></svg>
      </div>
    `;
    setTimeout(() => {
      renderInlineGraph(graphId, data.graph);
    }, 50);
  }

  // 4. Citations & Top Verified Sources
  let sourcesHtml = '';
  if (data.sources && data.sources.length > 0) {
    sourcesHtml = `
      <div class="citations-box">
        <div class="citations-title">Verified Sources &amp; Archives</div>
        <div class="citations-list">
          ${data.sources.map(s => `
            <a href="${escapeHtml(s.url)}" target="_blank" class="citation-link" rel="noopener noreferrer">
              <i data-lucide="external-link" style="width: 12px; height: 12px;"></i>
              <span>${escapeHtml(s.title || s.domain)}</span>
            </a>
          `).join('')}
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="assistant-document">
      ${parsedHtml}
      ${cardsHtml}
      ${graphHtml}
      ${sourcesHtml}
    </div>
  `;

  if (window.lucide) lucide.createIcons();

  const scrollArea = document.getElementById('chat-scroll-area');
  if (scrollArea) {
    scrollArea.scrollTop = scrollArea.scrollHeight;
  }
}

// ---------------------------------------------------------
// D3 Inline Relational Graph
// ---------------------------------------------------------
function renderInlineGraph(svgId, graphData) {
  const svg = d3.select(`#${svgId}`);
  if (svg.empty()) return;

  const width = svg.node().getBoundingClientRect().width || 600;
  const height = 140;

  svg.selectAll('*').remove();

  const simulation = d3.forceSimulation(graphData.nodes)
    .force('link', d3.forceLink(graphData.links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(width / 2, height / 2));

  const link = svg.append('g')
    .attr('stroke', 'rgba(255, 255, 255, 0.15)')
    .attr('stroke-width', 1.2)
    .selectAll('line')
    .data(graphData.links)
    .join('line');

  const node = svg.append('g')
    .selectAll('g')
    .data(graphData.nodes)
    .join('g');

  node.append('circle')
    .attr('r', d => d.type === 'movie' ? 7 : 5)
    .attr('fill', d => {
      if (d.type === 'movie') return '#ff6b35';
      if (d.type === 'director' || d.type === 'actor') return '#38bdf8';
      if (d.type === 'genre') return '#34d399';
      return '#cbd5e1';
    })
    .attr('stroke', '#08080a')
    .attr('stroke-width', 1.5);

  node.append('text')
    .text(d => d.label)
    .attr('x', 9)
    .attr('y', 3)
    .attr('font-size', '10px')
    .attr('fill', 'rgba(255, 255, 255, 0.7)')
    .attr('font-family', 'Plus Jakarta Sans, sans-serif');

  simulation.on('tick', () => {
    link
      .attr('x1', d => Math.max(10, Math.min(width - 10, d.source.x)))
      .attr('y1', d => Math.max(10, Math.min(height - 10, d.source.y)))
      .attr('x2', d => Math.max(10, Math.min(width - 10, d.target.x)))
      .attr('y2', d => Math.max(10, Math.min(height - 10, d.target.y)));

    node
      .attr('transform', d => `translate(${Math.max(10, Math.min(width - 60, d.x))}, ${Math.max(10, Math.min(height - 10, d.y))})`);
  });
}

// ---------------------------------------------------------
// ---------------------------------------------------------
// Dedicated D3 Knowledge Graph Explorer
// ---------------------------------------------------------
let graphZoomBehavior = null;
let graphSvg = null;
let graphNodesData = [];
let graphLinksData = [];
let graphAdjacency = new Map();

async function initKnowledgeGraphExplorer(customFocus = null) {
  const container = document.getElementById('graph-canvas-container');
  if (!container) return;
  container.innerHTML = '<div style="color: rgba(255,255,255,0.5); padding: 120px 20px; text-align: center; font-size: 14px;"><span class="status-pulse-dot" style="display:inline-block; margin-right:8px;"></span> Loading cinema relational graph topology...</div>';

  try {
    const url = customFocus 
      ? `/api/graph?focus=${encodeURIComponent(customFocus)}`
      : '/api/graph?limit=150';
    const res = await fetch(getApiUrl(url));
    if (!res.ok) throw new Error('Failed to load graph data');
    const data = await res.json();
    container.innerHTML = '';

    graphNodesData = data.nodes || [];
    graphLinksData = data.links || [];

    if (graphNodesData.length === 0) {
      container.innerHTML = '<div style="color: var(--text-dim); padding: 80px; text-align: center;">No graph relationships found for this focus. Try another query or reset layout.</div>';
      return;
    }

    // Build Adjacency Index for instant O(1) hover highlighting
    graphAdjacency.clear();
    graphLinksData.forEach(link => {
      const sId = typeof link.source === 'object' ? link.source.id : link.source;
      const tId = typeof link.target === 'object' ? link.target.id : link.target;
      if (!graphAdjacency.has(sId)) graphAdjacency.set(sId, new Set());
      if (!graphAdjacency.has(tId)) graphAdjacency.set(tId, new Set());
      graphAdjacency.get(sId).add(tId);
      graphAdjacency.get(tId).add(sId);
    });

    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || (window.innerHeight - 90);

    const svg = d3.select(container).append('svg')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('viewBox', [0, 0, width, height]);

    graphSvg = svg;

    // Floating Tooltip Element
    let tooltip = d3.select('#graph-tooltip');
    if (tooltip.empty()) {
      tooltip = d3.select(container).append('div')
        .attr('id', 'graph-tooltip')
        .style('position', 'absolute')
        .style('pointer-events', 'none')
        .style('background', 'rgba(18, 17, 23, 0.95)')
        .style('backdrop-filter', 'blur(16px)')
        .style('border', '1px solid rgba(255, 255, 255, 0.12)')
        .style('border-radius', '8px')
        .style('padding', '8px 12px')
        .style('font-size', '12px')
        .style('color', '#fff')
        .style('box-shadow', '0 8px 24px rgba(0,0,0,0.6)')
        .style('opacity', 0)
        .style('z-index', '50')
        .style('transition', 'opacity 0.15s ease');
    }

    const g = svg.append('g');

    graphZoomBehavior = d3.zoom()
      .scaleExtent([0.15, 4.5])
      .on('zoom', (event) => g.attr('transform', event.transform));

    svg.call(graphZoomBehavior);

    // Dynamic node radii and coloring
    const getNodeRadius = (d) => {
      if (d.type === 'genre') return 12;
      if (d.type === 'director') return 9;
      if (d.type === 'movie') return 7;
      if (d.type === 'actor') return 5;
      return 6;
    };

    const getNodeColor = (d) => {
      if (d.type === 'genre') return '#10b981';
      if (d.type === 'director') return '#f59e0b';
      if (d.type === 'movie') return '#ff6b35';
      if (d.type === 'actor') return '#38bdf8';
      return '#cbd5e1';
    };

    // Advanced Force Simulation tuned for dense clustering
    d3Simulation = d3.forceSimulation(graphNodesData)
      .force('link', d3.forceLink(graphLinksData).id(d => d.id).distance(d => {
        const targetType = d.target ? d.target.type : '';
        return targetType === 'genre' ? 75 : 50;
      }))
      .force('charge', d3.forceManyBody().strength(d => {
        if (d.type === 'genre') return -220;
        if (d.type === 'director') return -140;
        return -75;
      }).distanceMax(450))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => getNodeRadius(d) + 5));

    // Warm-up ticks for instant organic distribution
    for (let i = 0; i < 35; ++i) d3Simulation.tick();

    const link = g.append('g')
      .attr('class', 'graph-links')
      .selectAll('line')
      .data(graphLinksData)
      .join('line')
      .attr('stroke', 'rgba(255, 255, 255, 0.13)')
      .attr('stroke-width', 1.2);

    const node = g.append('g')
      .attr('class', 'graph-nodes')
      .selectAll('g')
      .data(graphNodesData)
      .join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended));

    // Outer glow ring
    node.append('circle')
      .attr('class', 'node-halo')
      .attr('r', d => getNodeRadius(d) + 3)
      .attr('fill', 'transparent')
      .attr('stroke', d => getNodeColor(d))
      .attr('stroke-width', 1)
      .attr('opacity', 0);

    // Main Circle
    node.append('circle')
      .attr('class', 'node-circle')
      .attr('r', d => getNodeRadius(d))
      .attr('fill', d => getNodeColor(d))
      .attr('stroke', '#08080a')
      .attr('stroke-width', 1.6);

    // Label Text for Prominent Hubs (Genres, Directors, and Movies)
    node.append('text')
      .text(d => d.label)
      .attr('x', d => getNodeRadius(d) + 5)
      .attr('y', 3.5)
      .attr('font-size', d => d.type === 'genre' ? '12px' : (d.type === 'director' ? '11px' : '9.5px'))
      .attr('font-weight', d => (d.type === 'genre' || d.type === 'director') ? '600' : '400')
      .attr('fill', d => (d.type === 'genre' || d.type === 'director') ? 'rgba(255, 255, 255, 0.95)' : 'rgba(255, 255, 255, 0.65)')
      .attr('font-family', 'Plus Jakarta Sans, sans-serif')
      .attr('pointer-events', 'none')
      .style('display', d => d.type === 'actor' ? 'none' : 'block');

    // Interactive Hover Highlighting & Tooltip
    node
      .on('mouseenter', (event, d) => {
        const neighbors = graphAdjacency.get(d.id) || new Set();

        // Highlight connected nodes
        node.style('opacity', n => (n.id === d.id || neighbors.has(n.id)) ? 1 : 0.12);
        d3.select(event.currentTarget).select('.node-halo').attr('opacity', 0.8);

        // Highlight connected links
        link
          .attr('stroke', l => {
            const sId = l.source.id;
            const tId = l.target.id;
            return (sId === d.id || tId === d.id) ? '#ff6b35' : 'rgba(255, 255, 255, 0.04)';
          })
          .attr('stroke-width', l => {
            const sId = l.source.id;
            const tId = l.target.id;
            return (sId === d.id || tId === d.id) ? 2 : 1;
          });

        // Show Tooltip
        const degree = neighbors.size;
        const typeLabel = d.type ? d.type.toUpperCase() : 'NODE';
        tooltip
          .html(`
            <div style="font-weight: 600; color: #fff; margin-bottom: 3px;">${escapeHtml(d.label)}</div>
            <div style="display: flex; gap: 8px; align-items: center; color: var(--text-muted); font-size: 11px;">
              <span style="color: ${getNodeColor(d)}; font-weight: 600;">${escapeHtml(typeLabel)}</span>
              <span>·</span>
              <span>${degree} Connections</span>
            </div>
          `)
          .style('left', `${event.pageX + 14}px`)
          .style('top', `${event.pageY - 28}px`)
          .style('opacity', 1);
      })
      .on('mousemove', (event) => {
        tooltip
          .style('left', `${event.pageX + 14}px`)
          .style('top', `${event.pageY - 28}px`);
      })
      .on('mouseleave', () => {
        node.style('opacity', 1);
        node.selectAll('.node-halo').attr('opacity', 0);
        link
          .attr('stroke', 'rgba(255, 255, 255, 0.13)')
          .attr('stroke-width', 1.2);
        tooltip.style('opacity', 0);
      })
      .on('click', (event, d) => {
        if (d.type === 'movie') {
          openMovieDetail(d.label);
        } else if (d.type === 'director' || d.type === 'actor' || d.type === 'genre') {
          const input = document.getElementById('graph-search-input');
          if (input) {
            input.value = d.label;
            filterKnowledgeGraph({ target: { value: d.label } });
          }
        }
      });

    d3Simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);

      node
        .attr('transform', d => `translate(${d.x}, ${d.y})`);
    });

    function dragstarted(event, d) {
      if (!event.active) d3Simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }
    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }
    function dragended(event, d) {
      if (!event.active) d3Simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }

  } catch (err) {
    container.innerHTML = `<div style="color: #ff6b35; padding: 40px; text-align: center;">Could not load graph: ${escapeHtml(err.message)}</div>`;
  }
}

function resetKnowledgeGraph() {
  const input = document.getElementById('graph-search-input');
  if (input) input.value = '';
  initKnowledgeGraphExplorer();
}

function filterKnowledgeGraph(e) {
  const query = e.target.value.toLowerCase().trim();
  const nodes = d3.select('#graph-canvas-container').selectAll('.graph-nodes g');
  const links = d3.select('#graph-canvas-container').selectAll('.graph-links line');

  if (!query) {
    nodes.style('opacity', 1);
    nodes.selectAll('text').style('display', d => d.type === 'actor' ? 'none' : 'block');
    links.style('opacity', 1);
    return;
  }

  // Find matching nodes and their neighbors
  const matchingIds = new Set();
  graphNodesData.forEach(d => {
    if (d.label && d.label.toLowerCase().includes(query)) {
      matchingIds.add(d.id);
      const neighbors = graphAdjacency.get(d.id) || new Set();
      neighbors.forEach(nId => matchingIds.add(nId));
    }
  });

  nodes.style('opacity', d => matchingIds.has(d.id) ? 1 : 0.1);
  nodes.selectAll('text').style('display', d => matchingIds.has(d.id) ? 'block' : (d.type === 'actor' ? 'none' : 'block'));
  links.style('opacity', l => (matchingIds.has(l.source.id) && matchingIds.has(l.target.id)) ? 0.9 : 0.05);
}

// ---------------------------------------------------------
// Catalog / Movie Discovery Carousel
// ---------------------------------------------------------
function renderDiscoveryMovie() {
  if (!discoveryMovies || discoveryMovies.length === 0) return;
  const m = discoveryMovies[currentDiscoveryIndex];
  if (!m) return;

  const bg = document.getElementById('discovery-backdrop');
  const poster = document.getElementById('discovery-poster');
  const title = document.getElementById('discovery-title');
  const year = document.getElementById('discovery-year');
  const director = document.getElementById('discovery-director');
  const genre = document.getElementById('discovery-genre');
  const plot = document.getElementById('discovery-plot');

  if (bg) bg.style.backgroundImage = `url('${m.backdrop || ''}')`;
  if (poster) poster.style.backgroundImage = `url('${m.backdrop || ''}')`;
  if (title) title.textContent = m.title;
  if (year) year.textContent = m.year || '';
  if (director) director.textContent = m.director || 'Cinema Director';
  if (genre) genre.textContent = `${m.genre || 'Film'} · Curated`;
  if (plot) plot.textContent = m.plot || 'A compelling cinematic journey.';
}

function nextDiscoveryMovie() {
  if (discoveryMovies.length === 0) return;
  currentDiscoveryIndex = (currentDiscoveryIndex + 1) % discoveryMovies.length;
  renderDiscoveryMovie();
}

function prevDiscoveryMovie() {
  if (discoveryMovies.length === 0) return;
  currentDiscoveryIndex = (currentDiscoveryIndex - 1 + discoveryMovies.length) % discoveryMovies.length;
  renderDiscoveryMovie();
}

function inspectCurrentDiscoveryMovie() {
  if (discoveryMovies.length === 0) return;
  const m = discoveryMovies[currentDiscoveryIndex];
  if (m) openMovieDetail(m.title);
}

// ---------------------------------------------------------
// Movie Detail Modal
// ---------------------------------------------------------
async function openMovieDetail(title) {
  const modal = document.getElementById('movie-detail-modal');
  if (!modal) return;
  modal.classList.add('active');

  const titleEl = document.getElementById('modal-title');
  const metaEl = document.getElementById('modal-meta');
  const plotEl = document.getElementById('modal-plot');
  const backdropEl = document.getElementById('modal-backdrop');
  const wikiLink = document.getElementById('modal-wiki-link');

  if (titleEl) titleEl.textContent = title;
  if (metaEl) metaEl.textContent = 'Loading movie archive metadata...';
  if (plotEl) plotEl.textContent = 'Querying Neo4j knowledge graph...';

  try {
    const res = await fetch(getApiUrl(`/api/movies/${encodeURIComponent(title)}`));
    if (!res.ok) throw new Error('Film details not found');
    const data = await res.json();

    if (metaEl) metaEl.textContent = `${data.year || ''} · Directed by ${data.director || 'Unknown'} · ${data.genre || 'Cinema'}`;
    if (plotEl) plotEl.textContent = data.plot || 'No plot summary available.';
    if (backdropEl) backdropEl.style.backgroundImage = `url('${data.backdrop || ''}')`;
    if (wikiLink) {
      wikiLink.href = data.wiki_url || `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/\s+/g, '_'))}`;
    }

    if (data.graph && data.graph.nodes) {
      renderInlineGraph('modal-graph-svg', data.graph);
    }
  } catch (err) {
    if (metaEl) metaEl.textContent = 'Archived Film';
    if (plotEl) plotEl.textContent = `Could not load full graph metadata: ${err.message}`;
  }
}

function closeMovieDetail(event) {
  if (event.target.id === 'movie-detail-modal') {
    closeMovieDetailDirect();
  }
}

function closeMovieDetailDirect() {
  const modal = document.getElementById('movie-detail-modal');
  if (modal) modal.classList.remove('active');
}

// ---------------------------------------------------------
// Cookie & LocalStorage Multi-Tenant User Validation System
// ---------------------------------------------------------
function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^|;\\s*)' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[2]) : null;
}

function setCookie(name, value, days = 365) {
  const expires = new Date(Date.now() + days * 864e5).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

function deleteCookie(name) {
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax`;
}

async function initUserSession() {
  const cookieUser = getCookie('mg_user_id');
  const lsUser = localStorage.getItem('mg_user_id');
  let userId = null;

  if (cookieUser && /^usr_[a-zA-Z0-9_\-]+$/.test(cookieUser)) {
    userId = cookieUser;
    if (lsUser !== cookieUser) {
      localStorage.setItem('mg_user_id', cookieUser);
    }
  } else if (lsUser && /^usr_[a-zA-Z0-9_\-]+$/.test(lsUser)) {
    userId = lsUser;
    setCookie('mg_user_id', lsUser, 365);
  }

  // Validate or issue with backend
  try {
    const res = await fetch(getApiUrl('/api/user/validate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId })
    });
    if (res.ok) {
      const data = await res.json();
      if (data.user_id) {
        userId = data.user_id;
        setCookie('mg_user_id', userId, 365);
        localStorage.setItem('mg_user_id', userId);
      }
    }
  } catch (err) {
    console.warn('Backend user validation offline fallback:', err);
    if (!userId) {
      userId = `usr_${Math.random().toString(36).substring(2, 10)}${Date.now().toString(36)}`;
      setCookie('mg_user_id', userId, 365);
      localStorage.setItem('mg_user_id', userId);
    }
  }

  currentUserId = userId;
  updateUserBadges();
  loadUserSessionsFromStorage();
}

function updateUserBadges() {
  const navBadge = document.getElementById('navbar-user-id');
  const dropSub = document.getElementById('user-dropdown-id');
  const sidebarLabel = document.getElementById('sidebar-user-label');

  if (navBadge) navBadge.textContent = currentUserId;
  if (dropSub) dropSub.textContent = `Active ID: ${currentUserId}`;
  if (sidebarLabel) sidebarLabel.textContent = currentUserId;
}

function toggleUserDropdown(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('user-dropdown-menu');
  const badge = document.getElementById('user-profile-badge');
  if (menu) {
    const isShown = menu.classList.contains('show');
    menu.classList.toggle('show', !isShown);
    if (badge) badge.classList.toggle('active', !isShown);
  }
}

async function startNewUserSession(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('user-dropdown-menu');
  if (menu) menu.classList.remove('show');
  const badge = document.getElementById('user-profile-badge');
  if (badge) badge.classList.remove('active');

  // Generate a brand new user ID completely isolating the new user
  const newUserId = `usr_${Math.random().toString(36).substring(2, 10)}${Date.now().toString(36)}`;
  deleteCookie('mg_user_id');
  setCookie('mg_user_id', newUserId, 365);
  localStorage.setItem('mg_user_id', newUserId);

  currentUserId = newUserId;
  userChatSessions = [];
  currentSessionId = null;
  updateUserBadges();
  loadUserSessionsFromStorage();
  startNewChat();

  try {
    await fetch(getApiUrl('/api/user/validate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: newUserId })
    });
  } catch (e) {}
}

function confirmClearAllHistory(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('user-dropdown-menu');
  if (menu) menu.classList.remove('show');
  const badge = document.getElementById('user-profile-badge');
  if (badge) badge.classList.remove('active');

  if (confirm('Are you sure you want to erase all research history for this profile?')) {
    userChatSessions = [];
    currentSessionId = null;
    try {
      localStorage.removeItem(`mg_user_${currentUserId}_chats`);
      localStorage.removeItem(`mg_user_${currentUserId}_active_session`);
    } catch (e) {}
    renderHistoryList();
    startNewChat();
  }
}

// ---------------------------------------------------------
// Per-User Chat Sessions & LocalStorage Management
// ---------------------------------------------------------
function loadUserSessionsFromStorage() {
  if (!currentUserId) return;
  try {
    const raw = localStorage.getItem(`mg_user_${currentUserId}_chats`);
    if (raw) {
      userChatSessions = JSON.parse(raw);
    } else {
      userChatSessions = [];
    }

    const savedActive = localStorage.getItem(`mg_user_${currentUserId}_active_session`);
    if (savedActive && userChatSessions.some(s => s.id === savedActive)) {
      currentSessionId = savedActive;
    } else if (userChatSessions.length > 0) {
      currentSessionId = userChatSessions[0].id;
    } else {
      currentSessionId = null;
    }
  } catch (e) {
    userChatSessions = [];
    currentSessionId = null;
  }

  renderHistoryList();
  if (currentState === 'chat') {
    renderActiveChatSession();
  }
}

function saveUserSessionsToStorage() {
  if (!currentUserId) return;
  try {
    localStorage.setItem(`mg_user_${currentUserId}_chats`, JSON.stringify(userChatSessions.slice(0, 30)));
    if (currentSessionId) {
      localStorage.setItem(`mg_user_${currentUserId}_active_session`, currentSessionId);
    }
  } catch (e) {}
}

function renderActiveChatSession() {
  const scrollArea = document.getElementById('chat-scroll-area');
  if (!scrollArea) return;
  scrollArea.innerHTML = '';

  const session = userChatSessions.find(s => s.id === currentSessionId);
  if (!session || !session.turns || session.turns.length === 0) {
    // Show welcoming empty state
    scrollArea.innerHTML = `
      <div class="chat-empty-welcome">
        <div class="chat-empty-icon">
          <i data-lucide="sparkles" style="width: 26px; height: 26px;"></i>
        </div>
        <h2 class="chat-empty-title">Cinema GraphRAG Intelligence Workspace</h2>
        <p class="chat-empty-sub">
          Ask research inquiries, traverse director filmographies, uncover hidden thematic links, and inspect graph connections across cinema history.
        </p>
        <div class="empty-suggestions-grid">
          <div class="empty-prompt-card" onclick="applySuggestion('Films similar to Inception exploring dream layers and simulated reality')">
            <strong>Mind-bending films like Inception</strong>
            <p style="margin: 4px 0 0; font-size: 11.5px; color: var(--text-dim);">Simulated reality, layered narratives & perception</p>
          </div>
          <div class="empty-prompt-card" onclick="applySuggestion('Which films did Christopher Nolan direct and what connects their plots?')">
            <strong>Christopher Nolan's Directorial Graph</strong>
            <p style="margin: 4px 0 0; font-size: 11.5px; color: var(--text-dim);">Neo4j traversal of Nolan's filmography & collaborators</p>
          </div>
          <div class="empty-prompt-card" onclick="applySuggestion('Find neo-noir psychological thrillers with nonlinear timelines')">
            <strong>Neo-Noir Psychological Thrillers</strong>
            <p style="margin: 4px 0 0; font-size: 11.5px; color: var(--text-dim);">Subversion, fatalism, and high-tension narrative arcs</p>
          </div>
          <div class="empty-prompt-card" onclick="applySuggestion('Who starred in the 1924 silent classic Beau Brummel?')">
            <strong>Beau Brummel (1924) Cast Archive</strong>
            <p style="margin: 4px 0 0; font-size: 11.5px; color: var(--text-dim);">Historical archive verification from Wikipedia & Neo4j</p>
          </div>
        </div>
      </div>
    `;
    if (window.lucide) lucide.createIcons();
    return;
  }

  // Render all saved turns in this session
  session.turns.forEach((turn, idx) => {
    const block = document.createElement('div');
    block.className = 'message-block';
    block.id = `msg-${turn.id || idx}`;
    block.innerHTML = `
      <h2 class="user-query-heading">${escapeHtml(turn.query)}</h2>
      <div class="assistant-content-container" style="display:block;"></div>
    `;
    scrollArea.appendChild(block);
    renderAssistantResponse(block, turn.result);
  });

  scrollArea.scrollTop = scrollArea.scrollHeight;
}

function toggleMobileSidebar(open) {
  const sidebar = document.querySelector('.chat-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!sidebar) return;

  const willOpen = open !== undefined ? open : !sidebar.classList.contains('drawer-open');
  if (willOpen) {
    sidebar.classList.add('drawer-open');
    if (backdrop) backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  } else {
    sidebar.classList.remove('drawer-open');
    if (backdrop) backdrop.classList.remove('active');
    document.body.style.overflow = '';
  }
}

function switchChatSession(sessionId) {
  toggleMobileSidebar(false);
  currentSessionId = sessionId;
  saveUserSessionsToStorage();
  navigateTo('chat');
  renderHistoryList();
  renderActiveChatSession();
}

function deleteChatSession(sessionId, event) {
  if (event) event.stopPropagation();

  userChatSessions = userChatSessions.filter(s => s.id !== sessionId);

  // Clean up server-side memory
  try {
    fetch(getApiUrl(`/api/sessions/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(currentUserId)}`), {
      method: 'DELETE'
    });
  } catch (e) {}

  if (currentSessionId === sessionId) {
    if (userChatSessions.length > 0) {
      currentSessionId = userChatSessions[0].id;
    } else {
      currentSessionId = null;
      startNewChat();
      return;
    }
  }

  saveUserSessionsToStorage();
  renderHistoryList();
  renderActiveChatSession();
}

function renderHistoryList() {
  const list = document.getElementById('history-list');
  const countBadge = document.getElementById('mobile-history-count');
  const count = userChatSessions ? userChatSessions.length : 0;
  if (countBadge) countBadge.textContent = count;

  if (!list) return;
  list.innerHTML = '';

  if (!userChatSessions || userChatSessions.length === 0) {
    list.innerHTML = `
      <li class="history-empty-notice">
        No active research threads.<br>
        Click <strong>+ New Research</strong> above to start.
      </li>
    `;
    return;
  }

  userChatSessions.forEach(session => {
    const isActive = session.id === currentSessionId;
    const li = document.createElement('li');
    li.className = `history-item ${isActive ? 'active' : ''}`;
    li.id = `hist-${session.id}`;

    const timeStr = formatRelativeTime(session.updatedAt || session.createdAt);

    li.innerHTML = `
      <div class="history-item-body" onclick="switchChatSession('${escapeHtml(session.id)}')">
        <div class="history-item-title" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</div>
        <div class="history-item-time">${escapeHtml(timeStr)}</div>
      </div>
      <button class="btn-delete-chat" onclick="deleteChatSession('${escapeHtml(session.id)}', event)" title="Delete this chat">
        <i data-lucide="trash-2" style="width: 13px; height: 13px;"></i>
      </button>
    `;
    list.appendChild(li);
  });

  if (window.lucide) lucide.createIcons();
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return 'Recently';
  const diff = Date.now() - timestamp;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function initGlobalEvents() {
  document.addEventListener('click', (e) => {
    const badge = document.getElementById('user-profile-badge');
    const menu = document.getElementById('user-dropdown-menu');
    if (menu && menu.classList.contains('show')) {
      if (!badge || !badge.contains(e.target)) {
        menu.classList.remove('show');
        if (badge) badge.classList.remove('active');
      }
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      toggleMobileSidebar(false);
      const menu = document.getElementById('user-dropdown-menu');
      if (menu) menu.classList.remove('show');
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
