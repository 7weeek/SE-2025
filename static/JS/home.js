


// home.js — dynamic test loading & navigation with domain filtering, search, and view toggle

const statusEl = document.getElementById('status');
const testsContainer = document.getElementById('testsContainer');
const domainFiltersEl = document.getElementById('domainFilters');
const testCountEl = document.getElementById('testCount');
const searchInput = document.getElementById('searchInput');
const clearSearch = document.getElementById('clearSearch');
const emptyState = document.getElementById('emptyState');
const gridViewBtn = document.getElementById('gridView');
const listViewBtn = document.getElementById('listView');
const token = localStorage.getItem('authToken');

let allTests = [];
let allDomains = [];
let currentDomain = 'all';
let currentSearch = '';
let currentView = 'grid';

// Redirect if user is not authenticated
if (!token) {
  localStorage.removeItem('authToken');
  window.location.href = '/login.html';
}

// Logout button
document.getElementById('logout').addEventListener('click', () => {
  localStorage.removeItem('authToken');
  window.location.href = '/login.html';
});

// Load user profile
(async function loadProfile() {
  try {
    const res = await fetch('/api/me', {
      headers: { 'Authorization': 'Bearer ' + token }
    });

    if (res.status === 401) {
      localStorage.removeItem('authToken');
      return window.location.href = '/login.html';
    }

    const data = await res.json();
    statusEl.textContent = `Signed in as ${data.name}`;

  } catch (err) {
    statusEl.textContent = 'Network error verifying session.';
  }
})();

// Load available tests
async function loadTests(domain = '') {
  try {
    const url = domain 
      ? `/api/tests?domain=${encodeURIComponent(domain)}`
      : '/api/tests';
    
    const res = await fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token }
    });

    if (!res.ok) {
      testsContainer.innerHTML = "<p>Unable to load tests.</p>";
      return;
    }

    const data = await res.json();

    // Store all tests and domains on first load (only when loading all tests)
    if (domain === '') {
      if (data.domains && data.domains.length > 0) {
        allDomains = data.domains;
        setupDomainFilters();
      }
      allTests = data.tests;
    }

    renderTests(data.tests);
    updateTestCount(data.total || data.tests.length);

  } catch (err) {
    console.error('Error loading tests:', err);
    testsContainer.innerHTML = "<p>Network error loading tests.</p>";
  }
}

// Setup domain filter buttons using event delegation
function setupDomainFilters() {
  if (!domainFiltersEl) {
    console.error('domainFilters element not found');
    return;
  }

  if (!allDomains || allDomains.length === 0) {
    console.warn('No domains available to create filters');
    return;
  }

  // Clear existing filters and recreate "All Tests" button
  domainFiltersEl.innerHTML = '';
  
  // Create "All Tests" button
  const allBtn = document.createElement('button');
  allBtn.className = 'domain-btn active';
  allBtn.setAttribute('data-domain', 'all');
  allBtn.textContent = 'All Tests';
  domainFiltersEl.appendChild(allBtn);

  // Add domain buttons
  allDomains.forEach(domain => {
    const btn = document.createElement('button');
    btn.className = 'domain-btn';
    btn.setAttribute('data-domain', domain.toLowerCase());
    btn.textContent = domain;
    domainFiltersEl.appendChild(btn);
  });
}

// Filter tests by domain
function filterByDomain(domain) {
  // Handle "all" case
  if (domain === 'all' || domain === 'All Tests' || !domain) {
    currentDomain = 'all';
  } else {
    // Store the original domain name for API call, but use lowercase for comparison
    currentDomain = domain.toLowerCase();
  }
  
  // Update active button state
  document.querySelectorAll('.domain-btn').forEach(btn => {
    const btnDomain = btn.getAttribute('data-domain');
    if (btnDomain === currentDomain) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Clear search when changing domain
  if (searchInput) {
    searchInput.value = '';
    currentSearch = '';
    if (clearSearch) clearSearch.style.display = 'none';
  }

  // Load tests for selected domain
  if (currentDomain === 'all') {
    loadTests('');
  } else {
    // Pass the original domain name (with proper casing) to the API
    // The backend will handle case-insensitive matching
    loadTests(domain);
  }
}

// Render tests to the container
function renderTests(tests) {
  testsContainer.innerHTML = ""; // clear
  emptyState.style.display = "none";

  // Apply search filter
  let filteredTests = tests;
  if (currentSearch.trim()) {
    const searchLower = currentSearch.toLowerCase();
    filteredTests = tests.filter(test => 
      test.title.toLowerCase().includes(searchLower) ||
      test.domain.toLowerCase().includes(searchLower) ||
      (test.description && test.description.toLowerCase().includes(searchLower))
    );
  }

  if (filteredTests.length === 0) {
    testsContainer.style.display = "none";
    emptyState.style.display = "block";
    return;
  }

  testsContainer.style.display = "grid";
  
  // Apply view class
  testsContainer.classList.remove('list-view');
  if (currentView === 'list') {
    testsContainer.classList.add('list-view');
  }

  filteredTests.forEach(test => {
    const card = document.createElement("div");
    card.className = `test-card ${currentView === 'list' ? 'list-view' : ''}`;

    const cardContent = currentView === 'list' 
      ? `
        <div class="test-content">
          <div style="display:flex; gap:12px; align-items:center; margin-bottom:8px;">
            <span class="domain-badge">${test.domain}</span>
            <span class="difficulty ${test.difficulty.toLowerCase()}">${test.difficulty}</span>
          </div>
          <h3>${test.title}</h3>
          <p>${test.description}</p>
        </div>
        <button class="btn start-btn" data-id="${test.id}" style="width:auto; min-width:140px;">
          <span>🚀</span>
          Start Test
        </button>
      `
      : `
        <span class="domain-badge">${test.domain}</span>
        <span class="difficulty ${test.difficulty.toLowerCase()}">${test.difficulty}</span>
        <h3>${test.title}</h3>
        <p>${test.description}</p>
        <button class="btn start-btn" data-id="${test.id}">
          <span>🚀</span>
          Start Test
        </button>
      `;

    card.innerHTML = cardContent;
    testsContainer.appendChild(card);
  });

  // Add click handlers with animation
  document.querySelectorAll(".start-btn").forEach(btn => {
    btn.addEventListener("click", function() {
      this.style.transform = "scale(0.95)";
      setTimeout(() => {
        const testId = this.getAttribute("data-id");
        window.location.href = `/verify.html?testId=${testId}`;
      }, 150);
    });
  });
}

// Update test count display
function updateTestCount(count) {
  const domainText = currentDomain === 'all' 
    ? 'All Tests' 
    : allDomains.find(d => d.toLowerCase() === currentDomain) || currentDomain;
  
  // Apply search filter to count
  let filteredCount = count;
  if (currentSearch.trim() && allTests.length > 0) {
    const searchLower = currentSearch.toLowerCase();
    filteredCount = allTests.filter(test => {
      const matchesDomain = currentDomain === 'all' || test.domain.toLowerCase() === currentDomain;
      const matchesSearch = test.title.toLowerCase().includes(searchLower) ||
        test.domain.toLowerCase().includes(searchLower) ||
        (test.description && test.description.toLowerCase().includes(searchLower));
      return matchesDomain && matchesSearch;
    }).length;
  }
  
  testCountEl.textContent = `Showing ${filteredCount} test${filteredCount !== 1 ? 's' : ''}${currentDomain !== 'all' ? ` in ${domainText}` : ''}${currentSearch ? ` matching "${currentSearch}"` : ''}`;
}

// Search functionality
if (searchInput) {
  let searchTimeout;
  searchInput.addEventListener('input', (e) => {
    clearTimeout(searchTimeout);
    currentSearch = e.target.value;
    
    if (currentSearch.trim()) {
      clearSearch.style.display = 'block';
    } else {
      clearSearch.style.display = 'none';
    }
    
    searchTimeout = setTimeout(() => {
      // Re-render with search filter
      if (currentDomain === 'all') {
        renderTests(allTests);
      } else {
        const filtered = allTests.filter(t => 
          t.domain.toLowerCase() === currentDomain
        );
        renderTests(filtered);
      }
      updateTestCount(allTests.length);
    }, 300);
  });
}

if (clearSearch) {
  clearSearch.addEventListener('click', () => {
    searchInput.value = '';
    currentSearch = '';
    clearSearch.style.display = 'none';
    if (currentDomain === 'all') {
      renderTests(allTests);
    } else {
      const filtered = allTests.filter(t => 
        t.domain.toLowerCase() === currentDomain
      );
      renderTests(filtered);
    }
    updateTestCount(allTests.length);
  });
}

// View toggle
if (gridViewBtn && listViewBtn) {
  gridViewBtn.addEventListener('click', () => {
    currentView = 'grid';
    gridViewBtn.classList.add('active');
    listViewBtn.classList.remove('active');
    if (currentDomain === 'all') {
      renderTests(allTests);
    } else {
      const filtered = allTests.filter(t => 
        t.domain.toLowerCase() === currentDomain
      );
      renderTests(filtered);
    }
  });
  
  listViewBtn.addEventListener('click', () => {
    currentView = 'list';
    listViewBtn.classList.add('active');
    gridViewBtn.classList.remove('active');
    if (currentDomain === 'all') {
      renderTests(allTests);
    } else {
      const filtered = allTests.filter(t => 
        t.domain.toLowerCase() === currentDomain
      );
      renderTests(filtered);
    }
  });
}

// Use event delegation for the initial "All Tests" button as well
if (domainFiltersEl) {
  domainFiltersEl.addEventListener('click', (e) => {
    if (e.target.classList.contains('domain-btn')) {
      e.preventDefault();
      const domainAttr = e.target.getAttribute('data-domain');
      if (domainAttr === 'all') {
        filterByDomain('all');
      } else if (allDomains.length > 0) {
        // Find the original domain name from allDomains
        const originalDomain = allDomains.find(d => d.toLowerCase() === domainAttr);
        if (originalDomain) {
          filterByDomain(originalDomain);
        }
      }
    }
  });
}

// Initialize on page load
loadTests();
