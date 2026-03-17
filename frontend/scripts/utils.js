/* ===================================
   Utils - Helper Functions
   =================================== */

// API URL (use current origin for flexibility)
const API_URL = window.location.origin;

// ===== State Persistence =====

// Save state to localStorage
function saveState(jobId, view) {
    localStorage.setItem('translationState', JSON.stringify({
        currentJobId: jobId,
        currentView: view,
        timestamp: Date.now()
    }));
}

// Expose to window for other scripts
window.saveState = saveState;

// Swap Languages
function swapLanguages() {
    const sourceLang = document.getElementById('sourceLang');
    const targetLang = document.getElementById('targetLang');

    if (!sourceLang || !targetLang) return;

    const sourceVal = sourceLang.value;
    const targetVal = targetLang.value;

    // Prevent swap if source is auto
    if (sourceVal === 'auto') return;

    sourceLang.value = targetVal;
    targetLang.value = sourceVal;
}

// Update Swap Button State
function updateSwapButtonState() {
    const sourceLang = document.getElementById('sourceLang');
    const swapBtn = document.querySelector('.swap-btn');

    if (!sourceLang || !swapBtn) return;

    const sourceVal = sourceLang.value;

    if (sourceVal === 'auto') {
        swapBtn.disabled = true;
        swapBtn.classList.add('disabled');
        swapBtn.style.opacity = '0.5';
        swapBtn.style.cursor = 'not-allowed';
    } else {
        swapBtn.disabled = false;
        swapBtn.classList.remove('disabled');
        swapBtn.style.opacity = '1';
        swapBtn.style.cursor = 'pointer';
    }
}

// Expose to window
window.updateSwapButtonState = updateSwapButtonState;
window.swapLanguages = swapLanguages;
window.resetApp = resetApp;

// Reset App - Just reset UI, don't delete files
async function resetApp() {
    // 1. Stop process timer if running
    if (window.TranslationUI) {
        window.TranslationUI.stopTimer();
    }

    // 2. Use the central removeFile function to clear state and UI
    if (typeof window.removeFile === 'function') {
        // Pass false to keep the job on server (Persist Cache)
        await window.removeFile(false);
    } else {
        console.error('removeFile function not found, reloading page...');
        window.location.reload();
    }
}

// Clear all files (manual cleanup)
async function clearAllFiles() {
    // Show custom modal
    const modal = document.getElementById('clearFilesModal');
    modal.classList.add('active');
}

// Close clear files modal
window.closeClearFilesModal = function () {
    const modal = document.getElementById('clearFilesModal');
    const confirmStep = document.getElementById('clearFilesConfirmStep');
    const successStep = document.getElementById('clearFilesSuccessStep');

    // Reset modal state
    confirmStep.style.display = 'block';
    successStep.style.display = 'none';

    modal.classList.remove('active');
};

// Confirm clear all files
window.confirmClearFiles = async function () {
    const confirmStep = document.getElementById('clearFilesConfirmStep');
    const successStep = document.getElementById('clearFilesSuccessStep');
    const messageEl = document.getElementById('clearFilesMessage');

    // Hide confirm step
    confirmStep.style.display = 'none';

    try {
        const response = await fetch(`${API_URL}/api/cleanup`, {
            method: 'POST'
        });

        if (response.ok) {
            const data = await response.json();
            const totalDeleted = (data.deleted_count?.uploads || 0) + (data.deleted_count?.outputs || 0);

            // Show success in modal
            messageEl.textContent = `ลบไฟล์ทั้งหมด ${totalDeleted} รายการ`;
            successStep.style.display = 'block';
        } else {
            // Show error
            messageEl.textContent = 'ไม่สามารถลบไฟล์ได้';
            successStep.style.display = 'block';
        }
    } catch (error) {
        console.error('Error clearing files:', error);
        // Show error in modal
        messageEl.textContent = error.message;
        successStep.style.display = 'block';
    }
};
