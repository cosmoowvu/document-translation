/* ===================================
   Polling Module
   Handles translation status polling
   =================================== */

// Import API
const API_URL = window.location.origin;

export const PollingService = {
    // Poll job status
    async pollStatus(jobId, callbacks) {
        if (!jobId) {
            return;
        }

        try {
            const res = await fetch(`${API_URL}/api/status/${jobId}`);
            const data = await res.json();

            if (data.status === 'completed') {
                callbacks.onComplete(data);
            } else if (data.status === 'cancelled') {
                console.log('Job was cancelled');
                callbacks.onCancelled();
            } else if (data.status === 'error') {
                callbacks.onError(data.message || 'เกิดข้อผิดพลาด');
            } else {
                callbacks.onProgress(data.message || 'กำลังประมวลผล...', data.progress || 10);
                // Continue polling
                setTimeout(() => this.pollStatus(jobId, callbacks), 2000);
            }
        } catch (error) {
            console.error('Poll error:', error);
            if (jobId) {
                callbacks.onError('ไม่สามารถเชื่อมต่อ server ได้');
            }
        }
    }
};
