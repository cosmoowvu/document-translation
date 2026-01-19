/* ===================================
   Modal - Fullscreen, Zoom, Pan
   =================================== */

// Fullscreen Modal with Zoom
let currentZoom = 100;

function openFullscreen(type) {
    const modal = document.getElementById('fullscreenModal');
    const modalTitle = document.getElementById('modalTitle');
    const modalContent = document.getElementById('modalContent');

    // Reset zoom
    currentZoom = 100;
    updateZoomDisplay();

    // Set title
    modalTitle.textContent = type === 'original' ? '📄 ต้นฉบับ' : '🌐 แปลแล้ว';

    // Get images from the source preview
    const sourcePreview = document.getElementById(type === 'original' ? 'originalPreview' : 'translatedPreview');
    const images = sourcePreview.querySelectorAll('img');

    // Clone images to modal
    modalContent.innerHTML = '';
    images.forEach((img, index) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'page-wrapper';
        wrapper.innerHTML = `
            <div class="page-number-indicator" style="color: white; background: rgba(255,255,255,0.1);">หน้า ${index + 1} / ${images.length}</div>
            <img src="${img.src}" alt="Page ${index + 1}" class="zoomable-img">
        `;
        modalContent.appendChild(wrapper);
    });

    // Show modal
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeFullscreen() {
    const modal = document.getElementById('fullscreenModal');
    modal.classList.remove('active');
    document.body.style.overflow = '';
    currentZoom = 100;
}

function zoomIn() {
    if (currentZoom < 300) {
        currentZoom += 25;
        applyZoom();
    }
}

function zoomOut() {
    if (currentZoom > 25) {
        currentZoom -= 25;
        applyZoom();
    }
}

function resetZoom() {
    currentZoom = 100;
    panX = 0;
    panY = 0;
    applyZoom();
}

// Pan position
let panX = 0;
let panY = 0;

function applyZoom() {
    const modalContent = document.getElementById('modalContent');
    const modal = document.getElementById('fullscreenModal');

    // Apply transform to modal content
    modalContent.style.transform = `scale(${currentZoom / 100}) translate(${panX}px, ${panY}px)`;

    updateZoomDisplay();

    // Add/remove zoomed class for cursor style
    if (currentZoom > 100) {
        modal.classList.add('zoomed');
    } else {
        modal.classList.remove('zoomed');
        panX = 0;
        panY = 0;
    }
}

function updateZoomDisplay() {
    const display = document.getElementById('zoomLevel');
    if (display) {
        display.textContent = `${currentZoom}%`;
    }
}

// Drag/Pan functionality for zoomed images
let isDragging = false;
let lastX, lastY;

function initDragPan() {
    const modal = document.getElementById('fullscreenModal');

    modal.addEventListener('mousedown', (e) => {
        if (currentZoom <= 100) return;
        if (e.target.closest('.zoom-controls') || e.target.classList.contains('close-btn')) return;

        isDragging = true;
        modal.classList.add('dragging');
        lastX = e.clientX;
        lastY = e.clientY;
        e.preventDefault();
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            const modal = document.getElementById('fullscreenModal');
            modal.classList.remove('dragging');
        }
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;

        const deltaX = e.clientX - lastX;
        const deltaY = e.clientY - lastY;

        panX += deltaX / (currentZoom / 100);
        panY += deltaY / (currentZoom / 100);

        lastX = e.clientX;
        lastY = e.clientY;

        const modalContent = document.getElementById('modalContent');
        modalContent.style.transform = `scale(${currentZoom / 100}) translate(${panX}px, ${panY}px)`;
    });

    // Touch support for mobile
    modal.addEventListener('touchstart', (e) => {
        if (currentZoom <= 100) return;
        if (e.target.closest('.zoom-controls') || e.target.classList.contains('close-btn')) return;

        isDragging = true;
        lastX = e.touches[0].clientX;
        lastY = e.touches[0].clientY;
    }, { passive: true });

    document.addEventListener('touchend', () => {
        isDragging = false;
    });

    document.addEventListener('touchmove', (e) => {
        if (!isDragging) return;

        const deltaX = e.touches[0].clientX - lastX;
        const deltaY = e.touches[0].clientY - lastY;

        panX += deltaX / (currentZoom / 100);
        panY += deltaY / (currentZoom / 100);

        lastX = e.touches[0].clientX;
        lastY = e.touches[0].clientY;

        const modalContent = document.getElementById('modalContent');
        modalContent.style.transform = `scale(${currentZoom / 100}) translate(${panX}px, ${panY}px)`;
    }, { passive: true });
}

// ===== Sync Scroll =====

// Global sync scroll state
let syncScrollEnabled = false;
let isSyncing = false;

// Toggle sync scroll on/off
function toggleSyncScroll() {
    syncScrollEnabled = !syncScrollEnabled;
    const btn = document.getElementById('syncToggleBtn');
    if (syncScrollEnabled) {
        btn.classList.add('active');
        btn.innerHTML = '🔗 Sync Scroll: ON';
    } else {
        btn.classList.remove('active');
        btn.innerHTML = '🔗 Sync Scroll: OFF';
    }
}

// Setup sync scroll listeners after results are loaded
function setupSyncScrollListeners() {
    const originalPreview = document.getElementById('originalPreview');
    const textCombinedPreview = document.getElementById('textCombinedPreview');
    const translatedPreview = document.getElementById('translatedPreview');

    if (!originalPreview || !translatedPreview) {
        console.log('❌ Missing panels:', { originalPreview: !!originalPreview, translatedPreview: !!translatedPreview });
        return;
    }

    console.log('✅ Sync scroll listeners setup completed');

    // Track the last synced page to avoid unnecessary jumps
    let lastSyncedPage = null;

    // Sync Original -> Translated (direct scrollTop, same size files)
    // Also sync Text panel by page number
    originalPreview.addEventListener('scroll', () => {
        if (!syncScrollEnabled || isSyncing) return;
        isSyncing = true;

        // Direct sync with Translated (same size)
        translatedPreview.scrollTop = originalPreview.scrollTop;

        // Sync Text panel by page number
        const pageNum = getVisiblePageNum(originalPreview);
        if (pageNum && pageNum !== lastSyncedPage) {
            lastSyncedPage = pageNum;
            scrollTextPanelToPage(textCombinedPreview, pageNum);
            console.log('📜 Synced to page:', pageNum);
        }

        setTimeout(() => isSyncing = false, 30);
    });

    // Sync Translated -> Original (direct scrollTop, same size files)
    // Also sync Text panel by page number
    translatedPreview.addEventListener('scroll', () => {
        if (!syncScrollEnabled || isSyncing) return;
        isSyncing = true;

        // Direct sync with Original (same size)
        originalPreview.scrollTop = translatedPreview.scrollTop;

        // Sync Text panel by page number
        const pageNum = getVisiblePageNum(translatedPreview);
        if (pageNum && pageNum !== lastSyncedPage) {
            lastSyncedPage = pageNum;
            scrollTextPanelToPage(textCombinedPreview, pageNum);
            console.log('📜 Synced to page:', pageNum);
        }

        setTimeout(() => isSyncing = false, 30);
    });

    // Sync Text panel -> Image panels (by page number)
    if (textCombinedPreview) {
        textCombinedPreview.addEventListener('scroll', () => {
            if (!syncScrollEnabled || isSyncing) return;
            isSyncing = true;

            const pageNum = getVisibleTextPageNum(textCombinedPreview);
            if (pageNum && pageNum !== lastSyncedPage) {
                lastSyncedPage = pageNum;
                scrollPanelToPage(originalPreview, pageNum);
                scrollPanelToPage(translatedPreview, pageNum);
                console.log('📜 Text synced to page:', pageNum);
            }

            setTimeout(() => isSyncing = false, 30);
        });
    }
}

// Get visible page number from image panel
function getVisiblePageNum(panel) {
    const wrappers = panel.querySelectorAll('.page-wrapper');
    const panelTop = panel.scrollTop; // detect when header is at top

    for (const wrapper of wrappers) {
        const wrapperTop = wrapper.offsetTop;
        const wrapperBottom = wrapperTop + wrapper.offsetHeight;

        if (wrapperTop <= panelTop && wrapperBottom > panelTop) {
            const indicator = wrapper.querySelector('.page-number-indicator');
            if (indicator) {
                const match = indicator.textContent.match(/หน้า\s*(\d+)/);
                if (match) return parseInt(match[1]);
            }
        }
    }
    return null;
}

// Get visible page number from text panel
function getVisibleTextPageNum(panel) {
    const headers = panel.querySelectorAll('.ocr-page-header[data-page]');
    const panelTop = panel.scrollTop; // detect when header is at top

    for (let i = 0; i < headers.length; i++) {
        const header = headers[i];
        const headerTop = header.offsetTop;
        const nextHeader = headers[i + 1];
        const sectionEnd = nextHeader ? nextHeader.offsetTop : panel.scrollHeight;

        if (headerTop <= panelTop && sectionEnd > panelTop) {
            return parseInt(header.dataset.page);
        }
    }
    return null;
}

// Scroll image panel to specific page
function scrollPanelToPage(panel, pageNum) {
    if (!panel) return;
    const wrappers = panel.querySelectorAll('.page-wrapper');
    for (const w of wrappers) {
        const indicator = w.querySelector('.page-number-indicator');
        if (indicator) {
            const match = indicator.textContent.match(/หน้า\s*(\d+)/);
            if (match && parseInt(match[1]) === pageNum) {
                panel.scrollTop = w.offsetTop;
                return;
            }
        }
    }
}

// Scroll text panel to specific page
function scrollTextPanelToPage(panel, pageNum) {
    if (!panel) return;
    const headers = panel.querySelectorAll('.ocr-page-header[data-page]');
    for (const header of headers) {
        if (parseInt(header.dataset.page) === pageNum) {
            panel.scrollTop = header.offsetTop;
            return;
        }
    }
}
