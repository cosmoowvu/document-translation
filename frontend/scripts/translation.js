/* ===================================
   Translation - API, Polling, Results
   =================================== */

// Start Translation (triggered by button)
async function startTranslation() {
    try {
        // Show progress - เริ่มต้นที่ 5% (Analyze Phase)
        showProgress('กำลังตรวจสอบไฟล์...', 5);

        const modelElement = document.getElementById('translationModel');
        const payload = {
            job_id: currentJobId,
            source_lang: sourceLang.value || 'tha_Thai',
            target_lang: targetLang.value || 'eng_Latn',
            translation_mode: (modelElement && modelElement.value) ? modelElement.value : 'qwen_direct'
        };
        console.log('Sending translate request:', payload);

        // Save state for resume capability
        saveState(currentJobId, 'progress');

        const translateRes = await fetch(`${API_URL}/api/translate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!translateRes.ok) {
            const err = await translateRes.json();
            throw new Error(err.detail || 'Translation start failed');
        }

        // Step 3: Poll for status
        pollStatus();
    } catch (error) {
        showError(error.message || 'เกิดข้อผิดพลาด');
    }
}

// Poll Status
async function pollStatus() {
    // ถ้า currentJobId เป็น null แสดงว่ายกเลิกแล้ว - หยุด polling
    if (!currentJobId) {
        return;
    }

    try {
        const res = await fetch(`${API_URL}/api/status/${currentJobId}`);
        const data = await res.json();

        if (data.status === 'completed') {
            localStorage.removeItem('translationState'); // Clear state
            showResult();
        } else if (data.status === 'cancelled') {
            // ถูกยกเลิก - หยุด polling
            console.log('Job was cancelled');
            localStorage.removeItem('translationState');
            return; // หยุด polling
        } else if (data.status === 'error') {
            localStorage.removeItem('translationState'); // Clear state
            showError(data.message || 'เกิดข้อผิดพลาด');
        } else {
            showProgress(data.message || 'กำลังประมวลผล...', data.progress || 10);
            setTimeout(pollStatus, 2000);
        }
    } catch (error) {
        console.error('Poll error:', error);
        // ถ้า error อาจเป็นเพราะยกเลิกแล้ว - ไม่ต้อง show error
        if (currentJobId) {
            showError('ไม่สามารถเชื่อมต่อ server ได้');
        }
    }
}

// Show Progress
function showProgress(message, percent) {
    uploadSection.style.display = 'none';
    errorSection.classList.remove('active');
    resultSection.style.display = 'none';
    exportSection.classList.remove('active');

    progressSection.classList.add('active');
    progressFill.style.width = percent + '%';
    progressDetail.textContent = message;

    // Update step indicators based on progress
    const stepAnalyze = document.getElementById('stepAnalyze');
    const stepExtract = document.getElementById('stepExtract');
    const stepTranslate = document.getElementById('stepTranslate');
    const stepRefine = document.getElementById('stepRefine');
    const stepRender = document.getElementById('stepRender');

    // Check if using NLLB+Refine mode
    const modelElement = document.getElementById('translationModel');
    const isNLLBRefine = modelElement && (modelElement.value === 'nllb_qwen' || modelElement.value === 'nllb_gemma');

    // Show/hide Refine step based on mode
    if (stepRefine) {
        stepRefine.style.display = isNLLBRefine ? 'inline-block' : 'none';
    }

    // Dynamic Label for Extraction
    const fileName = document.getElementById('fileName').textContent.trim();
    if (fileName.toLowerCase().endsWith('.pdf')) {
        stepExtract.textContent = '📖 ดึงข้อความ';
    } else {
        stepExtract.textContent = '📖 OCR';
    }

    // Reset all steps
    const allSteps = isNLLBRefine
        ? [stepAnalyze, stepExtract, stepTranslate, stepRefine, stepRender]
        : [stepAnalyze, stepExtract, stepTranslate, stepRender];

    allSteps.forEach(el => {
        if (el) el.classList.remove('active', 'done', 'pending');
    });

    // Progress mapping for NLLB+Refine mode (5 steps)
    if (isNLLBRefine) {
        // เช็คจากข้อความว่าอยู่ขั้นตอนไหน
        const msg = message.toLowerCase();
        const isRefining = msg.includes('เกลา') || msg.includes('refine');

        if (percent < 10) {
            // Analyze
            stepAnalyze.classList.add('active');
            stepExtract.classList.add('pending');
            stepTranslate.classList.add('pending');
            stepRefine.classList.add('pending');
            stepRender.classList.add('pending');
        } else if (percent < 30) {
            // Extract/OCR
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('active');
            stepTranslate.classList.add('pending');
            stepRefine.classList.add('pending');
            stepRender.classList.add('pending');
        } else if (isRefining || percent >= 55) {
            // ถ้าข้อความมี "เกลา" หรือ percent >= 55 → Refine step
            if (percent < 80) {
                stepAnalyze.classList.add('done');
                stepExtract.classList.add('done');
                stepTranslate.classList.add('done');
                stepRefine.classList.add('active');
                stepRender.classList.add('pending');
            } else {
                // Render
                stepAnalyze.classList.add('done');
                stepExtract.classList.add('done');
                stepTranslate.classList.add('done');
                stepRefine.classList.add('done');
                stepRender.classList.add('active');
            }
        } else {
            // Translate (NLLB Translate)
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('done');
            stepTranslate.classList.add('active');
            stepRefine.classList.add('pending');
            stepRender.classList.add('pending');
        }
    } else {
        // Direct mode (4 steps) - original logic
        if (percent < 10) {
            // Analyze
            stepAnalyze.classList.add('active');
            stepExtract.classList.add('pending');
            stepTranslate.classList.add('pending');
            stepRender.classList.add('pending');
        } else if (percent < 30) {
            // Extract/OCR
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('active');
            stepTranslate.classList.add('pending');
            stepRender.classList.add('pending');
        } else if (percent < 80) {
            // Translation
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('done');
            stepTranslate.classList.add('active');
            stepRender.classList.add('pending');
        } else {
            // Render
            stepAnalyze.classList.add('done');
            stepExtract.classList.add('done');
            stepTranslate.classList.add('done');
            stepRender.classList.add('active');
        }
    }

    progressDetail.textContent = `${percent}% - ${message}`;
}

// Cancel Process
async function cancelProcess() {
    if (confirm('คุณต้องการยกเลิกกระบวนการแปลหรือไม่?')) {
        const jobToCancel = currentJobId; // เก็บไว้ก่อน

        // ล้าง currentJobId ทันที เพื่อหยุด polling
        currentJobId = null;

        // ส่งคำขอยกเลิกไปที่ backend
        if (jobToCancel) {
            try {
                await fetch(`${API_URL}/api/cancel/${jobToCancel}`, {
                    method: 'DELETE'  // ← เปลี่ยนจาก POST เป็น DELETE
                });
                console.log('Cancelled job:', jobToCancel);
            } catch (error) {
                console.error('Error cancelling job:', error);
            }
        }

        localStorage.removeItem('translationState');
        resetApp();
    }
}

// Show Error
function showError(message) {
    localStorage.removeItem('translationState'); // Clear state
    uploadSection.style.display = 'none';
    progressSection.classList.remove('active');
    resultSection.style.display = 'none';
    exportSection.classList.remove('active');

    errorSection.classList.add('active');
    errorText.textContent = message;
}

// Show Result
async function showResult() {
    uploadSection.style.display = 'none';
    progressSection.classList.remove('active');
    errorSection.classList.remove('active');

    resultSection.style.display = 'block';
    exportSection.classList.add('active');

    // Load number of pages
    const numPages = await getNumPages();

    // Load all original file pages
    await loadAllOriginalPages(numPages);

    // Load OCR logs
    await loadOCRLogs();

    // Load all translated pages
    await loadAllTranslatedPages(numPages);

    // Set export links
    document.getElementById('exportPdf').href = `${API_URL}/api/export/${currentJobId}?format=pdf`;
    document.getElementById('exportDocx').href = `${API_URL}/api/export/${currentJobId}?format=docx`;
    document.getElementById('exportPng').href = `${API_URL}/api/export/${currentJobId}?format=png`;
    document.getElementById('exportJpg').href = `${API_URL}/api/export/${currentJobId}?format=jpg`;

    // Save state for refresh persistence
    saveState(currentJobId, 'result');

    // Setup sync scroll listeners after everything is loaded
    setupSyncScrollListeners();
}

// Get number of pages from logs
async function getNumPages() {
    try {
        const response = await fetch(`${API_URL}/api/logs/${currentJobId}`);
        if (response.ok) {
            const data = await response.json();
            const pageKeys = Object.keys(data.block_logs || {});
            return pageKeys.length || 1;
        }
    } catch (error) {
        console.error('Error getting page count:', error);
    }
    return 1;
}

// Load all original pages
async function loadAllOriginalPages(numPages) {
    const originalPreview = document.getElementById('originalPreview');
    originalPreview.innerHTML = '';

    for (let page = 1; page <= numPages; page++) {
        // Create wrapper with page number
        const wrapper = document.createElement('div');
        wrapper.className = 'page-wrapper';

        const pageIndicator = document.createElement('div');
        pageIndicator.className = 'page-number-indicator';
        pageIndicator.textContent = `หน้า ${page} / ${numPages}`;
        wrapper.appendChild(pageIndicator);

        // Add skeleton loader first
        const skeleton = document.createElement('div');
        skeleton.className = 'skeleton-loader';
        skeleton.id = `original-skeleton-${page}`;
        wrapper.appendChild(skeleton);

        const img = document.createElement('img');
        img.src = `${API_URL}/api/preview/${currentJobId}/original?page=${page}&t=${Date.now()}`;
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
}

// Load all translated pages
async function loadAllTranslatedPages(numPages) {
    const translatedPreview = document.getElementById('translatedPreview');
    translatedPreview.innerHTML = '';

    for (let page = 1; page <= numPages; page++) {
        // Create wrapper with page number
        const wrapper = document.createElement('div');
        wrapper.className = 'page-wrapper';

        const pageIndicator = document.createElement('div');
        pageIndicator.className = 'page-number-indicator';
        pageIndicator.textContent = `หน้า ${page} / ${numPages}`;
        wrapper.appendChild(pageIndicator);

        // Add skeleton loader first
        const skeleton = document.createElement('div');
        skeleton.className = 'skeleton-loader';
        skeleton.id = `translated-skeleton-${page}`;
        wrapper.appendChild(skeleton);

        const img = document.createElement('img');
        img.src = `${API_URL}/api/preview/${currentJobId}?page=${page}&t=${Date.now()}`;
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
}

// Load OCR Logs - Combined format for 3-column layout
async function loadOCRLogs() {
    const textCombinedPreview = document.getElementById('textCombinedPreview');

    // Populate Model/OCR Info Badges
    const modelElement = document.getElementById('translationModel');
    const modelName = modelElement ? modelElement.options[modelElement.selectedIndex].text : 'Unknown Model';
    const ocrName = 'EasyOCR';

    // Fetch total time from status and add to badges
    let timeBadge = '';
    try {
        const statusRes = await fetch(`${API_URL}/api/status/${currentJobId}`);
        const statusData = await statusRes.json();
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
    } catch (e) {
        console.log('Could not fetch time stats:', e);
    }

    document.getElementById('resultInfoBadges').innerHTML = `
        <span class="badge" style="background-color: #e0f2f1; color: #00695c; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">
            🤖 ${modelName}
        </span>
        <span class="badge" style="background-color: #fff3e0; color: #e65100; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">
            📷 ${ocrName}
        </span>
        ${timeBadge}
    `;

    // Clear previous content
    textCombinedPreview.innerHTML = '<p style="color: #999; padding: 20px; text-align: center;">กำลังโหลด...</p>';

    try {
        const response = await fetch(`${API_URL}/api/logs/${currentJobId}`);

        if (!response.ok) {
            throw new Error('ไม่พบข้อมูล OCR');
        }

        const data = await response.json();

        // Parse block logs and display
        const blockLogs = data.block_logs || {};
        let combinedHTML = '';

        // Sort pages
        const pages = Object.keys(blockLogs).sort();
        const totalPages = pages.length;

        if (pages.length === 0) {
            textCombinedPreview.innerHTML = '<p style="color: #999; padding: 20px; text-align: center;">ไม่มีข้อมูล</p>';
            return;
        }

        for (let i = 0; i < pages.length; i++) {
            const pageKey = pages[i];
            const logText = blockLogs[pageKey];
            const pageNum = pageKey.replace('page_', '');

            // Add page header with data attribute for sync scroll
            combinedHTML += `<div class="ocr-page-header" data-page="${pageNum}">หน้า ${parseInt(pageNum)} / ${totalPages}</div>`;

            // Parse blocks from log text
            const blocks = parseBlockLog(logText, pageNum);

            blocks.forEach(block => {
                combinedHTML += createCombinedBlockHTML(block.num, block.original, block.nllb, block.translated, pageNum, block.isTable, block.isHeader);
            });
        }

        textCombinedPreview.innerHTML = combinedHTML;

    } catch (error) {
        console.error('Error loading OCR logs:', error);
        textCombinedPreview.innerHTML = `<p style="color: #e74c3c; padding: 20px;">เกิดข้อผิดพลาด: ${error.message}</p>`;
    }
}

// Parse block log text -> Returns array of objects (includes both blocks and table cells)
function parseBlockLog(logText, pageNum) {
    const blocks = [];
    const lines = logText.split('\n');

    let currentBlock = null;
    let currentOriginal = '';
    let currentNLLB = '';  // Store NLLB translation
    let currentTranslated = '';
    let currentTable = null;

    for (const line of lines) {
        // Match "TABLE X [NxM]"
        const tableMatch = line.match(/^TABLE (\d+) \[(\d+)x(\d+)\]$/);
        if (tableMatch) {
            // Save previous block if exists
            if (currentBlock) {
                blocks.push({
                    num: currentBlock.num,
                    original: currentOriginal.trim(),
                    nllb: currentNLLB.trim(),
                    translated: currentTranslated.trim(),
                    isTable: false
                });
                currentBlock = null;
            }
            currentTable = {
                num: tableMatch[1],
                rows: tableMatch[2],
                cols: tableMatch[3]
            };
            // Add table header as a special block
            blocks.push({
                num: `Table ${tableMatch[1]}`,
                original: `📊 ตาราง ${tableMatch[2]}x${tableMatch[3]}`,
                nllb: '',
                translated: `📊 Table ${tableMatch[2]}x${tableMatch[3]}`,
                isTable: true,
                isHeader: true
            });
            continue;
        }

        // Match "Cell [X,Y] [STATUS] (detected: lang)"
        const cellMatch = line.match(/^Cell \[(\d+),(\d+)\] \[(TRANSLATED|SKIPPED)\] \(detected: (.+)\)$/);
        if (cellMatch) {
            // Save previous block if exists
            if (currentBlock) {
                blocks.push({
                    num: currentBlock.num,
                    original: currentOriginal.trim(),
                    nllb: currentNLLB.trim(),
                    translated: currentTranslated.trim(),
                    isTable: !!currentTable
                });
            }
            currentBlock = {
                num: `[${cellMatch[1]},${cellMatch[2]}]`,
                status: cellMatch[3],
                lang: cellMatch[4],
                isCell: true
            };
            currentOriginal = '';
            currentNLLB = '';
            currentTranslated = '';
            continue;
        }

        // Match "Block X [STATUS] (detected: lang)"
        const blockMatch = line.match(/^Block (\d+) \[(TRANSLATED|SKIPPED)\] \(detected: (.+)\)$/);
        if (blockMatch) {
            // Save previous block
            if (currentBlock) {
                blocks.push({
                    num: currentBlock.num,
                    original: currentOriginal.trim(),
                    nllb: currentNLLB.trim(),
                    translated: currentTranslated.trim(),
                    isTable: false
                });
            }
            currentTable = null; // Exit table mode
            currentBlock = {
                num: blockMatch[1],
                status: blockMatch[2],
                lang: blockMatch[3]
            };
            currentOriginal = '';
            currentNLLB = '';
            currentTranslated = '';
        }
        // Match "  Original: text"
        else if (line.trim().startsWith('Original:')) {
            currentOriginal = line.replace(/^\s*Original:\s*/, '');
        }
        // Match "  NLLB:   text"
        else if (line.trim().startsWith('NLLB:')) {
            currentNLLB = line.replace(/^\s*NLLB:\s*/, '');
        }
        // Match "  Result:   text"
        else if (line.trim().startsWith('Result:')) {
            currentTranslated = line.replace(/^\s*Result:\s*/, '');
        }
    }

    // Save last block
    if (currentBlock) {
        blocks.push({
            num: currentBlock.num,
            original: currentOriginal.trim(),
            nllb: currentNLLB.trim(),
            translated: currentTranslated.trim(),
            isTable: !!currentTable
        });
    }

    return blocks;
}

// Create combined block HTML showing OCR, NLLB (optional), and Model translation
function createCombinedBlockHTML(blockNum, originalText, nllbText, translatedText, pageNum, isTable = false, isHeader = false) {
    const blockId = `p${pageNum}_b${blockNum}`;
    const tableClass = isTable ? 'table-cell' : '';
    const headerClass = isHeader ? 'table-header' : '';
    const labelPrefix = isTable && !isHeader ? 'Cell' : (isTable ? '' : 'Block');

    // Decide how many rows to show: 2 (OCR + Model) or 3 (OCR + NLLB + Model)
    const hasNLLB = nllbText && nllbText.trim().length > 0;

    return `
        <div class="combined-block ${tableClass} ${headerClass}" data-block-id="${blockId}" data-page="${pageNum}">
            <div class="block-label">${labelPrefix} ${blockNum}</div>
            <div class="block-row">
                <div class="block-ocr">
                    <span class="label-icon">${isTable ? '📊' : '🔍'}</span>
                    <span class="block-content">${escapeHTML(originalText)}</span>
                </div>
                ${hasNLLB ? `
                <div class="block-nllb">
                    <span class="label-icon">🌐</span>
                    <span class="block-content">${escapeHTML(nllbText)}</span>
                </div>
                ` : ''}
                <div class="block-translated">
                    <span class="label-icon">${hasNLLB ? '📝' : '📝'}</span>
                    <span class="block-content">${escapeHTML(translatedText)}</span>
                </div>
            </div>
        </div>
    `;
}

// Create block HTML - with data-block-id for sync scrolling
function createBlockHTML(blockNum, text, pageNum) {
    const blockId = `p${pageNum}_b${blockNum}`;
    return `
        <div class="ocr-block" data-block-id="${blockId}">
            <div class="block-label">Block ${blockNum}</div>
            <div class="block-text">${escapeHTML(text)}</div>
        </div>
    `;
}
