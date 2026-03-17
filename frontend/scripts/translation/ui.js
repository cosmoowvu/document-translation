/* ===================================
   Translation UI Module
   Handles all UI updates and rendering
   =================================== */

// Import API for preview URLs
import { TranslationAPI } from './api.js';
import { OCRParser } from './ocr-parser.js';

// Export UI functions
export const TranslationUI = {
    timerInterval: null,

    // Start process timer
    startTimer() {
        if (this.timerInterval) return;

        // Get or set start time (persist across reloads)
        let startTime = localStorage.getItem('processStartTime');
        if (!startTime) {
            startTime = Date.now();
            localStorage.setItem('processStartTime', startTime);
        }

        const timerEl = document.getElementById('processTimer');

        const update = () => {
            if (!timerEl) return;

            const now = Date.now();
            const elapsed = Math.max(0, Math.floor((now - parseInt(startTime)) / 1000));

            let timeText = `${elapsed}s`;
            if (elapsed >= 60) {
                const mins = Math.floor(elapsed / 60);
                const secs = elapsed % 60;
                timeText = `${mins}m ${secs}s`;
            }

            timerEl.textContent = ` - ⏱ ${timeText}`;
        };

        update(); // Initial update
        this.timerInterval = setInterval(update, 1000);
    },

    // Stop process timer
    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
        localStorage.removeItem('processStartTime');
    },

    // Show progress with step indicators
    showProgress(message, percent) {
        // Start timer if not running
        this.startTimer();

        const uploadSection = document.getElementById('uploadSection');
        const errorSection = document.getElementById('errorSection');
        const resultSection = document.getElementById('resultSection');
        const exportSection = document.getElementById('exportSection');
        const progressSection = document.getElementById('progressSection');
        const progressFill = document.getElementById('progressFill');
        const progressDetail = document.getElementById('progressDetail');

        uploadSection.style.display = 'none';
        errorSection.classList.remove('active');
        resultSection.style.display = 'none';
        exportSection.classList.remove('active');

        progressSection.classList.add('active');
        progressFill.style.width = percent + '%';
        progressDetail.textContent = message;

        // Update step indicators
        // Update step indicators
        const stepAnalyze = document.getElementById('stepAnalyze');
        const stepExtract = document.getElementById('stepExtract');
        const stepTranslate = document.getElementById('stepTranslate');
        const stepRender = document.getElementById('stepRender');




        // Reset all steps
        const allSteps = [stepAnalyze, stepExtract, stepTranslate, stepRender];

        allSteps.forEach(el => {
            if (el) el.classList.remove('active', 'done', 'pending');
        });

        // Update step classes based on progress (Standard Flow)
        if (percent < 30) {
            stepAnalyze.classList.add('active');
            stepExtract.classList.add('pending');
            stepTranslate.classList.add('pending');
            stepRender.classList.add('pending');
        } else if (percent < 50) {
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('active');
            stepTranslate.classList.add('pending');
            stepRender.classList.add('pending');
        } else if (percent < 90) {
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('done');
            stepTranslate.classList.add('active');
            stepRender.classList.add('pending');
        } else {
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('done');
            stepTranslate.classList.add('done');
            stepRender.classList.add('active');
        }

        progressDetail.textContent = `${percent}% - ${message}`;
    },

    // Show error
    showError(message) {
        this.stopTimer();
        localStorage.removeItem('translationState');

        const uploadSection = document.getElementById('uploadSection');
        const progressSection = document.getElementById('progressSection');
        const resultSection = document.getElementById('resultSection');
        const exportSection = document.getElementById('exportSection');
        const errorSection = document.getElementById('errorSection');
        const errorText = document.getElementById('errorText');

        uploadSection.style.display = 'none';
        progressSection.classList.remove('active');
        resultSection.style.display = 'none';
        exportSection.classList.remove('active');

        errorSection.classList.add('active');
        errorText.textContent = message;
    },

    // Show result view
    async showResult(jobId) {
        this.stopTimer();
        const uploadSection = document.getElementById('uploadSection');
        const progressSection = document.getElementById('progressSection');
        const errorSection = document.getElementById('errorSection');
        const resultSection = document.getElementById('resultSection');
        const exportSection = document.getElementById('exportSection');

        uploadSection.style.display = 'none';
        progressSection.classList.remove('active');
        errorSection.classList.remove('active');

        resultSection.style.display = 'block';
        exportSection.classList.add('active');

        // Get number of pages
        const numPages = await this.getNumPages(jobId);

        // Load previews
        await this.loadAllOriginalPages(jobId, numPages);
        await this.loadResultStats(jobId);
        await this.loadAllTranslatedPages(jobId, numPages);

        // Set export links
        document.getElementById('exportPdf').href = TranslationAPI.getExportUrl(jobId, 'pdf');
        document.getElementById('exportDocx').href = TranslationAPI.getExportUrl(jobId, 'docx');
        document.getElementById('exportPng').href = TranslationAPI.getExportUrl(jobId, 'png');
        document.getElementById('exportJpg').href = TranslationAPI.getExportUrl(jobId, 'jpg');
    },

    // Get number of pages from logs
    async getNumPages(jobId) {
        try {
            const data = await TranslationAPI.getLogs(jobId);
            const pageKeys = Object.keys(data.block_logs || {});
            return pageKeys.length || 1;
        } catch (error) {
            console.error('Error getting page count:', error);
            return 1;
        }
    },

    // Load all original pages
    async loadAllOriginalPages(jobId, numPages) {
        const originalPreview = document.getElementById('originalPreview');
        originalPreview.innerHTML = '';

        for (let page = 1; page <= numPages; page++) {
            const wrapper = document.createElement('div');
            wrapper.className = 'page-wrapper';

            const pageIndicator = document.createElement('div');
            pageIndicator.className = 'page-number-indicator';
            pageIndicator.textContent = `หน้า ${page} / ${numPages}`;
            wrapper.appendChild(pageIndicator);

            const skeleton = document.createElement('div');
            skeleton.className = 'skeleton-loader';
            skeleton.id = `original-skeleton-${page}`;
            wrapper.appendChild(skeleton);

            const img = document.createElement('img');
            img.src = TranslationAPI.getPreviewUrl(jobId, page, 'original');
            img.alt = `Original Page ${page}`;
            img.style.display = 'none';

            img.onload = function () {
                skeleton.style.display = 'none';
                this.style.display = 'block';
            };
            img.onerror = function () {
                skeleton.style.display = 'none';
                this.style.display = 'none';
            };
            wrapper.appendChild(img);
            originalPreview.appendChild(wrapper);
        }
    },

    // Load all translated pages
    async loadAllTranslatedPages(jobId, numPages) {
        const translatedPreview = document.getElementById('translatedPreview');
        translatedPreview.innerHTML = '';

        for (let page = 1; page <= numPages; page++) {
            const wrapper = document.createElement('div');
            wrapper.className = 'page-wrapper';

            const pageIndicator = document.createElement('div');
            pageIndicator.className = 'page-number-indicator';
            pageIndicator.textContent = `หน้า ${page} / ${numPages}`;
            wrapper.appendChild(pageIndicator);

            const skeleton = document.createElement('div');
            skeleton.className = 'skeleton-loader';
            skeleton.id = `translated-skeleton-${page}`;
            wrapper.appendChild(skeleton);

            const img = document.createElement('img');
            img.src = TranslationAPI.getPreviewUrl(jobId, page, 'translated');
            img.alt = `Translated Page ${page}`;
            img.style.display = 'none';

            img.onload = function () {
                skeleton.style.display = 'none';
                this.style.display = 'block';
            };
            img.onerror = function () {
                skeleton.style.display = 'none';
                this.style.display = 'none';
            };
            wrapper.appendChild(img);
            translatedPreview.appendChild(wrapper);
        }
    },

    // Load result stats (Badges only)
    async loadResultStats(jobId) {
        // Get model info
        let modelName = 'Typhoon (Direct)';

        let timeBadge = '';
        let langBadge = '';
        let detectedLangBadge = '';
        let ocrBadge = '';

        try {
            const statusData = await TranslationAPI.pollStatus(jobId);

            // Time Badge
            if (statusData.stats && statusData.stats.total_seconds) {
                const seconds = statusData.stats.total_seconds;
                let timeText;
                if (seconds >= 60) {
                    const mins = Math.floor(seconds / 60);
                    const secs = Math.round(seconds % 60);
                    timeText = `${mins}m ${secs}s`;
                } else {
                    timeText = `${Math.round(seconds)}s`;
                }
                timeBadge = `<span class="badge" style="background-color: #e3f2fd; color: #1565c0; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">⏱ ${timeText}</span>`;
            }

            // Language Badge
            let sourceLang = 'tha_Thai';
            let targetLang = 'eng_Latn';

            if (statusData.stats && statusData.stats.languages) {
                sourceLang = statusData.stats.languages.source;
                targetLang = statusData.stats.languages.target;
            } else {
                const sourceEl = document.getElementById('sourceLang');
                const targetEl = document.getElementById('targetLang');
                if (sourceEl) sourceLang = sourceEl.value;
                if (targetEl) targetLang = targetEl.value;
            }

            const langMap = {
                'tha_Thai': '🇹🇭 Thai',
                'eng_Latn': '🇬🇧 English',
                'zho_Hans': '🇨🇳 Chinese',
                'zho_Hant': '🇨🇳 Chinese',
                'jpn_Jpan': '🇯🇵 Japanese'
            };

            const sourceName = langMap[sourceLang] || sourceLang;
            const targetName = langMap[targetLang] || targetLang;

            langBadge = `<span class="badge" style="background-color: #f3e5f5; color: #7b1fa2; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">${sourceName} ➝ ${targetName}</span>`;

            // Detected Language Badge
            if (statusData.stats && statusData.stats.detected_language) {
                const detectedCode = statusData.stats.detected_language;
                const detectedName = langMap[detectedCode] || detectedCode;
                detectedLangBadge = `<span class="badge" style="background-color: #fce4ec; color: #c2185b; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; margin-left: 4px;">🔍 Detected: ${detectedName}</span>`;
            }

            // OCR Engine Badge
            if (statusData.stats && statusData.stats.ocr_engine) {
                const ocrEngine = statusData.stats.ocr_engine;
                let ocrName;

                if (ocrEngine.includes('paddleocr') || ocrEngine.includes('paddle')) {
                    ocrName = 'PaddleOCR';
                } else if (ocrEngine.includes('typhoon')) {
                    ocrName = 'Typhoon OCR';
                } else {
                    ocrName = ocrEngine;
                }

                ocrBadge = `<span class="badge" style="background-color: #fff3e0; color: #e65100; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">📸 ${ocrName}</span>`;
            }

        } catch (e) {
            console.log('Could not fetch stats:', e);
        }

        document.getElementById('resultInfoBadges').innerHTML = `
            <span class="badge" style="background-color: #e0f2f1; color: #00695c; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">
                🤖 ${modelName}
            </span>
            ${langBadge}
            ${detectedLangBadge}
            ${ocrBadge}
            ${timeBadge}
        `;
    },

    // ==========================================
    // Detailed Compare Modal Logic
    // ==========================================

    openCompareModal(jobId) {
        if (!jobId) return;
        const modal = document.getElementById('compareModal');
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden'; // Prevent background scrolling

        // Load default view (Original)
        this.switchCompareView(jobId, 'original');

        // Load text cards
        this.loadCompareCards(jobId);
    },

    closeCompareModal() {
        const modal = document.getElementById('compareModal');
        modal.style.display = 'none';
        document.body.style.overflow = '';
    },

    async switchCompareView(jobId, viewType = null) {
        if (!jobId && window.getCurrentJobId) jobId = window.getCurrentJobId();

        // If viewType not passed, get from select
        if (!viewType) {
            viewType = document.getElementById('compareViewSelect').value;
        }

        const viewerContent = document.getElementById('compareViewerContent');
        viewerContent.innerHTML = '<div class="placeholder-text">กำลังโหลด...</div>';

        try {
            // Get number of pages
            const numPages = await this.getNumPages(jobId);
            viewerContent.innerHTML = ''; // Clear placeholder

            for (let page = 1; page <= numPages; page++) {
                const wrapper = document.createElement('div');
                wrapper.className = 'page-wrapper';
                wrapper.style.maxWidth = '90%';
                wrapper.style.marginBottom = '20px';

                const img = document.createElement('img');
                img.src = TranslationAPI.getPreviewUrl(jobId, page, viewType);
                img.alt = `${viewType} Page ${page}`;
                img.style.display = 'block'; // Always block in modal
                img.loading = 'lazy';

                wrapper.appendChild(img);
                viewerContent.appendChild(wrapper);
            }

        } catch (error) {
            console.error('Error loading compare view:', error);
            viewerContent.innerHTML = `<div class="placeholder-text" style="color: #ef4444;">เกิดข้อผิดพลาดในการโหลดรูปภาพ</div>`;
        }
    },

    async loadCompareCards(jobId) {
        if (!jobId && window.getCurrentJobId) jobId = window.getCurrentJobId();

        const contentArea = document.getElementById('compareCardsContent');
        contentArea.innerHTML = '<div class="placeholder-text">กำลังโหลดข้อมูล...</div>';

        try {
            const data = await TranslationAPI.getLogs(jobId);
            const blockLogs = data.block_logs || {};
            let combinedHTML = '';

            const pages = Object.keys(blockLogs).sort();
            const totalPages = pages.length;

            if (pages.length === 0) {
                contentArea.innerHTML = '<div class="placeholder-text">ไม่มีข้อมูลข้อความ</div>';
                return;
            }

            for (let i = 0; i < pages.length; i++) {
                const pageKey = pages[i];
                const logText = blockLogs[pageKey];
                const pageNum = pageKey.replace('page_', '');

                combinedHTML += `<div class="ocr-page-header" data-page="${pageNum}">หน้า ${parseInt(pageNum)} / ${totalPages}</div>`;

                const blocks = OCRParser.parseBlockLog(logText, pageNum);

                blocks.forEach(block => {
                    combinedHTML += OCRParser.createCombinedBlockHTML(
                        block.num,
                        block.original,
                        block.translated,
                        pageNum,
                        block.isTable,
                        block.isHeader,
                        block.isQwen3 || false
                    );
                });
            }

            contentArea.innerHTML = combinedHTML;

        } catch (error) {
            console.error('Error loading compare cards:', error);
            contentArea.innerHTML = `<div class="placeholder-text" style="color: #ef4444;">เกิดข้อผิดพลาด: ${error.message}</div>`;
        }
    }
};
