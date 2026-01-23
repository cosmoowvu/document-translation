/* ===================================
   Upload - File Upload & Drag/Drop
   =================================== */

// Upload Area Events
uploadArea.addEventListener('click', () => {
    fileInput.click();
});

uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
});

// Remove file button in file info bar
document.getElementById('removeFileBtn').addEventListener('click', (e) => {
    e.stopPropagation(); // Prevent upload area click event
    removeFile();
});

// Handle File Upload
async function handleFile(file) {
    // Validate file type
    const validTypes = ['application/pdf', 'image/png', 'image/jpeg'];
    if (!validTypes.includes(file.type)) {
        showError('ไม่รองรับไฟล์ประเภทนี้ (รองรับ PDF, PNG, JPG)');
        return;
    }

    // Validate file size (30MB)
    if (file.size > 30 * 1024 * 1024) {
        showError('ไฟล์ใหญ่เกิน 30MB');
        return;
    }

    try {
        // Show loading in upload area (ไม่เปลี่ยนหน้า)
        const uploadContent = document.getElementById('uploadContent');
        const originalText = uploadContent.innerHTML;
        uploadContent.innerHTML = '<div class="skeleton-loader" style="height: 100px;"></div>';

        // Step 1: Upload file
        const formData = new FormData();
        formData.append('file', file);

        const uploadRes = await fetch(`${API_URL}/api/upload`, {
            method: 'POST',
            body: formData
        });

        if (!uploadRes.ok) {
            const err = await uploadRes.json();
            uploadContent.innerHTML = originalText;  // คืนค่าเดิมถ้า error
            throw new Error(err.detail || 'Upload failed');
        }

        const uploadData = await uploadRes.json();
        currentJobId = uploadData.job_id;

        // Update module state if available
        if (window.setCurrentJobId) {
            window.setCurrentJobId(currentJobId);
        }

        // Show file preview
        showFilePreview(file, uploadData);

    } catch (error) {
        showError(error.message || 'เกิดข้อผิดพลาด');
    }
}

// Show File Preview - New UI with large preview area and file info bar
async function showFilePreview(file, uploadData) {
    // Show upload section (in case it was hidden)
    uploadSection.style.display = 'block';
    progressSection.classList.remove('active');

    // Update upload area to show file
    uploadArea.classList.add('has-file');

    // Hide upload content, show file preview section
    document.getElementById('uploadContent').classList.add('hidden');
    document.getElementById('filePreviewSection').style.display = 'block';

    // Update file info bar
    document.getElementById('fileNameDisplay').textContent = file.name;
    document.getElementById('fileSizeDisplay').textContent = formatFileSize(file.size);

    // Get preview elements
    const imagePreview = document.getElementById('imagePreview');
    const pdfPreview = document.getElementById('pdfPreview');
    const pdfPages = document.getElementById('pdfPages');

    // Clear previous previews
    imagePreview.style.display = 'none';
    pdfPreview.style.display = 'none';
    pdfPages.innerHTML = '';

    if (file.type.startsWith('image/')) {
        // Image preview
        const reader = new FileReader();
        reader.onload = (e) => {
            imagePreview.src = e.target.result;
            imagePreview.style.display = 'block';
        };
        reader.readAsDataURL(file);
    } else if (file.type === 'application/pdf') {
        // PDF multi-page preview
        try {
            if (typeof pdfjsLib !== 'undefined') {
                const arrayBuffer = await file.arrayBuffer();
                const pdf = await pdfjsLib.getDocument(arrayBuffer).promise;

                // Render all pages
                for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
                    const page = await pdf.getPage(pageNum);
                    const canvas = document.createElement('canvas');
                    canvas.className = 'pdf-page';

                    const viewport = page.getViewport({ scale: 1.5 });
                    canvas.width = viewport.width;
                    canvas.height = viewport.height;

                    const context = canvas.getContext('2d');
                    await page.render({
                        canvasContext: context,
                        viewport: viewport
                    }).promise;

                    pdfPages.appendChild(canvas);
                }

                pdfPreview.style.display = 'block';
            } else {
                console.warn('PDF.js not loaded, cannot show PDF preview');
            }
        } catch (error) {
            console.error('PDF preview error:', error);
        }
    }

    // Enable translate button
    document.getElementById('translateBtn').classList.add('active');
}

// Format file size
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

// Remove File - Updated for new UI
async function removeFile() {
    // Delete job files
    if (currentJobId) {
        try {
            await fetch(`${API_URL}/api/job/${currentJobId}`, {
                method: 'DELETE'
            });
        } catch (error) {
            console.error('Error deleting job:', error);
        }
    }

    // Reset state
    currentJobId = null;
    if (window.setCurrentJobId) {
        window.setCurrentJobId(null);
    }
    fileInput.value = '';
    localStorage.removeItem('translationState');

    // Hide all sections except upload
    uploadSection.style.display = 'block';
    progressSection.classList.remove('active');
    errorSection.classList.remove('active');
    resultSection.style.display = 'none';
    exportSection.classList.remove('active');

    // Reset upload area UI
    uploadArea.classList.remove('has-file');

    // Restore original upload content HTML (in case skeleton loader was shown)
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
    document.getElementById('filePreviewSection').style.display = 'none';

    // Clear previews
    document.getElementById('imagePreview').style.display = 'none';
    document.getElementById('imagePreview').src = '';
    document.getElementById('pdfPreview').style.display = 'none';
    document.getElementById('pdfPages').innerHTML = '';

    // Reset buttons
    document.getElementById('translateBtn').classList.remove('active');
}
