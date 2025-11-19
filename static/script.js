// 






const MAX_VOICE_WARNINGS = 5;



// ==============================
//  CLEAN + FIXED SCRIPT.JS
// ==============================

// --- DOM ELEMENTS ---
let video = document.getElementById("video");
let overlay = document.getElementById("overlay");
let events = document.getElementById("events");
let warningBox = document.getElementById("warningBox");

let startPage = document.getElementById("startPage");
let testArea = document.getElementById("testArea");
let completePage = document.getElementById("completePage");

let startBtn = document.getElementById("startBtn");
let submitBtn = document.getElementById("submitBtn");
let restartBtn = document.getElementById("restartBtn");

let questionPanel = document.getElementById("questionPanel");
let timerElement = document.getElementById("timer");
let examTitleEl = document.getElementById("examTitle");
let violationCountEl = document.getElementById("violationCount");
let answeredCountEl = document.getElementById("answeredCount");
let progressPercentEl = document.getElementById("progressPercent");

let statusText = document.getElementById("statusText");
let faceCountSpan = document.getElementById("faceCount");
let voiceStatus = document.getElementById("voiceStatus");

// --- VIDEO/MIC STREAM ---
let stream = null;
let canvas = document.createElement("canvas");
let ctx = canvas.getContext("2d");

// --- AUDIO SETUP ---
let audioContext = null;
let analyser = null;
let rms = 0;
let voiceActive = false;
let voiceThreshold = 0.08;

// --- STATE ---
let sending = false;
let sendTimer = null;
let timerInterval = null;
let timeRemainingSeconds = 0;

// --- CONFIG ---
const HEAD_HOLD_MS = 1000;
const VIOLATION_COOLDOWN_MS = 5000;
const VOICE_HOLD_MS = 350;
const DEFAULT_EXAM_DURATION_MINUTES = 5;
let calibrationMultiplier = 2.5;

// --- HEAD + VOICE TRACKERS ---
let lastShownTime = {};
let lastHeadDetected = "Center";
let headDetectedStart = 0;
let voiceStartTs = 0;
let voiceWarningCount = 0;
let answeredQuestionIds = new Set();


// ---------------- Window-change / fullscreen enforcement ----------------
let windowChangeCount = 0;
const MAX_WINDOW_CHANGES = 3;
const WINDOW_CHANGE_DEBOUNCE_MS = 900; // ignore duplicate events within this ms
let lastWindowChangeTs = 0;
let lastWindowSize = { w: window.innerWidth, h: window.innerHeight };
let windowChangeModal = null;
let windowChangeBackdrop = null;
let winModalMessageEl = null;
let winModalTitleEl = null;
let winModalContinueBtn = null;
let winModalExitBtn = null;
let firstViolationIgnored = false;



function initWindowChangeUI() {
    windowChangeModal = document.getElementById('windowChangeModal');
    windowChangeBackdrop = document.getElementById('windowChangeBackdrop');
    winModalMessageEl = document.getElementById('winModalMessage');
    winModalTitleEl = document.getElementById('winModalTitle');
    winModalContinueBtn = document.getElementById('winModalContinue');
    winModalExitBtn = document.getElementById('winModalExit');

    if (winModalContinueBtn) {
        winModalContinueBtn.addEventListener('click', () => {
            hideWindowChangeModal();
            // try to re-request fullscreen (best-effort)
            tryRequestFullscreen();
        });
    }
    if (winModalExitBtn) {
        winModalExitBtn.addEventListener('click', () => {
            hideWindowChangeModal();
            // submit and exit
            submitExam(true);
        });
    }
}

function showWindowChangeModal(title, message) {
    if (!windowChangeModal || !windowChangeBackdrop) return;
    winModalTitleEl.textContent = title || "Window changed";
    winModalMessageEl.textContent = message || "";
    windowChangeBackdrop.style.display = 'block';
    windowChangeModal.style.display = 'block';
    windowChangeModal.setAttribute('aria-hidden', 'false');
    // also log
    logEvent(`WINDOW_CHANGE: ${message}`);
}

function hideWindowChangeModal() {
    if (!windowChangeModal || !windowChangeBackdrop) return;
    windowChangeBackdrop.style.display = 'none';
    windowChangeModal.style.display = 'none';
    windowChangeModal.setAttribute('aria-hidden', 'true');
}

// perform final action when violation threshold reached
function handleWindowViolation(reason) {
    const now = Date.now();
    if (now - lastWindowChangeTs < WINDOW_CHANGE_DEBOUNCE_MS) return;
    lastWindowChangeTs = now;

    // If this is the very first violation, mark it ignored and inform user
    if (!firstViolationIgnored) {
    firstViolationIgnored = true;
    logEvent("WINDOW_CHANGE_IGNORED (first occurrence)");
    return; // absolutely no popup or warning
    }

    // Normal behavior from second violation onward
    windowChangeCount += 1;
    const msg = `${reason}. Violation ${windowChangeCount} of ${MAX_WINDOW_CHANGES}.`;
    showWindowChangeModal("Attention", msg);
    pushWarning(msg);
    logEvent("WINDOW_CHANGE: " + msg);

    if (windowChangeCount >= MAX_WINDOW_CHANGES) {
        showWindowChangeModal("Test Submitted", "Too many window changes. Submitting the test now.");
        setTimeout(async () => {
            try { hideWindowChangeModal(); } catch (e) {}
            await attemptAutoSubmit();
        }, 900);
    } else {
        // auto-hide after a while so user can resume
        setTimeout(() => {
            try { hideWindowChangeModal(); } catch (e) {}
        }, 6000);
    }
}


// Try to request fullscreen (best-effort, must be called from user gesture ideally)
function tryRequestFullscreen() {
    const docEl = document.documentElement;
    if (!docEl) return;
    if (document.fullscreenElement) return; // already
    const request = docEl.requestFullscreen || docEl.webkitRequestFullscreen || docEl.msRequestFullscreen;
    if (request) {
        try {
            request.call(docEl).catch?.(()=>{/*ignore*/});
        } catch (e) {
            try { request.call(docEl); } catch (e) {}
        }
    }
}

// Try to exit fullscreen (best effort)
function tryExitFullscreen() {
    const exit = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
    if (exit && document.fullscreenElement) {
        try { exit.call(document).catch?.(()=>{}); } catch (e) { try { exit.call(document); } catch(e){} }
    }
}

// Attach listeners to detect tab/window changes
function attachWindowChangeListeners() {
    // visibility change (tab switch or minimize)
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            handleWindowViolation('Tab hidden / switched away');
        }
    });

    // blur (window lost focus)
    window.addEventListener('blur', () => {
        // ignore if the document is being closed/submitted - this is a simple heuristic
        handleWindowViolation('Window lost focus');
    });

    // resize (explicit window resize or if user changes monitor)
    window.addEventListener('resize', () => {
        // Only count it if size actually changed meaningfully
        if (Math.abs(window.innerWidth - lastWindowSize.w) > 20 || Math.abs(window.innerHeight - lastWindowSize.h) > 20) {
            lastWindowSize.w = window.innerWidth;
            lastWindowSize.h = window.innerHeight;
            handleWindowViolation('Window resized');
        }
    });

    // fullscreen exit (user pressed Esc)
    document.addEventListener('fullscreenchange', () => {
        if (!document.fullscreenElement) {
            handleWindowViolation('Exited full screen');
        }
    });
}

// Reset counters (call at start)
function resetWindowChangeCounter() {
    windowChangeCount = 0;
    lastWindowChangeTs = 0;
    lastWindowSize = { w: window.innerWidth, h: window.innerHeight };
    hideWindowChangeModal();
}

// initialize UI hooks on load
document.addEventListener('DOMContentLoaded', () => {
    initWindowChangeUI();
    attachWindowChangeListeners();
});



// ==========================================================
// Utility: Friendly warning text
// ==========================================================
function friendly(msg) {
    msg = msg.toLowerCase();
    if (msg.includes("left")) return "Looking left — keep your head straight";
    if (msg.includes("right")) return "Looking right — keep your head straight";
    if (msg.includes("no person")) return "Person not present";
    if (msg.includes("multiple")) return "Multiple persons detected";
    if (msg.includes("voice") || msg.includes("silent")) return "Please remain silent";
    return msg;
}

// ==========================================================
// UI HELPERS
// ==========================================================
function pushWarning(text) {
    const now = Date.now();
    const last = lastShownTime[text] || 0;

    if (now - last < VIOLATION_COOLDOWN_MS) return;

    lastShownTime[text] = now;

    let el = document.createElement("div");
    el.className = "warning-item";
    el.innerText = text;
    warningBox.prepend(el);

    setTimeout(() => {
        if (el.parentNode) el.parentNode.removeChild(el);
    }, 9000);
}

function logEvent(text) {
    let now = new Date().toLocaleTimeString();
    events.textContent = `[${now}] ${text}\n` + events.textContent;
}

function resetVoiceWarnings() {
    voiceWarningCount = 0;
    updateViolationDisplay();
}

function updateViolationDisplay() {
    if (violationCountEl) {
        violationCountEl.textContent = voiceWarningCount.toString();
    }
}

function updateQuestionStats() {
    const totalQuestions = examQuestions.length;
    const answered = Math.min(answeredQuestionIds.size, totalQuestions);

    if (answeredCountEl) {
        answeredCountEl.textContent = answered.toString();
    }

    if (progressPercentEl) {
        const percent = totalQuestions > 0 ? Math.round((answered / totalQuestions) * 100) : 0;
        progressPercentEl.textContent = `${percent}%`;
    }
}

function handleAnswerSelection(inputEl) {
    if (!inputEl) return;
    const questionId = inputEl.getAttribute("data-question-id");
    if (!questionId) return;
    answeredQuestionIds.add(questionId);
    updateQuestionStats();
}

function incrementVoiceWarnings() {
    voiceWarningCount += 1;
    updateViolationDisplay();
    if (voiceWarningCount > MAX_VOICE_WARNINGS) {
        alert("Too many voice warnings. The test will be submitted automatically.");
        submitExam(true);
    }
}

// ==========================================================
// TIMER HELPERS
// ==========================================================
function parseDurationMinutes(raw) {
    if (raw === undefined || raw === null) return null;
    if (typeof raw === "number") return raw;
    if (typeof raw === "string") {
        const trimmed = raw.trim();
        if (!trimmed) return null;
        if (trimmed.includes(":")) {
            const parts = trimmed.split(":").map(part => parseInt(part, 10));
            if (parts.length === 3 && parts.every(num => !isNaN(num))) {
                const [hours, minutes, seconds] = parts;
                return hours * 60 + minutes + Math.floor((seconds || 0) / 60);
            }
        }
        const numeric = parseFloat(trimmed);
        if (!isNaN(numeric)) return numeric;
    }
    return null;
}

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.max(0, seconds % 60);
    const paddedMins = String(mins).padStart(2, "0");
    const paddedSecs = String(secs).padStart(2, "0");
    return `${paddedMins}:${paddedSecs}`;
}

function updateTimerDisplay(seconds) {
    if (!timerElement) return;
    timerElement.textContent = formatTime(Math.max(0, seconds));
    timerElement.classList.toggle("warning", seconds <= 300 && seconds > 60);
    timerElement.classList.toggle("danger", seconds <= 60);
}

function startExamTimer(durationMinutes) {
    if (!timerElement) return;

    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }

    if (!durationMinutes || isNaN(durationMinutes) || durationMinutes <= 0) {
        timerElement.textContent = "--:--";
        timerElement.classList.remove("warning", "danger");
        return;
    }

    timeRemainingSeconds = Math.floor(durationMinutes * 60);
    updateTimerDisplay(timeRemainingSeconds);

    timerInterval = setInterval(() => {
        timeRemainingSeconds -= 1;
        if (timeRemainingSeconds <= 0) {
            clearInterval(timerInterval);
            timerInterval = null;
            updateTimerDisplay(0);
            autoSubmitDueToTimer();
        } else {
            updateTimerDisplay(timeRemainingSeconds);
        }
    }, 1000);
}

async function autoSubmitDueToTimer() {
    if (submitBtn.disabled) return;
    alert("Time is up. Submitting test automatically.");
    await submitExam(true);
}


// ==========================================================
// BUTTON HANDLERS
// ==========================================================
startBtn.onclick = async () => {
    startPage.classList.add("hidden");

    // Request fullscreen and reset window-change counters
    tryRequestFullscreen();      // best-effort to go fullscreen
    resetWindowChangeCounter();  // reset violation counter at start

    resetVoiceWarnings();
    await startProctoring();
    await loadQuestions();
    testArea.classList.remove("hidden");
};

async function localSubmitFallback(reason) {
    try {
        logEvent("AUTO_SUBMIT_FALLBACK: " + (reason || "no session"));
        sending = false;
        if (sendTimer) clearTimeout(sendTimer);
        if (audioContext) try { audioContext.close(); } catch(e){}
        if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }

        // show UI as submitted (client-side)
        testArea.classList.add("hidden");
        completePage.classList.remove("hidden");

        // Optionally store a flag so teacher/system can see it client-side (localStorage)
        localStorage.setItem('autoSubmitted', JSON.stringify({ reason, ts: Date.now() }));
    } catch (e) {
        console.warn("localSubmitFallback error:", e);
    }
}

async function attemptAutoSubmit() {
    // If we have a session + token, attempt server submit
    if (currentSessionId && token) {
        try {
            const ok = await submitExam(true); // we'll modify submitExam to return boolean
            if (ok === true) return true;
            // if submitExam returned false, fallthrough to fallback
        } catch (e) {
            console.warn("attemptAutoSubmit server submit failed:", e);
        }
    }

    // either no session/token, or server-submission failed -> fallback
    await localSubmitFallback('Server submit failed or no active session');
    return false;
}



// SUBMIT → Collect answers, end session, show completion page
submitBtn.onclick = () => submitExam(false);

async function submitExam(autoTriggered = false) {
    tryExitFullscreen();
    if (submitBtn.disabled) return;

    if (!currentSessionId || !token) {
        alert("Session not initialized. Please restart the test from home page.");
        return;
    }

    sending = false;
    if (sendTimer) clearTimeout(sendTimer);
    if (audioContext) audioContext.close();
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }

    // Collect answers
    const answers = {};
    const radioButtons = document.querySelectorAll('input[type="radio"]:checked');
    radioButtons.forEach(radio => {
        const questionId = radio.getAttribute('data-question-id');
        if (questionId) {
            answers[questionId] = parseInt(radio.value);
        }
    });

    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = autoTriggered ? 'Submitting (Time Up)...' : 'Submitting...';

    try {
        const res = await fetch('/api/session/end', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: parseInt(currentSessionId),
                answers: answers
            })
        });

        const data = await res.json();

        if (data.success) {
            window.location.href = `/report.html?sessionId=${currentSessionId}`;
        } else {
            alert('Error submitting test: ' + (data.message || 'Unknown error'));
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
            return;
        }
    } catch (err) {
        console.error('Error submitting test:', err);
        alert('Error submitting test. Please try again.');
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
        return;
    }

    testArea.classList.add("hidden");
    completePage.classList.remove("hidden");
}

// BACK → Home
restartBtn.addEventListener("click", () => {
    window.location.href = "/home.html";
});


// ==========================================================
// START PROCTORING (Camera + Mic + Calibration)
// ==========================================================
async function startProctoring() {
    stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 1280, height: 720 },
        audio: true
    });

    const videoOnly = new MediaStream(stream.getVideoTracks());
    video.srcObject = videoOnly;
    video.muted = true;
    await video.play();

    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioContext.createMediaStreamSource(stream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    src.connect(analyser);

    // --- Calibrate mic ---
    logEvent("Calibrating microphone... stay silent");
    let samples = [];
    let t0 = performance.now();

    while (performance.now() - t0 < 4000) {
        let buf = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(buf);

        let s = 0;
        for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
        samples.push(Math.sqrt(s / buf.length));

        await new Promise(r => setTimeout(r, 140));
    }

    let avg = samples.reduce((a, b) => a + b, 0) / samples.length;
    voiceThreshold = Math.max(0.01, avg * calibrationMultiplier);

    logEvent(`Calibration done. Threshold ≈ ${voiceThreshold.toFixed(4)}`);

    sending = true;
    monitorVoice();
    scheduleSend();
}


// ==========================================================
// LOAD QUESTIONS FROM API
// ==========================================================
let currentExamId = null;
let currentSessionId = null;
let examQuestions = [];
let token = null;

async function loadQuestions() {
    try {
        // Get exam_id and session_id from URL or localStorage
        const urlParams = new URLSearchParams(window.location.search);
        currentExamId = urlParams.get('examId') || localStorage.getItem('currentExamId');
        currentSessionId = urlParams.get('sessionId') || localStorage.getItem('currentSessionId');
        token = localStorage.getItem('authToken');
        
        if (!currentExamId) {
            questionPanel.innerHTML = "<p>No exam ID provided. Please select an exam from the home page.</p>";
            return;
        }
        
        if (!token) {
            questionPanel.innerHTML = "<p>Not authenticated. Please login.</p>";
            window.location.href = '/login.html';
            return;
        }
        
        // Fetch questions from API
        const res = await fetch(`/api/exam/${currentExamId}/questions`, {
            headers: {
                'Authorization': 'Bearer ' + token
            }
        });
        
        if (!res.ok) {
            questionPanel.innerHTML = "<p>Unable to load questions.</p>";
            return;
        }
        
        const data = await res.json();
        examQuestions = data.questions || [];
        answeredQuestionIds.clear();
        updateQuestionStats();
        renderQuestions(examQuestions);

        if (examTitleEl && data.exam_title) {
            examTitleEl.textContent = data.exam_title;
        }

        startExamTimer(DEFAULT_EXAM_DURATION_MINUTES);
        
    } catch (e) {
        console.error('Error loading questions:', e);
        questionPanel.innerHTML = "<p>Unable to load questions.</p>";
    }
}

function renderQuestions(qs) {
    questionPanel.innerHTML = "";
    qs.forEach((q, i) => {
        const wrapper = document.createElement("div");
        wrapper.className = "question-item";

        const prompt = document.createElement("div");
        prompt.innerHTML = `<b>${i + 1}. ${q.question}</b>`;
        wrapper.appendChild(prompt);

        q.options.forEach((opt, j) => {
            const label = document.createElement("label");
            label.className = "option";

            const input = document.createElement("input");
            input.type = "radio";
            input.name = `q${q.question_id}`;
            input.value = j;
            input.setAttribute("data-question-id", q.question_id);
            
            if (q.selected_option !== undefined && q.selected_option === j) {
                input.checked = true;
                answeredQuestionIds.add(String(q.question_id));
            }

            input.addEventListener("change", () => handleAnswerSelection(input));

            label.appendChild(input);
            label.append(` ${opt}`);
            wrapper.appendChild(label);
        });

        questionPanel.appendChild(wrapper);
    });

    updateQuestionStats();
}

function monitorVoice() {
    if (!analyser || !sending) return;

    let buffer = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buffer);

    let s = 0;
    for (let i = 0; i < buffer.length; i++) s += buffer[i] * buffer[i];
    rms = Math.sqrt(s / buffer.length);

    const now = Date.now();

    if (rms > voiceThreshold) {
        if (!voiceActive) {
            voiceActive = true;
            voiceStartTs = now;
            sendVoiceEvent("voice_start");
        } else {
            if (now - voiceStartTs >= VOICE_HOLD_MS) {
                const vtext = "Please remain silent";
                if (!lastShownTime[vtext] || now - lastShownTime[vtext] >= VIOLATION_COOLDOWN_MS) {
                    pushWarning(vtext);
                    logEvent(vtext);
                    lastShownTime[vtext] = now;
                    incrementVoiceWarnings();

                    const duration = (now - voiceStartTs) / 1000;
                    sendVoiceEvent("voice_stop", { duration });
                }
            }
        }
    } else {
        if (voiceActive) {
            // Voice stopped
            const duration = (now - voiceStartTs) / 1000;
            sendVoiceEvent("voice_stop", { duration });
        }
        voiceActive = false;
    }

    // Send periodic update
    if (rms > voiceThreshold) {
        sendVoiceEvent("periodic");
    }

    setTimeout(monitorVoice, 200);
}

function sendVoiceEvent(eventType, extra = {}) {
    if (!currentSessionId) return;
    const payload = {
        session_id: parseInt(currentSessionId),
        rms: rms,
        event: eventType,
        ...extra
    };
    fetch("/voice_event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    }).catch(e => console.warn("voice_event error:", e));
}


// ==========================================================
// SEND VIDEO FRAMES TO BACKEND
// ==========================================================
function scheduleSend() {
    if (!sending) return;
    sendTimer = setTimeout(async () => {
        await sendFrame();
        scheduleSend();
    }, 300);
}

async function sendFrame() {
    if (!video || video.readyState < 2) return;
    if (!currentSessionId) return; // Don't send if no session

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    let data = canvas.toDataURL("image/jpeg", 0.6);

    try {
        let res = await fetch("/analyze_frame", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                image: data,
                session_id: parseInt(currentSessionId)
            })
        });
        let json = await res.json();
        processDetection(json);
    } catch (e) {
        console.warn("sendFrame error", e);
    }
}


// ==========================================================
// PROCESS DETECTION RESULTS
// ==========================================================
function processDetection(res) {
    let faces = res.faces || [];
    faceCountSpan.innerText = "Faces: " + faces.length;

    const now = Date.now();

    // --- PERSON NOT PRESENT ---
    if (faces.length === 0) {
        const text = "Person not present";
        if (!lastShownTime[text] || now - lastShownTime[text] >= VIOLATION_COOLDOWN_MS) {
            pushWarning(text);
            logEvent(text);
            lastShownTime[text] = now;
        }
    }

    // --- MULTIPLE PERSONS ---
    else if (faces.length > 1) {
        const text = "Multiple persons detected";
        if (!lastShownTime[text] || now - lastShownTime[text] >= VIOLATION_COOLDOWN_MS) {
            pushWarning(text);
            logEvent(text);
            lastShownTime[text] = now;
        }
    }

    // --- HEAD DIRECTION ---
    let detected = "Center";
    if (res.head_pose && res.head_pose.direction)
        detected = res.head_pose.direction;

    if (detected !== lastHeadDetected) {
        lastHeadDetected = detected;
        headDetectedStart = now;
    } else {
        if ((detected === "Left" || detected === "Right")) {
            if (now - headDetectedStart >= HEAD_HOLD_MS) {
                const text = detected === "Left" ? "Looking left" : "Looking right";
                if (!lastShownTime[text] || now - lastShownTime[text] >= VIOLATION_COOLDOWN_MS) {
                    pushWarning(friendly(text));
                    logEvent(friendly(text));
                    lastShownTime[text] = now;
                }
            }
        }
    }

    // --- DRAW RED BOXES IF VIOLATION ---
    const ov = overlay.getContext("2d");
    overlay.width = canvas.width;
    overlay.height = canvas.height;
    ov.clearRect(0, 0, overlay.width, overlay.height);

    let showBoxes = false;
    if (faces.length === 0 || faces.length > 1) showBoxes = true;
    if ((lastHeadDetected === "Left" || lastHeadDetected === "Right") &&
        (now - headDetectedStart >= HEAD_HOLD_MS)) showBoxes = true;

    if (showBoxes && faces.length > 0) {
        ov.strokeStyle = "red";
        ov.lineWidth = 3;
        faces.forEach(f => ov.strokeRect(f.x, f.y, f.w, f.h));
    }
}

// Log panel toggle functionality
const logToggle = document.getElementById('logToggle');
const logContent = document.getElementById('logContent');
const logPanel = document.querySelector('.log-panel');

if (logToggle && logContent) {
    logToggle.addEventListener('click', () => {
        logPanel.classList.toggle('collapsed');
        logContent.classList.toggle('collapsed');
    });
}