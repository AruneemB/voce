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
