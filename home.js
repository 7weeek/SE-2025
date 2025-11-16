// // home.js — handles auth check, profile load, navigation

// const statusEl = document.getElementById('status');
// const token = localStorage.getItem('authToken');

// // If no token at all → redirect to login
// if (!token) {
//   localStorage.removeItem('authToken');
//   window.location.href = '/login.html';
// }

// // Start Quiz: redirect to verify
// document.getElementById('startQuiz').addEventListener('click', () => {
//   window.location.href = '/verify.html';
// });

// // Logout
// document.getElementById('logout').addEventListener('click', () => {
//   localStorage.removeItem('authToken');
//   window.location.href = '/login.html';
// });

// // Load user details
// (async function loadProfile() {
//   try {
//     const res = await fetch('/api/me', {
//       headers: { 'Authorization': 'Bearer ' + token }
//     });

//     if (res.status === 401) {
//       localStorage.removeItem('authToken');
//       return window.location.href = '/login.html';
//     }

//     if (!res.ok) {
//       const txt = await res.text();
//       statusEl.textContent = 'Could not verify session: ' + txt;
//       return;
//     }

//     const data = await res.json();
//     const name = data.name || 'User';
//     statusEl.textContent = `Signed in as ${name}`;

//   } catch (err) {
//     statusEl.textContent = 'Network error verifying session.';
//   }
// })();



// home.js — dynamic test loading & navigation with domain filtering

const statusEl = document.getElementById('status');
const testsContainer = document.getElementById('testsContainer');
const domainFiltersEl = document.getElementById('domainFilters');
const testCountEl = document.getElementById('testCount');
const token = localStorage.getItem('authToken');

let allTests = [];
let allDomains = [];
let currentDomain = 'all';

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

  if (tests.length === 0) {
    testsContainer.innerHTML = "<p style='text-align:center; color:var(--muted); padding:40px;'>No tests found for this domain.</p>";
    return;
  }

  tests.forEach(test => {
    const card = document.createElement("div");
    card.className = "test-card";

    card.innerHTML = `
      <span class="domain-badge">${test.domain}</span>
      <span class="difficulty ${test.difficulty.toLowerCase()}">${test.difficulty}</span>
      <h3>${test.title}</h3>
      <p>${test.description}</p>
      <button class="btn start-btn" data-id="${test.id}">Start Test</button>
    `;

    testsContainer.appendChild(card);
  });

  // Add click handlers
  document.querySelectorAll(".start-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const testId = btn.getAttribute("data-id");
      window.location.href = `/verify.html?testId=${testId}`;
    });
  });
}

// Update test count display
function updateTestCount(count) {
  const domainText = currentDomain === 'all' 
    ? 'All Tests' 
    : allDomains.find(d => d.toLowerCase() === currentDomain) || currentDomain;
  testCountEl.textContent = `Showing ${count} test${count !== 1 ? 's' : ''} in ${domainText}`;
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
