// login.js — handles login form submit and token storage with enhanced UI feedback

const loginForm = document.getElementById('loginForm');
const loginBtn = document.getElementById('loginBtn');
const loginError = document.getElementById('loginError');
const togglePassword = document.getElementById('togglePassword');
const passwordInput = document.getElementById('password');
const emailInput = document.getElementById('email');

// Toggle password visibility
if (togglePassword && passwordInput) {
  togglePassword.addEventListener('click', () => {
    const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
    passwordInput.setAttribute('type', type);
    togglePassword.textContent = type === 'password' ? '👁️' : '🙈';
  });
}

// Real-time input validation feedback
if (emailInput) {
  emailInput.addEventListener('blur', () => {
    const email = emailInput.value.trim();
    if (email && !email.includes('@')) {
      emailInput.style.borderColor = '#ef4444';
    } else {
      emailInput.style.borderColor = '';
    }
  });
}

// Form submission with enhanced UI
loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  loginError.style.display = 'none';
  
  const btnText = loginBtn.querySelector('.btn-text');
  const btnLoader = loginBtn.querySelector('.btn-loader');
  
  loginBtn.disabled = true;
  if (btnText) btnText.style.display = 'none';
  if (btnLoader) btnLoader.style.display = 'flex';

  const payload = {
    email: emailInput.value.trim(),
    password: passwordInput.value
  };

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const text = await res.text();
    let data = {};
    try { data = JSON.parse(text); } catch(e){ /* server returned plain text */ }

    if (!res.ok) {
      const msg = (data && data.message) ? data.message : text || `Server returned ${res.status}`;
      throw new Error(msg);
    }

    if (data.token) {
      try {
        localStorage.setItem('authToken', data.token);
        // Success animation
        loginBtn.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
        if (btnLoader) btnLoader.innerHTML = '<span class="spinner"></span> Success! Redirecting...';
        
        // Small delay for visual feedback
        setTimeout(() => { 
          window.location.href = '/home.html'; 
        }, 800);
      } catch (err) {
        console.error('Failed to store token:', err);
        throw new Error('Login succeeded but storing session failed. Check browser settings.');
      }
    } else {
      const msg = (data && data.message) ? data.message : 'No token returned';
      throw new Error(msg);
    }

  } catch (err) {
    console.error('Login error:', err);
    const errorText = loginError.querySelector('.error-text');
    if (errorText) {
      errorText.textContent = err.message || 'unknown error';
    }
    loginError.style.display = 'flex';
    
    // Shake animation
    loginForm.style.animation = 'shake 0.5s ease';
    setTimeout(() => {
      loginForm.style.animation = '';
    }, 500);
  } finally {
    loginBtn.disabled = false;
    if (btnText) btnText.style.display = 'inline';
    if (btnLoader) btnLoader.style.display = 'none';
    loginBtn.style.background = '';
  }
});
