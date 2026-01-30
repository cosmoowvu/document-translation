/* ===================================
   Translation Module Entry Point
   =================================== */

// Import modules
import { TranslationAPI } from './api.js';
import { TranslationUI } from './ui.js';
import { PollingService } from './polling.js';
import { OCRParser } from './ocr-parser.js';

// Re-export for external use
export { TranslationAPI } from './api.js';
export { TranslationUI } from './ui.js';
export { PollingService } from './polling.js';
export { OCRParser } from './ocr-parser.js';


// State management 
let currentJobId = null;
let pollInterval = null;

// Initialize translation module
export function initTranslation(jobId) {
    currentJobId = jobId;

    // Try to resume if there's a saved state
    const savedState = localStorage.getItem('translationState');
    if (savedState) {
        try {
            const state = JSON.parse(savedState);
            if (state.jobId && state.status) {
                currentJobId = state.jobId;
                // Sync global scope
                if (typeof setCurrentJobId === 'function') {
                    setCurrentJobId(currentJobId);
                } else if (window.setCurrentJobId) {
                    window.setCurrentJobId(currentJobId);
                }

                if (state.status === 'progress') {
                    resumeTranslation();
                } else if (state.status === 'result') {
                    showResult();
                }
            }
        } catch (e) {
            console.error('Error resuming state:', e);
            localStorage.removeItem('translationState');
        }
    }
}

// Start translation
export async function startTranslation() {
    try {
        const sourceLang = document.getElementById('sourceLang');
        const targetLang = document.getElementById('targetLang');
        const modelElement = document.getElementById('translationModel');
        const ocrEngineElement = document.getElementById('ocrEngine');

        // ✅ Get selected OCR engine from dropdown
        const ocrEngine = ocrEngineElement ? ocrEngineElement.value : 'docling';

        TranslationUI.showProgress('กำลังตรวจสอบไฟล์...', 5);

        await TranslationAPI.startTranslation(
            currentJobId,
            sourceLang.value,
            targetLang.value,
            modelElement ? modelElement.value : 'qwen_direct',
            ocrEngine  // ✅ Pass OCR engine
        );

        // Save state
        localStorage.setItem('translationState', JSON.stringify({
            jobId: currentJobId,
            status: 'progress'
        }));

        // Start polling
        pollStatus();
    } catch (error) {
        TranslationUI.showError(error.message || 'เกิดข้อผิดพลาด');
    }
}

// Poll status
async function pollStatus() {
    if (!currentJobId) {
        return;
    }

    try {
        const data = await TranslationAPI.pollStatus(currentJobId);

        if (data.status === 'completed') {
            localStorage.removeItem('translationState');
            await showResult();
        } else if (data.status === 'cancelled') {
            console.log('Job was cancelled');
            localStorage.removeItem('translationState');
            return;
        } else if (data.status === 'error') {
            localStorage.removeItem('translationState');
            TranslationUI.showError(data.message || 'เกิดข้อผิดพลาด');
        } else {
            TranslationUI.showProgress(data.message || 'กำลังประมวลผล...', data.progress || 10);
            setTimeout(pollStatus, 2000);
        }
    } catch (error) {
        console.error('Poll error:', error);

        // Handle 404 or specific errors that imply job is gone
        if (error.message && (error.message.includes('404') || error.message.includes('not found'))) {
            console.log('Job not found (404) - resetting state');
            localStorage.removeItem('translationState');

            // Reset UI silently or with toast
            if (window.resetApp) {
                window.resetApp();
            } else {
                window.location.reload();
            }
            return;
        }

        if (currentJobId) {
            TranslationUI.showError('ไม่สามารถเชื่อมต่อ server ได้: ' + error.message);
        }
    }
}

// Resume translation
async function resumeTranslation() {
    TranslationUI.showProgress('กำลังกู้คืนสถานะ...', 10);
    pollStatus();
}

// Show result
async function showResult() {
    await TranslationUI.showResult(currentJobId);

    // Save state
    localStorage.setItem('translationState', JSON.stringify({
        jobId: currentJobId,
        status: 'result'
    }));

    // Setup sync scroll (from utils.js)
    if (typeof setupSyncScrollListeners === 'function') {
        setupSyncScrollListeners();
    }
}

// Cancel translation
export async function cancelProcess() {
    // Show custom modal instead of browser confirm
    const modal = document.getElementById('cancelModal');
    const confirmStep = document.getElementById('cancelConfirmStep');
    const progressStep = document.getElementById('cancelProgressStep');
    const successStep = document.getElementById('cancelSuccessStep');

    // Reset modal state
    confirmStep.style.display = 'block';
    progressStep.style.display = 'none';
    successStep.style.display = 'none';

    // Show modal
    modal.classList.add('active');

    // Make confirm function available globally
    window.confirmCancel = async function () {
        const jobToCancel = currentJobId;

        if (!jobToCancel) {
            closeCancelModal();
            return;
        }

        // Show loading step
        confirmStep.style.display = 'none';
        progressStep.style.display = 'block';

        try {
            // Send cancel request
            await TranslationAPI.cancelJob(jobToCancel);
            console.log('Cancel request sent for job:', jobToCancel);

            // Poll until job is actually cancelled
            await pollCancellationStatus(jobToCancel);

            // Clear job
            currentJobId = null;
            localStorage.removeItem('translationState');

            // Show success step
            progressStep.style.display = 'none';
            successStep.style.display = 'block';

        } catch (error) {
            console.error('Error cancelling job:', error);
            // Still show success (best effort)
            progressStep.style.display = 'none';
            successStep.style.display = 'block';
        }
    };

    // Polling function
    async function pollCancellationStatus(jobId) {
        const maxAttempts = 300; // 5 minutes safety limit (wait for real cancellation)
        let attempts = 0;

        console.log('⏳ Waiting for backend to confirm cancellation...');

        while (attempts < maxAttempts) {
            try {
                const data = await TranslationAPI.pollStatus(jobId);

                if (data.status === 'cancelled') {
                    console.log('✅ Cancellation confirmed');
                    // Wait 2 more seconds to ensure background stops
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    return;
                }

                console.log(`Waiting... (${data.status}, attempt ${attempts + 1})`)
            } catch (error) {
                // Might still be processing, keep waiting
                console.log(`Polling... (attempt ${attempts + 1})`);
            }

            // Wait 1 second before next check
            await new Promise(resolve => setTimeout(resolve, 1000));
            attempts++;
        }

        console.log('Polling timeout - assuming cancelled');
    }
}

// Close cancel modal
window.closeCancelModal = function () {
    const modal = document.getElementById('cancelModal');
    modal.classList.remove('active');
};

// Export current job ID getter/setter
export function getCurrentJobId() {
    return currentJobId;
}

export function setCurrentJobId(jobId) {
    currentJobId = jobId;
    // Ensure global scope is updated for UI calls
    window.currentJobId = jobId;
}
