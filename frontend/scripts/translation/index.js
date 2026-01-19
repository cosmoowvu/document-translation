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
        if (currentJobId) {
            TranslationUI.showError('ไม่สามารถเชื่อมต่อ server ได้');
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
    if (confirm('คุณต้องการยกเลิกกระบวนการแปลหรือไม่?')) {
        const jobToCancel = currentJobId;
        currentJobId = null;

        if (jobToCancel) {
            try {
                await TranslationAPI.cancelJob(jobToCancel);
                console.log('Cancelled job:', jobToCancel);
            } catch (error) {
                console.error('Error cancelling job:', error);
            }
        }

        localStorage.removeItem('translationState');

        // Call resetApp from global scope (utils.js)
        if (typeof window.resetApp === 'function') {
            window.resetApp();
        } else {
            // Fallback: reload page
            window.location.reload();
        }
    }
}

// Export current job ID getter/setter
export function getCurrentJobId() {
    return currentJobId;
}

export function setCurrentJobId(jobId) {
    currentJobId = jobId;
}
