// verify.js — handles camera, capture, send to /api/verify and navigate

let stream = null;
const video = document.getElementById('video');
const captured = document.getElementById('captured');
const startCam = document.getElementById('startCam');
const capture = document.getElementById('capture');
const retake = document.getElementById('retake');
const back = document.getElementById('back');
const result = document.getElementById('result');

const token = localStorage.getItem('authToken');
if (!token) {
  alert('Not authenticated. Please login.');
  window.location.href = '/login.html';
}

startCam.addEventListener('click', async () => {
  result.textContent = '';
  try {
    if (stream) {
      // stop
      stopCamera();
      startCam.textContent = 'Start Camera';
      capture.disabled = true;
      return;
    }
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
    video.srcObject = stream;
    video.style.display = 'block';
    captured.style.display = 'none';
    startCam.textContent = 'Stop Camera';
    capture.disabled = false;
  } catch (err) {
    console.error(err);
    result.innerHTML = '<span class="error">Could not access camera. Allow camera permission or use a supported device.</span>';
  }
});

function stopCamera() {
  if (!stream) return;
  stream.getTracks().forEach(t => t.stop());
  stream = null;
  video.srcObject = null;
  capture.disabled = true;
}

capture.addEventListener('click', async () => {
  result.textContent = '';
  if (!stream) {
    result.innerHTML = '<span class="error">Start camera first</span>';
    return;
  }
  // draw to canvas
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  // show preview
  const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
  captured.src = dataUrl;
  captured.style.display = 'block';
  video.style.display = 'none';
  retake.disabled = false;
  capture.disabled = true;
  stopCamera();

  // convert to blob
  const blob = await (await fetch(dataUrl)).blob();

  // send to backend
  const fd = new FormData();
  fd.append('photo', blob, 'capture.jpg');

  result.textContent = 'Verifying...';

  try {
    const res = await fetch('/api/verify', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token
      },
      body: fd
    });

    // try to parse JSON safely
    let data = {};
    try { data = await res.json(); } catch(e) { data = {}; }

    if (!res.ok) {
      result.innerHTML = `<span class="error">Verification failed: ${data.message || res.statusText}</span>`;
      return;
    }
    if (data.success) {
      result.innerHTML = `<span class="success">Verification success — ${data.message || 'Verified'}</span>`;
      
      // Get exam_id from URL
      const urlParams = new URLSearchParams(window.location.search);
      const examId = urlParams.get('testId') || urlParams.get('examId');
      
      if (examId) {
        // Start exam session
        try {
          const sessionRes = await fetch('/api/session/start', {
            method: 'POST',
            headers: {
              'Authorization': 'Bearer ' + token,
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ exam_id: parseInt(examId) })
          });
          
          const sessionData = await sessionRes.json();
          if (sessionData.success) {
            // Store session_id for use in exam page
            localStorage.setItem('currentSessionId', sessionData.session_id);
            localStorage.setItem('currentExamId', examId);
            // Proceed to exam
            setTimeout(() => window.location.href = `/index.html?examId=${examId}&sessionId=${sessionData.session_id}`, 1000);
          } else {
            result.innerHTML = `<span class="error">Failed to start exam session: ${sessionData.message}</span>`;
          }
        } catch (err) {
          console.error('Error starting session:', err);
          result.innerHTML = `<span class="error">Error starting exam: ${err.message}</span>`;
        }
      } else {
        result.innerHTML = `<span class="error">No exam ID provided</span>`;
      }
    } else {
      result.innerHTML = `<span class="error">Verification failed: ${data.message || 'Face did not match'}</span>`;
    }
  } catch (err) {
    console.error(err);
    result.innerHTML = `<span class="error">Error verifying: ${err.message}</span>`;
  }
});

retake.addEventListener('click', () => {
  captured.style.display = 'none';
  video.style.display = 'block';
  retake.disabled = true;
  capture.disabled = false;
  result.textContent = '';
  // restart camera
  startCam.click();
});

back.addEventListener('click', () => {
  stopCamera();
  window.location.href = '/home.html';
});

// stop camera on unload
window.addEventListener('beforeunload', () => stopCamera());
