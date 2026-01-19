/* ===================================
   Translation API Module
   Handles all API calls and polling
   =================================== */

const API_URL = window.location.origin;

// Export API functions
export const TranslationAPI = {
    // Start translation job
    async startTranslation(jobId, sourceLang, targetLang, translationMode, ocrEngine = 'docling') {
        const payload = {
            job_id: jobId,
            source_lang: sourceLang || 'tha_Thai',
            target_lang: targetLang || 'eng_Latn',
            translation_mode: translationMode || 'qwen_direct',
            ocr_engine: ocrEngine  // ✅ Add OCR engine
        };

        console.log('Sending translate request:', payload);

        const response = await fetch(`${API_URL}/api/translate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Translation start failed');
        }

        return await response.json();
    },

    // Poll job status
    async pollStatus(jobId) {
        const response = await fetch(`${API_URL}/api/status/${jobId}`);
        return await response.json();
    },

    // Get logs
    async getLogs(jobId) {
        const response = await fetch(`${API_URL}/api/logs/${jobId}`);
        if (!response.ok) {
            throw new Error('ไม่พบข้อมูล OCR');
        }
        return await response.json();
    },

    // Cancel job
    async cancelJob(jobId) {
        await fetch(`${API_URL}/api/cancel/${jobId}`, {
            method: 'DELETE'  // ← แก้จาก POST เป็น DELETE
        });
    },

    // Get preview image URL
    getPreviewUrl(jobId, page, type = 'translated') {
        if (type === 'original') {
            return `${API_URL}/api/preview/${jobId}/original?page=${page}&t=${Date.now()}`;
        }
        return `${API_URL}/api/preview/${jobId}?page=${page}&t=${Date.now()}`;
    },

    // Get export URL
    getExportUrl(jobId, format) {
        return `${API_URL}/api/export/${jobId}?format=${format}`;
    }
};
