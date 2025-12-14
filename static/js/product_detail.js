/**
 * product_detail.js
 * Handles interactions for the single product detail page.
 */

document.addEventListener('DOMContentLoaded', () => {
    setupGallery();
    setupCartActions();
});

/**
 * Initializes image gallery functionality (thumbnail clicking).
 */
function setupGallery() {
    const mainImage = document.getElementById('main-image');
    const thumbnails = document.querySelectorAll('.thumbnail-img');

    if (!mainImage || thumbnails.length === 0) return;

    thumbnails.forEach(thumb => {
        thumb.addEventListener('click', function() {
            // Update main image source
            const newSrc = this.getAttribute('src');
            mainImage.classList.add('opacity-50'); // Fade out effect
            
            setTimeout(() => {
                mainImage.src = newSrc;
                mainImage.classList.remove('opacity-50');
            }, 150);

            // Update active state border
            thumbnails.forEach(t => t.parentElement.classList.remove('ring-2', 'ring-primary'));
            this.parentElement.classList.add('ring-2', 'ring-primary');
        });
    });
}

function setupCartActions() {
    const addBtn = document.getElementById('add-to-cart-btn');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            // Visual feedback
            const originalText = addBtn.innerHTML;
            addBtn.innerHTML = `<span class="material-symbols-outlined animate-spin">progress_activity</span> Agregando...`;
            addBtn.disabled = true;

            setTimeout(() => {
                addBtn.innerHTML = `<span class="material-symbols-outlined">check</span> Agregado`;
                addBtn.classList.replace('bg-primary', 'bg-green-600');
                
                setTimeout(() => {
                    addBtn.innerHTML = originalText;
                    addBtn.disabled = false;
                    addBtn.classList.replace('bg-green-600', 'bg-primary');
                }, 2000);
            }, 600);
        });
    }
}