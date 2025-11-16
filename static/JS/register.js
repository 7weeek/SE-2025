// register.js — handles camera, preview, validation and POST to /api/register

// DOM refs
const startCam = document.getElementById('startCam');
const captureBtn = document.getElementById('captureBtn');
const retakeBtn = document.getElementById('retakeBtn');
const previewVideo = document.getElementById('previewVideo');
const previewImg = document.getElementById('previewImg');
const placeholder = document.getElementById('placeholder');
const fileInput = document.getElementById('fileInput');
const registerForm = document.getElementById('registerForm');
const submitBtn = document.getElementById('submitBtn');
const clearBtn = document.getElementById('clearBtn');
const photoError = document.getElementById('photoError');

let stream = null;
let capturedBlob = null;

// Start camera
startCam.addEventListener('click', async () => {
  photoError.style.display = 'none';
  if (stream) {
    stopCamera();
    startCam.textContent = 'Start Camera';
    captureBtn.disabled = true;
    previewVideo.style.display = 'none';
    placeholder.style.display = 'block';
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    previewVideo.srcObject = stream;
    previewVideo.style.display = 'block';
    placeholder.style.display = 'none';
    previewImg.style.display = 'none';
    startCam.textContent = 'Stop Camera';
    captureBtn.disabled = false;
  } catch (err) {
    console.error(err);
    photoError.style.display = 'block';
    photoError.textContent = 'Unable to access camera. Please allow camera or use upload.';
  }
});

function stopCamera(){
  if (!stream) return;
  stream.getTracks().forEach(t => t.stop());
  stream = null;
  previewVideo.srcObject = null;
  startCam.textContent = 'Start Camera';
  captureBtn.disabled = true;
}

// Capture frame
captureBtn.addEventListener('click', () => {
  if (!stream) return;
  const videoTrack = stream.getVideoTracks()[0];
  const settings = videoTrack.getSettings();
  const w = previewVideo.videoWidth || settings.width || 640;
  const h = previewVideo.videoHeight || settings.height || 480;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(previewVideo, 0, 0, canvas.width, canvas.height);
  canvas.toBlob(blob => {
    capturedBlob = blob;
    previewImg.src = URL.createObjectURL(blob);
    previewImg.style.display = 'block';
    previewVideo.style.display = 'none';
    placeholder.style.display = 'none';
    retakeBtn.disabled = false;
    captureBtn.disabled = true;
    stopCamera();
  }, 'image/jpeg', 0.92);
});

// Retake: clear captured
retakeBtn.addEventListener('click', () => {
  capturedBlob = null;
  previewImg.style.display = 'none';
  placeholder.style.display = 'block';
  retakeBtn.disabled = true;
  captureBtn.disabled = true;
});

// File upload fallback
fileInput.addEventListener('change', (ev) => {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  if (!/^image\/(jpeg|png|jpg)$/i.test(f.type) && f.type !== 'image/jpeg' && f.type !== 'image/png') {
    photoError.style.display = 'block';
    photoError.textContent = 'Only JPG/PNG allowed';
    return;
  }
  if (f.size > 4 * 1024 * 1024) {
    photoError.style.display = 'block';
    photoError.textContent = 'File size must be < 4 MB';
    return;
  }
  photoError.style.display = 'none';
  capturedBlob = f;
  previewImg.src = URL.createObjectURL(f);
  previewImg.style.display = 'block';
  previewVideo.style.display = 'none';
  placeholder.style.display = 'none';
  retakeBtn.disabled = false;
  captureBtn.disabled = true;
  stopCamera();
});

// Clear form
clearBtn.addEventListener('click', () => {
  registerForm.reset();
  capturedBlob = null;
  previewImg.style.display = 'none';
  previewVideo.style.display = 'none';
  placeholder.style.display = 'block';
  retakeBtn.disabled = true;
  captureBtn.disabled = true;
  photoError.style.display = 'none';
  stopCamera();
});

// Form submit
registerForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  photoError.style.display = 'none';

  // client-side validations
  const pwd = document.getElementById('password').value;
  const cpwd = document.getElementById('confirmPassword').value;
  if (pwd !== cpwd) {
    photoError.style.display = 'block';
    photoError.textContent = 'Passwords do not match';
    return;
  }
  if (!capturedBlob) {
    photoError.style.display = 'block';
    photoError.textContent = 'Please capture or upload a photo.';
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Registering...';

  const fd = new FormData();
  fd.append('fullName', document.getElementById('fullName').value.trim());
  fd.append('studentId', document.getElementById('studentId').value.trim());
  fd.append('email', document.getElementById('email').value.trim());
  fd.append('phone', document.getElementById('phone').value.trim());
  fd.append('course', document.getElementById('course').value.trim());
  fd.append('role', document.getElementById('role').value);
  fd.append('password', pwd);
  fd.append('notes', document.getElementById('notes').value.trim());

  if (capturedBlob instanceof Blob && !(capturedBlob instanceof File)) {
    const file = new File([capturedBlob], 'capture.jpg', { type: 'image/jpeg' });
    fd.append('photo', file);
  } else {
    fd.append('photo', capturedBlob);
  }

  try {
    const res = await fetch('/api/register', {
      method: 'POST',
      body: fd
    });

    if (!res.ok) {
      const text = await res.text().catch(()=>null);
      throw new Error(text || `Server returned ${res.status}`);
    }

    const data = await res.json();
    alert(data.message || 'Registered successfully ✅');
    window.location.href = '/login.html';
  } catch (err) {
    console.error(err);
    photoError.style.display = 'block';
    photoError.textContent = 'Registration failed: ' + (err.message || 'unknown error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Register';
  }
});

// cleanup
window.addEventListener('beforeunload', () => stopCamera());
