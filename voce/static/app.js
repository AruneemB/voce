// ── State ────────────────────────────────────────────────────────────────────
let currentSection = null;
let currentTopic = null;
let currentStatus = null;
let currentOffset = 0;
const PAGE_SIZE = 30;

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 10);
}

// ── Articles ──────────────────────────────────────────────────────────────────
async function loadArticles(reset = true) {
  const list = document.getElementById('article-list');
  if (reset) {
    list.innerHTML = '';
    currentOffset = 0;
  }

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: currentOffset });
  if (currentSection) params.set('section', currentSection);
  if (currentStatus) params.set('status', currentStatus);
  if (currentTopic) params.set('topic', currentTopic);

  try {
    const res = await fetch(`/api/articles?${params}`);
    if (!res.ok) throw new Error('articles fetch failed');
    const data = await res.json();
    data.items.forEach(article => {
      const card = document.createElement('div');
      card.className = 'article-card';
      card.dataset.articleId = article.id;
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      const summary = article.summary ? article.summary.slice(0, 200) : '';
      card.innerHTML = `
        <div class="article-card-title text-sm font-semibold leading-snug">${article.title}</div>
        <div class="article-card-meta text-xs text-gray-500 mt-0.5">${article.author || ''} · ${formatDate(article.published_at)}</div>
        <div class="article-card-summary text-xs text-gray-500 mt-1 leading-snug">${summary}${summary.length === 200 ? '…' : ''}</div>
        <span class="status-badge status-${article.status} mt-1">${article.status}</span>
      `;
      card.addEventListener('click', () => loadArticleDetail(article.id));
      card.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') loadArticleDetail(article.id);
      });
      list.appendChild(card);
    });
    currentOffset += PAGE_SIZE;
  } catch (e) {
    showToast('Failed to load articles', 'error');
  }
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
      btn.innerHTML = `<span>${item.display_name}</span><span class="badge text-xs bg-gray-300 text-gray-700 rounded-full px-1.5 ml-1">${item.unread_count}</span>`;
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
