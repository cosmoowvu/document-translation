/* ===================================
   OCR Parser Module
   Handles OCR log parsing and HTML generation
   =================================== */

export const OCRParser = {
    // Parse block log text
    parseBlockLog(logText, pageNum) {
        const blocks = [];
        const lines = logText.split('\n');

        let currentBlock = null;
        let currentOriginal = '';
        let currentTranslated = '';
        let currentSection = null;  // Track which section we're in
        let currentTable = null;
        let inQwen3Section = false;

        for (const line of lines) {
            // Detect QWEN3 CORRECTIONS section header
            if (line.trim() === 'QWEN3 CORRECTIONS') {
                inQwen3Section = true;
                continue;
            }
            // Reset QWEN3 section on next separator-only line (=== or ---)
            if (inQwen3Section && line.startsWith('='.repeat(10))) {
                continue; // skip the === line
            }

            // Match table header
            const tableMatch = line.match(/^TABLE (\d+) \[(\d+)x(\d+)\]$/);
            if (tableMatch) {
                if (currentBlock) {
                    blocks.push({
                        num: currentBlock.num,
                        original: currentOriginal.trim(),
                        translated: currentTranslated.trim(),
                        isTable: false,
                        isQwen3: currentBlock.isQwen3 || false
                    });
                    currentBlock = null;
                }
                currentTable = {
                    num: tableMatch[1],
                    rows: tableMatch[2],
                    cols: tableMatch[3]
                };
                blocks.push({
                    num: `Table ${tableMatch[1]}`,
                    original: `📊 ตาราง ${tableMatch[2]}x${tableMatch[3]}`,
                    translated: `📊 Table ${tableMatch[2]}x${tableMatch[3]}`,
                    isTable: true,
                    isHeader: true
                });
                continue;
            }

            // Match cell
            const cellMatch = line.match(/^Cell \[(\d+),(\d+)\] \[(TRANSLATED|SKIPPED)\] \(detected: (.+)\)$/);
            if (cellMatch) {
                if (currentBlock) {
                    blocks.push({
                        num: currentBlock.num,
                        original: currentOriginal.trim(),
                        translated: currentTranslated.trim(),
                        isTable: !!currentTable,
                        isQwen3: currentBlock.isQwen3 || false
                    });
                }
                currentBlock = {
                    num: `[${cellMatch[1]},${cellMatch[2]}]`,
                    status: cellMatch[3],
                    lang: cellMatch[4],
                    isCell: true,
                    isQwen3: false
                };
                currentOriginal = '';
                currentTranslated = '';
                continue;
            }

            // Match block header (with optional [QWEN3] tag)
            const blockMatch = line.match(/^Block (\d+) \[(TRANSLATED|SKIPPED)\](?: \[QWEN3\])? \(detected: (.+)\)$/);
            if (blockMatch) {
                if (currentBlock) {
                    // If this is a QWEN3 correction, update the existing block
                    const existingIdx = blocks.findIndex(b => b.num === currentBlock.num && !b.isTable);
                    const newBlock = {
                        num: blockMatch[1],
                        original: currentOriginal.trim(),
                        translated: currentTranslated.trim(),
                        isTable: false,
                        isQwen3: inQwen3Section || line.includes('[QWEN3]')
                    };
                    if (inQwen3Section && existingIdx >= 0) {
                        // Replace the existing entry with the Qwen3-fixed one
                        blocks[existingIdx] = newBlock;
                    } else {
                        blocks.push({
                            num: currentBlock.num,
                            original: currentOriginal.trim(),
                            translated: currentTranslated.trim(),
                            isTable: false,
                            isQwen3: currentBlock.isQwen3 || false
                        });
                    }
                }
                currentTable = null;
                currentBlock = {
                    num: blockMatch[1],
                    status: blockMatch[2],
                    lang: blockMatch[3],
                    isQwen3: inQwen3Section || line.includes('[QWEN3]')
                };
                currentOriginal = '';
                currentTranslated = '';
            }
            // Match content lines
            else if (line.trim().startsWith('Original:')) {
                currentOriginal = line.replace(/^\s*Original:\s*/, '');
                currentSection = 'original';
            }
            else if (line.trim().startsWith('Result:')) {
                currentTranslated = line.replace(/^\s*Result:\s*/, '');
                currentSection = 'result';
            }
            // Continuation lines
            else if (currentBlock && line.trim() &&
                !line.includes('Block ') &&
                !line.includes('TABLE ') &&
                !line.includes('Cell ') &&
                !line.includes('----')) {
                // Append to current section
                if (currentSection === 'result') {
                    currentTranslated += '\n' + line;
                } else if (currentSection === 'original') {
                    currentOriginal += '\n' + line;
                }
            }
        }

        // Save last block
        if (currentBlock) {
            const existingIdx = blocks.findIndex(b => b.num === currentBlock.num && !b.isTable);
            const lastBlock = {
                num: currentBlock.num,
                original: currentOriginal.trim(),
                translated: currentTranslated.trim(),
                isTable: !!currentTable,
                isQwen3: currentBlock.isQwen3 || false
            };
            if (inQwen3Section && existingIdx >= 0) {
                blocks[existingIdx] = lastBlock;
            } else {
                blocks.push(lastBlock);
            }
        }

        return blocks;
    },

    // Create combined block HTML
    createCombinedBlockHTML(blockNum, originalText, translatedText, pageNum, isTable = false, isHeader = false, isQwen3 = false) {
        const blockId = `p${pageNum}_b${blockNum}`;
        const tableClass = isTable ? 'table-cell' : '';
        const headerClass = isHeader ? 'table-header' : '';
        const labelPrefix = isTable && !isHeader ? 'Cell' : (isTable ? '' : 'Block');

        const qwen3Badge = isQwen3
            ? `<span style="background:#ede7f6;color:#6a1fa2;padding:2px 7px;border-radius:10px;font-size:0.72rem;margin-left:6px;font-weight:600;">🤖 Qwen3</span>`
            : '';

        const escapeHTML = (text) => {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        };

        return `
            <div class="combined-block ${tableClass} ${headerClass}" data-block-id="${blockId}" data-page="${pageNum}">
                <div class="block-label">${labelPrefix} ${blockNum}${qwen3Badge}</div>
                <div class="block-row-cards">
                    <div class="text-card original-card">
                        <div class="card-header">
                            <span class="card-icon">🔍</span>
                            <span class="card-title">ข้อความต้นฉบับ</span>
                        </div>
                        <div class="card-content">${escapeHTML(originalText)}</div>
                    </div>
                    <div class="text-card result-card">
                        <div class="card-header">
                            <span class="card-icon">📝</span>
                            <span class="card-title">ข้อความแปลภาษา</span>
                        </div>
                        <div class="card-content">${escapeHTML(translatedText)}</div>
                    </div>
                </div>
            </div>
        `;
    }
};
