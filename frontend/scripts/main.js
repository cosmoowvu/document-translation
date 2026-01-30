/* ===================================
   Main - Config, State, Initialization
   =================================== */

// Configuration
const API_URL = 'http://localhost:8000';

// State
let currentJobId = null;

// DOM Elements
const uploadSection = document.getElementById('uploadSection');
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const sourceLang = document.getElementById('sourceLang');
const targetLang = document.getElementById('targetLang');
const progressSection = document.getElementById('progressSection');
const progressFill = document.getElementById('progressFill');
const progressDetail = document.getElementById('progressDetail');
const errorSection = document.getElementById('errorSection');
const errorText = document.getElementById('errorText');
const resultSection = document.getElementById('resultSection');
const exportSection = document.getElementById('exportSection');

// ===== State Persistence =====

// Save state to localStorage
function saveState(jobId, view) {
    localStorage.setItem('translationState', JSON.stringify({
        currentJobId: jobId,
        currentView: view,
        timestamp: Date.now()
    }));
}

// Load and restore state on page load
window.addEventListener('DOMContentLoaded', async () => {
    // Initialize drag pan for modal
    initDragPan();

    // Initialize Swap Button State
    if (window.updateSwapButtonState) {
        window.updateSwapButtonState();
        const sourceLang = document.getElementById('sourceLang');
        if (sourceLang) {
            sourceLang.addEventListener('change', window.updateSwapButtonState);
        }
    }

    // Note: State restoration is now handled by translation module
    // This event listener kept for modal initialization only
});

// Close fullscreen on ESC key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeFullscreen();
    }
});
