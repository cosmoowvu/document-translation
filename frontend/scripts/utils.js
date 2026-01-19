/* ===================================
   Utils - Helper Functions
   =================================== */

// Escape HTML
function escapeHTML(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Swap Languages
function swapLanguages() {
    const sourceVal = sourceLang.value;
    const targetVal = targetLang.value;
    sourceLang.value = targetVal;
    targetLang.value = sourceVal;
}

// Reset App
async function resetApp() {
    // Delete job files if exists
    if (currentJobId) {
        try {
            await fetch(`${API_URL}/api/job/${currentJobId}`, {
                method: 'DELETE'
            });
            console.log('Deleted job files for:', currentJobId);
        } catch (error) {
            console.error('Error deleting job:', error);
        }
    }

    // Clear state
    localStorage.removeItem('translationState');
    currentJobId = null;
    if (window.setCurrentJobId) {
        window.setCurrentJobId(null);
    }
    fileInput.value = '';

    // Reset UI sections
    uploadSection.style.display = 'block';
    progressSection.classList.remove('active');
    errorSection.classList.remove('active');
    resultSection.style.display = 'none';
    exportSection.classList.remove('active');

    // Reset upload area UI (important!)
    uploadArea.classList.remove('has-file');

    // Restore original upload content
    const uploadContent = document.getElementById('uploadContent');
    uploadContent.innerHTML = `
        <div class="upload-icon">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
        </div>
        <p class="upload-text">คลิกเพื่ออัปโหลด หรือลากไฟล์มาที่นี่</p>
        <p class="supported-formats">รองรับ PDF, JPEG, PNG (สูงสุด 30MB)</p>
    `;
    uploadContent.classList.remove('hidden');
    document.getElementById('fileDisplay').classList.remove('active');

    // Reset buttons
    document.getElementById('translateBtn').classList.remove('active');
    document.getElementById('clearBtn').classList.remove('active');
}

// Clear all files (manual cleanup)
async function clearAllFiles() {
    if (!confirm('ต้องการลบไฟล์ทั้งหมดบน Server หรือไม่?\n\n(ไฟล์อัปโหลดและผลแปลทั้งหมดจะถูกลบ)')) {
        return;
    }

    try {
        const response = await fetch(`${API_URL}/api/cleanup`, {
            method: 'POST'
        });

        if (response.ok) {
            const data = await response.json();
            const totalDeleted = (data.deleted_count?.uploads || 0) + (data.deleted_count?.outputs || 0);
            alert(`✅ ลบไฟล์เรียบร้อย\n\nลบไปทั้งหมด ${totalDeleted} รายการ`);
            resetApp();
        } else {
            alert('❌ ไม่สามารถลบไฟล์ได้');
        }
    } catch (error) {
        console.error('Error clearing files:', error);
        alert('❌ เกิดข้อผิดพลาด: ' + error.message);
    }
}
