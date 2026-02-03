/**
 * init.js - Application Initialization
 * Handles Job ID generation, recovery, and global function bindings
 */

import { initTranslation, startTranslation as startTranslationModule, cancelProcess as cancelProcessModule, setCurrentJobId } from './translation/index.js';
import { TranslationUI } from './translation/ui.js';

// Generate UUID for job ID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Initialize application
function initApp() {
    // Try to get job ID from URL params
    const urlParams = new URLSearchParams(window.location.search);
    let jobId = urlParams.get('job');

    // If no URL param, try to recover from localStorage
    if (!jobId) {
        try {
            const savedState = localStorage.getItem('translationState');
            if (savedState) {
                const state = JSON.parse(savedState);
                if (state.jobId) {
                    jobId = state.jobId;
                    console.log('🔄 Restoring Job ID from storage:', jobId);
                }
            }
        } catch (e) {
            console.error('Error reading storage:', e);
        }
    }

    // If still no ID, generate new one
    if (!jobId) {
        jobId = generateUUID();
        console.log('✨ Generated new Job ID:', jobId);
    }

    // Set the job ID in the translation module
    setCurrentJobId(jobId);

    // Set global job ID for other scripts (backward compatibility)
    window.currentJobId = jobId;

    // Initialize translation system
    initTranslation(jobId);

    // Expose functions to global scope for onclick handlers
    window.startTranslation = function () {
        startTranslationModule().catch(err => {
            console.error('Translation error:', err);
            alert('เกิดข้อผิดพลาด: ' + err.message);
        });
    };

    window.cancelProcess = cancelProcessModule;
    window.setCurrentJobId = setCurrentJobId;
    window.TranslationUI = TranslationUI;

    // Expose Compare Modal functions
    window.openCompareModal = () => TranslationUI.openCompareModal(window.currentJobId);
    window.closeCompareModal = () => TranslationUI.closeCompareModal();
    window.switchCompareView = () => TranslationUI.switchCompareView(window.currentJobId);

    // Initialize drag pan for modal (from main.js)
    if (typeof initDragPan === 'function') {
        initDragPan();
    }

    // Initialize Swap Button State (from main.js)
    if (window.updateSwapButtonState) {
        window.updateSwapButtonState();
        const sourceLangEl = document.getElementById('sourceLang');
        if (sourceLangEl) {
            sourceLangEl.addEventListener('change', window.updateSwapButtonState);
        }
    }
}

// Close fullscreen on ESC key (from main.js)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && typeof closeFullscreen === 'function') {
        closeFullscreen();
    }
});

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    // DOM already loaded, init with slight delay to ensure all scripts are ready
    setTimeout(initApp, 50);
}

// Export for potential external use
export { generateUUID, initApp };
