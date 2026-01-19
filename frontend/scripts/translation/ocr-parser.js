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
        let currentNLLB = '';
        let currentTranslated = '';
        let currentTable = null;

        for (const line of lines) {
            // Match table header
            const tableMatch = line.match(/^TABLE (\d+) \[(\d+)x(\d+)\]$/);
            if (tableMatch) {
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

            // Match cell
            const cellMatch = line.match(/^Cell \[(\d+),(\d+)\] \[(TRANSLATED|SKIPPED)\] \(detected: (.+)\)$/);
            if (cellMatch) {
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

            // Match block header
            const blockMatch = line.match(/^Block (\d+) \[(TRANSLATED|SKIPPED)\] \(detected: (.+)\)$/);
            if (blockMatch) {
                if (currentBlock) {
                    blocks.push({
                        num: currentBlock.num,
                        original: currentOriginal.trim(),
                        nllb: currentNLLB.trim(),
                        translated: currentTranslated.trim(),
                        isTable: false
                    });
                }
                currentTable = null;
                currentBlock = {
                    num: blockMatch[1],
                    status: blockMatch[2],
                    lang: blockMatch[3]
                };
                currentOriginal = '';
                currentNLLB = '';
                currentTranslated = '';
            }
            // Match content lines
            else if (line.trim().startsWith('Original:')) {
                currentOriginal = line.replace(/^\s*Original:\s*/, '');
            }
            else if (line.trim().startsWith('NLLB:')) {
                currentNLLB = line.replace(/^\s*NLLB:\s*/, '');
            }
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
    },

    // Create combined block HTML
    createCombinedBlockHTML(blockNum, originalText, nllbText, translatedText, pageNum, isTable = false, isHeader = false) {
        const blockId = `p${pageNum}_b${blockNum}`;
        const tableClass = isTable ? 'table-cell' : '';
        const headerClass = isHeader ? 'table-header' : '';
        const labelPrefix = isTable && !isHeader ? 'Cell' : (isTable ? '' : 'Block');

        const hasNLLB = nllbText && nllbText.trim().length > 0;

        const escapeHTML = (text) => {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        };

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
};
