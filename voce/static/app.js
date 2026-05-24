// ── State ────────────────────────────────────────────────────────────────────
let currentSection = null;
let currentTopic = null;
let currentStatus = null;
let currentOffset = 0;
let currentArticleId = null;
const PAGE_SIZE = 30;

// Allowed reading-status values — used to whitelist CSS class names derived
// from API responses so that unexpected values cannot inject arbitrary classes.
const VALID_STATUSES = new Set(['unread', 'queued', 'listened']);

// Pagination guards — prevent IntersectionObserver from firing a second load
// while a fetch is already in flight, and stop requesting once the last page
// has been received.
let isLoadingArticles = false;
let hasMoreArticles = true;

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 10);
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

// ── Articles ──────────────────────────────────────────────────────────────────
async function loadArticles(reset = true) {
  if (isLoadingArticles) return;
  const list = document.getElementById('article-list');
  if (reset) {
    list.innerHTML = '';
    currentOffset = 0;
    hasMoreArticles = true;
  }
  if (!hasMoreArticles) return;
  isLoadingArticles = true;

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: currentOffset });
  if (currentSection) params.set('section', currentSection);
  if (currentStatus) params.set('status', currentStatus);
  if (currentTopic) params.set('topic', currentTopic);

  try {
    const res = await fetch(`/api/articles?${params}`);
    if (!res.ok) throw new Error('articles fetch failed');
    const data = await res.json();
    const items = Array.isArray(data.items) ? data.items : [];
    items.forEach(article => {
      const card = document.createElement('div');
      card.className = 'article-card';
      card.dataset.articleId = article.id;
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      const summary = article.summary ? article.summary.slice(0, 200) : '';
      const status = VALID_STATUSES.has(article.status) ? article.status : 'unread';
      card.innerHTML = `
        <div class="article-card-title text-sm font-semibold leading-snug">${escapeHtml(article.title)}</div>
        <div class="article-card-meta text-xs text-gray-500 mt-0.5">${escapeHtml(article.author || '')} · ${formatDate(article.published_at)}</div>
        <div class="article-card-summary text-xs text-gray-500 mt-1 leading-snug">${escapeHtml(summary)}${summary.length === 200 ? '…' : ''}</div>
        <span class="status-badge status-${status} mt-1">${escapeHtml(status)}</span>
      `;
      card.addEventListener('click', () => loadArticleDetail(article.id));
      card.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') loadArticleDetail(article.id);
      });
      list.appendChild(card);
    });
    currentOffset += items.length;
    hasMoreArticles = items.length === PAGE_SIZE;
  } catch (e) {
    showToast('Failed to load articles', 'error');
  } finally {
    isLoadingArticles = false;
  }
}

// ── Article Detail ────────────────────────────────────────────────────────────
async function loadArticleDetail(articleId) {
  currentArticleId = articleId;
  document.querySelectorAll('.article-card').forEach(c => c.classList.remove('active'));
  const activeCard = document.querySelector(`.article-card[data-article-id="${articleId}"]`);
  if (activeCard) activeCard.classList.add('active');

  try {
    const res = await fetch(`/api/articles/${articleId}`);
    if (!res.ok) throw new Error('detail fetch failed');
    const article = await res.json();

    const paragraphs = (article.body_text || '')
      .split('\n\n')
      .filter(p => p.trim())
      .map(p => `<p>${escapeHtml(p.trim())}</p>`)
      .join('');

    document.getElementById('article-detail').innerHTML = `
      <h1 class="text-2xl font-bold leading-tight mb-2">${escapeHtml(article.title)}</h1>
      <p class="byline text-sm text-gray-500 mb-4">${escapeHtml(article.author || '')} · ${formatDate(article.published_at)}</p>
      <a href="${escapeHtml(article.url)}" target="_blank" rel="noopener" class="quanta-link">Open in Quanta ↗</a>
      <div id="audio-player-section"></div>
      <div class="prose">${paragraphs}</div>
    `;

    history.pushState({ articleId }, '', `#article/${articleId}`);

    try {
      const statusRes = await fetch(`/api/articles/${articleId}/audio/status`);
      const statusData = statusRes.ok
        ? await statusRes.json()
        : { cached: false, pending: false };
      renderAudioSection(articleId, statusData, article);
    } catch (_) {
      renderAudioSection(articleId, { cached: false, pending: false }, article);
    }
  } catch (e) {
    showToast('Failed to load article', 'error');
  }
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
  const colors = {
    error: 'background:#ef4444;color:#fff',
    success: 'background:#22c55e;color:#fff',
    info: 'background:#3b82f6;color:#fff',
  };
  const div = document.createElement('div');
  div.style.cssText = `${colors[type] || colors.info};padding:0.5rem 1rem;border-radius:0.375rem;box-shadow:0 2px 8px rgba(0,0,0,0.15);font-size:0.875rem;font-weight:500`;
  div.textContent = message;
  document.getElementById('toast-container').appendChild(div);
  setTimeout(() => div.remove(), 4000);
}

// ── Refresh ───────────────────────────────────────────────────────────────────
async function triggerRefresh() {
  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    if (!res.ok) throw new Error('refresh failed');
    showToast('Feed refreshed', 'success');
    loadSections();
    loadArticles(true);
  } catch (e) {
    showToast('Failed to refresh feed', 'error');
  }
}

// ── Debounced Search ──────────────────────────────────────────────────────────
let _searchTimer = null;

function setupSearch() {
  document.getElementById('search-input').addEventListener('input', e => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async () => {
      const q = e.target.value.trim();
      if (!q) {
        loadArticles(true);
        return;
      }
      const list = document.getElementById('article-list');
      list.innerHTML = '';
      currentOffset = 0;
      try {
        let res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        if (res.status === 404) {
          res = await fetch(`/api/articles?q=${encodeURIComponent(q)}&limit=${PAGE_SIZE}&offset=0`);
        }
        if (!res.ok) throw new Error('search failed');
        const data = await res.json();
        const items = Array.isArray(data) ? data : (data.items || []);
        items.forEach(article => {
          const card = document.createElement('div');
          card.className = 'article-card';
          card.dataset.articleId = article.id;
          card.setAttribute('role', 'button');
          card.setAttribute('tabindex', '0');
          const summary = article.summary ? article.summary.slice(0, 200) : '';
          const status = VALID_STATUSES.has(article.status) ? article.status : 'unread';
          card.innerHTML = `
            <div class="article-card-title text-sm font-semibold leading-snug">${escapeHtml(article.title)}</div>
            <div class="article-card-meta text-xs text-gray-500 mt-0.5">${escapeHtml(article.author || '')} · ${formatDate(article.published_at)}</div>
            <div class="article-card-summary text-xs text-gray-500 mt-1 leading-snug">${escapeHtml(summary)}${summary.length === 200 ? '…' : ''}</div>
            <span class="status-badge status-${status} mt-1">${escapeHtml(status)}</span>
          `;
          card.addEventListener('click', () => loadArticleDetail(article.id));
          list.appendChild(card);
        });
      } catch (e) {
        showToast('Search failed', 'error');
      }
    }, 300);
  });
}

// ── Initialisation ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSections();
  loadArticles(true);

  // Infinite scroll
  const sentinel = document.getElementById('load-more-sentinel');
  new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) loadArticles(false);
  }, { threshold: 0.1 }).observe(sentinel);

  // State filter buttons
  document.getElementById('state-filters').addEventListener('click', e => {
    const btn = e.target.closest('[data-status]');
    if (!btn) return;
    document.querySelectorAll('#state-filters button').forEach(b => b.classList.remove('bg-blue-100', 'text-blue-800', 'font-semibold'));
    btn.classList.add('bg-blue-100', 'text-blue-800', 'font-semibold');
    currentStatus = btn.dataset.status || null;
    currentOffset = 0;
    loadArticles(true);
  });

  // Topic filter
  document.getElementById('topic-filter').addEventListener('change', e => {
    currentTopic = e.target.value || null;
    currentOffset = 0;
    loadArticles(true);
  });

  // Search
  setupSearch();

  // Deep-link via hash
  const match = location.hash.match(/^#article\/(.+)$/);
  if (match) loadArticleDetail(match[1]);
});

// ── Audio Player ──────────────────────────────────────────────────────────────
function renderAudioSection(articleId, statusData, article) {
  const container = document.getElementById('audio-player-section');
  if (!container) return;
  if (statusData.cached) {
    container.innerHTML = buildAudioPlayer(statusData.url, statusData.duration_sec);
  } else if (article && article.quanta_audio_url) {
    container.innerHTML =
      buildAudioPlayer(article.quanta_audio_url, null) +
      '<p class="text-sm text-gray-500 mt-1">Quanta\'s own narration</p>';
  } else {
    container.innerHTML = buildGenerateButton(statusData.pending);
    if (!statusData.pending) {
      container.querySelector('.btn-generate').addEventListener('click', () => requestAudio(articleId));
    }
  }
}

function buildAudioPlayer(src, durationSec) {
  const durationStr = durationSec ? formatDuration(durationSec) : '';
  return (
    `<audio controls src="${escapeHtml(src)}" class="w-full my-2"></audio>` +
    (durationStr ? `<p class="text-xs text-gray-500">${escapeHtml(durationStr)}</p>` : '')
  );
}

function buildGenerateButton(pending) {
  if (pending) {
    return '<p class="text-sm text-gray-500 animate-pulse">Generating audio…</p>';
  }
  return '<button class="btn-generate">Listen with Voce</button>';
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

async function requestAudio(articleId) {
  const container = document.getElementById('audio-player-section');
  if (container) {
    container.innerHTML = '<p class="text-sm text-gray-500 animate-pulse">Generating audio…</p>';
  }
  try {
    const res = await fetch(`/api/articles/${articleId}/audio`, { method: 'POST' });
    if (!res.ok) throw new Error('trigger failed');
    const data = await res.json();
    if (data.status === 'ready') {
      const statusRes = await fetch(`/api/articles/${articleId}/audio/status`);
      if (statusRes.ok) renderAudioSection(articleId, await statusRes.json(), null);
    } else {
      pollAudioStatus(articleId, 0);
    }
  } catch (_) {
    showToast('Failed to start audio generation', 'error');
    if (container) {
      container.innerHTML = buildGenerateButton(false);
      container.querySelector('.btn-generate').addEventListener('click', () => requestAudio(articleId));
    }
  }
}

function pollAudioStatus(articleId, attempt) {
  if (attempt >= 60) {
    if (articleId !== currentArticleId) return;
    showToast('Audio generation timed out', 'error');
    const container = document.getElementById('audio-player-section');
    if (container) {
      container.innerHTML = buildGenerateButton(false);
      container.querySelector('.btn-generate').addEventListener('click', () => requestAudio(articleId));
    }
    return;
  }
  setTimeout(async () => {
    if (articleId !== currentArticleId) return;
    try {
      const res = await fetch(`/api/articles/${articleId}/audio/status`);
      if (!res.ok) throw new Error('status fetch failed');
      const data = await res.json();
      if (data.cached) {
        renderAudioSection(articleId, data, null);
      } else {
        pollAudioStatus(articleId, attempt + 1);
      }
    } catch (_) {
      pollAudioStatus(articleId, attempt + 1);
    }
  }, 2000);
}

// ── Sections ──────────────────────────────────────────────────────────────────
async function loadSections() {
  try {
    const res = await fetch('/api/sections');
    if (!res.ok) throw new Error('sections fetch failed');
    const sections = await res.json();
    const list = document.getElementById('section-list');
    list.innerHTML = '';
    sections.forEach(item => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.className = 'w-full text-left px-2 py-1.5 text-sm rounded hover:bg-gray-200 flex justify-between items-center';
      btn.dataset.section = item.section;
      btn.innerHTML = `<span>${escapeHtml(item.display_name)}</span><span class="badge text-xs bg-gray-300 text-gray-700 rounded-full px-1.5 ml-1">${item.unread_count}</span>`;
      btn.addEventListener('click', () => {
        list.querySelectorAll('button').forEach(b => b.classList.remove('active', 'bg-blue-100', 'text-blue-800', 'font-semibold'));
        btn.classList.add('active', 'bg-blue-100', 'text-blue-800', 'font-semibold');
        currentSection = item.section;
        currentOffset = 0;
        loadArticles(true);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
  } catch (e) {
    showToast('Failed to load sections', 'error');
  }
}
